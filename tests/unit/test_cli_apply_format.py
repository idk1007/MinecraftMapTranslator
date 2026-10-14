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


# --- F5／F6／F7：摘要文字 --------------------------------------------------------


def _with_backend_refusals(refusals, entries):
    summary = _summary([])
    summary["plan"] = SimpleNamespace(document={"unwritten": refusals})
    summary["translations"] = {"entries": entries}
    return summary


def _entry(source, where):
    return {"source": source, "where": where, "target": "x"}


def test_f5_a_placeholder_mismatch_says_it_was_not_written() -> None:
    summary = _with_backend_refusals(
        [{"unit_id": "u:a", "reason": "placeholder_mismatch"}],
        {"u:a": _entry("[[0]]Hello [[1]]world", "overworld 1,2,3")},
    )

    text = format_apply(summary)

    assert "格式標記 [[n]] 數量與原文不符（未寫入）" in text
    assert "hard fail" not in text


def test_f6_an_unreadable_chunk_is_described_plainly() -> None:
    text = format_apply(_summary([_refusal("chunk_unreadable", "")]))

    assert "區塊讀取失敗（存檔可能損毀）" in text


def test_f7_rejected_entries_are_listed_with_source_and_where() -> None:
    refusals = [
        {"unit_id": f"u:{i}", "reason": "placeholder_mismatch"} for i in range(8)
    ]
    entries = {f"u:{i}": _entry(f"原文{i}", f"overworld {i},64,0") for i in range(8)}

    text = format_apply(_with_backend_refusals(refusals, entries))

    for i in range(5):
        assert f"原文{i}" in text
        assert f"overworld {i},64,0" in text
    assert "原文5" not in text
    assert "另有 3 筆" in text
    assert "apply_report.json" in text


def test_f7_untranslated_entries_are_not_listed() -> None:
    """「還沒翻」可能有幾百筆，逐筆列出來只是噪音。"""
    refusals = [{"unit_id": f"u:{i}", "reason": "untranslated"} for i in range(30)]
    entries = {f"u:{i}": _entry(f"原文{i}", "somewhere") for i in range(30)}

    text = format_apply(_with_backend_refusals(refusals, entries))

    assert "還沒翻" in text
    assert "原文0" not in text


def test_f7_writer_refusals_list_their_entries_too() -> None:
    summary = _summary([_refusal("node_changed", "預期 A，現在是 B", n=1)])
    summary["translations"] = {"entries": {"u:command_say_text:0000000000000001": _entry("Hello", "3,-60,19")}}

    text = format_apply(summary)

    assert "Hello" in text
    assert "3,-60,19" in text


def test_f7_a_long_source_is_shortened() -> None:
    long = "很長的原文" * 40
    text = format_apply(
        _with_backend_refusals(
            [{"unit_id": "u:a", "reason": "overflow_rejected"}],
            {"u:a": _entry(long, "here")},
        )
    )

    assert long not in text
    assert "…" in text
