# SPDX-License-Identifier: GPL-3.0-or-later
"""M2.3 `mcmt sandbox import`（CLAUDE.md §1.1）。

**這是唯一合法的把世界帶進 sandbox 的入口。** 完整目錄複製、不是 symlink 也不是
硬連結——工具會改寫檔案，連結會直接改到使用者的原始地圖上。
"""

import json

import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.errors import (
    PathOutsideSandboxError,
    SandboxTargetExistsError,
    SandboxTargetInsideSourceError,
    WorldNotFoundError,
)
from mcmt.fingerprint import world_fingerprint
from mcmt.sandbox import import_world


@pytest.fixture
def source_world(project):
    world = project / "saves" / "Minecraft Party 2"
    write_region_file(
        world / "region",
        RegionBuilder().add_chunk_nbt(0, modern_chunk()).build(),
    )
    write_region_file(
        world / "DIM1" / "region",
        RegionBuilder().add_chunk_nbt(1, modern_chunk()).build(),
    )
    (world / "level.dat").write_bytes(b"fake level.dat")
    (world / "datapacks" / "pack").mkdir(parents=True)
    (world / "datapacks" / "pack" / "pack.mcmeta").write_text("{}", encoding="utf-8")
    return world


def test_every_file_is_copied_with_identical_bytes(project, source_world) -> None:
    result = import_world(source_world)

    assert result.target == project / "sandbox" / "Minecraft Party 2"
    for original in source_world.rglob("*"):
        copied = result.target / original.relative_to(source_world)
        assert copied.exists()
        if original.is_file():
            assert copied.read_bytes() == original.read_bytes()


def test_the_copy_is_independent_of_the_source(project, source_world) -> None:
    """不是 symlink、不是硬連結——之後我們會改寫這些檔案。"""
    result = import_world(source_world)

    (source_world / "level.dat").write_bytes(b"changed afterwards")

    assert (result.target / "level.dat").read_bytes() == b"fake level.dat"


def test_origin_records_where_it_came_from(project, source_world) -> None:
    result = import_world(source_world)

    origin = json.loads((result.target / ".mcmt-origin.json").read_text("utf-8"))

    assert origin["source"] == str(source_world.resolve())
    assert origin["world_fingerprint"] == world_fingerprint(source_world)
    assert origin["imported_at"].startswith("20")


def test_the_recorded_fingerprint_is_the_source_not_the_copy(project, source_world) -> None:
    """兩者現在相同，但記的必須是來源——之後 sandbox 裡的副本會被改。"""
    result = import_world(source_world)
    origin = json.loads((result.target / ".mcmt-origin.json").read_text("utf-8"))

    assert origin["world_fingerprint"] == world_fingerprint(result.target)


def test_importing_twice_is_refused(project, source_world) -> None:
    import_world(source_world)

    with pytest.raises(SandboxTargetExistsError):
        import_world(source_world)


def test_replace_overwrites_and_leaves_no_stale_files(project, source_world) -> None:
    first = import_world(source_world)
    (first.target / "region" / "leftover.mca").write_bytes(b"stale")

    second = import_world(source_world, replace=True)

    assert not (second.target / "region" / "leftover.mca").exists()
    assert (second.target / "level.dat").exists()


def test_a_custom_name_is_used_for_the_target(project, source_world) -> None:
    result = import_world(source_world, name="mp2")

    assert result.target == project / "sandbox" / "mp2"


def test_a_name_that_escapes_the_sandbox_is_refused(project, source_world) -> None:
    with pytest.raises(PathOutsideSandboxError):
        import_world(source_world, name="../escaped")


def test_a_folder_that_is_not_a_world_is_refused(project) -> None:
    not_a_world = project / "just-a-folder"
    (not_a_world / "sub").mkdir(parents=True)

    with pytest.raises(WorldNotFoundError):
        import_world(not_a_world)


def test_a_missing_source_is_refused(project) -> None:
    with pytest.raises(WorldNotFoundError):
        import_world(project / "沒有這個世界")


def test_a_target_inside_the_source_is_refused(project) -> None:
    """來源包住目標時，複製會把自己一直複製進自己。"""
    world = project / "sandbox" / "outer"
    write_region_file(
        world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
    )

    with pytest.raises(SandboxTargetInsideSourceError):
        import_world(world, name="outer/inner")


def test_the_file_count_is_reported(project, source_world) -> None:
    """數的是複製過去的檔案，不含我們自己寫的 .mcmt-origin.json。"""
    result = import_world(source_world)

    assert result.file_count == len([p for p in source_world.rglob("*") if p.is_file()])
