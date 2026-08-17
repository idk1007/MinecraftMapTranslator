# SPDX-License-Identifier: GPL-3.0-or-later
"""世界指紋（M2.2）。

合約（`docs/contracts/extract.schema.json`）對這個值只有一條硬性要求：

> MUST be derived from per-chunk DataVersions and region content, NOT from file
> mtime or size

理由是 [實測]：在遊戲裡開一次世界，120,036 個 chunk 裡有 182 個被升級，而 mtime
沒有任何有意義的訊號。用 mtime 當身分，會在「世界其實變了」時說沒變。

**實作**：blake2b 掃過每個 region 檔的每個 chunk，餵進去的是

    <region 檔相對於世界根的路徑>\\x1f<chunk index>\\x1f<原始壓縮 payload>

per-chunk DataVersion 被 payload 涵蓋——DataVersion 就在那段 NBT 裡面，它變了
payload 就變了。刻意**不**餵進去的三樣東西：

* **檔案 mtime 與大小** —— 合約明文禁止。
* **磁區排列** —— 只走 `read_region` 讀出來的 chunk，不碰磁區間的空隙與尾端補零。
  磁區重整後的世界與重整前是同一個世界（CLAUDE.md §1.5）。
* **chunk 時間戳** —— 後設資料。內容一樣，既有的 extract 就還適用。

**壞掉的 region 不會讓指紋失敗**：它會被折成一個穩定的標記寫進 hash。指紋負責
身分，健檢是 `doctor` 的事——壞掉的世界更需要能先被複製進 sandbox 再診斷。
"""

from hashlib import blake2b
from pathlib import Path

from mcmt.errors import FormatError
from mcmt.nbtio.region import read_region, region_files
from mcmt.safety.paths import ensure_readable

__all__ = ["world_fingerprint"]

_DIGEST_SIZE = 16  # 32 hex，符合合約的 ^blake2b:[0-9a-f]{16,64}$
_SEP = b"\x1f"


def world_fingerprint(world: Path | str) -> str:
    """回傳 `blake2b:<32 hex>` 形式的世界內容身分。"""
    readable = ensure_readable(Path(world))
    digest = blake2b(digest_size=_DIGEST_SIZE)

    for path in region_files(readable):
        # 一律用 / 分隔：同一個世界在 Windows 與 Linux 上必須算出同一個指紋。
        name = path.relative_to(readable).replace("\\", "/").encode("utf-8")
        try:
            for chunk in read_region(path):
                digest.update(name)
                digest.update(_SEP)
                digest.update(str(chunk.index).encode("ascii"))
                digest.update(_SEP)
                digest.update(chunk.payload)
        except FormatError as exc:
            # 相對路徑 + 例外類別名，不放訊息——訊息含絕對路徑，會讓同一個世界
            # 在不同機器上算出不同的指紋。
            digest.update(name)
            digest.update(b"\x1funreadable\x1f")
            digest.update(type(exc).__name__.encode("ascii"))

    return f"blake2b:{digest.hexdigest()}"
