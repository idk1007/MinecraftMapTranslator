# SPDX-License-Identifier: GPL-3.0-or-later
"""M7.3 `mcmt extract` 的產出（`extract/build.py` + `extract/emit.py`）。

**最重要的一條測試是「產出的文件真的通過 schema 驗證」。** 合約如果只驗手寫的
sample fixture，那它驗的是我當初手寫的東西，不是程式真的會吐出來的東西——那正是
CLAUDE.md 說的「schema 只是文件，沒有東西強制它與程式碼一致」。
"""

import json
from pathlib import Path

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mcmt.extract.build import build_units
from mcmt.extract.emit import (
    build_extract_document,
    build_translations_document,
    dump_json,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


@pytest.fixture(scope="module")
def validators():
    registry = Registry()
    schemas = {}
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text("utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        schemas[path.name.split(".")[0]] = schema
    return {
        name: Draft202012Validator(schema, registry=registry)
        for name, schema in schemas.items()
    }


def sign(*lines, x=1, y=2, z=3, block_id="minecraft:oak_sign"):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag(block_id)
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


def documents(world, *, language="zh_tw", namespace="mcmt"):
    result = build_units(world, namespace=namespace)
    extract = build_extract_document(
        result,
        world_name=world.name,
        world_fingerprint="blake2b:0011223344556677",
        level_data_version=4671,
        namespace=namespace,
        target_languages=[language],
    )
    translations = build_translations_document(
        result, language=language, extract_document=extract
    )
    return result, extract, translations


# --- 合約驗證 -------------------------------------------------------------


def test_the_emitted_extract_validates_against_the_schema(tmp_path, validators) -> None:
    world = world_with(
        tmp_path,
        chunk_with(sign("歡迎光臨", "前方危險", "", "")),
        chunk_with(sign("§a綠色§c紅色", "", "", "", x=9)),
    )
    _, extract, _ = documents(world)

    errors = sorted(validators["extract"].iter_errors(extract), key=str)

    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def test_the_emitted_translations_validate_against_the_schema(tmp_path, validators) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, _, translations = documents(world)

    errors = sorted(validators["translations"].iter_errors(translations), key=str)

    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def test_the_output_is_strict_json(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, extract, _ = documents(world)

    text = dump_json(extract)

    assert json.loads(text)
    assert "//" not in text
    assert "歡迎光臨" in text  # ensure_ascii=False：中文保持字面


# --- 待翻檔對人是否好用 ---------------------------------------------------


def test_the_translation_file_shows_the_source_and_leaves_target_empty(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert entry["source"] == "歡迎光臨"
    assert entry["target"] == ""


def test_a_single_segment_entry_has_no_placeholder_noise(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert "[[" not in entry["source"]


def test_a_multi_segment_entry_explains_its_placeholders(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("§a綠色§c紅色", "", "", "")))
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert entry["source"] == "[[0]]綠色[[1]]紅色"
    assert "[[0]] [[1]]" in entry["note"]


def test_the_note_carries_the_width_budget(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert "90px" in entry["note"]


def test_the_entry_says_where_it_is(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "", x=123, y=64, z=-45)))
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert "123,64,-45" in entry["where"]


# --- 去重與統計 -----------------------------------------------------------


def test_the_same_text_twice_is_one_unit_with_two_occurrences(tmp_path) -> None:
    """去重是 per-unit——同一句話翻一次就好。"""
    world = world_with(
        tmp_path,
        chunk_with(sign("歡迎光臨", "", "", "")),
        chunk_with(sign("歡迎光臨", "", "", "", x=99)),
    )
    result, extract, _ = documents(world)

    assert len(result.units) == 1
    assert len(extract["units"][0]["occurrences"]) == 2
    assert extract["stats"]["deduped_count"] == 1


def test_the_note_mentions_how_many_places_a_unit_appears(tmp_path) -> None:
    world = world_with(
        tmp_path,
        chunk_with(sign("歡迎光臨", "", "", "")),
        chunk_with(sign("歡迎光臨", "", "", "", x=99)),
    )
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert "出現 2 次" in entry["note"]


def test_empty_lines_do_not_become_units(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("", "", "", "")))
    result, _, _ = documents(world)

    assert result.units == []


# --- 三條「不翻」的路徑各自計數 -------------------------------------------


def test_legacy_json_in_a_native_chunk_is_skipped_and_counted(tmp_path) -> None:
    """[遊戲實測 M0-3] 那些在遊戲裡本來就是字面亂碼。"""
    world = world_with(
        tmp_path, chunk_with(sign('{"text":"亂碼"}', "", "", ""), data_version=4671)
    )
    result, extract, _ = documents(world)

    assert result.units == []
    assert extract["stats"]["skipped_legacy_json_in_native_chunk"] == 1


def test_legacy_json_in_an_old_chunk_is_translated(tmp_path) -> None:
    """[遊戲實測 M4-2] 同一個字串在 DV 3700 的 chunk 裡是真內容。"""
    world = world_with(
        tmp_path, chunk_with(sign('{"text":"真內容"}', "", "", ""), data_version=3700)
    )
    result, _, translations = documents(world)

    assert len(result.units) == 1
    assert list(translations["entries"].values())[0]["source"] == "真內容"


def test_unparseable_json_is_skipped_and_counted(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign('{"text":', "", "", "")))
    result, extract, _ = documents(world)

    assert result.units == []
    assert extract["stats"]["skipped_unparseable"] == 1


def test_denylisted_paths_never_become_units(tmp_path) -> None:
    box = amulet_nbt.CompoundTag()
    box["id"] = amulet_nbt.StringTag("minecraft:command_block")
    box["LastOutput"] = amulet_nbt.StringTag('{"text":"不要翻我"}')
    world = world_with(tmp_path, chunk_with(box))

    result, _, _ = documents(world)

    assert result.units == []


# --- 身分 -----------------------------------------------------------------


def test_the_translations_file_binds_to_this_extract(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, extract, translations = documents(world)

    assert (
        translations["extract_ref"]["extract_fingerprint"]
        == extract["world"]["extract_fingerprint"]
    )


def test_a_different_namespace_changes_the_extract_fingerprint(tmp_path) -> None:
    """同一個世界換命名空間重跑，舊譯文不該安靜地套上去。"""
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, a, _ = documents(world, namespace="mcmt")
    _, b, _ = documents(world, namespace="other")

    assert a["world"]["extract_fingerprint"] != b["world"]["extract_fingerprint"]


def test_the_key_and_unit_id_share_a_discriminator(tmp_path) -> None:
    world = world_with(tmp_path, chunk_with(sign("歡迎光臨", "", "", "")))
    _, extract, _ = documents(world)

    unit = extract["units"][0]

    assert unit["unit_id"].split(":")[-1] == unit["key"].split(".")[-1]


# --- M8 寬度預算：譯者動手之前就要看得到 -----------------------------------


def test_the_note_says_how_many_chinese_characters_fit(tmp_path) -> None:
    """「90px」對譯者沒有意義，「約 10 個中文字」有。"""
    world = world_with(tmp_path, chunk_with(sign("Welcome", "", "", "")))
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert "10 個中文字" in entry["note"]


def test_a_hanging_sign_note_shows_a_smaller_budget(tmp_path) -> None:
    """[遊戲實測 M11-2] 吊掛告示牌窄很多。兩者共用一個數字就是把它抹掉。"""
    world = world_with(
        tmp_path,
        chunk_with(sign("Welcome", "", "", "", block_id="minecraft:oak_hanging_sign")),
    )
    _, _, translations = documents(world)

    (entry,) = translations["entries"].values()

    assert "6 個中文字" in entry["note"]


def test_the_constraints_come_from_the_width_table(tmp_path) -> None:
    from mcmt.width import MEASUREMENT_ID, budget_for

    world = world_with(tmp_path, chunk_with(sign("Welcome", "", "", "")))
    _, extract, _ = documents(world)

    constraints = extract["units"][0]["constraints"]

    assert constraints["max_width_px"] == budget_for("sign").max_width_px
    assert constraints["measurement"] == MEASUREMENT_ID


def test_enforcement_is_warn_until_the_table_is_calibrated(tmp_path) -> None:
    """校準完成前一律 warn（CLAUDE.md C 題）。"""
    world = world_with(tmp_path, chunk_with(sign("Welcome", "", "", "")))
    _, extract, _ = documents(world)

    assert extract["units"][0]["constraints"]["enforcement"] == "warn"


def test_a_source_that_already_overflows_is_reported_not_hidden(tmp_path) -> None:
    """原文本來就超寬是地圖自己的事，但譯者該知道——他沒有必要塞回一樣長。"""
    world = world_with(
        tmp_path,
        chunk_with(
            sign("這一行中文字非常多一定放不下", "", "", "",
                 block_id="minecraft:oak_hanging_sign")
        ),
    )
    _, extract, _ = documents(world)

    assert extract["units"][0]["constraints"]["source_width_px"] > 60
