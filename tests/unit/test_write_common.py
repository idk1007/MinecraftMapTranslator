# SPDX-License-Identifier: GPL-3.0-or-later
"""`write/common.py` 的節點編輯引擎（M13b）——`apply_edit_to_compound`／`apply_edits`。

這裡只加一個分派點的測試：`node_path` 以 `decode` 步驟結尾時，`apply_edits`
現在委派給 `write/command_span.py::apply_command_edits` 做字串內部的 splice，
而不是無條件 `refuse(..., "unsupported_encoding", ...)`。其餘 key／index 結尾
的行為已經被 `test_write_datfile_apply.py`／`test_write_datapack_apply.py` 覆蓋，
不在這裡重複。
"""

import amulet_nbt

from mcmt.write.common import ApplyOutcome, apply_edits


def test_a_decode_terminated_edit_is_applied_via_command_span():
    original = 'tellraw @a {"text":"Hello"}'
    span = [original.index("{"), len(original)]

    root = amulet_nbt.CompoundTag(
        {
            "block_entities": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {"Command": amulet_nbt.StringTag(original)}
                    )
                ]
            )
        }
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:aaaaaaaaaaaaaaaa",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "block_entities"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": [0, len(original)]},
            {"t": "decode", "codec": "json_component", "arg": None, "span": span},
        ],
        "expected_encoding": "text_compound",
        "value": {
            "kind": "translate",
            "key": "mcmt.command_component_text.aaaaaaaaaaaaaaaa",
            "fallback": "Hello",
            "style": None,
        },
    }
    outcome = ApplyOutcome()

    written = apply_edits(root, [edit], outcome)

    assert written == 1
    assert not outcome.unwritten
    new_command = str(root["block_entities"][0]["Command"])
    assert new_command == (
        'tellraw @a {"translate":"mcmt.command_component_text.aaaaaaaaaaaaaaaa",'
        '"fallback":"Hello"}'
    )
    assert isinstance(root["block_entities"][0]["Command"], amulet_nbt.StringTag)


def test_command_say_text_edit_preserves_the_verb_prefix():
    """`command_say_text`（`say`/`me`）沒有 component 包裝，`node_path` 用兩個
    `decode("command")` 步驟收尾（`scan/command.py` 的 say/me 分支）：第一個
    固定是 `(0, len(original))`，`_command_length_matches` 依賴這個固定的第一
    步；第二個才是 payload 自己的位置，是真正的 splice 目標。這裡驗證的正是
    Task 8 review 抓到的那個 bug——只給一個 span、且 span 起點不是 0 的話，
    `_command_length_matches` 會把每一筆 edit 都當成「世界被改過」拒寫，連
    splice 都碰不到；就算真的碰到 splice，錯的實作也會把整個 `Command` 字串
    換成 payload，`say ` 這個動詞前綴會被一起換掉。"""
    original = "say Hello world"
    span = [original.index("Hello world"), len(original)]

    root = amulet_nbt.CompoundTag(
        {
            "block_entities": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {"Command": amulet_nbt.StringTag(original)}
                    )
                ]
            )
        }
    )
    edit = {
        "occurrence_id": "o:00002",
        "unit_id": "u:command_say_text:bbbbbbbbbbbbbbbb",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "block_entities"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": [0, len(original)]},
            {"t": "decode", "codec": "command", "arg": None, "span": span},
        ],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": "你好世界", "style": None},
    }
    outcome = ApplyOutcome()

    written = apply_edits(root, [edit], outcome)

    assert written == 1
    assert not outcome.unwritten
    new_command = str(root["block_entities"][0]["Command"])
    assert new_command == "say 你好世界"
    assert isinstance(root["block_entities"][0]["Command"], amulet_nbt.StringTag)
