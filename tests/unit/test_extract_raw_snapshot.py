# SPDX-License-Identifier: GPL-3.0-or-later
"""`occurrence.raw_snapshot`（已知缺口，2026-08-31 補齊）。

合約裡的欄位描述："Byte-exact original value at this node, when it was a
string. Used by the writer's expected-encoding guard to detect that the world
changed under a stale plan." ——`extract` 此前一律填 `None`，`write/` 那邊
自然也沒有人用它。這裡先補上 extract 這一半：把這一刻磁碟上的字面值記下來。

`expected_encoding` 守門看得到「形狀變了」，看不到「形狀沒變但內容變了」
（`in_place` 保留形狀，使用者把箱子從「補給箱」改名成「彈藥箱」，形狀還是
`bare_string`，守門看不出來）。`raw_snapshot` 就是為了補那個洞——但它只在
「這個節點就是一段孤立文字」時有意義，`compound_tree`（帶 `extra`／
`click_event` 等結構）沒有單一字串能代表整個節點，所以刻意留 `None`。
"""

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.extract.build import build_units


def chest(custom_name, *, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:chest")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    tag["CustomName"] = custom_name
    return tag


def sign(*lines, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag([amulet_nbt.StringTag(l) for l in lines])
    tag["front_text"] = face
    return tag


def chunk_with(*entities, data_version=4671):
    root = modern_chunk(data_version=data_version)
    root["block_entities"] = amulet_nbt.ListTag(list(entities))
    return root


def world_with(tmp_path, chunk, *, name="world"):
    world = tmp_path / name
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, chunk).build())
    return world


def occurrence_of(result, category):
    (unit,) = [u for u in result.units if u.category == category]
    (occurrence,) = unit.occurrences
    return occurrence


def test_a_bare_string_keeps_its_literal_text_as_the_snapshot(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(chest(amulet_nbt.StringTag("補給箱"))))

    result = build_units(world)

    occurrence = occurrence_of(result, "block_entity_name")
    assert occurrence.encoding == "bare_string"
    assert occurrence.raw_snapshot == "補給箱"


def test_a_text_compound_snapshots_the_inner_text_key(tmp_path) -> None:
    world = world_with(
        tmp_path,
        chunk_with(
            chest(amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("Star Stealer")}))
        ),
    )

    result = build_units(world)

    occurrence = occurrence_of(result, "block_entity_name")
    assert occurrence.encoding == "text_compound"
    assert occurrence.raw_snapshot == "Star Stealer"


def test_an_empty_key_compound_snapshots_the_inner_empty_key(tmp_path) -> None:
    world = world_with(
        tmp_path,
        chunk_with(
            chest(amulet_nbt.CompoundTag({"": amulet_nbt.StringTag("Ultra Health Potion")}))
        ),
    )

    result = build_units(world)

    occurrence = occurrence_of(result, "block_entity_name")
    assert occurrence.encoding == "empty_key_compound"
    assert occurrence.raw_snapshot == "Ultra Health Potion"


def test_a_legacy_json_scalar_snapshots_the_quoted_disk_string(tmp_path) -> None:
    """byte-exact 是指**磁碟上那個 StringTag 的字面值**，含引號——不是解析後
    的內容。守門比對的是「這個節點現在的字面值」，跟 sniff() 的 raw 是同一份。"""
    world = world_with(
        tmp_path,
        chunk_with(chest(amulet_nbt.StringTag('"Supply Crate"')), data_version=3700),
    )

    result = build_units(world)

    occurrence = occurrence_of(result, "block_entity_name")
    assert occurrence.encoding == "json_string_scalar"
    assert occurrence.raw_snapshot == '"Supply Crate"'


def test_a_compound_tree_has_no_snapshot(tmp_path) -> None:
    """帶 `extra` 的樹沒有單一字串能代表整個節點——snapshot 是 None，不是硬湊
    一個只反映得出第一段文字的字串（那會讓「只改樣式沒改字」被誤判成內容變了，
    「改了文字但骨架恰好一樣」又可能誤判成沒變）。"""
    entity = sign("", "", "", "")
    entity["front_text"]["messages"] = amulet_nbt.ListTag(
        [
            amulet_nbt.CompoundTag(
                {
                    "text": amulet_nbt.StringTag("父"),
                    "extra": amulet_nbt.ListTag(
                        [amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("子")})]
                    ),
                }
            )
        ]
    )
    world = world_with(tmp_path, chunk_with(entity))

    result = build_units(world)

    occurrence = occurrence_of(result, "sign")
    assert occurrence.encoding == "compound_tree"
    assert occurrence.raw_snapshot is None


def test_the_raw_snapshot_survives_into_the_extract_document(tmp_path) -> None:
    """M13b 那個 bug 的重演方式：`build.py` 算對了，`emit.py` 卻硬寫 `None`。"""
    from mcmt.extract.emit import build_extract_document

    world = world_with(tmp_path, chunk_with(chest(amulet_nbt.StringTag("補給箱"))))
    result = build_units(world)
    document = build_extract_document(
        result,
        world_name="world",
        world_fingerprint="blake2b:0011223344556677",
        level_data_version=4671,
        namespace="mcmt",
        target_languages=["zh_tw"],
    )

    (unit,) = [u for u in document["units"] if u["category"] == "block_entity_name"]
    assert unit["occurrences"][0]["raw_snapshot"] == "補給箱"
