# SPDX-License-Identifier: GPL-3.0-or-later
"""掃描來源註冊表（M13.2）。

M13 之前 `extract/build.py` 自己硬編碼了「走 region 檔」。那在只有一個來源時看不出
問題，加到七個之後它就變成「每加一個來源都要改的那個函式」。

**來源之間是同型的**——每一個都只做「找到文字節點、記下它在哪」，讀出來之後交給
同一套嗅探／攤平／規則引擎。所以這裡抽象沒有藏起任何東西。（寫入器不同型，那邊
維持顯式分派。）
"""

from collections import Counter

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.safety.paths import ensure_readable
from mcmt.scan import registry
from mcmt.scan.node import ScannedNode
from mcmt.scan.sources import region


def sign(*lines, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag(
        [amulet_nbt.StringTag(line) for line in lines]
    )
    tag["front_text"] = face
    return tag


def world_with(tmp_path, *entities, name="world"):
    world = tmp_path / name
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag(list(entities))
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())
    return ensure_readable(world)


def test_every_source_is_callable_with_the_same_signature():
    """註冊表的價值就在於「加一個來源不必改別的地方」。

    簽名一旦漂移，那個價值就沒了——而漂移的症狀是某個來源安靜地不被呼叫。
    """
    assert registry.SOURCES
    for source in registry.SOURCES:
        assert callable(source)


def test_the_region_source_yields_scanned_nodes(tmp_path) -> None:
    world = world_with(tmp_path, sign("歡迎光臨", "", "", ""))
    stats = Counter()

    found = list(region.scan(world, stats))

    assert found
    assert all(isinstance(item, ScannedNode) for item in found)


def test_a_scanned_node_carries_its_container(tmp_path) -> None:
    """container 是寫回去的地址。來源自己產生它——只有來源知道自己讀的是什麼檔案。"""
    world = world_with(tmp_path, sign("歡迎光臨", "", "", ""))

    (first, *_) = list(region.scan(world, Counter()))

    assert first.container["kind"] == "region_chunk"
    assert first.container["path"] == "region/r.0.0.mca"
    assert first.container["data_version"] == 4671
    assert first.container["chunk"] == {"cx": 0, "cz": 0}


def test_an_unreadable_region_is_counted_not_fatal(tmp_path) -> None:
    """一張 region 讀不下去時要記錄並跳過，不讓整次 extract 消失。"""
    world = tmp_path / "broken"
    (world / "region").mkdir(parents=True)
    (world / "region" / "r.0.0.mca").write_bytes(b"not a region file")
    stats = Counter()

    found = list(region.scan(ensure_readable(world), stats))

    assert found == []
    assert stats["skipped_region"] == 1
