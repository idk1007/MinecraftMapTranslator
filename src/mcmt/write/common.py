# SPDX-License-Identifier: GPL-3.0-or-later
"""legacy 與 native 都需要的那一點點共同邏輯（M11.1），以及跨容器種類共用的節點
編輯引擎（M13b）。**高風險目錄。**

前半段（`component_for`／`refuse_residue`）只放兩者真的完全相同的東西：
editplan 的 value 該長成什麼 component（合約定義的），以及佔位符殘留的檢查。
形狀怎麼寫進 NBT、list 要不要提升——那些是不對稱的部分，各自在 `legacy.py`／
`native.py`。

後半段（`ApplyOutcome`／`apply_edit_to_compound`）是「照 node_path 走到節點、
按 expected_encoding 守門、按 value.kind 決定寫什麼」這件事——這一段與容器是
region chunk 還是 `.dat` 檔完全無關，兩者共用同一份，不是巧合的重複。把它們搬
到這裡而不是留在 `write/apply.py`，是因為 `write/datfile_apply.py` 也要用同一份
（見 `docs/ownership.md`「為什麼寫入層與輸出後端是分開的」同一條理由）。

**`apply_edits()`（複數）才是呼叫端該用的入口。** 同一個 native list（告示牌
`messages[]`、`minecraft:lore` 之類）收到兩筆以上 edit 時不能逐筆呼叫
`apply_edit_to_compound()`：第一筆把 list 從 String 提升成 Compound 後，root
上的 list 已經變形，第二筆的 `expected_encoding`（extract 當下量的舊形狀）在
守門那關會被誤判成「世界被改過了」——實際上是**這一次 apply 自己造成的**，不
是使用者在遊戲裡動的（2026-08-31 補的已知缺口）。`apply_edits()` 把同一個
list 的所有 edit 分成一組，用「這次 apply 開始前」的快照統一過守門，再依序
寫入，讓「守門認得這個形狀變化是我們自己剛剛造成的」成立。`apply_edit_to_compound()`
仍然保留給只有一筆 edit、或呼叫端自己已經分好組的情境用。
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import amulet_nbt

from mcmt.errors import PlaceholderResidueError
from mcmt.model import SCHEMA_VERSION
from mcmt.model.component import sniff
from mcmt.model.generation import generation_of
from mcmt.model.node import NodePath

__all__ = [
    "ApplyOutcome",
    "apply_edit_to_compound",
    "apply_edits",
    "component_for",
    "refuse",
    "refuse_residue",
]


@dataclass
class ApplyOutcome:
    """一次 `apply` 的累計帳本。**跨容器種類共用**——region、`.dat`、datapack 的
    寫入器都把結果記進同一份，最後合成同一份 `apply_report.json`。"""

    outcome: str = "applied"
    counts: Counter = field(default_factory=Counter)
    unwritten: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    backup_directory: Path | None = None
    backup_files: int = 0

    def report(self, *, world: Path, fingerprint_before: str) -> dict[str, Any]:
        return {
            "format": "mcmt-apply-report",
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "outcome": self.outcome,
            "world": {
                "path": str(world),
                "world_fingerprint_before": fingerprint_before,
                "world_fingerprint_after": None,
                "extract_fingerprint": None,
            },
            "backup": (
                {
                    "directory": str(self.backup_directory),
                    "file_count": self.backup_files,
                }
                if self.backup_directory
                else None
            ),
            "counts": {
                "edits_planned": self.counts["edits_planned"],
                "edits_written": self.counts["edits_written"],
                "chunks_touched": self.counts["chunks_touched"],
                "chunks_copied_verbatim": self.counts["chunks_copied_verbatim"],
                "files_rewritten": self.counts["files_rewritten"],
                "list_promotions": self.counts["list_promotions"],
            },
            "unwritten": self.unwritten,
            "warnings": self.warnings,
        }


def refuse(outcome: ApplyOutcome, edit: dict, reason: str, detail: str) -> None:
    outcome.unwritten.append(
        {
            "unit_id": edit["unit_id"],
            "occurrence_id": edit["occurrence_id"],
            "reason": reason,
            "detail": detail,
        }
    )


def apply_edit_to_compound(
    root: amulet_nbt.CompoundTag, edit: dict[str, Any], outcome: ApplyOutcome
) -> bool:
    """走到 `edit['node_path']` 指的節點，過 `expected_encoding` 守門，寫值。

    **這裡不知道 `root` 是從哪裡讀出來的**——chunk 根與 `.dat` 根對這個函式是
    同一種東西（一棵 `CompoundTag`）。呼叫端負責讀進 `root`、負責在寫完之後把它
    編碼回磁碟；這裡只負責「找對節點、守好門、寫對值」。
    """
    from mcmt.write import in_place  # 延遲匯入，避免與 in_place.py 互相匯入成環

    path = NodePath.from_json(edit["node_path"])
    steps = list(path)
    if not steps:
        refuse(outcome, edit, "node_missing", "node_path 是空的")
        return False

    if steps[-1].t == "key":
        return _apply_to_key(root, steps, edit, outcome)
    if steps[-1].t != "index":
        refuse(outcome, edit, "unsupported_encoding", "v1 的寫入路徑不支援 decode 步驟")
        return False

    index = steps[-1].i
    try:
        container = _resolve(root, steps[:-1])
    except (KeyError, IndexError) as exc:
        refuse(outcome, edit, "node_missing", str(exc))
        return False

    if not isinstance(container, amulet_nbt.ListTag):
        refuse(outcome, edit, "node_missing", "目標的父節點不是 list")
        return False
    if index >= len(container):
        refuse(outcome, edit, "node_missing", f"list 只有 {len(container)} 個元素")
        return False

    current = _guarded_encoding(container[index], edit, outcome)
    if current is None:
        return False

    working, written = _write_index_edit(container, index, edit, current, outcome)
    if written:
        _replace_list(root, steps[:-1], working)
    return written


def apply_edits(
    root: amulet_nbt.CompoundTag, edits: list[dict[str, Any]], outcome: ApplyOutcome
) -> int:
    """`apply_edit_to_compound()` 的批次版本——**呼叫端該用這個，不是逐筆呼叫**。

    同一個 native list（告示牌 `messages[]`、`minecraft:lore` 之類）收到兩筆以上
    edit 時，第一筆會把整個 list 從 String 提升成 Compound（`write/native.py`）。
    逐筆呼叫 `apply_edit_to_compound()` 的話，第二筆讀到的 `container[index]`
    已經是提升後的形狀，跟它自己的 `expected_encoding`（extract 當下量的舊形狀）
    對不上，在 `_guarded_encoding` 這關被誤判成「世界在 extract 之後被使用者
    改過了」而拒寫——**實際上是這一次 apply 自己造成的**，不是外部改動。

    修法是把同一個 list 的所有 edit 分成一組，用「這次 apply 開始前」的快照
    統一過守門，再依序寫入（見 `_apply_index_group`）。`key` 結尾的 edit 沒有
    這個問題——每一筆都是整節點替換，不會被同批次裡的另一筆改變形狀。
    """
    written = 0
    index_groups: dict[NodePath, list[dict]] = defaultdict(list)
    decode_groups: dict[NodePath, list[dict]] = defaultdict(list)

    for edit in edits:
        steps = list(NodePath.from_json(edit["node_path"]))
        if not steps:
            refuse(outcome, edit, "node_missing", "node_path 是空的")
            continue
        if steps[-1].t == "key":
            if _apply_to_key(root, steps, edit, outcome):
                written += 1
            continue
        if steps[-1].t == "decode":
            # 找到最後一個非 decode 步驟，那就是這個字串節點的位址；同一個
            # 字串節點收到的所有 decode 結尾 edits 分成一組，理由跟同一個
            # native list 收到多筆 edit 要批次處理一樣（見本函式上面的說明）：
            # 這裡改成委派給 command_span，一次 splice 完同一物理字串上的所有
            # edit，而不是逐筆各自改一次字串（後面的 span 位移會被前一筆改壞）。
            string_node_steps = [s for s in steps if s.t != "decode"]
            decode_groups[NodePath(string_node_steps)].append(edit)
            continue
        if steps[-1].t != "index":
            refuse(outcome, edit, "unsupported_encoding", "v1 的寫入路徑不支援 decode 步驟")
            continue
        index_groups[NodePath(steps[:-1])].append(edit)

    for parent, group in index_groups.items():
        written += _apply_index_group(root, parent, group, outcome)

    for parent, group in decode_groups.items():
        written += _apply_decode_group(root, parent, group, outcome)

    return written


def _apply_decode_group(
    root: amulet_nbt.CompoundTag,
    parent: NodePath,
    edits: list[dict[str, Any]],
    outcome: ApplyOutcome,
) -> int:
    """`decode` 結尾的 edits，分組鍵是「這個物理字串的位址」（`parent` = 最後
    一個非 decode 步驟為止的路徑）。委派給 `command_span.apply_command_edits`
    做字串內部的 splice，這裡只負責走到那個 `StringTag`、守門、寫回。

    `apply_command_edits` 回傳的是新字串本身（不是筆數）——用 `outcome.unwritten`
    在呼叫前後的長度差算出這組裡實際寫成幾筆，比逐筆用 dict 比對可靠：
    `refuse()` 對每筆失敗的 edit 恰好 append 一筆進 `unwritten`，成功的不會。

    **在委派給 `apply_command_edits` 之前，這裡要做跟 `_guarded_encoding` 一樣
    的守門**——不然重放同一份 plan 時，指令字串裡已經被上一次 apply 寫過的
    譯文會被當成「還是原文」再蓋一次，`raw_snapshot` 那道防線對指令文字整個
    失效。指令文字沒有一棵獨立的 NBT tag 可以直接 sniff，所以先把 leaf 從
    「現在的」物理字串重新解碼出一棵 tag，再丟給同一套 `_guarded_encoding`。
    """
    from mcmt.write.command_span import apply_command_edits

    parent_steps = list(parent)
    if not parent_steps or parent_steps[-1].t != "key":
        for edit in edits:
            refuse(outcome, edit, "unsupported_encoding", "指令文字目前只支援 key 結尾的父節點")
        return 0
    try:
        container = _resolve(root, parent_steps[:-1])
    except (KeyError, IndexError) as exc:
        for edit in edits:
            refuse(outcome, edit, "node_missing", str(exc))
        return 0

    key = parent_steps[-1].name
    if not isinstance(container, amulet_nbt.CompoundTag) or key not in container:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到鍵 {key}")
        return 0

    tag = container[key]
    if not isinstance(tag, amulet_nbt.StringTag):
        for edit in edits:
            refuse(outcome, edit, "node_changed", f"{key} 不是字串節點，可能被改過了")
        return 0

    text = str(tag)
    guarded = guard_command_edits(text, edits, outcome)
    if not guarded:
        return 0

    before = len(outcome.unwritten)
    new_text = apply_command_edits(text, guarded, outcome=outcome)
    if new_text is None:
        return 0
    container[key] = amulet_nbt.StringTag(new_text)
    return len(guarded) - (len(outcome.unwritten) - before)


def guard_command_edits(
    text: str, edits: list[dict[str, Any]], outcome: ApplyOutcome
) -> list[dict[str, Any]]:
    """指令文字的守門，**唯一一份定義**：region／entities 的 `Command` 欄位
    （`_apply_decode_group`）與 `.mcfunction` 的一行（`mcfunction_apply.py`）
    都走這裡。留下通過的 edits，其餘拒寫。

    三道，由便宜到貴：

    1. 長度（`_command_length_matches`）——對不上，plan 裡的絕對位移全部失效。
    2. 從**現在的**字串重新解碼 leaf（`_decode_command_leaf`）——解不出來就
       承認解不出來，拒寫。
    3. `_guarded_encoding`——形狀，再加 `raw_snapshot` 逐位元組比對。長度一樣、
       字不一樣（使用者把字改成一樣長的另一句）只有這一道擋得住。

    `.mcfunction` 以前只有第 1 道（缺口 C，2026-10-14 補齊）。
    """
    guarded: list[dict[str, Any]] = []
    for edit in edits:
        decode_chain = [
            step for step in NodePath.from_json(edit["node_path"]) if step.t == "decode"
        ]
        if not _command_length_matches(text, decode_chain):
            refuse(
                outcome,
                edit,
                "node_changed",
                "指令字串的長度跟 extract 當下不一樣——世界在 extract 之後被改過了",
            )
            continue
        decoded = _decode_command_leaf(text, decode_chain)
        if decoded is None:
            refuse(outcome, edit, "unsupported_encoding", "無法重新解碼指令文字裡的節點")
            continue
        if _guarded_encoding(decoded, edit, outcome) is None:
            continue
        guarded.append(edit)
    return guarded


def _command_length_matches(text: str, decode_chain: list) -> bool:
    """`decode_chain` 第一步永遠是 `("command", (0, 原始 Command 字串長度))`
    （`scan/command.py::_yield_tag` 固定加的第一步）。長度都對不上，指令字串
    一定已經變了——不用真的重新解碼，就能先用這個便宜的訊號擋下重放。"""
    if not decode_chain:
        return False
    outer = decode_chain[0]
    if outer.codec is None or outer.codec.value != "command" or outer.span is None:
        return False
    return outer.span[1] - outer.span[0] == len(text)


def _decode_command_leaf(text: str, decode_chain: list) -> Any:
    """`decode_chain` 最後一步才是真正的 splice 目標（`command_span.py` 的
    說明）；把它對應的片段從**現在的**物理字串重新解碼回一棵 tag，只為了餵給
    `_guarded_encoding` 走跟原生 NBT 節點同一套形狀／內容守門——不是重新做一次
    `scan/command.py` 的動詞判斷，解碼失敗就承認解不出來，不猜。

    **`snbt → json_component` 三步鏈（SNBT 字串常值包 JSON）在這裡讀不回來**
    ——最後一步的 span 是字串常值本身（含引號），不是解開後的 JSON。這曾經是
    缺口 B；2026-10-14 的裁定是那個形狀在 1.21.11 本來就是字面亂碼，掃描端
    跳過不抽，所以這裡讀不回來反而是對的兜底：裁定之前產生的舊 editplan 帶著
    這種 edit 時，守門會拒寫。"""
    if not decode_chain:
        return None
    last = decode_chain[-1]
    if last.span is None:
        return None
    raw = text[last.span[0] : last.span[1]]
    codec = last.codec.value if last.codec else None
    from mcmt.tree.codecs import codec_for

    try:
        if codec == "command":
            return amulet_nbt.StringTag(raw)
        if codec == "json_component":
            from mcmt.scan.sources.datapack import _to_amulet

            return _to_amulet(codec_for("json_component").decode(raw))
        if codec == "snbt":
            return codec_for("snbt").decode(raw)
    except Exception:
        return None
    return None


def _apply_index_group(
    root: amulet_nbt.CompoundTag,
    parent: NodePath,
    edits: list[dict[str, Any]],
    outcome: ApplyOutcome,
) -> int:
    parent_steps = list(parent)
    try:
        container = _resolve(root, parent_steps)
    except (KeyError, IndexError) as exc:
        for edit in edits:
            refuse(outcome, edit, "node_missing", str(exc))
        return 0

    if not isinstance(container, amulet_nbt.ListTag):
        for edit in edits:
            refuse(outcome, edit, "node_missing", "目標的父節點不是 list")
        return 0

    # **快照在任何一筆寫入之前。** 這一批次裡每一筆 edit 的守門都要對照這份
    # 快照，不能對照批次裡另一筆 edit 剛剛造成的形狀變化——那正是本函式存在
    # 的理由。
    original = list(container)

    pending: list[tuple[int, dict, str]] = []
    for edit in edits:
        index = list(NodePath.from_json(edit["node_path"]))[-1].i
        if index >= len(original):
            refuse(outcome, edit, "node_missing", f"list 只有 {len(original)} 個元素")
            continue
        current = _guarded_encoding(original[index], edit, outcome)
        if current is None:
            continue
        pending.append((index, edit, current))

    if not pending:
        return 0

    working = container
    written = 0
    for index, edit, current in pending:
        working, ok = _write_index_edit(working, index, edit, current, outcome)
        if ok:
            written += 1

    _replace_list(root, parent_steps, working)
    return written


def _write_index_edit(
    working: amulet_nbt.ListTag,
    index: int,
    edit: dict[str, Any],
    current: str,
    outcome: ApplyOutcome,
) -> tuple[amulet_nbt.ListTag, bool]:
    """把一筆 index 結尾的 edit 寫進 `working`，回傳（可能是新物件的）list 與是否寫成。

    `current` 是這個索引**在快照當下**的形狀（由 `_guarded_encoding` 算出），
    不是呼叫當下 `working[index]` 的形狀——兩者在批次處理的第二筆以後會不一樣，
    但 `in_place.value_tag` 該收的就是快照那個。
    """
    from mcmt.write import in_place  # 延遲匯入，避免與 in_place.py 互相匯入成環

    if edit["value"].get("kind") == "literal":
        try:
            tag = in_place.value_tag(current, edit["value"])
        except in_place.UnsupportedInPlaceShape as exc:
            refuse(outcome, edit, "unsupported_encoding", str(exc))
            return working, False
        working[index] = tag
        return working, True

    writer = _translate_writer(edit)
    result = writer.apply_to_list(working, index, writer.value_tag(edit["value"]))
    if result.promoted:
        outcome.counts["list_promotions"] += 1
    return result.list, True


def _apply_to_key(root, steps, edit: dict, outcome: ApplyOutcome) -> bool:
    from mcmt.write import in_place  # 延遲匯入，避免與 in_place.py 互相匯入成環

    name = steps[-1].name
    try:
        parent = _resolve(root, steps[:-1])
    except (KeyError, IndexError) as exc:
        refuse(outcome, edit, "node_missing", str(exc))
        return False

    if not isinstance(parent, amulet_nbt.CompoundTag) or name not in parent:
        refuse(outcome, edit, "node_missing", f"找不到鍵 {name}")
        return False

    current = _guarded_encoding(parent[name], edit, outcome)
    if current is None:
        return False

    if edit["value"].get("kind") == "literal":
        try:
            tag = in_place.value_tag(current, edit["value"])
        except in_place.UnsupportedInPlaceShape as exc:
            refuse(outcome, edit, "unsupported_encoding", str(exc))
            return False
        parent[name] = tag
        return True

    writer = _translate_writer(edit)
    parent[name] = writer.value_tag(edit["value"])
    return True


def _translate_writer(edit: dict):
    """DV < 4325 寫 JSON 字串、DV >= 4325 寫 compound。與容器種類無關——
    `.dat` 檔一樣有自己的 DataVersion，一樣分兩個世代（見本檔案的實測表）。"""
    from mcmt.write import legacy, native

    return (
        legacy
        if generation_of(edit["container"]["data_version"]).legacy_json_is_content
        else native
    )


def _guarded_encoding(tag, edit: dict, outcome: ApplyOutcome) -> str | None:
    try:
        current = sniff(tag).encoding.value
    except TypeError:
        refuse(outcome, edit, "unsupported_encoding", "這個節點不是文字節點")
        return None
    expected = edit["expected_encoding"]
    # `plain_string` 是欄位決定的形狀（`level_name` 等），不是值決定的形狀——
    # `sniff()` 只看得到值本身，一個裸字串節點永遠回報 `bare_string`，絕不會
    # 回報 `plain_string`（component.py 的說明）。所以這裡不能直接比對字串
    # 相等：那會讓每一筆 `plain_string` 的 edit 在守門這關就被拒寫，不管世界
    # 有沒有真的被改過。守門要問的是「形狀變了嗎」，而 `plain_string` 這個
    # 欄位唯一合法的磁碟形狀就是 `bare_string`——兩者一致代表沒變。
    if current == "bare_string" and expected == "plain_string":
        current = expected
    if current != expected:
        refuse(
            outcome,
            edit,
            "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current}"
            f"——世界在 extract 之後被改過了",
        )
        return None

    # **形狀沒變不代表內容沒變。** `in_place` 保留節點既有的形狀，使用者若在
    # extract 之後自己把節點的字改了（沒動形狀），上面那關完全看不出來——
    # `occurrence.raw_snapshot` 就是為了補這一層才存在的欄位。`None` 代表
    # `compound_tree`（沒有單一字串能代表整個節點）或這份 edit 來自
    # raw_snapshot 接上之前的舊 editplan，兩種都跳過這關，只看形狀。
    expected_raw = edit.get("raw_snapshot")
    if expected_raw is not None:
        actual_raw = _current_raw_text(tag, current)
        if actual_raw != expected_raw:
            refuse(
                outcome,
                edit,
                "node_changed",
                f"形狀還是 {current}，但內容變了"
                f"——世界在 extract 之後被改過了",
            )
            return None
    return current


def _current_raw_text(tag, encoding: str) -> str | None:
    """節點**現在**的字面值，算法跟 `extract/build.py` 的 `_raw_snapshot()`
    刻意對稱——兩邊比對的必須是同一個定義，不然這道守門在說謊。"""
    if encoding == "text_compound":
        return str(tag["text"])
    if encoding == "empty_key_compound":
        return str(tag[""])
    if isinstance(tag, amulet_nbt.StringTag):
        return str(tag)
    return None


def _resolve(root, steps):
    current = root
    for step in steps:
        if step.t == "key":
            if step.name not in current:
                raise KeyError(f"找不到鍵 {step.name}")
            current = current[step.name]
        elif step.t == "index":
            current = current[step.i]
        else:
            raise KeyError("v1 的寫入路徑不支援 decode 步驟")
    return current


def _replace_list(root, steps, new_list) -> None:
    parent = _resolve(root, steps[:-1])
    last = steps[-1]
    if last.t == "key":
        parent[last.name] = new_list
    else:
        parent[last.i] = new_list


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_TOKEN = re.compile(r"\[\[\d+\]\]")


def refuse_residue(text: str) -> None:
    """任何 `literal` 的文字若殘留 `[[n]]`，**拒絕整份 plan**。

    不是「跳過這一筆」：殘留代表上游（後端或驗證）算錯了，而算錯的東西不會只錯一筆。
    寫出去玩家會看到那串記號。
    """
    found = _TOKEN.findall(text)
    if found:
        raise PlaceholderResidueError(text=text, tokens=found)


def component_for(value: dict[str, Any]) -> Any:
    """editplan 的 value → 一棵 component（純 Python，還沒變成 NBT）。"""
    kind = value.get("kind")

    if kind == "translate":
        component: dict[str, Any] = {"translate": value["key"]}
        if value.get("fallback"):
            component["fallback"] = value["fallback"]
        component.update(value.get("style") or {})
        return component

    if kind == "literal":
        refuse_residue(value["text"])
        component = {"text": value["text"]}
        component.update(value.get("style") or {})
        return component

    if kind == "component":
        return value["tree"]

    raise ValueError(f"不認得的寫入值種類：{kind!r}")
