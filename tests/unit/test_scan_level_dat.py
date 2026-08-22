# SPDX-License-Identifier: GPL-3.0-or-later
"""`level.dat` 掃描（M13.5）。

三個欄位：`LevelName`（in_place）、`CustomBossEvents.<id>.Name`（translate_key，
[全部遊戲實測]）、`Player.Inventory[]`（走 `scan_item` 的共用遞迴）。

[實測 2026-08-22] `CustomBossEvents` 是用 boss id 當鍵的 compound，不是 list——
`Arena of Darkness` 的 27 個、`100 Ways To Die` 的 3 個都是這個形狀。
"""

from collections import Counter

import amulet_nbt

from mcmt.nbtio.datfile import DatFile, write_dat
from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources import level_dat


def world_with(project, data: amulet_nbt.CompoundTag, *, root_key="Data"):
    """`write_dat` 過 `ensure_writable`，所以世界得落在 sandbox 底下（`project`
    fixture 把 `sandbox_root()` 指到 `tmp_path/sandbox`）——不能直接寫
    `tmp_path/level.dat`。"""
    world_dir = project / "sandbox" / "world"
    target = world_dir / "level.dat"
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({root_key: data}), "")
    write_dat(target, DatFile(tag=tag, compression="gzip"))
    return ensure_readable(world_dir)


def minimal_data(**extra) -> amulet_nbt.CompoundTag:
    fields = {
        "LevelName": amulet_nbt.StringTag("我的世界"),
        "DataVersion": amulet_nbt.IntTag(4671),
    }
    fields.update(extra)
    return amulet_nbt.CompoundTag(fields)


def test_the_level_name_is_found(project) -> None:
    world = world_with(project, minimal_data())
    stats = Counter()

    found = list(level_dat.scan(world, stats))

    names = [n.node.category for n in found]
    assert "level_name" in names
    level_name_node = next(n.node for n in found if n.node.category == "level_name")
    assert str(level_name_node.tag) == "我的世界"
    assert level_name_node.path.to_json() == [
        {"t": "key", "name": "Data"},
        {"t": "key", "name": "LevelName"},
    ]


def test_the_container_reports_this_files_own_data_version(project) -> None:
    world = world_with(project, minimal_data(DataVersion=amulet_nbt.IntTag(3700)))
    stats = Counter()

    (first, *_) = list(level_dat.scan(world, stats))

    assert first.container == {
        "kind": "level_dat",
        "path": "level.dat",
        "dimension": None,
        "chunk": None,
        "data_version": 3700,
        "compression": None,
        "external": False,
    }


def test_custom_boss_events_is_a_compound_keyed_by_id_not_a_list(project) -> None:
    """[實測] 真實形狀是 `Data.CustomBossEvents.<id>.Name`，用 boss id 當鍵。"""
    events = amulet_nbt.CompoundTag(
        {
            "minecraft:hyde": amulet_nbt.CompoundTag(
                {"Name": amulet_nbt.StringTag('"Mr.Hyde"'), "Color": amulet_nbt.StringTag("red")}
            )
        }
    )
    world = world_with(project, minimal_data(CustomBossEvents=events))
    stats = Counter()

    found = [n.node for n in level_dat.scan(world, stats) if n.node.category == "bossbar"]

    assert len(found) == 1
    assert str(found[0].tag) == '"Mr.Hyde"'
    assert found[0].path.to_json() == [
        {"t": "key", "name": "Data"},
        {"t": "key", "name": "CustomBossEvents"},
        {"t": "key", "name": "minecraft:hyde"},
        {"t": "key", "name": "Name"},
    ]


def test_a_boss_without_a_name_is_skipped(project) -> None:
    events = amulet_nbt.CompoundTag(
        {"minecraft:foo": amulet_nbt.CompoundTag({"Color": amulet_nbt.StringTag("red")})}
    )
    world = world_with(project, minimal_data(CustomBossEvents=events))
    stats = Counter()

    found = [n.node for n in level_dat.scan(world, stats) if n.node.category == "bossbar"]

    assert found == []


def test_player_inventory_recurses_through_scan_item(project) -> None:
    sword = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:diamond_sword")})
    sword["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag("屠龍劍")}
    )
    player = amulet_nbt.CompoundTag(
        {"Inventory": amulet_nbt.ListTag([sword])}
    )
    world = world_with(project, minimal_data(Player=player))
    stats = Counter()

    found = [n.node for n in level_dat.scan(world, stats) if n.node.category == "custom_name"]

    assert len(found) == 1
    assert str(found[0].tag) == "屠龍劍"
    assert found[0].path.to_json()[:3] == [
        {"t": "key", "name": "Data"},
        {"t": "key", "name": "Player"},
        {"t": "key", "name": "Inventory"},
    ]


def test_a_world_without_a_player_is_not_an_error(project) -> None:
    """[實測] `100 Ways To Die` 沒有 `Player` 節點——這是合法狀態，不是損壞。"""
    world = world_with(project, minimal_data())
    stats = Counter()

    found = list(level_dat.scan(world, stats))

    assert all(n.node.category != "custom_name" for n in found)


def test_a_missing_level_dat_yields_nothing(tmp_path) -> None:
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(level_dat.scan(world, stats)) == []
    assert stats["skipped_level_dat"] == 0


def test_an_unreadable_level_dat_is_counted_not_fatal(tmp_path) -> None:
    (tmp_path / "level.dat").write_bytes(b"not nbt at all")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(level_dat.scan(world, stats)) == []
    assert stats["skipped_level_dat"] == 1
