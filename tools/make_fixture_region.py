# SPDX-License-Identifier: GPL-3.0-or-later
"""從一張真實的 region 切一小片出來當測試 fixture。

    python tools/make_fixture_region.py <來源 .mca> <輸出 .mca> [--chunks 30]

**這是開發工具，不是 mcmt 執行期的一部分。** 它寫的是版控裡的測試 fixture
（`tests/fixtures/regions/`，`.gitignore` 對它開了例外），不是任何人的存檔，所以
不走 `ensure_writable`；來源仍然走 `ensure_readable`。

為什麼需要真實切片：合成的 region 驗得了格式，驗不了「Mojang 實際寫出來的位元組
被我們讀進來再寫回去仍然一模一樣」。外科式寫入的保證只有真實資料能證明。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mcmt.nbtio.region import SECTOR_SIZE, read_region  # noqa: E402
from mcmt.safety.paths import ensure_readable  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--chunks", type=int, default=30)
    args = parser.parse_args()

    chunks = []
    for chunk in read_region(ensure_readable(args.source)):
        if chunk.is_external:
            continue
        chunks.append(chunk)
        if len(chunks) >= args.chunks:
            break

    offsets = bytearray(SECTOR_SIZE)
    timestamps = bytearray(SECTOR_SIZE)
    body = bytearray()
    next_sector = 2
    for chunk in chunks:
        block = bytearray()
        block += (len(chunk.payload) + 1).to_bytes(4, "big")
        block += bytes([chunk.compression_type])
        block += chunk.payload
        sectors = -(-len(block) // SECTOR_SIZE)
        block += bytes(sectors * SECTOR_SIZE - len(block))
        slot = chunk.index * 4
        offsets[slot : slot + 4] = next_sector.to_bytes(3, "big") + bytes([sectors])
        timestamps[slot : slot + 4] = chunk.timestamp.to_bytes(4, "big")
        body += block
        next_sector += sectors

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = bytes(offsets + timestamps + body)
    output.write_bytes(data)

    print(f"{output}：{len(chunks)} 個 chunk，{len(data):,} bytes")
    print(f"  chunk index：{[c.index for c in chunks[:8]]}...")
    print(f"  壓縮類型：{sorted({c.compression_type for c in chunks})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
