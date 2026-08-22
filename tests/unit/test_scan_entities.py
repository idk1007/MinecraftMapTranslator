# SPDX-License-Identifier: GPL-3.0-or-later
"""實體掃描（M13.4）。

實體從 1.17 起存在 `entities/*.mca` 而不是 `region/*.mca`。**只掃 region/ 會漏掉
所有具名生物、盔甲座、展示框與 `text_display` 的浮空文字**——[實測] 100 Ways To Die
有 184 個 text_display 節點（169 個相異），Arena of Darkness 有 333 個具名實體。

格式與 region 完全一樣（同一套 header、同一套壓縮），所以讀寫都沿用
`read_region` / `write_region`。差別只在裡面裝的是 `Entities[]`。
"""

import zlib
from collections import Counter

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, set_offset_entry, write_region_file

from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources.entities import scan, scan_entities_chunk


def entity(entity_id="minecraft:armor_stand", **fields):
    tag = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag(entity_id)})
    tag["Pos"] = amulet_nbt.ListTag(
        [amulet_nbt.DoubleTag(1.5), amulet_nbt.DoubleTag(2.5), amulet_nbt.DoubleTag(3.5)]
    )
    for name, value in fields.items():
        tag[name] = value
    return tag


def chunk_with(*entities, data_version=4671):
    root = modern_chunk(data_version=data_version)
    root["Entities"] = amulet_nbt.ListTag(list(entities))
    return root


def categories_of(root):
    return {node.category for node in scan_entities_chunk(root)}


def test_a_named_entity_is_found():
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "entity_name"
    assert str(node.tag) == "守衛"


def test_a_non_text_tag_in_those_two_keys_is_not_yielded():
    """`is not None` 收得下 IntTag、ListTag、ByteArrayTag——嗅探器會對它們拋
    `TypeError`，而那個例外沒有人接。

    `region.py` 那邊的 `CustomName` 判的是 `isinstance(x, (StringTag, CompoundTag))`，
    這裡要一致。實務上不會有 modded 實體把 `text` 放成別的型別嗎？不知道，而
    「不知道」正是該用白名單型別檢查而不是 `is not None` 的理由。
    """
    root = chunk_with(
        entity(CustomName=amulet_nbt.IntTag(7)),
        entity("minecraft:text_display", text=amulet_nbt.ListTag([])),
    )

    assert list(scan_entities_chunk(root)) == []


def test_a_text_display_is_found():
    """[實測] 現代冒險地圖大量用 text_display 取代盔甲座做浮空文字。"""
    root = chunk_with(
        entity("minecraft:text_display", text=amulet_nbt.StringTag("歡迎光臨"))
    )

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "text_display"
    assert str(node.tag) == "歡迎光臨"


def test_passengers_are_scanned_too():
    """[實測] 100 Ways To Die 有 102 個 text_display 掛在載具上。

    只掃頂層實體會整批漏掉。
    """
    passenger = entity("minecraft:text_display", text=amulet_nbt.StringTag("分數"))
    root = chunk_with(
        entity(Passengers=amulet_nbt.ListTag([passenger]))
    )

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "text_display"
    assert str(node.tag) == "分數"


def test_items_on_an_entity_are_scanned():
    """展示框裡的物品、盔甲座身上的裝備。"""
    held = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:stone")})
    held["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag("聖劍")}
    )
    root = chunk_with(entity("minecraft:item_frame", Item=held))

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "custom_name"
    assert str(node.tag) == "聖劍"


def test_old_armor_items_are_scanned():
    """[實測] Arena of Darkness 的 `ArmorItems[]/tag/display/Name` 有 32 個。"""
    helmet = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:player_head")})
    helmet["tag"] = amulet_nbt.CompoundTag(
        {"display": amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag('{"text":"Steve"}')})}
    )
    root = chunk_with(
        entity(ArmorItems=amulet_nbt.ListTag([helmet]))
    )

    assert categories_of(root) == {"custom_name"}


def test_an_entity_anchor_carries_its_position():
    """實體的座標在 `Pos`，不是 x/y/z。"""
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))

    (node,) = list(scan_entities_chunk(root))

    assert node.anchor["kind"] == "entity"
    assert (node.anchor["x"], node.anchor["y"], node.anchor["z"]) == (1.5, 2.5, 3.5)


def test_mechanic_fields_are_ignored():
    """**白名單。** [實測] `Tags[]` 在 100 Ways To Die 有 96,168 個，全是識別碼。"""
    root = chunk_with(
        entity(
            CustomName=amulet_nbt.StringTag("守衛"),
            Tags=amulet_nbt.ListTag([amulet_nbt.StringTag("SpotlightMarker")]),
            variant=amulet_nbt.StringTag("minecraft:tabby"),
        )
    )

    assert categories_of(root) == {"entity_name"}


def test_the_source_reads_every_entities_file(tmp_path) -> None:
    world = tmp_path / "world"
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))
    write_region_file(
        world / "entities", RegionBuilder().add_chunk_nbt(0, root).build()
    )

    found = list(scan(ensure_readable(world), Counter()))

    assert len(found) == 1
    assert found[0].container["kind"] == "entities_chunk"
    assert found[0].container["path"] == "entities/r.0.0.mca"
    assert found[0].container["data_version"] == 4671


def test_the_source_ignores_region_files(tmp_path) -> None:
    """`region/` 是另一個來源的事。兩邊都掃會讓每個節點出現兩次。"""
    world = tmp_path / "world"
    write_region_file(
        world / "region",
        RegionBuilder().add_chunk_nbt(0, chunk_with(
            entity(CustomName=amulet_nbt.StringTag("不該被這個來源看到"))
        )).build(),
    )

    assert list(scan(ensure_readable(world), Counter())) == []


def test_a_clean_chunk_before_a_broken_one_is_not_lost(tmp_path) -> None:
    """`read_region` 是產生器，`scan()` 不能先 `list()` 整份收集完再迭代。

    這裡在同一張 entities region 裡放一個乾淨的具名實體 chunk（index 0）與一個
    中途讀壞的 chunk（index 1，offset 被改指進 header 磁區）。`list(read_region(...))`
    對一個中途拋例外的產生器不會回傳部分結果——已經成功讀到的 index 0 會連同壞掉的
    index 1 一起被丟棄。真正的串流則會在例外發生前，把 index 0 已經處理好的節點
    留在輸出裡。與 `tests/unit/test_scan_registry.py` 的
    `test_a_clean_chunk_before_a_broken_one_is_not_lost` 是同一個回歸，這裡補上
    `entities/` 那一側的版本。
    """
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))
    data = (
        RegionBuilder()
        .add_chunk_nbt(0, root)
        .add(1, zlib.compress(b"whatever"))
        .build()
    )
    # 把 index 1 的磁區偏移改成 1——落在 header（偏移表 + 時間戳表）裡，讀取時
    # 會在 index 0 已經被 yield 之後才觸發 MalformedRegionError。
    set_offset_entry(data, 1, sector=1, count=1)
    world = tmp_path / "world"
    write_region_file(world / "entities", data)
    stats = Counter()

    found = list(scan(ensure_readable(world), stats))

    assert found, "index 0 的乾淨 chunk 不該因為 index 1 壞掉而憑空消失"
    assert stats["entity_chunks"] == 1
    assert stats["skipped_region"] == 1
