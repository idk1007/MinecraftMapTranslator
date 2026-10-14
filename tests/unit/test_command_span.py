# SPDX-License-Identifier: GPL-3.0-or-later
"""`write/command_span.py` 的單元測試——指令字串內部的 splice 原語。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §4、§5 與
.superpowers/sdd/2026-09-05-command-text-implementation/task-7-brief.md。

**每一條 splice 測試都要跑一次 `assert_command_reparses()`**（`tests/conftest.py`）。
斷言「結果字串等於這一串」驗的是我們**預期**寫出去的東西；`assert_command_reparses`
驗的是**遊戲**還吃不吃得下它。C2 證明這兩件事會分家：span 完全正確、位移一個
都沒錯，塞進去的東西型別卻是錯的。
"""

import amulet_nbt
from conftest import assert_command_reparses

from mcmt.write.command_span import apply_command_edits
from mcmt.write.common import ApplyOutcome


def _edit(span, value, unit_id="u:command_component_text:aaaaaaaaaaaaaaaa"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": unit_id,
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": None},
            {"t": "decode", "codec": "json_component", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "text_compound",
        "value": {
            "kind": "translate",
            "key": "mcmt.command_component_text.aaaaaaaaaaaaaaaa",
            "fallback": "Hello",
            "style": None,
        },
    }


def test_a_single_l1_edit_replaces_just_its_span():
    original = 'tellraw @a {"text":"Hello"}'
    span = (original.index("{"), len(original))
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [_edit(span, None)], outcome=outcome)

    assert result == (
        'tellraw @a {"translate":"mcmt.command_component_text.aaaaaaaaaaaaaaaa",'
        '"fallback":"Hello"}'
    )
    assert not outcome.unwritten
    assert_command_reparses(result)


def test_a_string_wrapped_json_leaf_is_re_escaped_correctly():
    """spec §4 的例子：messages 元素是一個 SNBT 字串常值，內容才是 JSON。
    直接在絕對位移上 splice 新的 JSON 文字會切壞指令（外層引號被提前閉合）；
    正確結果必須把新值重新包成一個跳脫過的 SNBT 字串常值。"""
    original = 'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}'
    inner_start = original.index('"{')
    inner_end = original.index('}"') + 2
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:bbbbbbbbbbbbbbbb",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": None},
            {"t": "decode", "codec": "snbt", "arg": None, "span": [24, len(original)]},
            {
                "t": "decode",
                "codec": "json_component",
                "arg": None,
                "span": [inner_start, inner_end],
            },
        ],
        "expected_encoding": "json_string_object",
        "value": {
            "kind": "translate",
            "key": "mcmt.command_component_text.bbbbbbbbbbbbbbbb",
            "fallback": "Hello",
            "style": None,
        },
    }
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [edit], outcome=outcome)

    # 錯誤做法（沒有重新跳脫，直接把序列化出的 JSON 字面塞回去）會產出
    # `messages:["{"translate":...}"]}`——內層的 `"translate"` 引號沒有跳脫，
    # 提前閉合了外層的 SNBT 字串常值。正確結果裡，內層每個引號都帶 `\`。
    assert '"translate"' not in result
    assert '\\"translate\\"' in result
    assert result == (
        'data merge block ~ ~ ~ {messages:['
        '"{\\"translate\\":\\"mcmt.command_component_text.bbbbbbbbbbbbbbbb\\",'
        '\\"fallback\\":\\"Hello\\"}"]}'
    )
    assert not outcome.unwritten
    assert_command_reparses(result)


