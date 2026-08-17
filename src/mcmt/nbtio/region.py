# SPDX-License-Identifier: GPL-3.0-or-later
"""anvil region（`.mca`）的讀寫（M1.2 讀 · M3.1 寫）。

檔案結構：

    磁區 0      4096 bytes 偏移表：1024 格 × (3 bytes 磁區偏移 + 1 byte 磁區數)，大端
    磁區 1      4096 bytes 時間戳表：1024 個 uint32，大端
    磁區 2..    每個 chunk：4 bytes 長度 + 1 byte 壓縮類型 + payload，補齊到磁區邊界

長度欄位**含**那 1 byte 壓縮類型，所以 payload 是 `length - 1` bytes。

**`RawChunk.payload` 是磁碟上的原始壓縮位元組，這裡不解壓。** 外科式寫入的
整個保證建立在「未修改的 chunk 從沒被解碼過」之上（CLAUDE.md §1.4），所以讀取
層拿到什麼就給什麼；要看內容的人自己去呼叫 `decompress_chunk`。

`read_region` 是產生器，逐 chunk yield，峰值記憶體是單一 chunk——12 萬 chunk 的
世界不能整份讀進記憶體。

寫入端（`write_region`）的規則見 `ChunkWrite` 與 `write_region` 的 docstring。
一句話：**未修改的 chunk 原封複製原始壓縮位元組，這一層永遠不壓縮任何東西。**
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from mcmt.errors import (
    ChunkTooLargeError,
    ExternalChunkError,
    InvalidChunkWriteError,
    MalformedRegionError,
    TruncatedRegionError,
)
from mcmt.nbtio.compression import COMPRESSION_NAMES, parse_compression_byte
from mcmt.safety.paths import ReadOnlyPath, ensure_writable

__all__ = [
    "CHUNKS_PER_REGION",
    "ChunkWrite",
    "RawChunk",
    "RegionWriteReport",
    "SECTOR_SIZE",
    "read_region",
    "region_files",
    "write_region",
]

SECTOR_SIZE = 4096
CHUNKS_PER_REGION = 1024
_HEADER_SECTORS = 2  # 偏移表 + 時間戳表
_CHUNK_HEADER_LEN = 5  # 4 bytes 長度 + 1 byte 壓縮類型


@dataclass(frozen=True)
class RawChunk:
    """region 裡的一個 chunk，未解壓。"""

    index: int
    timestamp: int
    compression_type: int
    is_external: bool
    payload: bytes
    sector_offset: int
    sector_count: int

    @property
    def local_x(self) -> int:
        return self.index % 32

    @property
    def local_z(self) -> int:
        return self.index // 32


@dataclass(frozen=True)
class ChunkWrite:
    """一個要寫回 region 的 chunk。

    用 `unchanged()` 或 `replaced()` 建立，不要直接填欄位——那兩個建構子讓「這個
    chunk 有沒有被改過」在呼叫端**看得見**，而 `modified` 決定 timestamp 走哪條路。

    `payload` 一律是**已經壓縮好的位元組**。這一層永遠不壓縮任何東西：未修改的
    chunk 帶著它從磁碟上讀來的原始位元組，修改過的由呼叫端負責編碼。
    """

    index: int
    payload: bytes
    compression_type: int
    timestamp: int
    modified: bool

    @classmethod
    def unchanged(cls, chunk: RawChunk) -> "ChunkWrite":
        """原封沿用：原始壓縮位元組 + 原始 timestamp，一個位元都不動。"""
        if chunk.is_external:
            raise ExternalChunkError(chunk_index=chunk.index)
        return cls(
            index=chunk.index,
            payload=chunk.payload,
            compression_type=chunk.compression_type,
            timestamp=chunk.timestamp,
            modified=False,
        )

    @classmethod
    def replaced(cls, chunk: RawChunk, payload: bytes) -> "ChunkWrite":
        """換上新的壓縮位元組。timestamp 會被 `write_region` 更新為當下時間。"""
        if chunk.is_external:
            raise ExternalChunkError(chunk_index=chunk.index)
        return cls(
            index=chunk.index,
            payload=payload,
            compression_type=chunk.compression_type,
            timestamp=chunk.timestamp,
            modified=True,
        )


@dataclass(frozen=True)
class RegionWriteReport:
    """一次 region 寫入的結果。`size_*` 供 `apply_report` 的 `sector_realignment`。"""

    path: Path
    chunks_written: int
    modified_count: int
    size_before: int
    size_after: int

    @property
    def realigned(self) -> bool:
        """既有檔案的大小變了。**這不是資料遺失**，是磁區重整（原檔有空隙）。

        使用者看到檔案縮小會合理地恐慌，所以必須報告（CLAUDE.md §1.5）。但新建的
        檔案不算——`size_before` 是 0 只代表本來沒有這個檔案。警告出現在不需要它
        的地方，使用者就會學會忽略它。
        """
        return self.size_before != 0 and self.size_after != self.size_before


def write_region(
    path: Path | str,
    chunks: Iterable[ChunkWrite],
    *,
    now: int | None = None,
) -> RegionWriteReport:
    """把一組 chunk 寫成一張完整的 region 檔。

    * **未修改的 chunk 原封複製原始壓縮位元組**，絕不重新編碼（CLAUDE.md §1.4）。
    * timestamp 表：未修改的原樣搬運、修改過的更新為 `now`。不整表歸零（遊戲會
      誤判所有 chunk 都是新的），也不整表沿用（被改的 chunk 帶著舊時間）。
    * 先寫到 `.tmp` 再 `os.replace`：寫到一半掛掉時，磁碟上的原檔完好無損。
    """
    target = ensure_writable(path)
    stamp = int(time.time()) if now is None else now
    ordered = sorted(chunks, key=lambda c: c.index)
    _validate(ordered)  # 動磁碟之前先驗完

    offsets = bytearray(SECTOR_SIZE)
    timestamps = bytearray(SECTOR_SIZE)
    body = bytearray()
    next_sector = _HEADER_SECTORS

    for chunk in ordered:
        block = bytearray()
        block += (len(chunk.payload) + 1).to_bytes(4, "big")
        block += bytes([chunk.compression_type])
        block += chunk.payload
        sectors = -(-len(block) // SECTOR_SIZE)  # 無條件進位
        if sectors > 255:
            raise ChunkTooLargeError(chunk_index=chunk.index, sectors=sectors)
        block += bytes(sectors * SECTOR_SIZE - len(block))

        slot = chunk.index * 4
        offsets[slot : slot + 4] = next_sector.to_bytes(3, "big") + bytes([sectors])
        stored_time = stamp if chunk.modified else chunk.timestamp
        timestamps[slot : slot + 4] = stored_time.to_bytes(4, "big")
        body += block
        next_sector += sectors

    size_before = target.stat().st_size if target.exists() else 0
    data = bytes(offsets + timestamps + body)

    temporary = ensure_writable(target.with_name(target.name + ".mcmt-tmp"))
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    return RegionWriteReport(
        path=target,
        chunks_written=len(ordered),
        modified_count=sum(1 for c in ordered if c.modified),
        size_before=size_before,
        size_after=len(data),
    )


def _validate(chunks: list[ChunkWrite]) -> None:
    seen: set[int] = set()
    for chunk in chunks:
        if not 0 <= chunk.index < CHUNKS_PER_REGION:
            raise InvalidChunkWriteError(
                detail=f"chunk index {chunk.index} 不在 0..{CHUNKS_PER_REGION - 1} 之內"
            )
        if chunk.index in seen:
            raise InvalidChunkWriteError(
                detail=f"chunk index {chunk.index} 出現兩次——"
                f"其中一筆會變成檔案裡指不到的孤兒磁區"
            )
        seen.add(chunk.index)
        if chunk.compression_type not in COMPRESSION_NAMES:
            raise InvalidChunkWriteError(
                detail=f"chunk index {chunk.index} 的壓縮類型是 "
                f"0x{chunk.compression_type:02x}，不是 1/2/3/4。"
                f"（要寫的是已遮罩的類型，不是磁碟上那個含 0x80 的原始位元組）"
            )
        if not chunk.payload:
            raise InvalidChunkWriteError(
                detail=f"chunk index {chunk.index} 的 payload 是空的——"
                f"寫出去之後我們自己會讀不回來"
            )


def region_files(world: ReadOnlyPath) -> list[ReadOnlyPath]:
    """世界底下所有的方塊 region 檔，依路徑排序。

    「所有名為 `region` 的目錄」涵蓋 `region/`、`DIM-1/region/`、`DIM1/region/`
    與 datapack 自訂維度（`dimensions/<ns>/<name>/region/`）——[實測] MP2 有 5 個。

    `entities/` 與 `poi/` 底下也是 `.mca`，但那不是方塊 chunk，v1 不看。掃描範圍
    擴大到 entities 時（M13），**世界指紋的定義要一起重新考慮**，因為那會改變
    「什麼算這個世界的內容」。
    """
    return sorted(
        (
            path
            for directory in world.rglob("region")
            if directory.is_dir()
            for path in directory.glob("*.mca")
        ),
        key=str,
    )


def read_region(path: ReadOnlyPath) -> Iterator[RawChunk]:
    """依 slot 順序逐一 yield region 裡實際存在的 chunk。

    **只收 `ReadOnlyPath`。** 裸 `Path` 進不來，所以「忘了過 `ensure_readable`」
    在型別層就會被擋下，不是靠呼叫端自律（CLAUDE.md §1.1）。
    """
    if not isinstance(path, ReadOnlyPath):
        raise TypeError(
            f"read_region 只收 ReadOnlyPath，收到 {type(path).__name__}。"
            f"請先過 ensure_readable(...)。"
        )
    size = path.size()
    if size == 0:
        # 0 bytes 是「這個 region 沒有 chunk」的普遍慣例，不是損壞。
        # [實測] 20 個世界的 1,608 個 region 檔裡有 203 個（12.6%）正好 0 bytes，
        # 分佈在 6 個世界，其中一個世界全部 28 個都是。而介於 1..8191 bytes 的有
        # 0 個——「寫到一半的 header」在真實世界不存在。
        return
    if size < _HEADER_SECTORS * SECTOR_SIZE:
        raise TruncatedRegionError(
            path=path,
            detail=f"只有 {size} bytes，連 8192 bytes 的兩張表都放不下"
            f"（0 bytes 會被當成空 region，這個大小是真的寫到一半）",
        )

    with path.open_binary() as handle:
        offsets = handle.read(SECTOR_SIZE)
        timestamps = handle.read(SECTOR_SIZE)
        _check_for_overlaps(offsets, path)

        for index in range(CHUNKS_PER_REGION):
            entry = offsets[index * 4 : index * 4 + 4]
            sector_offset = int.from_bytes(entry[:3], "big")
            sector_count = entry[3]
            if sector_offset == 0 and sector_count == 0:
                continue
            timestamp = int.from_bytes(
                timestamps[index * 4 : index * 4 + 4], "big"
            )
            yield _read_chunk(
                handle,
                path=path,
                size=size,
                index=index,
                sector_offset=sector_offset,
                sector_count=sector_count,
                timestamp=timestamp,
            )


def _check_for_overlaps(offsets: bytes, path: ReadOnlyPath) -> None:
    """兩個 chunk 宣告的磁區範圍交疊 = 這張 region 壞了。

    兩邊都「讀得出東西」，所以不檢查就會安靜地讀到垃圾——是最難查的那種。整張表
    在這裡已經讀完了，所以這個檢查不影響串流。
    """
    spans = []
    for index in range(CHUNKS_PER_REGION):
        entry = offsets[index * 4 : index * 4 + 4]
        start = int.from_bytes(entry[:3], "big")
        count = entry[3]
        if start == 0 or count == 0:
            continue
        spans.append((start, start + count, index))

    spans.sort()
    for (_, previous_end, previous_index), (start, _, index) in zip(spans, spans[1:]):
        if start < previous_end:
            raise MalformedRegionError(
                path=path,
                chunk_index=index,
                detail=f"磁區範圍與 chunk index {previous_index} 交疊"
                f"（前者在磁區 {previous_end} 之前結束，這個從 {start} 開始）",
            )


def _read_chunk(
    handle,
    *,
    path: ReadOnlyPath,
    size: int,
    index: int,
    sector_offset: int,
    sector_count: int,
    timestamp: int,
) -> RawChunk:
    def malformed(detail: str) -> MalformedRegionError:
        return MalformedRegionError(path=path, chunk_index=index, detail=detail)

    def truncated(detail: str) -> TruncatedRegionError:
        return TruncatedRegionError(path=path, chunk_index=index, detail=detail)

    if sector_offset < _HEADER_SECTORS:
        raise malformed(
            f"磁區偏移 {sector_offset} 指進了前兩個磁區（偏移表與時間戳表）"
        )
    if sector_count == 0:
        raise malformed(f"磁區偏移是 {sector_offset} 但磁區數是 0")

    start = sector_offset * SECTOR_SIZE
    if start + _CHUNK_HEADER_LEN > size:
        raise truncated(
            f"chunk header 落在位移 {start}，檔案只有 {size} bytes"
        )

    handle.seek(start)
    declared_length = int.from_bytes(handle.read(4), "big")
    if declared_length < 1:
        raise malformed("宣告長度為 0，連壓縮類型那 1 byte 都不夠")
    available = sector_count * SECTOR_SIZE - 4
    if declared_length > available:
        raise malformed(
            f"宣告長度 {declared_length} 超過 {sector_count} 個磁區能放的 {available} bytes"
        )

    compression_byte = handle.read(1)[0]
    compression_type, is_external = parse_compression_byte(
        compression_byte, chunk_index=index
    )

    payload_length = declared_length - 1
    if start + _CHUNK_HEADER_LEN + payload_length > size:
        raise truncated(
            f"payload 宣告 {payload_length} bytes，但位移 {start + _CHUNK_HEADER_LEN} "
            f"之後檔案只剩 {max(size - start - _CHUNK_HEADER_LEN, 0)} bytes"
        )
    payload = handle.read(payload_length)
    if len(payload) != payload_length:
        raise truncated(
            f"payload 宣告 {payload_length} bytes，實際只讀到 {len(payload)} bytes"
        )
    if payload_length == 0 and not is_external:
        raise malformed(
            "payload 是空的，但沒有外部 chunk 旗標（0x80）——空 chunk 不是合法狀態"
        )

    return RawChunk(
        index=index,
        timestamp=timestamp,
        compression_type=compression_type,
        is_external=is_external,
        payload=payload,
        sector_offset=sector_offset,
        sector_count=sector_count,
    )
