# SPDX-License-Identifier: GPL-3.0-or-later
"""把一張地圖拖進來之後發生什麼——流程邏輯，跟畫面完全分開。

視窗（之後的 tkinter）只負責「畫對話框、回報按了哪個按鈕」，這裡負責「現在是
哪個狀態、該做什麼、該問什麼」。兩邊的介面是 `Ui`：測試用一個腳本化的假介面，
真的視窗實作同一個介面。

**判斷狀態只看沙盒裡有什麼**，使用者不必選：

    沙盒沒有這張地圖／還沒抽取  →  健檢 → 匯入 → 抽取，等使用者填譯文
    有翻譯檔但 target 全空      →  提醒先填，什麼都不動
    有譯文，還沒寫回           →  試跑 → 確認 → 寫回
    已經寫回過                 →  確認後重新開始（可選擇保留舊譯文）

**會刪東西的那一步（重新開始）在動手之前，先把所有會失敗的事檢查完**：原存檔
還在不在、原存檔現在還能不能處理。刪到一半才發現原存檔不見了，沙盒副本就回不來。
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from mcmt.cli.apply import run_apply
from mcmt.cli.extract import OUT_DIR_NAME, run_extract
from mcmt.cli.jsonfile import read_json_file
from mcmt.doctor import survey_world
from mcmt.errors import ExternalChunksFoundError, OriginMissingError
from mcmt.safety.paths import sandbox_root
from mcmt.sandbox import ORIGIN_FILENAME, import_world
from mcmt.world import open_world

__all__ = ["FlowOutcome", "Ui", "run_flow"]

DEFAULT_LANGUAGE = "zh_tw"

# 按鈕文字。流程用它們判斷使用者按了什麼，視窗用它們畫按鈕——只定義一次。
GO_ON, CANCEL, OVERWRITE = "繼續", "取消", "覆蓋"
RESTART, KEEP, FROM_SCRATCH = "重新開始", "保留舊譯文", "全部重來"
WRITE, SEE_REPORT = "寫回", "查看報告"
OPEN_FOLDER, CLOSE = "開啟資料夾", "關閉"

# 「還沒翻」「刻意不翻」是正常狀態，不算「有問題而被拒寫」。
_NOT_A_PROBLEM = {"untranslated", "skipped"}


class Ui(Protocol):
    def log(self, message: str) -> None: ...

    def ask(self, title: str, body: str, buttons: Sequence[str]) -> str | None:
        """顯示對話框，回傳按下的按鈕文字；直接關掉視窗回傳 `None`（當作取消）。"""

    def choose_language(self, default: str) -> str | None:
        """回傳語言代碼（如 `zh_tw`）；取消回傳 `None`。"""

    def open_path(self, path: Path) -> None: ...


@dataclass(frozen=True)
class FlowOutcome:
    """`kind`：`extracted`（等使用者填譯文）／`applied`（已寫回）／`nothing_to_do`
    （還沒有譯文）／`cancelled`。"""

    kind: str
    path: Path | None = None


def run_flow(dropped: Path | str, ui: Ui) -> FlowOutcome:
    """處理一次拖入。錯誤（`McmtError`）照原樣往外拋，由視窗層顯示成錯誤對話框。"""
    dropped = Path(dropped).resolve()
    sandbox = sandbox_root().resolve()
    open_world(dropped)  # 不是地圖就在這裡說，不要等到走了一半

    name = dropped.name
    sandbox_world = sandbox / name
    out_dir = sandbox / OUT_DIR_NAME / name
    from_sandbox = dropped.parent == sandbox
    source = _origin_source(dropped) if from_sandbox else dropped

    if not from_sandbox and sandbox_world.exists():
        origin = _origin_source(sandbox_world)
        if origin is not None and not _same_path(origin, dropped):
            # 資料夾名字一樣（例如預設的 New World），但不是同一張地圖。把它當成
            # 同一張的話，會拿另一張地圖的譯文去寫這一張。
            answer = ui.ask(
                "地圖已存在",
                f"沙盒已有同名的另一張地圖 {name}（來源：{origin}）。\n"
                f"改用現在拖入的這張，會刪除沙盒裡的副本（含已寫回的譯文與資源包），"
                f"並重新抽取文字。舊的翻譯檔會另存為 .bak-時間 備份。",
                [OVERWRITE, CANCEL],
            )
            if answer != OVERWRITE:
                return FlowOutcome("cancelled")
            return _first_time(dropped, name, sandbox_world, ui, replace_copy=True)

    existing = _latest_translations(out_dir)
    if not sandbox_world.exists() or existing is None:
        return _first_time(
            sandbox_world if from_sandbox else dropped, name, sandbox_world, ui, replace_copy=False
        )

    language, translations_path = existing
    if _already_applied(out_dir):
        return _restart(name, source, sandbox_world, language, ui)
    if not _has_any_target(translations_path):
        ui.ask(
            "還沒有譯文",
            f"翻譯檔裡還沒有填入任何譯文。請先填寫 {translations_path.name}，"
            f"再把地圖拖進來。",
            [OPEN_FOLDER, CLOSE],
        )
        return FlowOutcome("nothing_to_do", out_dir)
    return _apply(sandbox_world, translations_path, out_dir, ui)


# --- 狀態判斷 -------------------------------------------------------------------


def _origin_source(sandbox_world: Path) -> Path | None:
    try:
        origin = json.loads((sandbox_world / ORIGIN_FILENAME).read_text(encoding="utf-8"))
        return Path(origin["source"])
    except (OSError, ValueError, KeyError):
        return None


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _latest_translations(out_dir: Path) -> tuple[str, Path] | None:
    """輸出資料夾裡最近修改的 `translations.<語言>.json`。`.bak-` 結尾的備份不算。"""
    candidates = sorted(out_dir.glob("translations.*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None
    path = candidates[-1]
    return path.name[len("translations.") : -len(".json")], path


def _has_any_target(translations_path: Path) -> bool:
    document = read_json_file(translations_path, kind="翻譯檔")
    return any(
        str(entry.get("target", "")).strip() for entry in document.get("entries", {}).values()
    )


def _already_applied(out_dir: Path) -> bool:
    """`apply_report.json` 綁著它寫回的那一份 extract（指紋對得上）才算。"""
    report_path = out_dir / "apply_report.json"
    if not report_path.is_file():
        return False
    report = read_json_file(report_path, kind="報告")
    extract = read_json_file(out_dir / "extract.json", kind="掃描紀錄")
    return (
        report.get("outcome") == "applied"
        and report.get("world", {}).get("extract_fingerprint")
        == extract["world"]["extract_fingerprint"]
    )


# --- 閘門 -----------------------------------------------------------------------


def _gate(world: Path, ui: Ui) -> bool:
    """健檢。外部 `.mcc` 硬中止（拋例外）；舊格式區塊與損毀檔案問一聲。
    回傳 `False` 代表使用者選擇取消。"""
    ui.log("健檢地圖…")
    survey = survey_world(world)
    if survey.external_chunks:
        raise ExternalChunksFoundError(survey.external_chunks)

    legacy = sum(survey.unsupported.values())
    broken = len(survey.corrupt)
    if not (legacy or broken):
        return True
    parts = []
    if legacy:
        parts.append(f"偵測到 {legacy:,} 個舊格式區塊（遊戲尚未升級的區域），這些區塊將略過不處理。")
    if broken:
        parts.append(f"另有 {broken:,} 處檔案疑似損毀，也會略過。")
    title = "包含舊格式區塊" if legacy else "地圖檔案損毀"
    answer = ui.ask(title, "\n".join(parts) + "\n是否繼續？", [GO_ON, CANCEL])
    return answer == GO_ON


# --- 動作 -----------------------------------------------------------------------


def _first_time(source: Path, name, sandbox_world, ui, *, replace_copy) -> FlowOutcome:
    if not _gate(source, ui):
        return FlowOutcome("cancelled")
    language = ui.choose_language(DEFAULT_LANGUAGE)
    if language is None:
        return FlowOutcome("cancelled")

    if replace_copy or not sandbox_world.exists():
        ui.log("匯入沙盒…")
        import_world(source, name=name, replace=replace_copy)
    ui.log("抽取文字…")
    summary = run_extract(sandbox_world, language=language, replace=True)
    return _ask_for_translations(summary, ui, carry_note="")


def _ask_for_translations(summary: dict, ui: Ui, *, carry_note: str) -> FlowOutcome:
    out_dir = summary["out"]
    body = (
        f"已抽取 {summary['extract']['stats']['unit_count']:,} 個翻譯單位。"
        f"請編輯 {summary['translations_path'].name}，填完後再把同一張地圖拖進來。"
        f"{carry_note}"
    )
    answer = ui.ask("請填寫翻譯檔", body, [OPEN_FOLDER, CLOSE])
    if answer == OPEN_FOLDER:
        ui.open_path(out_dir)
    return FlowOutcome("extracted", out_dir)


def _restart(name, source, sandbox_world, language, ui) -> FlowOutcome:
    # 會刪東西的一步：先檢查所有會失敗的事（原存檔還在嗎）。
    if source is None or not Path(source).exists():
        raise OriginMissingError(name=name, source=source)

    answer = ui.ask(
        "重新開始？",
        "這張地圖已經寫回過譯文。重新開始會刪除沙盒裡的舊結果，並從原存檔重新抽取文字。\n"
        "目前的翻譯檔會另存為 .bak-時間 備份。",
        [RESTART, CANCEL],
    )
    if answer != RESTART:
        return FlowOutcome("cancelled")
    answer = ui.ask(
        "保留舊譯文？",
        "要把目前已填的譯文，帶到新的翻譯檔嗎？\n"
        "對得上的會自動填入；地圖裡已經找不到對應原文的，會列出清單。",
        [KEEP, FROM_SCRATCH, CANCEL],
    )
    if answer not in (KEEP, FROM_SCRATCH):
        return FlowOutcome("cancelled")

    # 刪沙盒副本之前，再確認一次原存檔現在還能不能處理（它可能在這段時間變了）。
    if not _gate(Path(source), ui):
        return FlowOutcome("cancelled")

    ui.log("重新匯入沙盒…")
    import_world(Path(source), name=name, replace=True)
    ui.log("抽取文字…")
    summary = run_extract(
        sandbox_world, language=language, replace=True, keep_translations=(answer == KEEP)
    )
    return _ask_for_translations(summary, ui, carry_note=_carry_note(summary))


def _carry_note(summary: dict) -> str:
    carry = summary.get("carry")
    if carry is None:
        return ""
    note = f"\n已沿用 {carry.carried:,} 筆舊譯文"
    if carry.orphans:
        note += f"，{len(carry.orphans):,} 筆對不上（詳見備份檔）"
    if carry.new_units:
        note += f"，{carry.new_units:,} 筆是新出現的"
    return note + "。"


def _apply(sandbox_world, translations_path, out_dir, ui) -> FlowOutcome:
    ui.log("試跑，檢查會寫入哪些文字…")
    dry = run_apply(sandbox_world, translations_path, dry_run=True)
    body = _confirm_body(dry)
    while True:
        answer = ui.ask("準備寫回", body, [WRITE, SEE_REPORT, CANCEL])
        if answer == SEE_REPORT:
            ui.open_path(out_dir / "apply_report.json")
            continue
        if answer != WRITE:
            return FlowOutcome("cancelled")
        break

    ui.log("寫回存檔…")
    real = run_apply(sandbox_world, translations_path)
    written = real["report"]["counts"]["edits_written"]
    if written:
        text = (
            f"已寫入 {written:,} 筆。請把 {sandbox_world} 複製回 "
            f".minecraft\\saves（工具不會自動複製）。"
        )
    else:
        text = "沒有寫入任何文字，地圖維持原樣。原因見報告。"
    answer = ui.ask("完成", text, [OPEN_FOLDER, CLOSE])
    if answer == OPEN_FOLDER:
        ui.open_path(sandbox_world)
    return FlowOutcome("applied", sandbox_world)


def _confirm_body(dry: dict) -> str:
    planned = dry["report"]["counts"]["edits_planned"]
    backend = dry["plan"].document["unwritten"]
    problems = len(dry["outcome"].unwritten) + sum(
        1 for item in backend if item["reason"] not in _NOT_A_PROBLEM
    )
    untranslated = sum(1 for item in backend if item["reason"] == "untranslated")
    lines = [f"將寫入 {planned:,} 筆譯文。"]
    if problems:
        lines.append(f"{problems:,} 筆有問題，不會寫入（原因見報告）。")
    if untranslated:
        lines.append(f"{untranslated:,} 筆還沒翻，會保留原文。")
    lines.append("寫回前會自動備份。")
    return "\n".join(lines)
