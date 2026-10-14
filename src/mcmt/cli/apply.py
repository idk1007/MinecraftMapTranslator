# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt apply` — 讀翻好的檔案，產出 resources.zip 並外科式寫回世界。

    mcmt apply <世界> --translations translations.zh_tw.json [--dry-run]

`--dry-run` 在**完全不碰存檔**的前提下印出「打算改哪些節點、改成什麼」，並把
editplan 寫出來給人看。那是這個工具最重要的安全網之一。

寫入順序不可協商：備份 → 改 → 寫。備份失敗就中止。
"""

import json
from pathlib import Path
from typing import Any

from mcmt.backends.resourcepack.backend import build_editplan
from mcmt.backends.resourcepack.pack import build_pack
from mcmt.errors import (
    InputFileNotFoundError,
    InvalidJsonFileError,
    WorldChangedSinceExtractError,
)
from mcmt.extract.emit import dump_json
from mcmt.fingerprint import world_fingerprint
from mcmt.safety.paths import ensure_readable, ensure_writable, sandbox_root
from mcmt.world import open_world
from mcmt.write.apply import apply_editplan

__all__ = ["format_apply", "run_apply"]


def run_apply(
    world: Path | str,
    translations_path: Path | str,
    *,
    extract_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    world_path = Path(world).resolve()
    open_world(world_path)  # 不是世界就早點說，不要跑到一半才發現
    if not dry_run:
        # 不能寫的地方（原存檔、沙盒之外）第一時間擋下，不要先讀完翻譯檔、算完計畫
        # 才在備份那一關說「只能修改沙盒」。dry-run 不碰存檔，預覽原存檔照舊允許。
        ensure_writable(world_path)

    translations_file = Path(translations_path).resolve()
    translations = _read_json_file(translations_file, kind="翻譯檔")
    language = translations["language"]

    extract_file = Path(extract_path) if extract_path else translations_file.parent / "extract.json"
    extract = _read_json_file(extract_file, kind="掃描紀錄")

    plan = build_editplan(extract, translations, language=language)

    out = ensure_writable(translations_file.parent)
    out.mkdir(parents=True, exist_ok=True)
    ensure_writable(out / "editplan.json").write_text(
        dump_json(plan.document), encoding="utf-8"
    )

    fingerprint_before = world_fingerprint(world_path)
    expected_fingerprint = extract["world"]["world_fingerprint"]
    if fingerprint_before != expected_fingerprint:
        # **在 dry-run 也擋。** dry-run 的賣點是「安全預覽」，預覽一份基於已經
        # 不存在的世界快照算出來的 editplan 沒有意義——與 build_editplan() 的
        # `_check_binding()` 對 extract_fingerprint 不對的處理一樣，不看 dry_run。
        raise WorldChangedSinceExtractError(
            world=world_path, expected=expected_fingerprint, actual=fingerprint_before
        )
    outcome = apply_editplan(world_path, plan.document, dry_run=dry_run)

    pack_report = None
    if not dry_run and outcome.counts["edits_written"]:
        pack_report = build_pack(
            world_path / "resources.zip",
            plan.lang,
            namespace=extract["project"]["namespace"],
        )
        if pack_report.pack_meta_changed:
            outcome.warnings.append(
                {
                    "kind": "pack_format_outdated",
                    "unit_id": None,
                    "detail": pack_report.pack_meta_note,
                }
            )

    report = outcome.report(world=world_path, fingerprint_before=fingerprint_before)
    report["world"]["extract_fingerprint"] = extract["world"]["extract_fingerprint"]
    if not dry_run:
        report["world"]["world_fingerprint_after"] = world_fingerprint(world_path)
    if pack_report:
        # 合約要的是物件不是字串。M12 的端到端測試第一次真的拿 apply_report 去驗
        # schema，才發現這裡一直產出一份不合自己合約的報告——單元測試驗的是手寫的
        # sample fixture，驗不到「程式真的會吐出來的東西」。
        report["assets_installed"] = [
            {
                "source": str(pack_report.path.name),
                "destination": str(pack_report.path.relative_to(world_path)),
                "replaced_existing": not pack_report.created,
            }
        ]
    report["unwritten"] = outcome.unwritten + [
        {**item, "occurrence_id": None} for item in plan.document["unwritten"]
        if item["reason"] in _WRITER_REASONS
    ]
    ensure_writable(out / "apply_report.json").write_text(
        dump_json(report), encoding="utf-8"
    )

    return {
        "world": world_path,
        "out": out,
        "plan": plan,
        "translations": translations,
        "outcome": outcome,
        "report": report,
        "pack": pack_report,
        "dry_run": dry_run,
    }


def _read_json_file(path: Path, *, kind: str) -> Any:
    """讀使用者給的 JSON。不存在、語法錯誤都換成使用者看得懂的訊息：
    哪個檔案、第幾行、出錯那一行與前後各一行——不是 `Errno 2` 或
    `Expecting property name…(char 1)`。"""
    if not path.is_file():
        raise InputFileNotFoundError(path, kind=kind)
    text = ensure_readable(path).read_bytes().decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        lines = text.splitlines()
        first = max(1, exc.lineno - 1)
        last = min(len(lines), exc.lineno + 1)
        context = [(number, lines[number - 1]) for number in range(first, last + 1)]
        raise InvalidJsonFileError(
            path=path, line=exc.lineno, column=exc.colno, context=context, kind=kind
        ) from exc


# editplan 的拒絕原因與 apply_report 的詞彙表是**互斥**的，所以後端的拒絕不會被
# 硬塞進寫入層的清單裡。這裡留空集合是刻意的：兩邊各報各的。
_WRITER_REASONS: set[str] = set()


def format_apply(summary: dict[str, Any]) -> str:
    outcome = summary["outcome"]
    plan = summary["plan"]
    counts = summary["report"]["counts"]
    lines = [f"世界：{summary['world']}"]

    if summary["dry_run"]:
        lines.append("**--dry-run：完全沒有碰存檔。**")
    lines += [
        "",
        f"計畫要改的節點：{counts['edits_planned']:,}",
        f"實際寫入：{counts['edits_written']:,}",
        f"改動的 chunk：{counts['chunks_touched']:,}"
        f"（原封複製 {counts['chunks_copied_verbatim']:,} 個）",
        f"重寫的 region 檔：{counts['files_rewritten']:,}",
    ]
    if counts["list_promotions"]:
        lines.append(
            f"NBT list 提升：{counts['list_promotions']:,}"
            f"（告示牌整面四行改寫成 compound——格式強制，不是選擇）"
        )

    entries = summary.get("translations", {}).get("entries", {})

    backend_refusals: dict[str, int] = {}
    for item in plan.document["unwritten"]:
        backend_refusals[item["reason"]] = backend_refusals.get(item["reason"], 0) + 1
    if backend_refusals:
        lines += ["", "後端沒有產生 edit 的單位"]
        for reason, count in sorted(backend_refusals.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:>7,}  {_REASON_TEXT.get(reason, reason)}")
            if reason not in _NOT_WORTH_LISTING:
                lines += _example_lines(
                    [i for i in plan.document["unwritten"] if i["reason"] == reason], entries
                )

    if outcome.unwritten:
        writer_refusals: dict[str, int] = {}
        for item in outcome.unwritten:
            writer_refusals[item["reason"]] = writer_refusals.get(item["reason"], 0) + 1
        lines += ["", "寫入層拒絕的節點"]
        for reason, count in sorted(writer_refusals.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:>7,}  {_REASON_TEXT.get(reason, reason)}")
            of_reason = [item for item in outcome.unwritten if item["reason"] == reason]
            lines += _detail_lines(of_reason)
            lines += _example_lines(of_reason, entries)

    for warning in outcome.warnings:
        lines += ["", f"※ {warning['detail']}"]

    if summary["report"]["backup"]:
        lines += [
            "",
            f"備份：{summary['report']['backup']['directory']}"
            f"（{summary['report']['backup']['file_count']} 個檔案）",
        ]
    if summary["pack"]:
        lines.append(f"資源包：{summary['pack'].path}")

    lines += ["", f"報告：{summary['out'] / 'apply_report.json'}"]
    if summary["dry_run"]:
        lines.append(f"編輯計畫：{summary['out'] / 'editplan.json'}（可以打開來看）")
    return "\n".join(lines)


_MAX_DETAILS_PER_REASON = 3
_MAX_EXAMPLES_PER_REASON = 5
_MAX_SOURCE_CHARS = 40

# 「還沒翻」「刻意不翻」可能有幾百筆，逐筆列出來只是噪音；其餘的拒寫原因才是
# 譯者要回頭修的東西，要讓他在畫面上就找得到是哪幾筆。
_NOT_WORTH_LISTING = {"untranslated", "skipped"}


def _example_lines(items: list[dict[str, Any]], entries: dict[str, Any]) -> list[str]:
    """把被拒的條目列成「位置 · 原文」，最多 5 筆，其餘指向報告。

    只印數字的話（「格式標記對不上：3」），要去翻 `apply_report.json` 才知道是哪三筆
    ——而譯者要回頭修的正是那三筆。"""
    seen: list[str] = []
    for item in items:
        unit_id = item.get("unit_id")
        if unit_id in entries and unit_id not in seen:
            seen.append(unit_id)
    lines = []
    for unit_id in seen[:_MAX_EXAMPLES_PER_REASON]:
        entry = entries[unit_id]
        source = str(entry.get("source", "")).replace("\n", " ").strip()
        if len(source) > _MAX_SOURCE_CHARS:
            source = source[:_MAX_SOURCE_CHARS] + "…"
        lines.append(f"  {'':>7}    · {entry.get('where', '?')}：{source}")
    rest = len(seen) - _MAX_EXAMPLES_PER_REASON
    if rest > 0:
        lines.append(f"  {'':>7}    · 另有 {rest} 筆，見 apply_report.json 的 unwritten")
    return lines


def _detail_lines(items: list[dict[str, Any]]) -> list[str]:
    """同一個 reason 底下的 `detail`，相同的合併計數、最多的排前面。

    reason 是合約裡的固定 enum，同一個 reason 可能是完全不同的事——
    `unsupported_encoding` 既是「這種節點形狀還沒有寫入路徑」，也是「say 的
    譯文含換行」（2026-10-14 遊戲實測時發現只印共用說明會誤導）。不拆新的
    reason（那是合約改動），改成把 detail 印出來。`node_changed` 的 detail 帶
    各自的形狀，大地圖可能有上百種，所以只列前幾種，其餘指向報告。"""
    tally: dict[str, int] = {}
    for item in items:
        detail = (item.get("detail") or "").strip()
        if detail:
            tally[detail] = tally.get(detail, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = [
        f"  {'':>7}    └ {count:,} 筆：{detail}"
        for detail, count in ranked[:_MAX_DETAILS_PER_REASON]
    ]
    rest = len(ranked) - _MAX_DETAILS_PER_REASON
    if rest > 0:
        lines.append(f"  {'':>7}    └ 另有 {rest} 種說明，見 apply_report.json 的 unwritten")
    return lines


_REASON_TEXT = {
    "untranslated": "還沒翻（target 是空的）",
    "skipped": "刻意不翻（status: skip）",
    "placeholder_mismatch": "格式標記 [[n]] 數量與原文不符（未寫入）",
    "overflow_rejected": "譯文太長，那一行放不下（寬度已校準，見報告的 detail）",
    "node_changed": "節點形狀變了（世界在 extract 之後被改過，多半是在遊戲裡開過）",
    "node_missing": "找不到那個節點",
    "chunk_unreadable": "區塊讀取失敗（存檔可能損毀）",
    "unsupported_encoding": "這種節點形狀還沒有寫入路徑",
}
