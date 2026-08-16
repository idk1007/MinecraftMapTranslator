# SPDX-License-Identifier: GPL-3.0-or-later
"""M1.1 壓縮分派。

規範來源：CLAUDE.md §1.3「未知的 chunk 壓縮類型必須明確報錯」。
關鍵不變式：**`0x80` 遮罩必須在判斷型別之前**。
"""

import gzip
import zlib

import pytest

from mcmt.errors import (
    CorruptCompressedDataError,
    MissingDependencyError,
    UnknownCompressionError,
)
from mcmt.nbtio.compression import decompress_chunk, parse_compression_byte

# --- LZ4 測試資料 ---------------------------------------------------------
# Mojang 的 type 4 走 lz4-java 的 LZ4BlockOutputStream，不是標準 LZ4 frame。
# 語料 5 張地圖 16.2 萬 chunk 沒有一個 type 4（SPIKE_RESULT.md），所以這裡的
# 編碼器是照 lz4-java 的格式手寫的，用來驗解碼器的框架解析。[待驗]
LZ4_MAGIC = b"LZ4Block"
LZ4_METHOD_RAW = 0x10
LZ4_METHOD_LZ4 = 0x20


def _lz4_block_stream(data: bytes, *, block_size: int = 1 << 16) -> bytes:
    """照 lz4-java LZ4BlockOutputStream 的框架把 data 包起來。"""
    import lz4.block

    level = block_size.bit_length() - 1 - 10  # log2(block_size) - 10
    out = bytearray()
    for start in range(0, len(data), block_size):
        block = data[start : start + block_size]
        compressed = lz4.block.compress(block, store_size=False)
        if len(compressed) >= len(block):
            method, body = LZ4_METHOD_RAW, block
        else:
            method, body = LZ4_METHOD_LZ4, compressed
        out += LZ4_MAGIC
        out += bytes([method | level])
        out += len(body).to_bytes(4, "little")
        out += len(block).to_bytes(4, "little")
        out += (0).to_bytes(4, "little")  # XXHash32 檢查碼，解碼端不驗
        out += body
    # 結束標記：originalLen == 0
    out += LZ4_MAGIC + bytes([LZ4_METHOD_RAW | level]) + (0).to_bytes(4, "little") * 3
    return bytes(out)


# --- parse_compression_byte ----------------------------------------------


@pytest.mark.parametrize("type_id", [1, 2, 3, 4])
def test_known_types_parse_without_external_flag(type_id: int) -> None:
    assert parse_compression_byte(type_id, chunk_index=0) == (type_id, False)


@pytest.mark.parametrize("type_id", [1, 2, 3, 4])
def test_external_flag_is_masked_before_type_is_decided(type_id: int) -> None:
    """0x80 先遮罩再判型別。不先遮罩的話 0x82 會被當成未知類型 130。"""
    assert parse_compression_byte(0x80 | type_id, chunk_index=0) == (type_id, True)


def test_unknown_type_reports_value_and_chunk_index() -> None:
    with pytest.raises(UnknownCompressionError) as exc:
        parse_compression_byte(5, chunk_index=317)
    message = str(exc.value)
    assert "5" in message
    assert "317" in message


def test_zero_is_not_a_valid_type() -> None:
    with pytest.raises(UnknownCompressionError):
        parse_compression_byte(0, chunk_index=0)


def test_unknown_type_with_external_flag_reports_raw_and_masked_value() -> None:
    """遮罩後才是型別，但原始位元組也要出現在訊息裡，才查得出磁碟上真正的值。"""
    with pytest.raises(UnknownCompressionError) as exc:
        parse_compression_byte(0x85, chunk_index=42)
    message = str(exc.value)
    assert "0x85" in message
    assert "5" in message
    assert "42" in message


def test_unknown_type_error_carries_structured_fields() -> None:
    with pytest.raises(UnknownCompressionError) as exc:
        parse_compression_byte(9, chunk_index=7)
    assert exc.value.raw_byte == 9
    assert exc.value.type_id == 9
    assert exc.value.chunk_index == 7


# --- decompress_chunk -----------------------------------------------------


def test_gzip_payload_is_decompressed() -> None:
    payload = gzip.compress(b"hello world")
    assert decompress_chunk(payload, 1, chunk_index=0) == b"hello world"


def test_zlib_payload_is_decompressed() -> None:
    payload = zlib.compress(b"hello world")
    assert decompress_chunk(payload, 2, chunk_index=0) == b"hello world"


def test_uncompressed_payload_is_returned_unchanged() -> None:
    payload = b"\x0a\x00\x00raw nbt bytes"
    assert decompress_chunk(payload, 3, chunk_index=0) == payload


def test_lz4_payload_is_decompressed() -> None:
    original = b"minecraft chunk data " * 64
    payload = _lz4_block_stream(original)
    assert decompress_chunk(payload, 4, chunk_index=0) == original


def test_lz4_payload_spanning_multiple_blocks_is_decompressed() -> None:
    original = bytes(range(256)) * 40  # > 4 個 1024-byte 區塊
    payload = _lz4_block_stream(original, block_size=1024)
    assert decompress_chunk(payload, 4, chunk_index=0) == original


def test_lz4_without_the_dependency_names_the_install_command(monkeypatch) -> None:
    import mcmt.nbtio.compression as compression

    def _no_lz4(name: str):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(compression, "import_module", _no_lz4)
    with pytest.raises(MissingDependencyError) as exc:
        decompress_chunk(b"whatever", 4, chunk_index=0)
    assert "pip install mcmt[lz4]" in str(exc.value)


def test_lz4_stream_without_magic_is_reported_as_corrupt() -> None:
    with pytest.raises(CorruptCompressedDataError):
        decompress_chunk(b"not an lz4 block stream at all", 4, chunk_index=11)


def test_decompress_rejects_the_unmasked_byte() -> None:
    """呼叫端若把沒遮罩的位元組直接丟進來，要爆而不是猜。"""
    with pytest.raises(UnknownCompressionError):
        decompress_chunk(zlib.compress(b"x"), 0x82, chunk_index=0)


def test_corrupt_zlib_payload_reports_chunk_index() -> None:
    with pytest.raises(CorruptCompressedDataError) as exc:
        decompress_chunk(b"\x78\x9c" + b"\x00" * 16, 2, chunk_index=1023)
    assert "1023" in str(exc.value)


def test_corrupt_gzip_payload_is_not_silently_retried_as_zlib() -> None:
    """猜錯壓縮法就是寫壞存檔，所以不 fallback。"""
    with pytest.raises(CorruptCompressedDataError):
        decompress_chunk(zlib.compress(b"hello"), 1, chunk_index=0)
