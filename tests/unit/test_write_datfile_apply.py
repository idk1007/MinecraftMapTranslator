# SPDX-License-Identifier: GPL-3.0-or-later
"""`.dat` 檔通用寫入器（M13.5）。

`level.dat` 與 `scoreboard.dat` 共用這個寫入器——兩者都是「整份 NBT 檔，改幾個
節點，整份重新編碼」，機制一樣，只是目標路徑不同。這裡不測 `level_dat.py`/
`scoreboard.py` 怎麼掃（那是各自的測試檔），只測「餵一份 editplan 進來，`.dat`
檔正確地被改、備份、原封不動的欄位真的沒動」。
"""

from pathlib import Path

import amulet_nbt
import pytest

from mcmt.nbtio.datfile import DatFile, read_dat, write_dat
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable
from mcmt.write.common import ApplyOutcome
from mcmt.write.datfile_apply import apply_to_datfile


def level_dat(tmp_path: Path, *, level_name="原本的世界", data_version=4671) -> Path:
    target = tmp_path / "level.dat"
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag(level_name),
            "DataVersion": amulet_nbt.IntTag(data_version),
            "Difficulty": amulet_nbt.ByteTag(2),
        }
    )
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({"Data": data}), "")
    write_dat(target, DatFile(tag=tag, compression="gzip"))
    return target


def edit_for_level_name(text: str, *, data_version=4671, expected_encoding="bare_string"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:level_name:aaaaaaaaaaaaaaaa",
        "container": {
            "kind": "level_dat",
            "path": "level.dat",
            "dimension": None,
            "chunk": None,
            "data_version": data_version,
            "compression": None,
            "external": False,
        },
        "node_path": [{"t": "key", "name": "Data"}, {"t": "key", "name": "LevelName"}],
        "expected_encoding": expected_encoding,
        "value": {"kind": "literal", "text": text, "style": None},
    }


def test_a_plain_string_expected_encoding_is_accepted_though_sniff_says_bare_string(
    project,
) -> None:
    """**回歸測試**：M13b Task 8 的端到端測試在真實 fixture 上抓到的 bug。

    `extract/build.py` 對 `level_name` category 把 `occurrence.encoding` 覆寫成
    `plain_string`（避免 `sniff()` 把剛好以 `{`/`"`/`[` 開頭的世界名誤判成
    JSON）。但 `sniff()` 本身**永遠不會**回報 `plain_string`——那是欄位決定的
    形狀，不是值決定的形狀（`model/component.py`），一個裸字串節點永遠回報
    `bare_string`。修好之前 `_guarded_encoding` 直接比對字串相等，於是每一筆
    `level_name` 的 edit 在守門這關就被拒寫成 `node_changed`，不管世界有沒有
    真的被改過——`LevelName` 事實上整個寫不出去。
    """
    world = project / "sandbox"
    target = level_dat(world)
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名", expected_encoding="plain_string")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(target))
    assert str(read_back.tag.compound["Data"]["LevelName"]) == "新的世界名"
    assert outcome.counts["edits_written"] == 1
    assert outcome.unwritten == []


def test_the_level_name_is_replaced_and_the_file_is_backed_up(project) -> None:
    world = project / "sandbox"
    target = level_dat(world)
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(target))
    assert str(read_back.tag.compound["Data"]["LevelName"]) == "新的世界名"
    assert outcome.counts["edits_written"] == 1
    assert outcome.counts["files_rewritten"] == 1
    assert backup.file_count == 1


def test_untouched_fields_are_not_re_encoded_away(project) -> None:
    """**這是整份重編寫入器唯一能驗的「原封不動」層級**：位元組不保證一致
    （M3.2：`.dat` 沒有外科式寫入這回事），但值必須一致。"""
    world = project / "sandbox"
    level_dat(world, data_version=4671)
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(world / "level.dat"))
    data = read_back.tag.compound["Data"]
    assert int(data["DataVersion"]) == 4671
    assert int(data["Difficulty"]) == 2


def test_a_missing_file_refuses_every_edit_without_crashing(project) -> None:
    world = project / "sandbox"
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten == [
        {
            "unit_id": edit["unit_id"],
            "occurrence_id": edit["occurrence_id"],
            "reason": "node_missing",
            "detail": "找不到 level.dat",
        }
    ]


def test_a_changed_node_is_refused_not_overwritten(project) -> None:
    world = project / "sandbox"
    level_dat(world, level_name="有人在中間改過")
    outcome = ApplyOutcome()
    # 磁碟上 LevelName 是 bare_string，但編輯期望 text_compound（形狀不符）
    edit = edit_for_level_name("新的世界名", expected_encoding="text_compound")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    # 編碼不符，守門拒絕
    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"
    # 磁碟上的值保持不變
    read_back = read_dat(ensure_readable(world / "level.dat"))
    assert str(read_back.tag.compound["Data"]["LevelName"]) == "有人在中間改過"


def test_a_legacy_scoreboard_display_name_gets_a_json_string(project) -> None:
    """`scoreboard.dat`：DV < 4325 走 legacy（JSON 字串），與 chunk 世代分派同一套。"""
    target = project / "sandbox" / "scoreboard.dat"
    data = amulet_nbt.CompoundTag(
        {
            "Objectives": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {
                            "Name": amulet_nbt.StringTag("obj1"),
                            "CriteriaName": amulet_nbt.StringTag("dummy"),
                            "DisplayName": amulet_nbt.StringTag('"ReFightTime"'),
                        }
                    )
                ]
            ),
        }
    )
    root = amulet_nbt.CompoundTag({"data": data, "DataVersion": amulet_nbt.IntTag(3700)})
    write_dat(target, DatFile(tag=amulet_nbt.NamedTag(root, ""), compression="gzip"))

    outcome = ApplyOutcome()
    edit = {
        "occurrence_id": "o:00002",
        "unit_id": "u:objective:bbbbbbbbbbbbbbbb",
        "container": {
            "kind": "scoreboard_dat",
            "path": "data/scoreboard.dat",
            "dimension": None,
            "chunk": None,
            "data_version": 3700,
            "compression": None,
            "external": False,
        },
        "node_path": [
            {"t": "key", "name": "data"},
            {"t": "key", "name": "Objectives"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "DisplayName"},
        ],
        "expected_encoding": "json_string_scalar",
        "value": {"kind": "translate", "key": "mcmt.objective.cccccccccccccccc", "fallback": None, "style": None},
    }

    with BackupSet(project / "sandbox") as backup:
        apply_to_datfile(project / "sandbox", "scoreboard.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(target))
    written = str(read_back.tag.compound["data"]["Objectives"][0]["DisplayName"])
    assert written == '{"translate":"mcmt.objective.cccccccccccccccc"}'
