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

import shutil
from datetime import datetime
from pathlib import Path

from mcmt.cli.jsonfile import read_json_file
from mcmt.errors import NamespaceConflictError, TranslationsExistError
from mcmt.extract.build import build_units
from mcmt.extract.carry import carry_translations
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

__all__ = ["OUT_DIR_NAME", "format_result", "keep_backup", "run_extract"]

OUT_DIR_NAME = ".mcmt-out"


def run_extract(
    world: Path | str,
    *,
    language: str = "zh_tw",
    namespace: str = "mcmt",
    out: Path | None = None,
    replace: bool = False,
    keep_translations: bool = False,
) -> dict:
    """跑一次 extract，回傳給 CLI 印的摘要。

    `keep_translations`：把既有待翻檔裡使用者填的 `target`／`status` 依編號搬進新檔，
    並在摘要的 `carry` 列出對不上的舊譯文。既有待翻檔不存在就什麼都不做。"""
    if namespace == "minecraft":
        # 在動任何東西之前擋：覆寫原版 key 會改掉原版所有語言的文字。
        raise NamespaceConflictError(namespace)
    world_path = Path(world).resolve()
    readable = open_world(world_path)
    destination = ensure_writable(
        Path(out) if out else sandbox_root() / OUT_DIR_NAME / world_path.name
    )
    translations_path = destination / f"translations.{language}.json"
    if translations_path.exists() and not replace:
        raise TranslationsExistError(translations_path)

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

    carry = None
    backup = None
    if translations_path.exists():
        if keep_translations:
            # 在覆蓋之前讀：讀不懂就報錯，而不是蓋掉一份讀不懂的檔案。
            carry = carry_translations(
                read_json_file(translations_path, kind="翻譯檔"), translations
            )
        # 覆蓋之前先留一份：這是整個專案裡唯一給人手動編輯的檔案，辛苦填的譯文
        # 不該因為按錯一次就沒了。
        backup = keep_backup(translations_path)
    destination.mkdir(parents=True, exist_ok=True)
    for stale in ("apply_report.json", "editplan.json"):
        # 上一輪 apply 的產物。留著的話，同一張沒改過的地圖重抽出同樣的指紋，
        # 舊報告會讓「這張地圖寫回過了嗎」的判斷誤以為寫回過。
        if (destination / stale).exists():
            keep_backup(destination / stale, remove=True)
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
        "carry": carry,
        "backup": backup,
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
        ("地圖裡本來就顯示成亂碼的文字（遊戲不會解析它，所以也不動它）",
         stats["skipped_legacy_json_in_native_chunk"]),
        ("JSON 解析失敗", stats["skipped_unparseable"]),
        ("地圖內建的多語言文字（略過以防覆蓋原作者做好的翻譯）",
         stats["skipped_already_localised"]),
        # **警告後仍可繼續，但要讓使用者看得到。** 混合世代地圖（[實測]
        # `Against Iskerside [1.21.11]`，2026-09-06）裡 v1 不支援的舊結構
        # chunk（`doctor` 會拒絕整個世界的那三種：1.12 `Level` 包裝層、
        # `Text1..Text4`、缺 `DataVersion`）——這裡選擇跳過那些 chunk 並繼續
        # 掃描其餘部分，而不是像 `doctor` 一樣直接拒絕整個世界。這個數字不是 0
        # 時，代表地圖裡有這麼多個 chunk 完全沒被掃到、翻不到。
        ("舊格式區塊（遊戲尚未升級的區域，完全沒被掃到）",
         stats["skipped_unsupported_structure"]),
        ("空白項目（無文字）", result.stats["skipped_empty"]),
        # **讀不下去的來源檔要看得見。** 這幾行不在的時候，一個壞掉的
        # `level.dat` 印出來的摘要和「這個世界沒有東西可翻」一模一樣——使用者
        # 沒有任何跡象可以知道有一整個檔案根本沒被讀到。
        ("level.dat 讀不下去（世界名／boss 條／玩家背包整個沒掃到）",
         result.stats["skipped_level_dat"]),
        ("scoreboard.dat 讀不下去（記分板顯示名與隊伍前後綴整個沒掃到）",
         result.stats["skipped_scoreboard_dat"]),
        ("資料包 zip 打不開（整包進度沒掃到）", result.stats["skipped_datapack_zip"]),
        ("進度 JSON 解析失敗", result.stats["skipped_advancement_unparseable"]),
        ("進度的文字形狀轉不出去", result.stats["skipped_advancement_shape"]),
        ("暫不支援文字抽取的指令（略過）", stats["skipped_command_unsupported_shape"]),
        ("指令巢狀引用另一條指令（L3，未支援）", stats["skipped_command_nested_reference"]),
        ("指令行尾反斜線延續（1.20.2+ 語法，未支援）",
         stats["skipped_command_line_continuation"]),
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

    lines += _carry_lines(summary)

    lines += [
        "",
        f"產出：{summary['out']}",
        f"  translations.{summary['language']}.json  ← **編輯這個檔案**，把 target 填上",
        "  extract.json / keymap.json               機器用，不必手動改",
        "",
        f"翻完之後：mcmt apply \"{summary['world']}\" --translations \"{summary['translations_path']}\"",
    ]
    return "\n".join(lines)


_MAX_ORPHANS_SHOWN = 10
_MAX_TEXT_CHARS = 30


def _short(text: str) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= _MAX_TEXT_CHARS else text[:_MAX_TEXT_CHARS] + "…"


def _carry_lines(summary: dict) -> list[str]:
    """沿用舊譯文的結果：搬了幾筆、哪幾筆對不上、新出現幾筆。

    對不上的要列出來，不能只印數字——地圖變了，那幾筆是白翻了，還是該手動搬去
    新的條目，只有看得到內容的人才判斷得了。"""
    carry = summary.get("carry")
    backup = summary.get("backup")
    lines: list[str] = []
    if carry is not None:
        lines += ["", f"沿用舊譯文：{carry.carried:,} 筆"]
        if carry.orphans:
            lines.append(f"  舊譯文對不上（地圖裡已找不到對應的原文）：{len(carry.orphans):,} 筆")
            for orphan in carry.orphans[:_MAX_ORPHANS_SHOWN]:
                where = f"{orphan.where}：" if orphan.where else ""
                lines.append(
                    f"    · {where}{_short(orphan.source)} → {_short(orphan.target)}"
                )
            if len(carry.orphans) > _MAX_ORPHANS_SHOWN:
                lines.append(
                    f"    · 另有 {len(carry.orphans) - _MAX_ORPHANS_SHOWN} 筆，完整內容在備份檔"
                )
        if carry.new_units:
            lines.append(f"  新出現、還沒翻：{carry.new_units:,} 筆")
    if backup is not None:
        lines += ["", f"舊的翻譯檔另存為：{backup}"]
    return lines


def _write(path: Path, text: str) -> None:
    ensure_writable(path).write_text(text, encoding="utf-8")


def keep_backup(path: Path, *, remove: bool = False) -> Path:
    """把 `path` 複製成 `<檔名>.bak-<時間>`，同一秒重複就加序號，絕不覆蓋既有備份。
    `remove=True` 是「改名」：備份建好之後把原檔刪掉。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.bak-{stamp}")
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.name}.bak-{stamp}-{counter}")
    shutil.copyfile(path, ensure_writable(candidate))
    if remove:
        ensure_writable(path).unlink()
    return candidate


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
