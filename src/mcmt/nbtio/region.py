# SPDX-License-Identifier: GPL-3.0-or-later
"""anvil region（`.mca`）的唯讀串流（M1.2）。

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

註：路徑目前直接開，還沒過 `safety.ensure_readable`（那是 M2）。接上安全層時，
唯一該改的地方是這裡的 `open`。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from mcmt.errors import MalformedRegionError, TruncatedRegionError
from mcmt.nbtio.compression import parse_compression_byte
from mcmt.safety.paths import ReadOnlyPath

__all__ = [
    "CHUNKS_PER_REGION",
    "RawChunk",
    "SECTOR_SIZE",
    "read_region",
    "region_files",
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
    if size < _HEADER_SECTORS * SECTOR_SIZE:
        raise TruncatedRegionError(
            path=path,
            detail=f"只有 {size} bytes，連 8192 bytes 的兩張表都放不下",
        )

    with path.open_binary() as handle:
        offsets = handle.read(SECTOR_SIZE)
        timestamps = handle.read(SECTOR_SIZE)

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
