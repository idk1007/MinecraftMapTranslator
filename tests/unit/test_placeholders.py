# SPDX-License-Identifier: GPL-3.0-or-later
"""M7.2 佔位符驗證（`extract/placeholders.py`）。

**這是 hard fail 不是 warn。** `§l`、`§n` 這類格式碼持續生效到 `§r` 或行尾，少一個
標記就是顏色／粗體染到整行結尾。

順序**可以**不同——中文語序重排是正常的。但兩個附帶規則：

* 原文含字面 `[[n]]` 時轉義成 `[[\\n]]`，那個不算我們的標記。
* 佔位符**全數前移**（`[[0]][[1]]文字`）集合檢查會過但語意全毀，要單獨警告。
"""

import pytest

from mcmt.extract.placeholders import (
    tokens_in,
    unescape,
    validate,
)


def ok(source: str, target: str) -> bool:
    return validate(source, target).ok


# --- 抓標記 ---------------------------------------------------------------


def test_tokens_are_found_in_order() -> None:
    assert tokens_in("[[0]]甲[[1]]乙") == ["[[0]]", "[[1]]"]


def test_an_escaped_literal_is_not_one_of_our_tokens() -> None:
    r"""`[[\0]]` 是原文自己的字，不是我們插的標記。"""
    assert tokens_in("按 [[\\0]] 繼續") == []


def test_a_mix_of_real_and_escaped_tokens() -> None:
    assert tokens_in("[[0]]按 [[\\1]] 鍵") == ["[[0]]"]


def test_text_with_no_tokens_has_none() -> None:
    assert tokens_in("歡迎光臨") == []


# --- 通過的情況 -----------------------------------------------------------


def test_an_exact_match_passes() -> None:
    assert ok("[[0]]Cost:[[1]] 5 Coins", "[[0]]花費：[[1]] 5 枚金幣")


def test_reordered_tokens_pass() -> None:
    """中文語序重排是正常的，順序不是我們要管的事。"""
    assert ok("[[0]]甲[[1]]乙", "[[1]]乙[[0]]甲")


def test_plain_text_with_no_tokens_passes() -> None:
    assert ok("歡迎光臨", "Welcome")


def test_an_escaped_literal_must_survive_but_is_not_a_token() -> None:
    assert ok("按 [[\\0]] 繼續", "Press [[\\0]] to continue")


# --- 硬失敗 ---------------------------------------------------------------


def test_a_missing_token_is_a_hard_failure() -> None:
    """少一個 § 碼就染到整行結尾。這是規範明定的 hard fail。"""
    result = validate("[[0]]甲[[1]]乙", "[[0]]甲乙")

    assert result.ok is False
    assert result.reason == "placeholder_mismatch"
    assert "[[1]]" in result.detail


def test_an_extra_token_is_a_hard_failure() -> None:
    assert not ok("[[0]]甲", "[[0]]甲[[1]]乙")


def test_a_duplicated_token_is_a_hard_failure() -> None:
    """多重集合要完全一致——不多、不少、**不重複**。"""
    assert not ok("[[0]]甲[[1]]乙", "[[0]]甲[[0]]乙[[1]]丙")


def test_dropping_an_escaped_literal_is_also_a_failure() -> None:
    """轉義過的字面文字被吃掉，使用者看到的字就少了一段。"""
    result = validate("按 [[\\0]] 繼續", "按 繼續")

    assert result.ok is False
    assert result.reason == "escaped_literal_lost"


# --- 前移警告 -------------------------------------------------------------


def test_all_tokens_moved_to_the_front_is_flagged() -> None:
    """集合檢查會過，但樣式全毀——所以單獨檢查、單獨警告，交人工複審。"""
    result = validate("[[0]]甲[[1]]乙", "[[0]][[1]]甲乙")

    assert result.ok is True
    assert "placeholder_front_loaded" in result.warnings


def test_normally_distributed_tokens_are_not_flagged() -> None:
    result = validate("[[0]]甲[[1]]乙", "[[0]]甲[[1]]乙")

    assert result.warnings == []


def test_a_single_token_at_the_front_is_not_front_loading() -> None:
    """只有一個標記時「全數前移」沒有意義，不該誤報。"""
    result = validate("[[0]]甲乙", "[[0]]甲乙")

    assert result.warnings == []


def test_two_tokens_adjacent_in_the_middle_are_flagged() -> None:
    """前移的判準是「標記彼此相鄰、之間沒有文字」，不是「在字串開頭」。"""
    result = validate("[[0]]甲[[1]]乙", "文字[[0]][[1]]甲乙")

    assert "placeholder_front_loaded" in result.warnings


# --- 還原 -----------------------------------------------------------------


def test_unescape_restores_the_literal_text() -> None:
    r"""寫回節點前要把 `[[\0]]` 還原成 `[[0]]`。"""
    assert unescape("按 [[\\0]] 繼續") == "按 [[0]] 繼續"


def test_unescape_leaves_real_tokens_alone() -> None:
    """真正的標記由寫入層自己處理，不歸還原管。"""
    assert unescape("[[0]]甲") == "[[0]]甲"


def test_an_empty_translation_is_not_a_placeholder_problem() -> None:
    """空 target 是「還沒翻」，那是另一件事，不該報成佔位符錯誤。"""
    result = validate("[[0]]甲[[1]]乙", "")

    assert result.reason == "empty_translation"
