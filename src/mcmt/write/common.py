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
"""

import re
from collections import Counter
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

    if edit["value"].get("kind") == "literal":
        try:
            tag = in_place.value_tag(current, edit["value"])
        except in_place.UnsupportedInPlaceShape as exc:
            refuse(outcome, edit, "unsupported_encoding", str(exc))
            return False
        container[index] = tag
        return True

    writer = _translate_writer(edit)
    result = writer.apply_to_list(container, index, writer.value_tag(edit["value"]))
    _replace_list(root, steps[:-1], result.list)
    if result.promoted:
        outcome.counts["list_promotions"] += 1
    return True


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
    if current != edit["expected_encoding"]:
        refuse(
            outcome,
            edit,
            "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current}"
            f"——世界在 extract 之後被改過了",
        )
        return None
    return current


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
