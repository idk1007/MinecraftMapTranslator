# SPDX-License-Identifier: GPL-3.0-or-later
"""`write/command_span.py` 的單元測試——指令字串內部的 splice 原語。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §4、§5 與
.superpowers/sdd/2026-09-05-command-text-implementation/task-7-brief.md。
"""

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
