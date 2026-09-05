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
