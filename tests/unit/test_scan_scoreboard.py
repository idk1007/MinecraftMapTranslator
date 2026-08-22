# SPDX-License-Identifier: GPL-3.0-or-later
"""`data/scoreboard.dat` 掃描（M13.6）。

[實測 2026-08-22] 根是兩個並列鍵：`data`（內容）與 `DataVersion`（整數，**不在**
`data` 裡面）——與 `level.dat` 的巢狀形狀不同，這是兩個檔案的真實差異。

`Objectives[].Name`／`CriteriaName`／`Teams[].Name` 是識別碼，denylist 在 M13a
就擋好了（見 `tests/unit/test_rules_denylist.py`），這裡不重測。
"""

from collections import Counter

import amulet_nbt

from mcmt.nbtio.datfile import DatFile, write_dat
from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources import scoreboard


def world_with(project, data: amulet_nbt.CompoundTag, *, data_version=4671):
    """`write_dat` 過 `ensure_writable`，所以世界得落在 sandbox 底下（`project`
    fixture 把 `sandbox_root()` 指到 `tmp_path/sandbox`）——不能直接寫
    `tmp_path/data/scoreboard.dat`。跟 `test_scan_level_dat.py` 同一套模式。"""
    world_dir = project / "sandbox" / "world"
    target = world_dir / "data" / "scoreboard.dat"
    root = amulet_nbt.CompoundTag({"data": data, "DataVersion": amulet_nbt.IntTag(data_version)})
    write_dat(target, DatFile(tag=amulet_nbt.NamedTag(root, ""), compression="gzip"))
    return ensure_readable(world_dir)


def objective(name="obj1", display="顯示名稱", criteria="dummy"):
    return amulet_nbt.CompoundTag(
        {
            "Name": amulet_nbt.StringTag(name),
            "CriteriaName": amulet_nbt.StringTag(criteria),
            "DisplayName": amulet_nbt.StringTag(display),
        }
    )


def team(name="team1", display="隊伍名稱", prefix=None, suffix=None):
    fields = {"Name": amulet_nbt.StringTag(name), "DisplayName": amulet_nbt.StringTag(display)}
    if prefix is not None:
        fields["MemberNamePrefix"] = amulet_nbt.StringTag(prefix)
    if suffix is not None:
        fields["MemberNameSuffix"] = amulet_nbt.StringTag(suffix)
    return amulet_nbt.CompoundTag(fields)


def test_an_objective_display_name_is_found(project) -> None:
    data = amulet_nbt.CompoundTag({"Objectives": amulet_nbt.ListTag([objective()])})
    world = world_with(project, data)
    stats = Counter()

    found = [n.node for n in scoreboard.scan(world, stats) if n.node.category == "objective"]

    assert len(found) == 1
    assert str(found[0].tag) == "顯示名稱"
    assert found[0].path.to_json() == [
        {"t": "key", "name": "data"},
        {"t": "key", "name": "Objectives"},
        {"t": "index", "i": 0},
        {"t": "key", "name": "DisplayName"},
    ]


def test_the_container_reads_data_version_from_the_sibling_key(project) -> None:
    """**這是與 `level.dat` 的差異點。** `DataVersion` 是根的兄弟節點，不在 `data` 裡。"""
    data = amulet_nbt.CompoundTag({"Objectives": amulet_nbt.ListTag([objective()])})
    world = world_with(project, data, data_version=3700)
    stats = Counter()

    (first, *_) = list(scoreboard.scan(world, stats))

    assert first.container == {
        "kind": "scoreboard_dat",
        "path": "data/scoreboard.dat",
        "dimension": None,
        "chunk": None,
        "data_version": 3700,
        "compression": None,
        "external": False,
    }


def test_a_team_yields_display_name_and_both_affixes(project) -> None:
    data = amulet_nbt.CompoundTag(
        {"Teams": amulet_nbt.ListTag([team(display="紅隊", prefix="[紅] ", suffix=" (R)")])}
    )
    world = world_with(project, data)
    stats = Counter()

    found = list(scoreboard.scan(world, stats))
    by_category = {n.node.category: str(n.node.tag) for n in found}

    assert by_category["team"] == "紅隊"
    assert by_category["team_affix"] in ("[紅] ", " (R)")
    affix_values = {str(n.node.tag) for n in found if n.node.category == "team_affix"}
    assert affix_values == {"[紅] ", " (R)"}


def test_a_team_without_affixes_yields_no_team_affix_nodes(project) -> None:
    """[實測] `100 Ways To Die`（native）的隊伍根本沒有這兩個欄位——省略不是錯誤。"""
    data = amulet_nbt.CompoundTag({"Teams": amulet_nbt.ListTag([team()])})
    world = world_with(project, data)
    stats = Counter()

    found = [n.node for n in scoreboard.scan(world, stats) if n.node.category == "team_affix"]

    assert found == []


def test_the_name_and_criteria_name_fields_are_not_yielded(project) -> None:
    """這個來源是白名單，本來就不去碰 `Name`/`CriteriaName`——不是靠 denylist 擋，
    是壓根不掃它們。"""
    data = amulet_nbt.CompoundTag(
        {
            "Objectives": amulet_nbt.ListTag([objective(name="internal_id_123")]),
            "Teams": amulet_nbt.ListTag([team(name="internal_team_id")]),
        }
    )
    world = world_with(project, data)
    stats = Counter()

    texts = {str(n.node.tag) for n in scoreboard.scan(world, stats)}

    assert "internal_id_123" not in texts
    assert "internal_team_id" not in texts


def test_a_missing_scoreboard_dat_yields_nothing(tmp_path) -> None:
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(scoreboard.scan(world, stats)) == []
