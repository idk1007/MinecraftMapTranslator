# SPDX-License-Identifier: GPL-3.0-or-later
"""M3.3 損壞防禦。

M1.2 已經擋下讀取端的四種畸形（截斷、offset 指向檔外、長度為 0 的空槽、長度溢出
磁區）。這裡補的是兩個當時沒處理的類別：

1. **磁區重疊** —— 兩個 chunk 宣告的磁區範圍交疊。兩邊都「讀得出東西」，所以不
   檢查就會安靜地讀到垃圾，是最難查的那種。
2. **寫入端的輸入驗證** —— 重複的 index、超出範圍的 index、非法壓縮類型、空
   payload。這些在 M11 是真的會發生的呼叫端錯誤，寫出去才發現就太晚了。
"""

import zlib

import pytest
from conftest import RegionBuilder, modern_chunk, set_offset_entry, write_region_file

from mcmt.errors import InvalidChunkWriteError, MalformedRegionError
from mcmt.nbtio.region import ChunkWrite, read_region, write_region
from mcmt.safety.paths import ensure_readable


def chunk_write(**overrides) -> ChunkWrite:
    fields = {
        "index": 0,
        "payload": zlib.compress(b"\x0a\x00\x00\x00"),
        "compression_type": 2,
        "timestamp": 1,
        "modified": False,
    }
    fields.update(overrides)
    return ChunkWrite(**fields)


# --- 讀取端：磁區重疊 -----------------------------------------------------


def test_two_chunks_claiming_the_same_sectors_is_malformed(tmp_path) -> None:
    data = (
        RegionBuilder()
        .add_chunk_nbt(0, modern_chunk())
        .add_chunk_nbt(1, modern_chunk())
        .build()
    )
    set_offset_entry(data, 1, sector=2, count=1)  # 指到 chunk 0 的磁區
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError) as exc:
        list(read_region(ensure_readable(path)))

    message = str(exc.value)
    assert "0" in message and "1" in message


def test_partially_overlapping_sectors_are_malformed(tmp_path) -> None:
    """後一個 chunk 的起點落在前一個的範圍中間。"""
    data = RegionBuilder().add(0, b"\x00" * 5000).add(9, b"\x00" * 100).build()
    set_offset_entry(data, 9, sector=3, count=1)  # chunk 0 佔 2..3
    path = write_region_file(tmp_path, data)

    with pytest.raises(MalformedRegionError):
        list(read_region(ensure_readable(path)))


def test_adjacent_chunks_are_not_overlapping(tmp_path) -> None:
    """磁區緊鄰是正常的，不能誤報。"""
    data = (
        RegionBuilder()
        .add_chunk_nbt(0, modern_chunk())
        .add_chunk_nbt(1, modern_chunk())
        .build()
    )
    path = write_region_file(tmp_path, data)

    assert [c.index for c in read_region(ensure_readable(path))] == [0, 1]


# --- 寫入端：輸入驗證 -----------------------------------------------------


def test_two_chunks_with_the_same_index_are_refused(project) -> None:
    """兩筆同 index 會讓其中一筆變成檔案裡指不到的孤兒磁區。"""
    target = project / "sandbox" / "r.0.0.mca"

    with pytest.raises(InvalidChunkWriteError) as exc:
        write_region(target, [chunk_write(index=7), chunk_write(index=7)])

    assert "7" in str(exc.value)


@pytest.mark.parametrize("index", [-1, 1024, 5000])
def test_an_index_outside_the_region_is_refused(project, index: int) -> None:
    target = project / "sandbox" / "r.0.0.mca"

    with pytest.raises(InvalidChunkWriteError):
        write_region(target, [chunk_write(index=index)])


@pytest.mark.parametrize("compression_type", [0, 5, 0x82, 255])
def test_an_illegal_compression_type_is_refused(project, compression_type: int) -> None:
    """寫出去的位元組要是我們自己讀得回來的。0x82 是沒遮罩的原始位元組。"""
    target = project / "sandbox" / "r.0.0.mca"

    with pytest.raises(InvalidChunkWriteError):
        write_region(target, [chunk_write(compression_type=compression_type)])


def test_an_empty_payload_is_refused(project) -> None:
    """空 payload 寫出去，讀回來會是 MalformedRegionError——不如現在就擋。"""
    target = project / "sandbox" / "r.0.0.mca"

    with pytest.raises(InvalidChunkWriteError):
        write_region(target, [chunk_write(payload=b"")])


def test_nothing_is_written_when_the_input_is_rejected(project) -> None:
    """驗證要在動磁碟之前做完。"""
    target = project / "sandbox" / "r.0.0.mca"

    with pytest.raises(InvalidChunkWriteError):
        write_region(target, [chunk_write(index=0), chunk_write(index=0)])

    assert not target.exists()
    assert list(target.parent.glob("*.mcmt-tmp")) == []
