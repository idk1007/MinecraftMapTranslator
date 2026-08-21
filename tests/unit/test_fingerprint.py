# SPDX-License-Identifier: GPL-3.0-or-later
"""M2.2 世界指紋。

合約要求（`docs/contracts/extract.schema.json`）：

> MUST be derived from per-chunk DataVersions and region content, NOT from file
> mtime or size：[實測] 在遊戲裡開一次世界，120,036 個 chunk 裡有 182 個被升級，
> 而 mtime 沒有任何有意義的訊號。

所以指紋是「這個世界的內容身分」，不是「這些檔案的狀態」。
"""

import re
import shutil
import zlib
from pathlib import Path

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.fingerprint import world_fingerprint


def build_world(tmp_path, *, name: str = "world", data_version: int = 4671):
    world = tmp_path / name
    write_region_file(
        world / "region",
        RegionBuilder()
        .add_chunk_nbt(0, modern_chunk(data_version=data_version))
        .add_chunk_nbt(5, modern_chunk(data_version=4556))
        .build(),
    )
    return world


def test_fingerprint_matches_the_contract_format(tmp_path) -> None:
    fingerprint = world_fingerprint(build_world(tmp_path))

    assert re.fullmatch(r"blake2b:[0-9a-f]{16,64}", fingerprint)


def test_the_same_world_in_a_different_folder_has_the_same_fingerprint(tmp_path) -> None:
    """指紋是內容的身分，不是位置的身分——不然 sandbox import 之後就對不上了。"""
    original = build_world(tmp_path, name="original")
    copy = tmp_path / "copy"
    shutil.copytree(original, copy)

    assert world_fingerprint(copy) == world_fingerprint(original)


def test_a_changed_chunk_changes_the_fingerprint(tmp_path) -> None:
    a = build_world(tmp_path, name="a", data_version=4671)
    b = build_world(tmp_path, name="b", data_version=4556)

    assert world_fingerprint(a) != world_fingerprint(b)


def test_mtime_alone_does_not_change_the_fingerprint(tmp_path) -> None:
    world = build_world(tmp_path)
    before = world_fingerprint(world)
    for path in world.rglob("*.mca"):
        path.touch()

    assert world_fingerprint(world) == before


def test_sector_layout_alone_does_not_change_the_fingerprint(tmp_path) -> None:
    """同樣的 chunk、不同的磁區排列（磁區重整之後）是同一個世界。"""
    packed = tmp_path / "packed"
    write_region_file(
        packed / "region",
        RegionBuilder().add_chunk_nbt(0, modern_chunk()).build(),
    )
    padded = tmp_path / "padded"
    data = RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
    write_region_file(padded / "region", bytes(data) + bytes(4096 * 3))

    assert world_fingerprint(padded) == world_fingerprint(packed)


def test_chunk_timestamps_do_not_change_the_fingerprint(tmp_path) -> None:
    """時間戳是後設資料。內容一樣，既有的 extract 就還適用。"""
    early = tmp_path / "early"
    late = tmp_path / "late"
    for world, timestamp in ((early, 1), (late, 2_000_000_000)):
        write_region_file(
            world / "region",
            RegionBuilder().add_chunk_nbt(0, modern_chunk(), timestamp=timestamp).build(),
        )

    assert world_fingerprint(early) == world_fingerprint(late)


def test_an_extra_dimension_changes_the_fingerprint(tmp_path) -> None:
    world = build_world(tmp_path)
    before = world_fingerprint(world)
    write_region_file(
        world / "DIM1" / "region",
        RegionBuilder().add_chunk_nbt(0, modern_chunk()).build(),
    )

    assert world_fingerprint(world) != before


def test_the_same_chunk_in_a_different_dimension_is_a_different_world(tmp_path) -> None:
    """只 hash payload 不 hash 位置的話，這兩個世界會撞在一起。"""
    a = tmp_path / "a"
    b = tmp_path / "b"
    region = RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
    write_region_file(a / "region", region)
    write_region_file(b / "DIM1" / "region", region)

    assert world_fingerprint(a) != world_fingerprint(b)


