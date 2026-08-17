# SPDX-License-Identifier: GPL-3.0-or-later
"""M1.3 世界結構偵測。

v1 拒絕處理兩種世界（CLAUDE.md §二）：

* 1.12 舊結構 —— chunk 根有 `Level` 包裝、方塊實體在 `Level.TileEntities`、
  告示牌是 `Text1..Text4`，且 882 個 chunk 根本沒有 `DataVersion` 欄位。
  1.12 地圖在 1.21.11 開過之後，同一個世界會**同時存在兩套結構**。
* 外部 `.mcc` chunk —— region 內只有 header，「原封複製壓縮位元組」複製到的是空的。

兩者的理由相同：**未測過的寫入路徑比拒絕處理危險得多。**
"""

import zlib

import amulet_nbt
import pytest

from mcmt.errors import ExternalChunkError, UnsupportedWorldStructureError
from mcmt.nbtio.region import RawChunk
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root


def make_raw_chunk(root: amulet_nbt.CompoundTag, *, index: int = 0) -> RawChunk:
    payload = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
    return RawChunk(
        index=index,
        timestamp=1_700_000_000,
        compression_type=2,
        is_external=False,
        payload=zlib.compress(payload),
        sector_offset=2,
        sector_count=1,
    )


def modern_chunk(*, data_version: int = 4671) -> amulet_nbt.CompoundTag:
    root = amulet_nbt.CompoundTag()
    root["DataVersion"] = amulet_nbt.IntTag(data_version)
    sign = amulet_nbt.CompoundTag()
    sign["id"] = amulet_nbt.StringTag("minecraft:sign")
    front = amulet_nbt.CompoundTag()
    front["messages"] = amulet_nbt.ListTag(
        [amulet_nbt.StringTag('""') for _ in range(4)]
    )
    sign["front_text"] = front
    root["block_entities"] = amulet_nbt.ListTag([sign])
    return root


def legacy_chunk() -> amulet_nbt.CompoundTag:
    """1.12 的形狀：Level 包裝 + TileEntities + Text1..Text4。"""
    root = amulet_nbt.CompoundTag()
    sign = amulet_nbt.CompoundTag()
    sign["id"] = amulet_nbt.StringTag("minecraft:sign")
    for n in range(1, 5):
        sign[f"Text{n}"] = amulet_nbt.StringTag('{"text":""}')
    level = amulet_nbt.CompoundTag()
    level["TileEntities"] = amulet_nbt.ListTag([sign])
    root["Level"] = level
    return root


# --- load_chunk_root ------------------------------------------------------


def test_chunk_payload_is_decompressed_and_parsed() -> None:
    root = load_chunk_root(make_raw_chunk(modern_chunk()))

    assert int(root["DataVersion"]) == 4671
    assert "block_entities" in root


def test_external_chunk_is_refused_before_anything_is_parsed() -> None:
    chunk = RawChunk(
        index=57,
        timestamp=0,
        compression_type=2,
        is_external=True,
        payload=b"",
        sector_offset=2,
        sector_count=1,
    )

    with pytest.raises(ExternalChunkError) as exc:
        load_chunk_root(chunk)
    assert exc.value.chunk_index == 57


# --- ensure_supported_structure -------------------------------------------


def test_modern_chunk_returns_its_own_data_version() -> None:
    """每個 chunk 讀自己的 DataVersion，不是 level.dat 的。"""
    root = modern_chunk(data_version=4556)

    assert ensure_supported_structure(root, chunk_index=0) == 4556


def test_level_wrapper_is_unsupported() -> None:
    with pytest.raises(UnsupportedWorldStructureError) as exc:
        ensure_supported_structure(legacy_chunk(), chunk_index=12)
    assert exc.value.reason == "level_wrapper"
    assert exc.value.chunk_index == 12


def test_missing_data_version_is_unsupported() -> None:
    """1.12 語料裡有 882 個 chunk 根本沒有這個欄位。"""
    root = modern_chunk()
    del root["DataVersion"]

    with pytest.raises(UnsupportedWorldStructureError) as exc:
        ensure_supported_structure(root, chunk_index=3)
    assert exc.value.reason == "missing_data_version"


def test_non_numeric_data_version_is_unsupported() -> None:
    root = modern_chunk()
    root["DataVersion"] = amulet_nbt.StringTag("4671")

    with pytest.raises(UnsupportedWorldStructureError) as exc:
        ensure_supported_structure(root, chunk_index=0)
    assert exc.value.reason == "missing_data_version"


def test_legacy_sign_fields_in_a_modern_container_are_unsupported() -> None:
    """1.12 地圖被 1.21.11 開過後，走過的區域升級、沒走過的沒有——會混在一起。"""
    root = modern_chunk()
    sign = root["block_entities"][0]
    del sign["front_text"]
    for n in range(1, 5):
        sign[f"Text{n}"] = amulet_nbt.StringTag('{"text":""}')

    with pytest.raises(UnsupportedWorldStructureError) as exc:
        ensure_supported_structure(root, chunk_index=0)
    assert exc.value.reason == "legacy_sign_text"


def test_level_wrapper_wins_over_missing_data_version() -> None:
    """兩個症狀都出現時要報那個講得出「這是什麼世界」的原因。"""
    with pytest.raises(UnsupportedWorldStructureError) as exc:
        ensure_supported_structure(legacy_chunk(), chunk_index=0)
    assert exc.value.reason == "level_wrapper"


def test_chunk_without_block_entities_is_fine() -> None:
    """絕大多數 chunk 沒有方塊實體，那不是結構問題。"""
    root = amulet_nbt.CompoundTag()
    root["DataVersion"] = amulet_nbt.IntTag(4671)

    assert ensure_supported_structure(root, chunk_index=0) == 4671
