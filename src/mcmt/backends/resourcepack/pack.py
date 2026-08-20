# SPDX-License-Identifier: GPL-3.0-or-later
"""`resources.zip` 的產生與合併（M10.2）。

格式要求（CLAUDE.md 二節）：

* zip 而非資料夾，檔名固定 `resources.zip`，放世界資料夾**根目錄**
* zip 內根目錄**直接是** `assets/` 與 `pack.mcmeta`，不可有外層包裹資料夾
* `pack_format` 宣告 75（1.21.11），另加 `supported_formats` 區間

**合併既有 pack 時必須處理 `pack.mcmeta`。** [遊戲實測 M4-5] 地圖自帶的
`pack_format: 22` 被 1.21.11 進世界前直接拒絕（「無法套用伺服器資源包」），我們併
進去的 lang 檔跟著陪葬——整份譯文一個字都沒顯示。

處理方式是**只加 `supported_formats` 區間，不改它宣告的 `pack_format`**：那個數字是
地圖作者寫的，改它等於謊報這個 pack 是為新版做的。加區間表達的是「這個 pack 在這個
範圍內都能用」，而那正是我們要主張的事。**這仍然是在改地圖自己的檔案，所以要回報。**
"""

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcmt.backends.resourcepack.lang import dump_lang
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.tree.codecs import codec_for

__all__ = ["PACK_FORMAT", "PackReport", "build_pack"]

PACK_FORMAT = 75  # 1.21.11
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
                    "min_inclusive": PACK_FORMAT,
                    "max_inclusive": PACK_FORMAT,
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
    """必要時加上 `supported_formats`，讓舊 pack 在 1.21.11 仍被接受。"""
    pack = dict(meta.get("pack") or {})
    declared = pack.get("pack_format")
    supported = pack.get("supported_formats")

    if isinstance(supported, dict) and supported.get("max_inclusive", 0) >= PACK_FORMAT:
        return meta, False, ""
    if isinstance(declared, int) and declared >= PACK_FORMAT and supported is None:
        return meta, False, ""

    low = declared if isinstance(declared, int) else PACK_FORMAT
    if isinstance(supported, dict):
        low = min(low, supported.get("min_inclusive", low))
    pack["supported_formats"] = {"min_inclusive": low, "max_inclusive": PACK_FORMAT}
    updated = dict(meta)
    updated["pack"] = pack
    note = (
        f"地圖原本的 resources.zip 宣告 pack_format {declared}，1.21.11 會拒絕整個 pack"
        f"（連我們的譯文一起）。已加上 supported_formats {low}–{PACK_FORMAT}，"
        f"未更動它原本宣告的 pack_format。"
    )
    return updated, True, note
