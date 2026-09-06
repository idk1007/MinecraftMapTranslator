# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串內部的 splice 原語——字串進、字串出，完全不碰 amulet_nbt Tag。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §4、§5。

**核心規則**：splice 只在最外層發生一次。每筆 edit 的 decode 鏈記著它是從哪個
codec 解出來的；`_compose_replacement()` 沿著這條鏈由內往外組字（每多一層
「值是一個字串常值、內容才是這段文字」，就多一次跳脫；每多一層「值本來就是
原生 compound/list」，不需要跳脫，直接換方言序列化），最後只在鏈上**最後一個
decode 步驟**記錄的絕對位移做一次替換。**這個函式完全不理解指令語法本身**
——它只知道「這一段字串換成那一段字串」。

**安全網有兩條線，缺一條就漏。**

1. **位置**：切在對的地方，靠 extract 時 span 定位器抓對範圍。
2. **型別**：塞進去的東西型別要對。這條是 2026-09-06 補的——span 可以完全
   正確而型別是錯的：把一棵 component 序列化成 SNBT compound、splice 進一個
   元素全是字串的 `TAG_List`（`data merge` 最常見的告示牌形狀「一行字＋三行
   空」），位移一個都沒錯，產出的卻是異質 list，而 `TAG_List` 在 NBT 格式層
   帶單一元素型別 id，遊戲的指令解析器吃不下（CLAUDE.md 二節「NBT list 同
   型」）。指令方塊被寫進磁碟、指令再也跑不動，報告卻說 `unwritten: []`。
   所以 `_compose_replacement()` 依 `value.kind` 決定要不要包成 SNBT 字串
   常值，而測試端有一條獨立的 `assert_command_reparses()`
   （`tests/conftest.py`）對每一次 splice 的結果問「這還解得回來嗎」。

`write/native.py::apply_to_list` 對**真的** NBT list 一直守著同型不變式（並計
`list_promotions`）；指令 splice 這條路整個繞過那個寫入器，所以那份保護在這裡
就是不在，必須自己重新長出來——CLAUDE.md 五節「舊範圍下碰巧成立的不變式」。

**同一物理字串收到多筆 edit 時必須由後往前 splice**（`span_order()`）——改完
前面那處，後面所有 span 的位移就失效了（`model/node.py` 的說明；[實測] 三層
巢狀確實存在，見 CLAUDE.md 四節）。
"""

from typing import Any

from mcmt.model.node import NodePath, span_order
from mcmt.scan.sources.datapack import _to_amulet
from mcmt.tree.codecs import codec_for
from mcmt.write.common import ApplyOutcome, component_for, refuse, refuse_residue


def apply_command_edits(
    original: str,
    edits: list[dict[str, Any]],
    *,
    outcome: ApplyOutcome,
) -> str | None:
    """`edits` 全部指向同一個物理字串（同一個 `Command` 欄位，或 `.mcfunction`
    同一行）。依 `span_order()` 由後往前 splice，回傳新字串；一筆都沒成功時
    回傳 `None`（呼叫端不寫回、不算 `files_rewritten`）。

    每筆 edit 的 `node_path` 前面可能有任意數量的 `key`/`index` 步驟（指令
    方塊是 `key("Command")` 一步，`.mcfunction` 沒有這種前綴步驟），後面接著
    decode 步驟本身——**用 `step.t == "decode"` 篩出 decode 鏈就好，不需要
    知道前面有幾步 key/index**。這比「用一個位置參數告訴呼叫端從第幾步開始」
    更簡單也更不會出錯：不管前面有 0 步還是 1 步非 decode 步驟，篩出來的
    decode 鏈都是同一個東西。"""
    paths = [NodePath.from_json(edit["node_path"]) for edit in edits]
    ordered = span_order(paths)
    by_id = {id(path): edit for path, edit in zip(paths, edits)}

    text = original
    written = 0
    for path in ordered:
        edit = by_id[id(path)]
        span = path.last_span
        if span is None:
            refuse(outcome, edit, "unsupported_encoding", "指令 edit 缺少 span")
            continue

        decode_chain = [step for step in path if step.t == "decode"]

        replacement = _compose_replacement(edit, decode_chain)
        if replacement is None:
            refuse(outcome, edit, "unsupported_encoding", "無法組出替換文字")
            continue

        text = text[: span[0]] + replacement + text[span[1] :]
        written += 1

    return text if written else None


def _compose_replacement(edit: dict[str, Any], decode_chain: list) -> str | None:
    """由內往外組字。`component_for()` 回傳的是**純 Python dict**（不是
    amulet_nbt tag——見 `write/common.py`），`json_component.encode()` 直接吃
    dict；`snbt.encode()` 要吃 amulet_nbt tag（它呼叫 `value.to_snbt()`），所以
    走 SNBT 方言時要先用 `_to_amulet()`（跟 `scan/command.py` 掃描時共用同一個
    轉換函式）轉一次。"""
    value = edit["value"]
    if not decode_chain:
        return None
    codecs = [step.codec.value for step in decode_chain]
    innermost = codecs[-1]

    if innermost == "command":
        # 沒有 JSON/SNBT 包裝——say/me 的參數本來就是純文字，不是 component，
        # 直接替換文字本身，不透過 component_for()。
        if value is None or value.get("kind") != "literal":
            return None
        text = value["text"]
        refuse_residue(text)
        return text

    if innermost == "snbt" and value is not None and value.get("kind") == "literal":
        # **in_place 的 SNBT leaf：換掉字串常值的內容，不換掉它的型別。**
        #
        # 這一格對應 `data merge` 的訊息本來就是一句沒有格式的裸文字
        # （`messages:["Hello","","",""]`）。它的兄弟元素還是字串，而 `TAG_List`
        # 在 NBT 格式層帶單一元素型別 id——把一棵 component 序列化成 SNBT
        # compound 塞進去，位移完全正確，產出的卻是遊戲解析不了的異質 list
        # （CLAUDE.md 二節「NBT list 同型」）。所以這裡走的是「重新包一個 SNBT
        # 字串常值」，list 維持全字串。
        #
        # 譯文在這裡是**資料不是語法**：`_snbt_string_literal` 負責把 `"` 與
        # `\` 跳脫掉，不然譯文裡一個引號就提前閉合了常值。
        text = value["text"]
        refuse_residue(text)
        return _snbt_string_literal(text)

    plain = component_for(value)
    if plain is None:
        return None
    if innermost == "json_component":
        serialized = codec_for("json_component").encode(plain)
    elif innermost == "snbt":
        serialized = codec_for("snbt").encode(_to_amulet(plain))
    else:
        return None

    # 由內往外：最內層是 json_component、它的直接外層是 snbt，代表這段 JSON
    # 是被一個 SNBT 字串常值包住（不是原生 SNBT compound），序列化結果要重新
    # 包成一個跳脫過的 SNBT 字串常值才能塞回去。
    if len(codecs) >= 2 and codecs[-1] == "json_component" and codecs[-2] == "snbt":
        serialized = _snbt_string_literal(serialized)
    return serialized


def _snbt_string_literal(text: str) -> str:
    """把 `text` 包成一個 SNBT 雙引號字串常值，內部的 `\\` 與 `"` 都跳脫。
    `[待驗]`：這裡選雙引號＋跳脫，Mojang 自己的序列化器是不是傾向換成單引號
    避免跳脫，等 spec §9.3／Task 13 的進遊戲驗證確認。"""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
