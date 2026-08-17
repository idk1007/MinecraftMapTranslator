# SPDX-License-Identifier: GPL-3.0-or-later
"""M1.2 region 讀取。

驗收條件（`docs/STATUS.md`）：原始壓縮位元組**不解壓**、offset/length/sector
邊界檢查、截斷檔 `TruncatedRegionError`。

region 格式：4096 bytes 偏移表（每格 3 bytes 磁區偏移 + 1 byte 磁區數，大端）
+ 4096 bytes 時間戳表（1024 個 uint32），之後每個 chunk 是 4 bytes 長度
+ 1 byte 壓縮類型 + payload，對齊到 4096 bytes 磁區。長度欄位**含**那 1 byte
壓縮類型。
"""

import os
import zlib

import pytest
from conftest import (
    RegionBuilder,
    set_declared_length,
    set_offset_entry,
    write_region_file,
)

from mcmt.errors import (
    MalformedRegionError,
    TruncatedRegionError,
    UnknownCompressionError,
)
from mcmt.nbtio.region import SECTOR_SIZE, read_region
from mcmt.safety.paths import ensure_readable


# --- 正常讀取 -------------------------------------------------------------


def test_payload_is_the_raw_compressed_bytes_and_is_not_decompressed(tmp_path) -> None:
    """外科式寫入的前提：讀出來的就是磁碟上的壓縮位元組本身。"""
    nbt = b"\x0a\x00\x00\x08\x00\x04test\x00\x02hi\x00"
    compressed = zlib.compress(nbt)
    path = write_region_file(tmp_path, RegionBuilder().add(0, compressed).build())

    (chunk,) = read_region(ensure_readable(path))

    assert chunk.payload == compressed
    assert chunk.payload != nbt


def test_chunk_header_fields_are_surfaced(tmp_path) -> None:
    path = write_region_file(
        tmp_path,
        RegionBuilder().add(0, zlib.compress(b"x"), timestamp=1_234_567).build(),
    )

    (chunk,) = read_region(ensure_readable(path))

    assert chunk.index == 0
    assert chunk.compression_type == 2
    assert chunk.is_external is False
    assert chunk.timestamp == 1_234_567
    assert chunk.sector_offset == 2


def test_empty_slots_are_skipped(tmp_path) -> None:
    builder = RegionBuilder().add(3, zlib.compress(b"a")).add(1023, zlib.compress(b"b"))
    path = write_region_file(tmp_path, builder.build())

    assert [c.index for c in read_region(ensure_readable(path))] == [3, 1023]


def test_local_coordinates_come_from_the_slot_index(tmp_path) -> None:
    path = write_region_file(tmp_path, RegionBuilder().add(33, zlib.compress(b"a")).build())

    (chunk,) = read_region(ensure_readable(path))

    assert (chunk.local_x, chunk.local_z) == (1, 1)


def test_external_flag_is_reported_without_being_treated_as_a_type(tmp_path) -> None:
    """`.mcc` 的 chunk 在 region 裡只有 header，payload 是空的。

    v1 拒絕處理外部 chunk，但那是 M1.3 的政策；讀取層只負責把事實報出來。
    """
    path = write_region_file(
        tmp_path, RegionBuilder().add(0, b"", compression_byte=0x82).build()
    )

    (chunk,) = read_region(ensure_readable(path))

    assert (chunk.compression_type, chunk.is_external) == (2, True)
    assert chunk.payload == b""


def test_unknown_compression_byte_names_the_chunk(tmp_path) -> None:
    path = write_region_file(
        tmp_path, RegionBuilder().add(7, b"junk", compression_byte=9).build()
    )

    with pytest.raises(UnknownCompressionError) as exc:
        list(read_region(ensure_readable(path)))
    assert exc.value.chunk_index == 7


# --- 邊界檢查 -------------------------------------------------------------


def test_file_shorter_than_the_two_tables_is_truncated(tmp_path) -> None:
    path = write_region_file(tmp_path, bytes(SECTOR_SIZE * 2 - 1))

    with pytest.raises(TruncatedRegionError):
        list(read_region(ensure_readable(path)))


def test_empty_file_is_truncated_not_an_empty_region(tmp_path) -> None:
    """0 bytes 的 .mca 是壞檔，不是「這個 region 沒有 chunk」。"""
    path = write_region_file(tmp_path, b"")

    with pytest.raises(TruncatedRegionError):
        list(read_region(ensure_readable(path)))


def test_payload_running_past_the_end_of_file_is_truncated(tmp_path) -> None:
    # 用亂數當 payload：壓不掉，所以真的會跨到第二個磁區，砍掉一個磁區才是砍到
    # payload 而不是砍掉整個 chunk 的 header。
    data = RegionBuilder().add(0, os.urandom(5000)).build()
    path = write_region_file(tmp_path, data[: len(data) - SECTOR_SIZE])

    with pytest.raises(TruncatedRegionError) as exc:
        list(read_region(ensure_readable(path)))
    assert exc.value.chunk_index == 0


def test_chunk_header_running_past_the_end_of_file_is_truncated(tmp_path) -> None:
    data = RegionBuilder().add(0, zlib.compress(b"x")).build()
    set_offset_entry(data, 0, sector=99, count=1)
    path = write_region_file(tmp_path, data)

    with pytest.raises(TruncatedRegionError):
        list(read_region(ensure_readable(path)))


def test_offset_pointing_into_the_tables_is_malformed(tmp_path) -> None:
    data = RegionBuilder().add(0, zlib.compress(b"x")).build()
    set_offset_entry(data, 0, sector=1, count=1)
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError):
        list(read_region(ensure_readable(path)))


def test_sector_count_of_zero_with_a_real_offset_is_malformed(tmp_path) -> None:
    data = RegionBuilder().add(0, zlib.compress(b"x")).build()
    set_offset_entry(data, 0, sector=2, count=0)
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError):
        list(read_region(ensure_readable(path)))


def test_declared_length_overflowing_its_sectors_is_malformed(tmp_path) -> None:
    data = RegionBuilder().add(0, zlib.compress(b"x")).build()
    set_declared_length(data, sector=2, length=SECTOR_SIZE)  # 1 個磁區只放得下 4092
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError):
        list(read_region(ensure_readable(path)))


def test_declared_length_of_zero_is_malformed(tmp_path) -> None:
    """長度至少要有壓縮類型那 1 byte。"""
    data = RegionBuilder().add(0, zlib.compress(b"x")).build()
    set_declared_length(data, sector=2, length=0)
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError):
        list(read_region(ensure_readable(path)))


def test_empty_payload_without_the_external_flag_is_malformed(tmp_path) -> None:
    data = RegionBuilder().add(0, b"", compression_byte=2).build()
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError):
        list(read_region(ensure_readable(path)))


# --- 串流 -----------------------------------------------------------------


def test_chunks_are_yielded_before_a_later_chunk_fails(tmp_path) -> None:
    """峰值記憶體要是單一 chunk，所以不能先整份讀完再回傳。"""
    data = RegionBuilder().add(0, zlib.compress(b"a")).add(1, zlib.compress(b"b")).build()
    set_offset_entry(data, 1, sector=1, count=1)
    path = write_region_file(tmp_path, data)

    seen = []
    with pytest.raises(MalformedRegionError):
        for chunk in read_region(ensure_readable(path)):
            seen.append(chunk.index)

    assert seen == [0]