def test_fingerprinting_is_deterministic(tmp_path) -> None:
    world = build_world(tmp_path)

    assert world_fingerprint(world) == world_fingerprint(world)


def test_a_corrupt_region_still_yields_a_stable_fingerprint(tmp_path) -> None:
    """指紋負責身分，不負責健檢——壞掉的世界也要能被複製進 sandbox 再診斷。"""
    world = build_world(tmp_path)
    write_region_file(world / "region", b"\x00" * 100, "r.9.9.mca")

    assert world_fingerprint(world) == world_fingerprint(world)


def test_a_world_with_no_regions_is_still_hashable(tmp_path) -> None:
    empty = tmp_path / "empty"
    (empty / "region").mkdir(parents=True)

    assert world_fingerprint(empty).startswith("blake2b:")


def test_unrelated_files_beside_the_regions_are_ignored(tmp_path) -> None:
    """v1 的指紋只看 region——level.dat 與 datapack 進來要等掃描範圍擴大。"""
    world = build_world(tmp_path)
    before = world_fingerprint(world)
    (world / "level.dat").write_bytes(b"whatever")
    (world / "region" / "notes.txt").write_text("hi")

    assert world_fingerprint(world) == before


def test_payload_bytes_are_what_is_hashed(tmp_path) -> None:
    """同一個 NBT 用不同壓縮等級寫出來，是不同的位元組 → 不同的世界。

    L2「重新壓縮後位元組一致」是巧合不是保證（SPIKE_RESULT L1/L2/L3），所以
    指紋不該假裝那是同一份東西。
    """
    nbt = amulet_nbt.NamedTag(modern_chunk(), "").save_to(compressed=False)
    a = tmp_path / "a"
    b = tmp_path / "b"
    write_region_file(a / "region", RegionBuilder().add(0, zlib.compress(nbt, 6)).build())
    write_region_file(b / "region", RegionBuilder().add(0, zlib.compress(nbt, 9)).build())

    assert world_fingerprint(a) != world_fingerprint(b)


def test_changing_an_entity_changes_the_fingerprint(tmp_path) -> None:
    """[預告於 nbtio/region.py] 掃描範圍擴大到 entities 之後，

    「什麼算這個世界的內容」就得包含它。不含的話，使用者在遊戲裡動了盔甲座、
    指紋卻不變，`extract_fingerprint` 會說「世界沒變」而實際上變了。
    """
    import amulet_nbt

    from mcmt.fingerprint import world_fingerprint

    def build(name: str) -> Path:
        world = tmp_path / name
        write_region_file(
            world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
        )
        root = modern_chunk()
        root["Entities"] = amulet_nbt.ListTag(
            [amulet_nbt.CompoundTag({"CustomName": amulet_nbt.StringTag(name)})]
        )
        write_region_file(
            world / "entities", RegionBuilder().add_chunk_nbt(0, root).build()
        )
        return world

    assert world_fingerprint(build("a")) != world_fingerprint(build("b"))


def test_the_same_world_still_fingerprints_the_same(tmp_path) -> None:
    """穩定性沒有被破壞——同樣的內容算兩次要一樣。"""
    import amulet_nbt

    from mcmt.fingerprint import world_fingerprint

    def build(name: str) -> Path:
        world = tmp_path / name
        write_region_file(
            world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
        )
        root = modern_chunk()
        root["Entities"] = amulet_nbt.ListTag(
            [amulet_nbt.CompoundTag({"CustomName": amulet_nbt.StringTag("同樣的")})]
        )
        write_region_file(
            world / "entities", RegionBuilder().add_chunk_nbt(0, root).build()
        )
        return world

    assert world_fingerprint(build("x")) == world_fingerprint(build("y"))
