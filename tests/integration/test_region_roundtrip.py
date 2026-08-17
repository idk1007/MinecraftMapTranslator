# SPDX-License-Identifier: GPL-3.0-or-later
"""外科式寫入在**真實 Mojang 位元組**上的驗證（M3.1）。

合成的 region 驗得了格式，驗不了這件事：Mojang 實際寫出來的位元組被我們讀進來
再寫回去，是不是一模一樣。SPIKE_RESULT 的 L3（原始壓縮位元組直接複製）恆為一致
是「定義如此」——但那是在說**設計**，這裡驗的是**實作真的照設計做了**。

fixture 是 `100 Ways To Die` 的 `r.-1.-1.mca` 前 30 個 chunk（131 KB），由
`tools/make_fixture_region.py` 切出來。
"""

import zlib
from pathlib import Path

import amulet_nbt
import pytest

from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import ChunkWrite, read_region, write_region
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root
from mcmt.safety.paths import ensure_readable

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "regions" / "r.-1.-1.slice.mca"


@pytest.fixture
def original():
    return list(read_region(ensure_readable(FIXTURE)))


def read_all(path):
    return list(read_region(ensure_readable(path)))


def test_the_fixture_is_real_data(original) -> None:
    assert len(original) == 30
    assert {chunk.compression_type for chunk in original} == {2}
    versions = {
        ensure_supported_structure(load_chunk_root(chunk), chunk_index=chunk.index)
        for chunk in original
    }
    assert versions == {4325}


def test_reading_and_writing_back_changes_nothing(project, original) -> None:
    """一個位元都不能變——包含 payload、壓縮類型、timestamp。"""
    target = project / "sandbox" / "r.-1.-1.mca"

    write_region(target, [ChunkWrite.unchanged(c) for c in original], now=9_999_999)

    written = read_all(target)
    assert len(written) == len(original)
    for before, after in zip(original, written):
        assert (after.index, after.payload, after.compression_type, after.timestamp) == (
            before.index,
            before.payload,
            before.compression_type,
            before.timestamp,
        )


def test_the_rewritten_file_is_byte_identical_to_the_fixture(project, original) -> None:
    """fixture 本身沒有磁區空隙，所以連檔案位元組都該一致。"""
    target = project / "sandbox" / "r.-1.-1.mca"

    write_region(target, [ChunkWrite.unchanged(c) for c in original])

    assert target.read_bytes() == FIXTURE.read_bytes()


def test_editing_one_chunk_leaves_the_other_29_untouched(project, original) -> None:
    """M11 的實際情境：改一個 chunk，同 region 其餘的必須完全沒被碰過。"""
    victim = original[7]
    root = load_chunk_root(victim)
    root["mcmtRoundTripMarker"] = amulet_nbt.StringTag("M3.1")
    new_payload = zlib.compress(
        amulet_nbt.NamedTag(root, "").save_to(compressed=False)
    )
    target = project / "sandbox" / "r.-1.-1.mca"

    report = write_region(
        target,
        [
            ChunkWrite.replaced(c, new_payload) if c.index == victim.index
            else ChunkWrite.unchanged(c)
            for c in original
        ],
        now=9_999_999,
    )

    written = {chunk.index: chunk for chunk in read_all(target)}
    assert report.modified_count == 1

    for chunk in original:
        after = written[chunk.index]
        if chunk.index == victim.index:
            assert after.payload == new_payload
            assert after.timestamp == 9_999_999
        else:
            assert after.payload == chunk.payload  # 原封不動的壓縮位元組
            assert after.timestamp == chunk.timestamp  # 時間戳也原樣搬運


def test_the_edited_chunk_still_parses_as_a_chunk(project, original) -> None:
    """改完寫回去，遊戲那邊要讀得懂——至少 NBT 與結構閘門要過。"""
    victim = original[7]
    root = load_chunk_root(victim)
    root["mcmtRoundTripMarker"] = amulet_nbt.StringTag("M3.1")
    payload = zlib.compress(amulet_nbt.NamedTag(root, "").save_to(compressed=False))
    target = project / "sandbox" / "r.-1.-1.mca"
    write_region(
        target,
        [
            ChunkWrite.replaced(c, payload) if c.index == victim.index
            else ChunkWrite.unchanged(c)
            for c in original
        ],
    )

    edited = next(c for c in read_all(target) if c.index == victim.index)
    reloaded = amulet_nbt.load(
        decompress_chunk(edited.payload, edited.compression_type, chunk_index=edited.index),
        compressed=False,
    ).compound

    assert str(reloaded["mcmtRoundTripMarker"]) == "M3.1"
    assert ensure_supported_structure(reloaded, chunk_index=edited.index) == 4325
