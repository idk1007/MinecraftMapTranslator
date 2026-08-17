# SPDX-License-Identifier: GPL-3.0-or-later
"""M3.1 region 寫入（CLAUDE.md §1.4 外科式寫入）。

> **未被修改的 chunk，必須原封不動複製其原始壓縮位元組，絕不重新編碼。
> 只有被修改的 chunk 才走「解碼 → 改 → 編碼」路徑。**

「重新壓縮後位元組一致」（SPIKE_RESULT 的 L2）是**巧合**——Python `zlib.compress()`
的預設等級恰好與 Mojang 的 Java `Deflater` 相同。外科式寫入讓「什麼都沒動」從
實測觀察變成結構性保證。

timestamp 表：未修改的**原樣搬運**、修改過的更新為當下時間。不可整表歸零（遊戲
會誤判所有 chunk 都是新的），也不可整表沿用（被改的 chunk 帶著舊時間）。
"""

import os
import zlib

import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.errors import ChunkTooLargeError, ExternalChunkError, PathOutsideSandboxError
from mcmt.nbtio.region import (
    SECTOR_SIZE,
    ChunkWrite,
    RawChunk,
    read_region,
    write_region,
)
from mcmt.safety.paths import ensure_readable


@pytest.fixture
def source(project):
    """一張有兩個 chunk 的 region，位置在 sandbox 外（來源是唯讀的）。"""
    return write_region_file(
        project / "saves",
        RegionBuilder()
        .add_chunk_nbt(0, modern_chunk(), timestamp=1_111_111)
        .add_chunk_nbt(5, modern_chunk(data_version=4556), timestamp=2_222_222)
        .build(),
    )


def read_all(path):
    return list(read_region(ensure_readable(path)))


# --- 外科式 ---------------------------------------------------------------


def test_untouched_chunks_are_written_back_byte_for_byte(project, source) -> None:
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"

    write_region(target, [ChunkWrite.unchanged(c) for c in original])

    written = read_all(target)
    assert [c.index for c in written] == [c.index for c in original]
    assert [c.payload for c in written] == [c.payload for c in original]
    assert [c.compression_type for c in written] == [c.compression_type for c in original]


def test_a_modified_chunk_is_written_exactly_as_given(project, source) -> None:
    """新 payload 原樣寫入——寫入層不重新壓縮任何東西。"""
    original = read_all(source)
    new_payload = zlib.compress(b"\x0a\x00\x00\x00", 9)
    target = project / "sandbox" / "r.0.0.mca"

    write_region(
        target,
        [
            ChunkWrite.replaced(original[0], new_payload),
            ChunkWrite.unchanged(original[1]),
        ],
    )

    written = read_all(target)
    assert written[0].payload == new_payload
    assert written[1].payload == original[1].payload


# --- timestamp 表 ---------------------------------------------------------


def test_untouched_chunks_keep_their_original_timestamp(project, source) -> None:
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"

    write_region(target, [ChunkWrite.unchanged(c) for c in original], now=9_999_999)

    assert [c.timestamp for c in read_all(target)] == [1_111_111, 2_222_222]


def test_a_modified_chunk_gets_the_current_time(project, source) -> None:
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"

    write_region(
        target,
        [
            ChunkWrite.replaced(original[0], original[0].payload),
            ChunkWrite.unchanged(original[1]),
        ],
        now=9_999_999,
    )

    written = read_all(target)
    assert written[0].timestamp == 9_999_999
    assert written[1].timestamp == 2_222_222


# --- 檔案結構 -------------------------------------------------------------


def test_the_file_is_sector_aligned_and_starts_after_the_two_tables(project, source) -> None:
    target = project / "sandbox" / "r.0.0.mca"

    write_region(target, [ChunkWrite.unchanged(c) for c in read_all(source)])

    assert target.stat().st_size % SECTOR_SIZE == 0
    assert min(c.sector_offset for c in read_all(target)) == 2


