# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt extract` — 掃描世界，產出待翻檔。

三個檔案，全部寫在 `sandbox/.mcmt-out/<世界名>/`，**與世界資料夾平行**：世界本身
不多出任何東西。

    extract.json              機器用
    translations.<lang>.json  **人直接編輯的**
    keymap.json               碰撞與人工消歧的紀錄；進版控

**不覆蓋既有的待翻檔**，除非 `--replace`。辛苦翻了一半的東西不該被重跑一次 extract
洗掉——那是這個指令唯一會造成真正損失的方式。
"""

from pathlib import Path

from mcmt.extract.build import build_units
from mcmt.extract.emit import (
    build_extract_document,
    build_translations_document,
    dump_json,
)
from mcmt.fingerprint import world_fingerprint
from mcmt.model.generation import TARGET_DATA_VERSION
from mcmt.nbtio.datfile import read_dat
from mcmt.safety.paths import ensure_writable, sandbox_root
from mcmt.world import open_world

__all__ = ["OUT_DIR_NAME", "format_result", "run_extract"]

OUT_DIR_NAME = ".mcmt-out"


def run_extract(
    world: Path | str,
    *,
    language: str = "zh_tw",
    namespace: str = "mcmt",
    out: Path | None = None,
    replace: bool = False,
) -> dict:
    """跑一次 extract，回傳給 CLI 印的摘要。"""
    world_path = Path(world).resolve()
    readable = open_world(world_path)
    destination = ensure_writable(
        Path(out) if out else sandbox_root() / OUT_DIR_NAME / world_path.name
    )
    translations_path = destination / f"translations.{language}.json"
    if translations_path.exists() and not replace:
        raise FileExistsError(translations_path)

    result = build_units(world_path, namespace=namespace, world_root=readable)
    extract = build_extract_document(
        result,
        world_name=world_path.name,
        world_fingerprint=world_fingerprint(world_path),
        level_data_version=_level_data_version(readable),
        namespace=namespace,
        target_languages=[language],
    )
    translations = build_translations_document(
        result, language=language, extract_document=extract
    )

    destination.mkdir(parents=True, exist_ok=True)
    _write(destination / "extract.json", dump_json(extract))
    _write(translations_path, dump_json(translations))
    _write(destination / "keymap.json", dump_json(result.keymap))

    return {
        "world": world_path,
        "out": destination,
        "language": language,
        "result": result,
        "extract": extract,
        "translations_path": translations_path,
    }


def format_result(summary: dict) -> str:
    result = summary["result"]
    stats = summary["extract"]["stats"]
    lines = [
        f"世界：{summary['world']}",
        f"掃過 chunk {result.chunks:,} 個 · 文字節點 {result.text_nodes:,} 個",
        "",
        f"翻譯單位：{stats['unit_count']:,} 個"
        f"（出現 {stats['occurrence_count']:,} 次，去重省下 {stats['deduped_count']:,} 次重複翻譯）",
    ]
    if stats["by_category"]:
        for category, count in sorted(
            stats["by_category"].items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"  {category:<20} {count:>7,}")

    skipped = [
        ("denylist（識別碼，翻了地圖會壞）", result.stats["skipped_denylist"]),
        ("新世代 chunk 裡的舊式 JSON（遊戲裡本來就是亂碼）",
         stats["skipped_legacy_json_in_native_chunk"]),
        ("JSON 解析失敗", stats["skipped_unparseable"]),
        ("已在地化（地圖自己的 translate key，翻了會蓋掉別人做好的多語言支援）",
         stats["skipped_already_localised"]),
        ("空白節點", result.stats["skipped_empty"]),
    ]
    listed = [(name, n) for name, n in skipped if n]
    if listed:
        lines += ["", "跳過的節點"]
        for name, count in listed:
            lines.append(f"  {count:>9,}  {name}")

    if result.keymap.get("collisions"):
        lines += [
            "",
            f"※ key 碰撞 {len(result.keymap['collisions'])} 組，已用 _1 解決並記進 keymap.json",
        ]

    lines += [
        "",
        f"產出：{summary['out']}",
        f"  translations.{summary['language']}.json  ← **編輯這個檔案**，把 target 填上",
        "  extract.json / keymap.json               機器用，不必手動改",
        "",
        f"翻完之後：mcmt apply \"{summary['world']}\" --translations \"{summary['translations_path']}\"",
    ]
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    ensure_writable(path).write_text(text, encoding="utf-8")


def _level_data_version(world) -> int:
    """讀 `level.dat` 的 DataVersion。讀不到就用目標版本，不讓它擋住整次 extract。"""
    candidate = world / "level.dat"
    if not candidate.exists():
        return TARGET_DATA_VERSION
    try:
        data = read_dat(candidate).tag.compound["Data"]
        return int(data["DataVersion"])
    except Exception:
        return TARGET_DATA_VERSION
