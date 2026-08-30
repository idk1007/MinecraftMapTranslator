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

**涵蓋 `region/` 與 `entities/`**（M13）。實體從 1.17 起分開存放，但它一樣是這個
世界的內容——具名生物、盔甲座、`text_display` 的浮空文字都在那裡。漏掉它的症狀
是「使用者玩過一次、動了實體，指紋卻說世界沒變」，而 `extract_fingerprint` 正是
靠指紋判斷譯文還適不適用。

**也涵蓋 `level.dat`／`data/scoreboard.dat`／`datapacks/**`**（2026-08-31，
M13b 最終 review 發現的已知缺口）。M13b 讓 `extract`／`apply` 讀寫這三個
非 chunk 來源之後，這裡有一段時間沒跟著擴大——後果是使用者把世界名或
datapack 的進度文字改掉，指紋不變，`extract_fingerprint` 會說「世界沒變」而
實際上變了，`apply_report.json` 的 `world_fingerprint_after` 也會跟 before
一樣，報告主動說謊。這三個不是版本化的 NBT chunk，沒有「per-chunk」這回事，
直接餵整份檔案的原始位元組：`level.dat`／`scoreboard.dat` 各一份，
`datapacks/` 底下逐檔（資料夾形式遞迴進每個檔案，zip 形式把整個 `.zip`
當一份檔案——不解開內容比對條目，那和「壓縮等級不同就是不同世界」
（下面 payload 那段）是同一種保守）。

**壞掉的 region 不會讓指紋失敗**：它會被折成一個穩定的標記寫進 hash。指紋負責
身分，健檢是 `doctor` 的事——壞掉的世界更需要能先被複製進 sandbox 再診斷。
"""

from hashlib import blake2b
from pathlib import Path

from mcmt.errors import FormatError
from mcmt.nbtio.region import entities_files, read_region, region_files
from mcmt.safety.paths import ensure_readable

__all__ = ["world_fingerprint"]

_DIGEST_SIZE = 16  # 32 hex，符合合約的 ^blake2b:[0-9a-f]{16,64}$
_SEP = b"\x1f"


def world_fingerprint(world: Path | str) -> str:
    """回傳 `blake2b:<32 hex>` 形式的世界內容身分。"""
    readable = ensure_readable(Path(world))
    digest = blake2b(digest_size=_DIGEST_SIZE)

    # **region 與 entities 都算。** [預告於 nbtio/region.py] 掃描範圍擴大到實體
    # 之後，「什麼算這個世界的內容」就得包含它們——不然使用者在遊戲裡動了盔甲座，
    # 指紋不變，extract_fingerprint 會說「世界沒變」而實際上變了。
    #
    # 兩份清單分開取再串起來（而不是 rglob 一次抓兩種），是為了讓順序穩定且
    # 與各自的 *_files() 定義一致——指紋對順序敏感。
    for path in [*region_files(readable), *entities_files(readable)]:
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

    # **`level.dat`／`scoreboard.dat`／datapack 也算**（見上方 2026-08-31 那段）。
    # 這三個不是版本化的 chunk，沒有「per-chunk」這回事，整份檔案的原始位元組
    # 就是內容——與 region/entities 分開一段迴圈，因為粒度不同（一份檔案一次
    # digest.update，不是逐 chunk）。
    for path in [*_dat_files(readable), *_datapack_files(readable)]:
        name = path.relative_to(readable).replace("\\", "/").encode("utf-8")
        try:
            data = path.read_bytes()
        except OSError as exc:
            digest.update(name)
            digest.update(b"\x1funreadable\x1f")
            digest.update(type(exc).__name__.encode("ascii"))
            continue
        digest.update(name)
        digest.update(_SEP)
        digest.update(data)

    return f"blake2b:{digest.hexdigest()}"


def _dat_files(world) -> list:
    """`level.dat` 與 `data/scoreboard.dat`——兩個都是「有就算，沒有是合法狀態」
    （自建探測世界常常沒有 `scoreboard.dat`）。"""
    candidates = [world / "level.dat", world / "data" / "scoreboard.dat"]
    return [p for p in candidates if p.is_file()]


def _datapack_files(world) -> list:
    """`datapacks/` 底下每一個檔案——資料夾形式遞迴進每個檔案，zip 形式把整個
    `.zip` 當一份檔案（不解開內容逐條目比對，理由同 payload 那段：保守，不假裝
    知道「內容一樣但重新壓縮」是同一份東西）。

    排序鍵正規化成 `/`，理由與 `nbtio/region.py` 的 `region_files()` 一樣
    （[已知缺口，2026-08-31 一併補掉]）：作業系統原生分隔符在子目錄名互為前綴
    時會給出不一致的順序，而指紋對順序敏感。
    """
    root = world / "datapacks"
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: str(p).replace("\\", "/"),
    )
