# SPDX-License-Identifier: GPL-3.0-or-later
"""`resources.zip` 的產生與合併（M10.2）。

格式要求（CLAUDE.md 二節）：

* zip 而非資料夾，檔名固定 `resources.zip`，放世界資料夾**根目錄**
* zip 內根目錄**直接是** `assets/` 與 `pack.mcmeta`，不可有外層包裹資料夾
* `pack_format` 宣告 `PACK_FORMAT`（我們真的進遊戲驗過的版本），另加一個
  **往兩端開很寬**的 `supported_formats` 區間

**`supported_formats` 的區間刻意開到 `MIN_PACK_FORMAT`–`FORWARD_PACK_FORMAT`。**
這個工具產的包裡**只有一個 lang 檔**（`assets/<ns>/lang/<lang>.json` 扁平
`key → 字串`），那個格式從 pack_format 4（1.13）到今天沒有任何破壞性改動。所以：

* 往下開到 `MIN_PACK_FORMAT = 4`——JSON lang 檔第一次存在的版本。再往下是
  `.lang` properties 格式，這個工具不產那種，開再低也是謊報。
* 往上開到 `FORWARD_PACK_FORMAT`（實質無上限）——未來版本不必改工具就能載入。
  代價是：真的哪天 Mojang 動了 lang 檔或資源包載入邏輯（不是只改版本號），
  這個包會**默默失效**（遊戲仍載入，但譯文不顯示），不是一個乾淨的錯誤。
  單人翻地圖的工具不保證跟上每個版本，這個取捨是刻意接受的。

**合併既有 pack 時必須處理 `pack.mcmeta`。** [遊戲實測 M4-5] 地圖自帶的
`pack_format: 22` 被 1.21.11 進世界前直接拒絕（「無法套用伺服器資源包」），我們併
進去的 lang 檔跟著陪葬——整份譯文一個字都沒顯示。同一件事會在任何「地圖的
`supported_formats` 沒開到未來、而遊戲又出了新大版本」時重演（[實測 2026-09-03]
`all-the-same` 在 Minecraft 26.2／pack_format 88 上，我們自己產的 `{75,75}` 包被
判過期）。

處理方式是**把 `supported_formats` 的上限推到 `FORWARD_PACK_FORMAT`，不改它宣告的
`pack_format`**：那個數字是地圖作者寫的。下限維持地圖自己宣告的值——地圖的材質與
模型可能真的需要那個地板，替它往下開等於謊報。**這仍然是在改地圖自己的檔案，所以
要回報。**
"""

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcmt.backends.resourcepack.lang import dump_lang
from mcmt.packmeta import FORWARD_PACK_FORMAT, widen_supported_formats
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.tree.codecs import codec_for

__all__ = [
    "FORWARD_PACK_FORMAT",
    "MIN_PACK_FORMAT",
    "PACK_FORMAT",
    "PackReport",
    "build_pack",
]

PACK_FORMAT = 75  # 1.21.11 — 我們真的進遊戲驗過的版本，當作誠實的「主要」宣告
MIN_PACK_FORMAT = 4  # [文件] JSON lang 檔第一次存在的版本（1.13）
# FORWARD_PACK_FORMAT 從 `mcmt.packmeta` re-export——datapack 的 pack.mcmeta
# 也共用同一個天花板與同一套加寬邏輯（`write/datapack_apply.py`）。
_META = "pack.mcmeta"

# zip 條目的時間戳固定，同樣的輸入產出同樣的位元組。
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)


@dataclass
class PackReport:
    path: Path
    languages: list[str] = field(default_factory=list)
    key_count: int = 0
    carried_entries: int = 0
    created: bool = False
    pack_meta_changed: bool = False
    pack_meta_note: str = ""


def build_pack(
    target: Path | str,
    lang_by_language: dict[str, dict[str, str]],
    *,
    namespace: str,
    description: str = "mcmt 翻譯",
) -> PackReport:
    """把譯文寫進 `resources.zip`。既有的 pack 一律合併，不覆蓋。"""
    path = ensure_writable(target)
    ours = {
        f"assets/{namespace}/lang/{language}.json": dump_lang(entries)
        for language, entries in lang_by_language.items()
    }
    report = PackReport(
        path=path,
        languages=sorted(lang_by_language),
        key_count=sum(len(entries) for entries in lang_by_language.values()),
    )

    carried: list[tuple[zipfile.ZipInfo, bytes]] = []
    meta: dict[str, Any]
    if path.exists():
        carried, meta = _read_existing(path, skip=set(ours))
        report.carried_entries = len(carried)
        meta, report.pack_meta_changed, report.pack_meta_note = _widen(meta)
    else:
        report.created = True
        meta = {
            "pack": {
                "pack_format": PACK_FORMAT,
                "supported_formats": {
                    "min_inclusive": MIN_PACK_FORMAT,
                    "max_inclusive": FORWARD_PACK_FORMAT,
                },
                "description": description,
            }
        }

    temporary = ensure_writable(path.with_name(path.name + ".mcmt-tmp"))
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                zipfile.ZipInfo(_META, _FIXED_TIME),
                json.dumps(meta, ensure_ascii=False, indent=2),
            )
            for info, data in carried:
                archive.writestr(info, data)
            for name, text in sorted(ours.items()):
                archive.writestr(zipfile.ZipInfo(name, _FIXED_TIME), text)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return report


def _read_existing(
    path: Path, *, skip: set[str]
) -> tuple[list[tuple[zipfile.ZipInfo, bytes]], dict[str, Any]]:
    """讀出既有 pack 的所有條目（除了 `pack.mcmeta` 與我們自己要重寫的）。"""
    source = ensure_readable(path)
    carried = []
    meta: dict[str, Any] = {"pack": {"pack_format": PACK_FORMAT}}
    with zipfile.ZipFile(str(source)) as archive:
        for info in archive.infolist():
            if info.filename == _META:
                raw = archive.read(info.filename).decode("utf-8", "replace")
                try:
                    # 地圖的 pack.mcmeta 常有註解與尾逗號，走寬容解析。
                    meta = codec_for("lang_json").decode(raw)
                except Exception as exc:
                    raise ValueError(
                        f"{path} 裡的 pack.mcmeta 解析不了：{exc}。"
                        f"不猜——猜錯會讓整包被拒而使用者不知道為什麼。"
                    ) from exc
                continue
            if info.filename in skip:
                continue
            carried.append((info, archive.read(info.filename)))
    return carried, meta


def _widen(meta: dict[str, Any]) -> tuple[dict[str, Any], bool, str]:
    """把 `supported_formats` 的上限推到 `FORWARD_PACK_FORMAT`，讓合併後的 pack 在
    現在與未來的遊戲版本都被接受。下限維持地圖自己宣告的值。

    邏輯在 `mcmt.packmeta`——datapack 的 pack.mcmeta 共用同一份（`write/
    datapack_apply.py`），兩個地方對「pack 過期」的處理必須是同一套語意。
    """
    return widen_supported_formats(meta)