def test_two_edits_in_the_same_snbt_argument_do_not_collide():
    original = (
        'data merge block ~ ~ ~ {front_text:{messages:'
        '[{text:"Line 1"},{text:"Line 2"}]}}'
    )
    line1_start = original.index('{text:"Line 1"}')
    line1_end = line1_start + len('{text:"Line 1"}')
    line2_start = original.index('{text:"Line 2"}')
    line2_end = line2_start + len('{text:"Line 2"}')

    def edit(span, key_suffix, fallback):
        return {
            "occurrence_id": f"o:{key_suffix}",
            "unit_id": f"u:command_component_text:{key_suffix}",
            "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
            "node_path": [
                {"t": "key", "name": "Command"},
                {"t": "decode", "codec": "command", "arg": None, "span": None},
                {"t": "decode", "codec": "snbt", "arg": None, "span": list(span)},
            ],
            "expected_encoding": "compound_tree",
            "value": {
                "kind": "translate",
                "key": f"mcmt.command_component_text.{key_suffix}",
                "fallback": fallback,
                "style": None,
            },
        }

    edits = [
        edit((line1_start, line1_end), "1111111111111111", "Line 1"),
        edit((line2_start, line2_end), "2222222222222222", "Line 2"),
    ]
    outcome = ApplyOutcome()

    result = apply_command_edits(original, edits, outcome=outcome)

    # `snbt` codec 不忠實往返（`amulet_nbt.to_snbt()` 依字母排序鍵、帶空格）——
    # 這裡序列化的是我們自己新產生的值，不是路過的既有節點，排序差異不違反
    # 外科式寫入（CLAUDE.md 一節第 4 條只保護「沒被修改的節點」）。
    assert (
        '{fallback: "Line 1", translate: "mcmt.command_component_text.1111111111111111"}'
        in result
    )
    assert (
        '{fallback: "Line 2", translate: "mcmt.command_component_text.2222222222222222"}'
        in result
    )
    # 兩段都在，而且中間的逗號、外層的 front_text/messages 結構完全沒被動過。
    assert result.startswith("data merge block ~ ~ ~ {front_text:{messages:[")
    assert result.endswith("]}}")
    assert not outcome.unwritten
    assert_command_reparses(result)


def test_command_say_text_splices_raw_text_without_component_wrapping():
    """`command_say_text`（in_place、literal kind）沒有 component 包裝——值是
    直接的文字，不經過 `component_for()`。"""
    original = "say Hello world"
    span = (len("say "), len(original))
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_say_text:cccccccccccccccc",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": "哈囉世界", "style": None},
    }
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [edit], outcome=outcome)

    assert result == "say 哈囉世界"
    assert not outcome.unwritten
    assert_command_reparses(result)


def test_a_bare_string_merge_message_stays_a_string_and_the_command_reparses():
    """**C2 迴歸**：`data merge` 的訊息是一句沒有格式的裸文字時，寫回去的東西
    必須**還是一個字串常值**，不能是一個 SNBT compound。

    `messages:["Hello","","",""]` 是最常見的告示牌形狀（一行字＋三行空）。把
    `{translate:…}` compound splice 進去，位移一個都沒錯，產出的卻是
    **異質 `TAG_List`**——`TAG_List` 在 NBT 格式層帶單一元素型別 id，1.21.11 的
    指令解析器跟 amulet 一樣吃不下它（CLAUDE.md 二節「NBT list 同型」）。指令
    方塊被寫進磁碟、指令再也跑不動，而 `apply_report` 說 `unwritten: []`——一次
    乾淨的成功。地圖的告示牌從此不會被寫出來，沒有任何跡象。

    `write/native.py::apply_to_list` 對**真的** NBT list 一直在守這條不變式
    （並計 `list_promotions`）；指令 splice 這條路整個繞過那個寫入器，所以保護
    就是不在——CLAUDE.md 五節「舊範圍下碰巧成立的不變式」的教科書實例。

    修法（控制者裁定）：裸字串那一支改走 `in_place`（`command_say_text`），
    直接換掉字串常值的**內容**，list 維持全字串。這裡從 `scan_command_string`
    一路跑到 `apply_edits`，兩端一起驗——只驗 writer 的話，scan 端把 category
    改回去也不會紅。
    """
    from collections import Counter

    from mcmt.model.node import NodePath, key_step
    from mcmt.model.strategy import strategy_for
    from mcmt.scan.command import scan_command_string
    from mcmt.write.common import apply_edits

    original = 'data merge block ~ ~ ~ {front_text:{messages:["Hello","","",""]}}'
    stats: Counter = Counter()
    (node,) = list(
        scan_command_string(
            original, base_path=NodePath([key_step("Command")]), anchor=None, stats=stats
        )
    )

    # 裸字串訊息**沒有地方可以放 translate key**（放了就破壞 list 同型），所以
    # 它必須被判成 in_place——這是本次修正的 scan 端斷言。
    assert strategy_for(node.category) == "in_place"

    edit = {
        "occurrence_id": "o:00001",
        "unit_id": f"u:{node.category}:eeeeeeeeeeeeeeee",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca", "data_version": 4671},
        "node_path": [step.to_json() for step in node.path],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": "哈囉", "style": None},
    }
    root = amulet_nbt.CompoundTag({"Command": amulet_nbt.StringTag(original)})
    outcome = ApplyOutcome()

    written = apply_edits(root, [edit], outcome)
    result = str(root["Command"])

    assert written == 1
    assert not outcome.unwritten
    # 這一行就是修正前紅的地方：異質 list 解不回來。
    assert_command_reparses(result)

    document = amulet_nbt.from_snbt(result[result.index("{") :])
    messages = document["front_text"]["messages"]
    assert all(isinstance(m, amulet_nbt.StringTag) for m in messages)
    assert [str(m) for m in messages] == ["哈囉", "", "", ""]