def test_chunks_are_written_in_index_order(project, source) -> None:
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"

    write_region(target, [ChunkWrite.unchanged(c) for c in reversed(original)])

    written = read_all(target)
    assert [c.index for c in written] == [0, 5]
    assert written[0].sector_offset < written[1].sector_offset


def test_a_region_with_no_chunks_is_just_the_two_tables(project) -> None:
    target = project / "sandbox" / "r.0.0.mca"

    write_region(target, [])

    assert target.stat().st_size == SECTOR_SIZE * 2
    assert read_all(target) == []


# --- 報告 -----------------------------------------------------------------


def test_the_report_carries_the_sizes_before_and_after(project, source) -> None:
    """檔案變小是磁區重整不是資料遺失，但使用者看到會恐慌，所以要報告。"""
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"
    # 先放一份帶空隙的舊檔在目標位置
    padded = bytes(RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()) + bytes(
        SECTOR_SIZE * 4
    )
    target.write_bytes(padded)

    report = write_region(target, [ChunkWrite.unchanged(c) for c in original])

    assert report.size_before == len(padded)
    assert report.size_after == target.stat().st_size
    assert report.realigned is True


def test_a_brand_new_file_is_not_a_realignment(project, source) -> None:
    """目標檔不存在時 size_before 是 0，但那不是「檔案縮小了」。

    整個世界跑一次 round-trip 時，13 張 region 全被報成磁區重整——警告只要出現在
    不需要它的地方，使用者就會學會忽略它。
    """
    target = project / "sandbox" / "r.0.0.mca"

    report = write_region(target, [ChunkWrite.unchanged(c) for c in read_all(source)])

    assert report.size_before == 0
    assert report.realigned is False


def test_no_realignment_is_reported_when_the_size_is_unchanged(project, source) -> None:
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"
    write_region(target, [ChunkWrite.unchanged(c) for c in original])

    report = write_region(target, [ChunkWrite.unchanged(c) for c in original])

    assert report.realigned is False
    assert report.modified_count == 0


def test_the_report_counts_modified_chunks(project, source) -> None:
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"

    report = write_region(
        target,
        [
            ChunkWrite.replaced(original[0], original[0].payload),
            ChunkWrite.unchanged(original[1]),
        ],
    )

    assert (report.chunks_written, report.modified_count) == (2, 1)


# --- 拒絕 -----------------------------------------------------------------


def test_writing_outside_the_sandbox_is_refused(project, source) -> None:
    with pytest.raises(PathOutsideSandboxError):
        write_region(project / "escaped.mca", [])


def test_an_external_chunk_cannot_be_carried_over(project) -> None:
    """`.mcc` 的 chunk 在 region 裡只有 header——「原封複製」複製到的是空的。"""
    external = RawChunk(
        index=0,
        timestamp=1,
        compression_type=2,
        is_external=True,
        payload=b"",
        sector_offset=2,
        sector_count=1,
    )

    with pytest.raises(ExternalChunkError):
        ChunkWrite.unchanged(external)


def test_a_chunk_too_big_for_the_sector_count_byte_is_refused(project) -> None:
    """超過 255 個磁區就必須外置成 .mcc，而那條寫入路徑 v1 不支援。"""
    huge = os.urandom(256 * SECTOR_SIZE)
    target = project / "sandbox" / "r.0.0.mca"

    with pytest.raises(ChunkTooLargeError):
        write_region(target, [ChunkWrite(index=0, payload=huge, compression_type=2, timestamp=1, modified=True)])


# --- 原子性 ---------------------------------------------------------------


def test_a_failed_write_leaves_the_original_file_intact(project, source, monkeypatch) -> None:
    """寫到一半掛掉不該留下半份 region。"""
    original = read_all(source)
    target = project / "sandbox" / "r.0.0.mca"
    write_region(target, [ChunkWrite.unchanged(c) for c in original])
    before = target.read_bytes()

    def explode(*args, **kwargs):
        raise OSError("模擬寫入失敗")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        write_region(target, [ChunkWrite.unchanged(original[0])])

    assert target.read_bytes() == before
    assert list(target.parent.glob("*.tmp")) == []
