# SPDX-License-Identifier: GPL-3.0-or-later
"""`CustomName` 走 `in_place`（`extract/build.py` + `extract/emit.py`）。

[遊戲實測 M11-3] native chunk 的 `CustomName` 不解析任何形狀——寫進去的 SNBT
`{translate:…}` 在容器 GUI 顯示為字面的大括號。所以 `block_entity_name` 不能走
translate key，譯文得直接寫進節點。

三件事在這裡被釘死：

1. `block_entity_name` 的 `strategy` 是 `in_place`，`key` 是 null；告示牌不受影響。
2. **legacy chunk（DV < 4325）的 CustomName 被 per-occurrence 排除**。那裡
   DataFixerUpper 會解析該欄位，native 的答案不能轉移過去，而那條路徑從沒進過遊戲。
   排除是 per-occurrence 的：同一段原文在 native chunk 的那一份照樣寫。
3. **不可塌縮的 CustomName 整個節點跳過。** `in_place` 沒有辦法表達「每段一個 key」，
   而合約同時要求「collapsible=false ⇒ translate_key」——留著它會產出一份違反自己
   合約的 extract.json。
"""

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.extract.build import build_units
from mcmt.extract.emit import build_extract_document


def chest(custom_name, *, x=1, y=2, z=3, block_id="minecraft:chest"):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag(block_id)
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
    face["messages"] = amulet_nbt.ListTag(
        [amulet_nbt.StringTag(line) for line in lines]
    )
    tag["front_text"] = face
    return tag


def chunk_with(*entities, data_version=4671):
    root = modern_chunk(data_version=data_version)
    root["block_entities"] = amulet_nbt.ListTag(list(entities))
    return root


def world_with(tmp_path, *chunks, name="world"):
    world = tmp_path / name
    builder = RegionBuilder()
    for index, chunk in enumerate(chunks):
        builder.add_chunk_nbt(index, chunk)
    write_region_file(world / "region", builder.build())
    return world


def extract_of(world):
    result = build_units(world, namespace="mcmt")
    return result, build_extract_document(
        result,
        world_name=world.name,
        world_fingerprint="blake2b:0011223344556677",
        level_data_version=4671,
        namespace="mcmt",
        target_languages=["zh_tw"],
    )


def unit_of(document, category):
    return next(u for u in document["units"] if u["category"] == category)


# --- strategy ------------------------------------------------------------


def test_a_custom_name_unit_is_in_place_with_no_key(tmp_path) -> None:
    world = world_with(
        tmp_path, chunk_with(chest(amulet_nbt.StringTag("Supply Crate")))
    )
    _, document = extract_of(world)

    unit = unit_of(document, "block_entity_name")

    assert unit["strategy"] == "in_place"
    assert unit["key"] is None


def test_a_sign_unit_still_goes_through_a_translate_key(tmp_path) -> None:
    """主路徑不能被一起改掉。"""
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, document = extract_of(world)

    unit = unit_of(document, "sign")

    assert unit["strategy"] == "translate_key"
    assert unit["key"] is not None


# --- legacy chunk 的 CustomName 是未測過的寫入路徑 -------------------------


def test_a_custom_name_in_a_legacy_chunk_is_excluded(tmp_path) -> None:
    world = world_with(
        tmp_path,
        chunk_with(chest(amulet_nbt.StringTag('"Supply Crate"')), data_version=3700),
    )
    _, document = extract_of(world)

    (occurrence,) = unit_of(document, "block_entity_name")["occurrences"]

    assert occurrence["excluded"]["reason"] == "untested_write_shape"


def test_the_exclusion_is_per_occurrence_not_per_unit(tmp_path) -> None:
    """同一段原文，native 的那一份照樣要寫得出去。"""
    world = world_with(
        tmp_path,
        chunk_with(chest(amulet_nbt.StringTag("Supply Crate"))),
        chunk_with(chest(amulet_nbt.StringTag('"Supply Crate"')), data_version=3700),
    )
    _, document = extract_of(world)

    occurrences = unit_of(document, "block_entity_name")["occurrences"]
    excluded = [bool(o.get("excluded")) for o in occurrences]

    assert sorted(excluded) == [False, True]


def test_a_native_custom_name_is_not_excluded(tmp_path) -> None:
    world = world_with(
        tmp_path, chunk_with(chest(amulet_nbt.StringTag("Supply Crate")))
    )
    _, document = extract_of(world)

    (occurrence,) = unit_of(document, "block_entity_name")["occurrences"]

    assert occurrence.get("excluded") is None


# --- in_place 表達不了的樹 -------------------------------------------------


def test_a_non_collapsible_custom_name_is_skipped_and_counted(tmp_path) -> None:
    """`click_event` 讓這棵樹不可塌縮，而 `in_place` 沒有每段一個 key 的位置。"""
    styled = amulet_nbt.CompoundTag(
        {
            "text": amulet_nbt.StringTag("Supply Crate"),
            "click_event": amulet_nbt.CompoundTag(
                {"action": amulet_nbt.StringTag("run_command")}
            ),
        }
    )
    world = world_with(tmp_path, chunk_with(chest(styled)))
    result, document = extract_of(world)

    assert [u for u in document["units"] if u["category"] == "block_entity_name"] == []
    assert result.stats["skipped_non_collapsible_in_place"] == 1


def test_a_non_collapsible_sign_is_still_extracted(tmp_path) -> None:
    """跳過只針對 in_place 的 category——告示牌重建整棵樹是常態路徑。"""
    styled = amulet_nbt.CompoundTag(
        {
            "text": amulet_nbt.StringTag("Click me"),
            "click_event": amulet_nbt.CompoundTag(
                {"action": amulet_nbt.StringTag("run_command")}
            ),
        }
    )
    tag = sign("", "", "", "")
    tag["front_text"]["messages"] = amulet_nbt.ListTag([styled])
    world = world_with(tmp_path, chunk_with(tag))
    _, document = extract_of(world)

    assert unit_of(document, "sign")["collapsible"] is False


# --- 報告與待翻檔 ---------------------------------------------------------


def test_the_skipped_count_reaches_the_extract_document(tmp_path) -> None:
    """跳過必須看得見。靜默少抽節點是最難查的 bug。"""
    styled = amulet_nbt.CompoundTag(
        {
            "text": amulet_nbt.StringTag("Supply Crate"),
            "click_event": amulet_nbt.CompoundTag(
                {"action": amulet_nbt.StringTag("run_command")}
            ),
        }
    )
    world = world_with(tmp_path, chunk_with(chest(styled)))
    _, document = extract_of(world)

    assert document["stats"]["skipped_non_collapsible_in_place"] == 1


def test_the_note_tells_the_translator_it_goes_back_into_the_save(tmp_path) -> None:
    """in_place 沒有 lang 檔那層——譯者該知道這一條只有一種語言的位置。"""
    from mcmt.extract.emit import build_translations_document

    world = world_with(
        tmp_path, chunk_with(chest(amulet_nbt.StringTag("Supply Crate")))
    )
    result, document = extract_of(world)
    translations = build_translations_document(
        result, language="zh_tw", extract_document=document
    )

    (entry,) = translations["entries"].values()

    assert "寫回節點本身" in entry["note"]