def test_a_bare_string_merge_message_escapes_quotes_and_backslashes():
    """裸字串走的是「換掉字串常值的內容」，所以譯文裡的 `"` 與 `\\` 必須跳脫
    ——不跳脫的話一個引號就提前閉合了常值，指令一樣壞掉。這是把譯文當**資料**
    而不是當**語法**的那條線。"""
    from collections import Counter

    from mcmt.model.node import NodePath, key_step
    from mcmt.scan.command import scan_command_string
    from mcmt.write.common import apply_edits

    original = 'data merge block ~ ~ ~ {front_text:{messages:["Hello","","",""]}}'
    stats: Counter = Counter()
    (node,) = list(
        scan_command_string(
            original, base_path=NodePath([key_step("Command")]), anchor=None, stats=stats
        )
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": f"u:{node.category}:ffffffffffffffff",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca", "data_version": 4671},
        "node_path": [step.to_json() for step in node.path],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": '他說「"好"」\\結束', "style": None},
    }
    root = amulet_nbt.CompoundTag({"Command": amulet_nbt.StringTag(original)})
    outcome = ApplyOutcome()

    apply_edits(root, [edit], outcome)
    result = str(root["Command"])

    assert not outcome.unwritten
    assert_command_reparses(result)
    document = amulet_nbt.from_snbt(result[result.index("{") :])
    assert str(document["front_text"]["messages"][0]) == '他說「"好"」\\結束'


def test_no_edit_succeeding_returns_none():
    original = 'tellraw @a {"text":"Hello"}'
    edit = _edit((0, 0), None)  # 空 span，故意讓組字失敗
    edit["node_path"][-1]["span"] = None
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [edit], outcome=outcome)

    assert result is None
    assert outcome.unwritten


def test_a_node_path_with_no_leading_key_step_works_the_same_way():
    """`.mcfunction` 的 node_path 沒有指令方塊那種 `key("Command")` 前綴——
    decode 鏈直接從第一步開始。type-based 篩選（`step.t == "decode"`）不需要
    知道前面有幾步 key/index，這條測試就是要證明沒有前綴步驟時一樣正確。"""
    original = 'tellraw @a {"text":"Hello"}'
    span = (original.index("{"), len(original))
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:dddddddddddddddd",
        "container": {"kind": "datapack_function", "path": "data/x/functions/y.mcfunction"},
        "node_path": [
            {"t": "decode", "codec": "command", "arg": None, "span": None},
            {"t": "decode", "codec": "json_component", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "text_compound",
        "value": {
            "kind": "translate",
            "key": "mcmt.command_component_text.dddddddddddddddd",
            "fallback": "Hello",
            "style": None,
        },
    }
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [edit], outcome=outcome)

    assert result == (
        'tellraw @a {"translate":"mcmt.command_component_text.dddddddddddddddd",'
        '"fallback":"Hello"}'
    )
    assert not outcome.unwritten
    assert_command_reparses(result)


# --- 缺口 E：控制字元 ---------------------------------------------------------
#
# amulet 的 `from_snbt` 收得下裸換行、也不認 `\n` 跳脫（兩個字元原樣保留），
# 所以 `assert_command_reparses()` 單獨抓不到這一格：它會說「解得回來」，而
# 1.21.11 的指令解析器說不。這幾條因此直接斷言「輸出裡沒有任何控制字元」，
# 再用 `_minecraft_unescape()` 照 1.21.5+ SNBT 的跳脫規則解回去比對原文。


