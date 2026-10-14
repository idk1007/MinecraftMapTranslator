# SPDX-License-Identifier: GPL-3.0-or-later
"""`cli/apply.py::format_apply()` 的人類可讀摘要。

寫入層的拒寫原因（`reason`）是合約裡的固定 enum，同一個 reason 底下可能是完全
不同的事：`unsupported_encoding` 既是「這種節點形狀還沒有寫入路徑」，也是
「say 的譯文含換行、純文字參數沒有跳脫語法」。摘要只印 reason 的共用說明會誤導
（2026-10-14 遊戲實測時發現），所以每個 reason 底下要接著印 `detail`。
"""

from pathlib import Path
from types import SimpleNamespace

from mcmt.cli.apply import format_apply


def _summary(writer_unwritten):
    counts = {
        "edits_planned": len(writer_unwritten) + 1,
        "edits_written": 1,
        "chunks_touched": 1,
        "chunks_copied_verbatim": 0,
        "files_rewritten": 1,
        "list_promotions": 0,
    }
    return {
        "world": Path("sandbox/w"),
        "dry_run": False,
        "outcome": SimpleNamespace(unwritten=writer_unwritten, warnings=[]),
        "plan": SimpleNamespace(document={"unwritten": []}),
        "report": {"counts": counts, "backup": None},
        "pack": None,
        "out": Path("sandbox/.mcmt-out/w"),
    }


def _refusal(reason, detail, n=1):
    return {"unit_id": f"u:command_say_text:{n:016x}", "reason": reason, "detail": detail}


def test_a_writer_refusal_prints_its_detail_under_the_shared_reason_text() -> None:
    detail = "譯文含控制字元（換行、tab 等），say／me 的純文字參數無法表示"
    text = format_apply(
        _summary([_refusal("unsupported_encoding", detail, 1), _refusal("unsupported_encoding", detail, 2)])
    )

    assert "這種節點形狀還沒有寫入路徑" in text
    assert detail in text
    # 同一個 detail 合併計數，不是逐筆重複印。
    assert text.count(detail) == 1
    detail_line = next(line for line in text.splitlines() if detail in line)
    assert "2" in detail_line


def test_different_details_under_one_reason_are_listed_separately() -> None:
    text = format_apply(
        _summary(
            [
                _refusal("unsupported_encoding", "原因甲", 1),
                _refusal("unsupported_encoding", "原因乙", 2),
            ]
        )
    )

    assert "原因甲" in text
    assert "原因乙" in text


def test_many_distinct_details_are_capped_and_point_to_the_report() -> None:
    """`node_changed` 的 detail 會帶各自的形狀（「預期 X，現在是 Y」），一張大地圖
    可能有上百種。摘要只列最多的幾種，其餘指向報告，不把終端機淹掉。"""
    refusals = [_refusal("node_changed", f"細節 {i}", i) for i in range(10)]
    text = format_apply(_summary(refusals))

    shown = [i for i in range(10) if f"細節 {i}" in text]
    assert len(shown) == 3
    assert "另有 7 種" in text
    assert "apply_report.json" in text


def test_a_refusal_without_detail_does_not_print_an_empty_line() -> None:
    text = format_apply(_summary([{"unit_id": "u:x:0", "reason": "node_missing", "detail": ""}]))

    assert "找不到那個節點" in text
    assert not any(line.strip() in ("└", "└ 1") for line in text.splitlines())
