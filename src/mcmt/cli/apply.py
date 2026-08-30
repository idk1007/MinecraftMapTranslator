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
from mcmt.errors import WorldChangedSinceExtractError
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

    translations_file = Path(translations_path).resolve()
    translations = json.loads(ensure_readable(translations_file).read_bytes().decode("utf-8"))
    language = translations["language"]

    extract_file = Path(extract_path) if extract_path else translations_file.parent / "extract.json"
    extract = json.loads(ensure_readable(extract_file).read_bytes().decode("utf-8"))

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
        "outcome": outcome,
        "report": report,
        "pack": pack_report,
        "dry_run": dry_run,
    }


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

    backend_refusals: dict[str, int] = {}
    for item in plan.document["unwritten"]:
        backend_refusals[item["reason"]] = backend_refusals.get(item["reason"], 0) + 1
    if backend_refusals:
        lines += ["", "後端沒有產生 edit 的單位"]
        for reason, count in sorted(backend_refusals.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:>7,}  {_REASON_TEXT.get(reason, reason)}")

    if outcome.unwritten:
        writer_refusals: dict[str, int] = {}
        for item in outcome.unwritten:
            writer_refusals[item["reason"]] = writer_refusals.get(item["reason"], 0) + 1
        lines += ["", "寫入層拒絕的節點"]
        for reason, count in sorted(writer_refusals.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:>7,}  {_REASON_TEXT.get(reason, reason)}")

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


_REASON_TEXT = {
    "untranslated": "還沒翻（target 是空的）",
    "skipped": "刻意不翻（status: skip）",
    "placeholder_mismatch": "佔位符對不上——hard fail，少一個標記 § 碼會染到行尾",
    "overflow_rejected": "譯文太長，那一行放不下（寬度已校準，見報告的 detail）",
    "node_changed": "節點形狀變了（世界在 extract 之後被改過，多半是在遊戲裡開過）",
    "node_missing": "找不到那個節點",
    "chunk_unreadable": "chunk 讀不下去",
    "unsupported_encoding": "這種節點形狀還沒有寫入路徑",
}
