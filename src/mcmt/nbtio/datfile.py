# SPDX-License-Identifier: GPL-3.0-or-later
"""`.dat` 檔的讀寫（M3.2）——`level.dat` 與同格式的 NBT 檔。

**和 region 不一樣，這裡沒有外科式寫入這回事。** region 可以「未修改的 chunk 根本
不解碼」，因為它是 1024 份獨立文件；`level.dat` 是**一份**文件，改一個欄位就得整份
重新編碼。所以這一層的保證只到 L1（amulet-nbt 解析→序列化位元組一致，`[實測]` 在
真實 `level.dat` 上成立），而不是 region 的 L3。

`level.dat` 是 `LevelName` 的所在地，那是 CLAUDE.md 列的 4 個 in_place 欄位之一
（其餘三個在別的地方）。M11 會用到。

**壓縮形式讀什麼寫什麼**：Mojang 寫的是 gzip，但別的工具寫過的檔案可能是 zlib 或
未壓縮。順手「升級」成 gzip 就是改了一個沒被要求改的東西。

gzip 的 `mtime` 固定為 0：預設會塞入當下時間，那會讓同一份內容每次寫出來的位元組
都不一樣，指紋與 diff 都會被那個雜訊淹掉。
"""

import gzip
import os
import zlib
from dataclasses import dataclass
from pathlib import Path

import amulet_nbt

from mcmt.errors import DatFormatError, DatWriteVerificationError
from mcmt.safety.paths import ReadOnlyPath, ensure_readable, ensure_writable

__all__ = ["DatFile", "read_dat", "write_dat"]

_GZIP_MAGIC = b"\x1f\x8b"
_NBT_COMPOUND = 0x0A  # 裸 NBT 一定以 TAG_Compound 開頭


@dataclass(frozen=True)
class DatFile:
    """一份 `.dat` 的內容與它在磁碟上的壓縮形式。"""

    tag: amulet_nbt.NamedTag
    compression: str  # "gzip" | "zlib" | "none"


def read_dat(path: ReadOnlyPath) -> DatFile:
    """讀一份 `.dat`，同時記下它原本是怎麼壓的。

    **只收 `ReadOnlyPath`**，理由同 `read_region`：忘了過 `ensure_readable` 要在
    型別層被擋下。
    """
    if not isinstance(path, ReadOnlyPath):
        raise TypeError(
            f"read_dat 只收 ReadOnlyPath，收到 {type(path).__name__}。"
            f"請先過 ensure_readable(...)。"
        )

    raw = path.read_bytes()
    payload, compression = _decompress(raw, path)
    try:
        tag = amulet_nbt.load(payload, compressed=False)
    except Exception as exc:  # amulet-nbt 的解析錯誤型別不只一種
        raise DatFormatError(path=path, detail=str(exc)) from exc
    return DatFile(tag=tag, compression=compression)


def _encode(dat: DatFile, target: Path) -> bytes:
    """把一份 `DatFile` 編成磁碟上的位元組。

    抽成函式是為了讓驗證測試替換得掉它——不然沒有辦法製造「編碼器吐出壞位元組」
    這個情境，而那正是要驗的那一件事。`target` 只在壓縮形式不認得時用來組錯誤訊息。
    """
    payload = dat.tag.save_to(compressed=False)
    return _compress(payload, dat.compression, target)


def write_dat(path: Path | str, dat: DatFile) -> Path:
    """整份重新編碼寫出去：**暫存 → 回讀驗證 → 原子替換**。

    中間那一步是這裡與 `write_region` 最大的差別。region 是外科式的——未改動的
    chunk 帶著磁碟上的原始位元組原封送回，所以編壞了最多壞一個 chunk。`.dat`
    是一份檔案整份重編，編壞了就是整個 `level.dat` 沒了，而那是世界的中樞。

    驗證失敗時**原檔一個位元都沒有被動過**，因為 `os.replace` 還沒發生。
    """
    target = ensure_writable(path)
    data = _encode(dat, target)

    temporary = ensure_writable(target.with_name(target.name + ".mcmt-tmp"))
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_bytes(data)
        _verify(temporary, target)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def _verify(temporary: Path, target: Path) -> None:
    """回讀剛寫出去的暫存檔，確認它真的解析得回來。"""
    try:
        read_back = read_dat(ensure_readable(temporary))
    except Exception as exc:  # noqa: BLE001 —— 任何讀不回來的理由都一樣致命
        raise DatWriteVerificationError(
            f"寫出去的位元組讀不回來，已中止：{target}。"
            f"原檔沒有被動過。原因：{type(exc).__name__}: {exc}"
        ) from exc

    # 用 `.tag` 而非 `.compound`：後者在根節點不是 Compound 時會自己先拋
    # `TypeError`（發生在這個 try/except 範圍之外，不會被轉成
    # `DatWriteVerificationError`），根本走不到這裡的 isinstance 檢查。
    # `.tag` 單純回傳根節點物件，不論型別為何都不會自爆。
    if not isinstance(read_back.tag.tag, amulet_nbt.CompoundTag):
        raise DatWriteVerificationError(
            f"寫出去的位元組解析出來不是 TAG_Compound，已中止：{target}。原檔沒有被動過。"
        )


def _decompress(raw: bytes, path) -> tuple[bytes, str]:
    if raw[:2] == _GZIP_MAGIC:
        try:
            return gzip.decompress(raw), "gzip"
        except OSError as exc:
            raise DatFormatError(path=path, detail=f"gzip 解壓失敗：{exc}") from exc
    if raw[:1] == bytes([_NBT_COMPOUND]):
        return raw, "none"
    try:
        return zlib.decompress(raw), "zlib"
    except zlib.error as exc:
        raise DatFormatError(
            path=path,
            detail="既不是 gzip（1f8b）、也不是裸 NBT（0a 開頭）、zlib 也解不開",
        ) from exc


def _compress(payload: bytes, compression: str, path) -> bytes:
    if compression == "gzip":
        # mtime=0：同一份內容每次都要寫出同樣的位元組。
        return gzip.compress(payload, mtime=0)
    if compression == "zlib":
        return zlib.compress(payload)
    if compression == "none":
        return payload
    raise DatFormatError(path=path, detail=f"不認得的壓縮形式 {compression!r}")
