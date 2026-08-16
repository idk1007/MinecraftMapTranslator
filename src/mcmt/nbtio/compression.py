# SPDX-License-Identifier: GPL-3.0-or-later
"""chunk 壓縮類型的分派與解壓（M1.1）。

region 檔裡每個 chunk 的第 5 個位元組是壓縮類型：

    1 gzip · 2 zlib · 3 未壓縮 · 4 LZ4

最高位 `0x80` 不是類型的一部分，而是「這個 chunk 的內容在外部 `.mcc` 檔」的旗標。
**遮罩必須在判斷型別之前**——不先遮罩的話，一個 zlib 的外部 chunk 會被讀成
「未知類型 130」。

這個模組只負責讀（解壓）。寫入端的壓縮在 M3，且只有**被修改的 chunk** 會走到
那裡：未修改的 chunk 一律原封複製原始壓縮位元組（CLAUDE.md §1.4）。
"""

import gzip
import zlib
from importlib import import_module

from mcmt.errors import (
    CorruptCompressedDataError,
    MissingDependencyError,
    UnknownCompressionError,
)

__all__ = [
    "COMPRESSION_NAMES",
    "EXTERNAL_FLAG",
    "decompress_chunk",
    "parse_compression_byte",
]

EXTERNAL_FLAG = 0x80

COMPRESSION_NAMES: dict[int, str] = {
    1: "gzip",
    2: "zlib",
    3: "none",
    4: "lz4",
}

# Mojang 的 type 4 走 lz4-java 的 LZ4BlockOutputStream，不是標準的 LZ4 frame 格式。
# 每個區塊： "LZ4Block" + token + compressedLen(LE32) + originalLen(LE32) + xxhash32(LE32)
# 結束標記是 originalLen == 0 的區塊。
# [待驗] 語料 5 張地圖 16.2 萬 chunk 全為 type 2，這條路徑沒有真實樣本走過。
_LZ4_MAGIC = b"LZ4Block"
_LZ4_HEADER_LEN = 21
_LZ4_METHOD_MASK = 0xF0
_LZ4_METHOD_RAW = 0x10
_LZ4_METHOD_LZ4 = 0x20


def parse_compression_byte(raw: int, *, chunk_index: int) -> tuple[int, bool]:
    """把 chunk header 的壓縮位元組拆成 `(type_id, is_external)`。

    `chunk_index` 是必填的——它唯一的用途就是讓錯誤訊息指得出是哪個 chunk，
    給它預設值等於允許呼叫端把這個資訊丟掉。
    """
    is_external = bool(raw & EXTERNAL_FLAG)
    type_id = raw & ~EXTERNAL_FLAG
    if type_id not in COMPRESSION_NAMES:
        raise UnknownCompressionError(
            raw_byte=raw, type_id=type_id, chunk_index=chunk_index
        )
    return type_id, is_external


def decompress_chunk(payload: bytes, type_id: int, *, chunk_index: int) -> bytes:
    """解開單一 chunk 的 payload。

    `type_id` 必須是**已遮罩**的類型（`parse_compression_byte` 的回傳值）。
    直接把原始位元組丟進來會拋 `UnknownCompressionError` 而不是被默默遮罩掉。
    """
    if type_id not in COMPRESSION_NAMES:
        raise UnknownCompressionError(
            raw_byte=type_id, type_id=type_id, chunk_index=chunk_index
        )

    if type_id == 3:
        return payload

    if type_id == 1:
        try:
            return gzip.decompress(payload)
        except (OSError, EOFError, zlib.error) as exc:
            raise CorruptCompressedDataError(
                type_name="gzip", chunk_index=chunk_index, detail=str(exc)
            ) from exc

    if type_id == 2:
        try:
            return zlib.decompress(payload)
        except zlib.error as exc:
            raise CorruptCompressedDataError(
                type_name="zlib", chunk_index=chunk_index, detail=str(exc)
            ) from exc

    return _decompress_lz4(payload, chunk_index=chunk_index)


def _decompress_lz4(payload: bytes, *, chunk_index: int) -> bytes:
    try:
        lz4_block = import_module("lz4.block")
    except ImportError as exc:
        raise MissingDependencyError(
            f"chunk index {chunk_index} 是 LZ4 壓縮（type 4），但沒有安裝 lz4。"
            f"請執行：pip install mcmt[lz4]"
        ) from exc

    def corrupt(detail: str) -> CorruptCompressedDataError:
        return CorruptCompressedDataError(
            type_name="lz4", chunk_index=chunk_index, detail=detail
        )

    out = bytearray()
    pos = 0
    while True:
        if len(payload) - pos < _LZ4_HEADER_LEN:
            raise corrupt(
                f"位移 {pos} 之後不足一個區塊標頭，且沒有遇到結束標記"
            )
        if payload[pos : pos + 8] != _LZ4_MAGIC:
            raise corrupt(f"位移 {pos} 缺少 LZ4Block magic")
        token = payload[pos + 8]
        compressed_len = int.from_bytes(payload[pos + 9 : pos + 13], "little")
        original_len = int.from_bytes(payload[pos + 13 : pos + 17], "little")
        pos += _LZ4_HEADER_LEN

        if original_len == 0:
            return bytes(out)

        body = payload[pos : pos + compressed_len]
        if len(body) != compressed_len:
            raise corrupt(
                f"區塊宣告 {compressed_len} bytes，實際只剩 {len(body)} bytes"
            )
        pos += compressed_len

        method = token & _LZ4_METHOD_MASK
        if method == _LZ4_METHOD_RAW:
            if len(body) != original_len:
                raise corrupt(
                    f"未壓縮區塊長度 {len(body)} 與宣告的 {original_len} 不符"
                )
            out += body
        elif method == _LZ4_METHOD_LZ4:
            try:
                out += lz4_block.decompress(body, uncompressed_size=original_len)
            except lz4_block.LZ4BlockError as exc:
                raise corrupt(f"位移 {pos} 的區塊解壓失敗：{exc}") from exc
        else:
            raise corrupt(f"未知的區塊壓縮方式 0x{method:02x}（token 0x{token:02x}）")
