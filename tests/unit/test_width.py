# SPDX-License-Identifier: GPL-3.0-or-later
"""M8 字寬（`mcmt/width.py` + `mcmt/fontdata/vanilla_v1.json`）。

**寬度預算要在人開始翻之前就看得到。** 事後才報超寬對譯者沒有幫助——他得先知道
「這行只放得下六個中文字」才有辦法斟酌用詞。

[遊戲實測 M11-2] 吊掛告示牌比一般告示牌窄很多：7 個 CJK 字被截掉，同樣長度在一般
告示牌上完全正常。所以兩者**必須分開量**，不能共用一個數字。

**校準完成前 `enforcement` 一律 `warn`**（CLAUDE.md C 題）。這份測試把那條規則綁在
資料本身的 `calibrated` 旗標上，而不是綁在某處的常數——旗標翻成 true 之前，任何人
想把 sign 升成 error 都會踩到紅燈。
"""

import json
from pathlib import Path

import pytest

from mcmt.width import (
    FONT_DATA,
    advance_of,
    budget_for,
    cjk_capacity,
    enforcement_for,
    measure,
)

FONTDATA = Path(__file__).resolve().parents[2] / "src" / "mcmt" / "fontdata"


# --- 資料本身 -------------------------------------------------------------


def test_every_advance_is_a_positive_integer():
    """0 或負數會讓「放得下幾個字」變成無限大，而那個錯誤看起來像沒有錯誤。"""
    advances = FONT_DATA["advances"].values()
    assert advances and all(isinstance(a, int) and a > 0 for a in advances)


def test_the_data_file_is_strict_json():
    text = (FONTDATA / "vanilla_v1.json").read_text("utf-8")
    assert json.loads(text)
    assert "//" not in text


def test_the_calibrated_numbers_record_what_was_observed():
    """推導過程要留得下來。「90px」本身說不出它是量的還是猜的。"""
    sign = FONT_DATA["budgets"]["sign"]

    assert sign["observed"] == {"ascii_max": 15, "cjk_max": 10, "ascii_advance": 6}
    assert FONT_DATA["bold_observed"]["hanging_sign"] == 8


def test_the_scale_caveat_is_recorded():
    """**階梯定的是比例，不是絕對 px。**

    滿足這組觀察的解全部是等比族（ASCII:CJK 恆為 2:3），整張表乘以 2 也一樣相容。
    絕對尺度靠 `ascii_advance` 那個 [文件] 級的錨。這件事必須寫在資料裡，否則下次
    看到 `evidence: 遊戲實測` 的人會以為 90 這個數字本身是量出來的。
    """
    assert FONT_DATA["scale_note"]
    assert FONT_DATA["advance_evidence"]["ascii"] == "文件"


def test_every_number_carries_an_evidence_level():
    """四級制（[實測]/[遊戲實測]/[文件]/[待驗]）是這個專案的價值所在。

    沒有標等級的數字，下次沒有人知道它是量出來的還是猜的。
    """
    levels = {"實測", "遊戲實測", "文件", "待驗"}
    for name, budget in FONT_DATA["budgets"].items():
        assert budget["evidence"] in levels, name
    assert FONT_DATA["advance_evidence"]["ascii"] in levels
    assert FONT_DATA["advance_evidence"]["cjk"] in levels


# --- 量測 -----------------------------------------------------------------


def test_an_empty_string_is_zero_px():
    assert measure("") == 0


def test_width_is_the_sum_of_the_advances():
    assert measure("MM") == 2 * advance_of("M")


def test_a_narrow_glyph_is_narrower_than_a_wide_one():
    """`i` 與 `M` 同寬的話，整張表就是假的。"""
    assert advance_of("i") < advance_of("M")


def test_a_cjk_glyph_uses_the_cjk_advance():
    assert advance_of("中") == FONT_DATA["cjk_advance"]


def test_sigma_codes_do_not_render_and_do_not_count():
    """§ 碼是內容的一部分（key 生成時不移除），但它**不佔像素**。"""
    assert measure("§a歡迎") == measure("歡迎")


def test_bold_adds_one_pixel_per_glyph():
    """§l 之後每個字多 1px，而且持續到行尾——那正是佔位符驗證是 hard fail 的理由。"""
    assert measure("§lMM") == measure("MM") + 2


def test_bold_is_reset_by_the_reset_code():
    assert measure("§lM§rM") == measure("MM") + 1


def test_a_lone_sigma_at_the_end_is_not_a_code():
    """`§` 在字串結尾沒有後續字元，不構成格式碼。不該讓量測炸掉。"""
    assert measure("M§") == advance_of("M") + advance_of("§")


# --- 預算 -----------------------------------------------------------------


def test_a_hanging_sign_is_narrower_than_a_regular_sign():
    """[遊戲實測 M11-2] 7 個 CJK 字在吊掛告示牌被截掉，在一般告示牌完全正常。"""
    assert budget_for("hanging_sign").max_width_px < budget_for("sign").max_width_px


def test_the_current_numbers_predict_the_m11_observation():
    """把實測觀察變成一條會紅的測試。

    [遊戲實測 M11-2] 吊掛告示牌上 7 個 CJK 字放不下。這一條在校準**之前**就寫了，
    當時 60px / CJK 9px 還只是猜的；[遊戲實測 2026-08-21] M8 的階梯量出來正是
    「6 個進得去、7 個不行」，所以那組猜測是對的，而這條測試從一開始就守著它。
    """
    assert measure("中" * 6) <= budget_for("hanging_sign").max_width_px
    assert measure("中" * 7) > budget_for("hanging_sign").max_width_px


def test_the_same_seven_characters_fit_on_a_regular_sign():
    assert measure("中" * 7) <= budget_for("sign").max_width_px


def test_cjk_capacity_is_what_the_translator_actually_needs():
    """「90px」對譯者沒有意義，「放得下 10 個中文字」有。"""
    assert cjk_capacity("hanging_sign") == 6


def test_an_unknown_category_has_no_budget():
    assert budget_for("command_text") is None
    assert cjk_capacity("command_text") is None


# --- 校準前一律 warn ------------------------------------------------------


def test_a_calibrated_category_enforces_error():
    """[遊戲實測 2026-08-21] 告示牌兩種都量過了，所以它們現在硬擋。"""
    assert budget_for("sign").calibrated is True
    assert enforcement_for("sign") == "error"
    assert enforcement_for("hanging_sign") == "error"


def test_an_uncalibrated_category_still_only_warns():
    """`book_page` 還沒量——v1 根本還沒掃到書本（M13），連一個資料點都沒有。"""
    assert budget_for("book_page").calibrated is False
    assert enforcement_for("book_page") == "warn"


def test_a_category_without_a_budget_enforces_nothing():
    assert enforcement_for("command_text") == "none"


def test_enforcement_falls_back_to_warn_if_a_category_is_un_calibrated(monkeypatch):
    """升級成 error 是**資料**的決定，不是程式碼裡某個 if 的決定。

    這條原本是反過來寫的（把 sign 假裝成已校準，斷言它變 error）。校準真的做完
    之後那個方向就測不到東西了，所以改成假裝**退回**未校準——要驗的是「旗標說了算」，
    不是某一個特定的值。
    """
    from mcmt import width

    uncalibrated = dict(FONT_DATA["budgets"]["sign"])
    uncalibrated["calibrated"] = False
    monkeypatch.setitem(width.FONT_DATA["budgets"], "sign", uncalibrated)

    assert width.enforcement_for("sign") == "warn"
