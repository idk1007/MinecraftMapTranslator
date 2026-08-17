# SPDX-License-Identifier: GPL-3.0-or-later
"""M1.4 `mcmt doctor`（唯讀）。

驗收條件：DataVersion 直方圖、壓縮分佈、`.mcc` 數、疑似損壞 chunk；per-region
串流；**唯讀，永不寫入**。

（節點形狀分佈等 M5 的嗅探器——不在這裡另寫第二份判斷邏輯，`occurrence.encoding`
的唯一權威只能有一個。）
"""

import zlib

import amulet_nbt
import pytest
from conftest import (
    RegionBuilder,
    legacy_chunk,
    modern_chunk,
    set_offset_entry,
    write_region_file,
)

from mcmt.doctor import WorldNotFoundError, survey_world


def build_world(tmp_path, *, name: str = "world"):
    world = tmp_path / name
    region = world / "region"
    write_region_file(
        region,
        RegionBuilder()
        .add_chunk_nbt(0, modern_chunk(data_version=4671))
        .add_chunk_nbt(1, modern_chunk(data_version=4556))
        .build(),
        "r.0.0.mca",
    )
    return world


# --- 統計 -----------------------------------------------------------------


def test_counts_chunks_and_data_versions(tmp_path) -> None:
    survey = survey_world(build_world(tmp_path))

    assert survey.chunks == 2
    assert survey.data_versions == {4671: 1, 4556: 1}
    assert survey.region_files == 1


def test_walks_every_dimension_not_just_the_overworld(tmp_path) -> None:
    """MP2 有 datapack 自訂維度，只掃 `region/` 會漏掉整個維度。"""
    world = build_world(tmp_path)
    write_region_file(
        world / "DIM1" / "region",
        RegionBuilder().add_chunk_nbt(0, modern_chunk(data_version=4671)).build(),
    )
    write_region_file(
        world / "dimensions" / "mcp" / "lobby" / "region",
        RegionBuilder().add_chunk_nbt(0, modern_chunk(data_version=4671)).build(),
    )

    survey = survey_world(world)

    assert survey.chunks == 4
    assert survey.region_files == 3


def test_entities_and_poi_are_not_counted_as_chunk_data(tmp_path) -> None:
    """`entities/` 與 `poi/` 也是 .mca，但不是方塊 chunk。v1 的 doctor 不看。"""
    world = build_world(tmp_path)
    write_region_file(
        world / "entities",
        RegionBuilder().add_chunk_nbt(0, modern_chunk()).build(),
    )

    assert survey_world(world).chunks == 2


def test_counts_compression_types(tmp_path) -> None:
    world = tmp_path / "world"
    nbt = amulet_nbt.NamedTag(modern_chunk(), "").save_to(compressed=False)
    write_region_file(
        world / "region",
        RegionBuilder()
        .add(0, zlib.compress(nbt))
        .add(1, nbt, compression_byte=3)
        .build(),
    )

    assert survey_world(world).compression_types == {2: 1, 3: 1}


def test_counts_external_chunks_and_refuses_the_world(tmp_path) -> None:
    world = build_world(tmp_path)
    write_region_file(
        world / "region",
        RegionBuilder().add(0, b"", compression_byte=0x82).build(),
        "r.0.1.mca",
    )

    survey = survey_world(world)

    assert survey.external_chunks == 1
    assert survey.supported is False


def test_counts_unsupported_structures_by_reason_with_an_example(tmp_path) -> None:
    world = build_world(tmp_path)
    write_region_file(
        world / "region",
        RegionBuilder().add_chunk_nbt(5, legacy_chunk()).build(),
        "r.0.1.mca",
    )

    survey = survey_world(world)

    assert survey.unsupported == {"level_wrapper": 1}
    assert survey.unsupported_examples["level_wrapper"] == ("r.0.1.mca", 5)
    assert survey.supported is False


def test_a_clean_world_is_supported(tmp_path) -> None:
    survey = survey_world(build_world(tmp_path))

    assert survey.supported is True
    assert survey.corrupt == []


# --- 損壞 -----------------------------------------------------------------


def test_a_corrupt_region_is_recorded_and_the_scan_continues(tmp_path) -> None:
    """一個壞掉的 region 不該讓整份健檢報告消失。"""
    world = build_world(tmp_path)
    data = RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
    set_offset_entry(data, 0, sector=1, count=1)
    write_region_file(world / "region", data, "r.9.9.mca")

    survey = survey_world(world)

    assert survey.chunks == 2  # 乾淨那張 region 的 chunk 還是數到了
    assert [entry.region for entry in survey.corrupt] == ["r.9.9.mca"]
    assert survey.corrupt[0].error == "MalformedRegionError"
    assert survey.supported is False


def test_unparseable_nbt_is_recorded_as_corrupt(tmp_path) -> None:
    world = tmp_path / "world"
    write_region_file(
        world / "region", RegionBuilder().add(0, zlib.compress(b"not nbt")).build()
    )

    survey = survey_world(world)

    assert len(survey.corrupt) == 1
    assert survey.corrupt[0].chunk_index == 0


def test_missing_world_is_reported_clearly(tmp_path) -> None:
    with pytest.raises(WorldNotFoundError):
        survey_world(tmp_path / "沒有這個世界")


def test_a_directory_without_any_region_folder_is_not_a_world(tmp_path) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(WorldNotFoundError):
        survey_world(tmp_path / "empty")


# --- 唯讀 -----------------------------------------------------------------


def test_survey_never_writes_anything(tmp_path) -> None:
    """doctor 是唯讀的。這條要有測試擋著，不能只是承諾。"""
    world = build_world(tmp_path)
    before = {
        p: (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(world.rglob("*"))
    }

    survey_world(world)

    after = {
        p: (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(world.rglob("*"))
    }
    assert after == before