def _minecraft_unescape(literal: str) -> str:
    """把一個雙引號 SNBT 字串常值照 Minecraft 1.21.5+ 的跳脫規則解回原文。
    **刻意不重用 `write/command_span.py` 的任何東西**——跟 conftest 的
    `assert_command_reparses` 同一個理由：被測的程式碼錯了，兩邊不能一起錯。"""
    assert literal[0] == literal[-1] == '"'
    body = literal[1:-1]
    simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "\\": "\\", '"': '"'}
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in simple:
            out.append(simple[nxt])
            i += 2
        elif nxt == "u":
            out.append(chr(int(body[i + 2 : i + 6], 16)))
            i += 6
        else:
            raise AssertionError(f"不認得的跳脫 \\{nxt}：{literal!r}")
    return "".join(out)


def _has_control_char(text: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text)


def _bare_merge_edit(text: str):
    from collections import Counter

    from mcmt.model.node import NodePath, key_step
    from mcmt.scan.command import scan_command_string

    original = 'data merge block ~ ~ ~ {front_text:{messages:["Hello","","",""]}}'
    (node,) = list(
        scan_command_string(
            original, base_path=NodePath([key_step("Command")]), anchor=None, stats=Counter()
        )
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": f"u:{node.category}:ffffffffffffffff",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca", "data_version": 4671},
        "node_path": [step.to_json() for step in node.path],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": text, "style": None},
    }
    return original, edit


def test_a_bare_string_merge_message_escapes_control_characters():
    """**缺口 E**：譯文裡的換行／歸位／tab 原樣 splice 進去，amulet 收得下，
    1.21.11 的指令解析器收不下；在 `.mcfunction` 裡那個換行還會把實體行切成
    兩行。`_snbt_string_literal` 必須把它們寫成跳脫序列。"""
    from mcmt.write.common import apply_edits

    translated = "第一行\n第二行\r\t尾\x01"
    original, edit = _bare_merge_edit(translated)
    root = amulet_nbt.CompoundTag({"Command": amulet_nbt.StringTag(original)})
    outcome = ApplyOutcome()

    apply_edits(root, [edit], outcome)
    result = str(root["Command"])

    assert not outcome.unwritten
    assert not _has_control_char(result)
    assert_command_reparses(result)
    start = result.index("messages:[") + len("messages:[")
    literal = result[start : result.index('","', start) + 1]
    assert _minecraft_unescape(literal) == translated


def test_a_native_snbt_component_escapes_control_characters_too():
    """原生 SNBT compound 那一格（`{text:"…"}` → `{translate:…,fallback:…}`）
    走的是 amulet 的 `to_snbt()`，它對字串裡的換行一樣原樣輸出。fallback 是原文，
    原文帶換行時同樣會寫出一條解析不了的指令。"""
    from collections import Counter

    from mcmt.model.node import NodePath, key_step
    from mcmt.scan.command import scan_command_string
    from mcmt.write.common import apply_edits

    original = (
        "data merge block ~ ~ ~ {front_text:{messages:["
        '{text:"Hello"},{text:""},{text:""},{text:""}]}}'
    )
    (node,) = list(
        scan_command_string(
            original, base_path=NodePath([key_step("Command")]), anchor=None, stats=Counter()
        )
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:abababababababab",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca", "data_version": 4671},
        "node_path": [step.to_json() for step in node.path],
        "expected_encoding": "text_compound",
        "value": {
            "kind": "translate",
            "key": "mcmt.command_component_text.abababababababab",
            "fallback": "上\n下",
            "style": None,
        },
    }
    root = amulet_nbt.CompoundTag({"Command": amulet_nbt.StringTag(original)})
    outcome = ApplyOutcome()

    apply_edits(root, [edit], outcome)
    result = str(root["Command"])

    assert not outcome.unwritten
    assert not _has_control_char(result)
    assert "\\n" in result
    assert_command_reparses(result)


def test_a_say_translation_with_a_control_character_is_refused():
    """`say`／`me` 的參數是純文字，**沒有任何跳脫語法**——寫 `\\n` 進去遊戲就
    印出反斜線加 n，寫裸換行進 `.mcfunction` 就把一行切成兩行。沒有正確的寫法，
    所以拒寫，而且要說清楚為什麼，不是籠統的「無法組出替換文字」。"""
    original = "say Hello world"
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_say_text:cccccccccccccccc",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": [4, len(original)]},
        ],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": "第一行\n第二行", "style": None},
    }
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [edit], outcome=outcome)

    assert result is None
    assert [item["reason"] for item in outcome.unwritten] == ["unsupported_encoding"]
    assert "控制字元" in outcome.unwritten[0]["detail"]
