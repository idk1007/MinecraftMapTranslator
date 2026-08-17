# SPDX-License-Identifier: GPL-3.0-or-later
"""chunk 的結構閘門（M1.3）。

這一層回答兩個是非題，兩題都在任何東西被處理之前問：

1. 這個 chunk 的內容是不是在外部 `.mcc` 檔？→ 拒絕。
2. 這個 chunk 是不是 1.21 的形狀？→ 不是就拒絕**整個世界**。

第 2 題有三個症狀（`docs/STATUS.md` M1.3 驗收條件）：

* `Level` 包裝層 —— 1.12 把方塊實體放在 `Level.TileEntities`
* `Text1..Text4` —— 1.12 的告示牌欄位，沒有 `front_text`/`back_text`
* 沒有 `DataVersion` —— [實測] `From Ashes Reborn 1.12` 有 882 個這種 chunk

拒絕的理由不是「做不到」而是「沒測過」：1.12 地圖在 1.21.11 開啟後，走過的
區域升級、沒走過的維持原狀，同一個世界會同時存在兩套結構（CLAUDE.md §二）。

**放在 `nbtio/` 而不是計畫裡的 `scan/`**：這裡判斷的是「磁碟上的位元組是什麼
形狀」，不碰任何語意，錯誤也都屬於 `FormatError` 家族。`scan/` 是第 1 層，要到
M5 才會存在，而 `doctor`（M1.4）現在就需要這個閘門。
"""

from typing import Any

import amulet_nbt

from mcmt.errors import ExternalChunkError, UnsupportedWorldStructureError
from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import RawChunk

__all__ = ["ensure_supported_structure", "load_chunk_root"]

# 1.12 的告示牌欄位。一個就夠判斷，四個一起列是為了讓意圖看得出來。
_LEGACY_SIGN_FIELDS = ("Text1", "Text2", "Text3", "Text4")


def load_chunk_root(chunk: RawChunk) -> amulet_nbt.CompoundTag:
    """解壓並解析一個 chunk，回傳它的根 compound。

    外部 chunk 在解壓之前就被擋下——它的 payload 是空的，硬解只會得到一個
    看不懂的錯誤。
    """
    if chunk.is_external:
        raise ExternalChunkError(chunk_index=chunk.index)
    data = decompress_chunk(
        chunk.payload, chunk.compression_type, chunk_index=chunk.index
    )
    return amulet_nbt.load(data, compressed=False).compound


def ensure_supported_structure(
    root: amulet_nbt.CompoundTag, *, chunk_index: int
) -> int:
    """確認 chunk 是 1.21 的形狀，並回傳**這個 chunk 自己的** `DataVersion`。

    DataVersion 決定寫回哪個世代，**不**決定節點是什麼形狀——形狀一律逐節點
    嗅探（CLAUDE.md §二）。這裡回傳它只是因為讀到了，不是要拿來推導形狀。
    """

    def unsupported(reason: str, detail: str) -> UnsupportedWorldStructureError:
        return UnsupportedWorldStructureError(
            reason=reason, chunk_index=chunk_index, detail=detail
        )

    if "Level" in root:
        raise unsupported(
            "level_wrapper",
            "chunk 根有 `Level` 包裝層（1.12 結構，方塊實體在 `Level.TileEntities`）",
        )

    data_version = root.get("DataVersion")
    if not isinstance(data_version, amulet_nbt.AbstractBaseIntTag):
        raise unsupported(
            "missing_data_version",
            "chunk 根沒有整數的 `DataVersion`"
            f"（實際是 {type(data_version).__name__}）",
        )

    for entry in _block_entities(root):
        for field in _LEGACY_SIGN_FIELDS:
            if field in entry:
                raise unsupported(
                    "legacy_sign_text",
                    f"方塊實體帶 1.12 的 `{field}` 欄位，而不是 `front_text`/`back_text`",
                )

    return int(data_version)


def _block_entities(root: amulet_nbt.CompoundTag) -> list[Any]:
    entries = root.get("block_entities")
    if not isinstance(entries, amulet_nbt.ListTag):
        return []
    return [e for e in entries if isinstance(e, amulet_nbt.CompoundTag)]
