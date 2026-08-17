# SPDX-License-Identifier: GPL-3.0-or-later
"""測試共用的 region 合成工具。

真實 region 切片（`tests/fixtures/regions/`）留給整合測試；單元測試用合成的
位元組，才能精準地製造畸形檔。
"""

import zlib

import amulet_nbt

SECTOR_SIZE = 4096


class RegionBuilder:
    """組出一個結構正確的 region，畸形的情況再事後改位元組。"""

    def __init__(self) -> None:
        self._slots: dict[int, tuple[int, bytes, int]] = {}

    def add(
        self,
        index: int,
        payload: bytes,
        *,
        compression_byte: int = 2,
        timestamp: int = 1_700_000_000,
    ) -> "RegionBuilder":
        self._slots[index] = (compression_byte, payload, timestamp)
        return self

    def add_chunk_nbt(
        self, index: int, root: amulet_nbt.CompoundTag, **kwargs
    ) -> "RegionBuilder":
        data = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
        return self.add(index, zlib.compress(data), **kwargs)

    def build(self) -> bytearray:
        offsets = bytearray(SECTOR_SIZE)
        timestamps = bytearray(SECTOR_SIZE)
        body = bytearray()
        next_sector = 2
        for index in sorted(self._slots):
            compression_byte, payload, timestamp = self._slots[index]
            block = bytearray()
            block += (len(payload) + 1).to_bytes(4, "big")
            block += bytes([compression_byte])
            block += payload
            sectors = (len(block) + SECTOR_SIZE - 1) // SECTOR_SIZE
            block += bytes(sectors * SECTOR_SIZE - len(block))
            offsets[index * 4 : index * 4 + 4] = next_sector.to_bytes(3, "big") + bytes(
                [sectors]
            )
            timestamps[index * 4 : index * 4 + 4] = timestamp.to_bytes(4, "big")
            body += block
            next_sector += sectors
        return offsets + timestamps + body


def set_offset_entry(data: bytearray, index: int, sector: int, count: int) -> None:
    data[index * 4 : index * 4 + 4] = sector.to_bytes(3, "big") + bytes([count])


def set_declared_length(data: bytearray, sector: int, length: int) -> None:
    start = sector * SECTOR_SIZE
    data[start : start + 4] = length.to_bytes(4, "big")


def write_region_file(directory, data: bytes | bytearray, name: str = "r.0.0.mca"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(bytes(data))
    return path


def modern_chunk(*, data_version: int = 4671) -> amulet_nbt.CompoundTag:
    """1.21 形狀的最小 chunk：只有 DataVersion。"""
    root = amulet_nbt.CompoundTag()
    root["DataVersion"] = amulet_nbt.IntTag(data_version)
    return root


def legacy_chunk() -> amulet_nbt.CompoundTag:
    """1.12 形狀：`Level` 包裝層。"""
    root = amulet_nbt.CompoundTag()
    level = amulet_nbt.CompoundTag()
    level["TileEntities"] = amulet_nbt.ListTag([])
    root["Level"] = level
    return root
