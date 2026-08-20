# SPDX-License-Identifier: GPL-3.0-or-later
"""M10.1 lang 檔的產生（`backends/resourcepack/lang.py`）。

`unit.collapsible` 決定寫回方式：

* `true` → 整棵樹塌成一個 `{translate: key}`，樣式轉成 § 碼進 lang 檔的**值**。
* `false` → 重建整棵樹，**每段一個 key**（`<key>.0`、`<key>.1`…）。

輸出是嚴格 JSON、鍵排序（diff 穩定）、`ensure_ascii=False`。
**永不覆寫 `minecraft.*`**——那是原版的命名空間。
"""

import json

import pytest

from mcmt.backends.resourcepack.lang import (
    build_lang,
    sigma_codes_for,
)


def unit(
    key="mcmt.sign.0123456789abcdef",
    *,
    collapsible=True,
    segments=1,
    styles=None,
):
    return {
        "key": key,
        "collapsible": collapsible,
        "segment_count": segments,
        "segment_styles": styles or [{}] * segments,
    }


# --- § 碼轉換 -------------------------------------------------------------


def test_a_colour_becomes_its_code() -> None:
    assert sigma_codes_for({"color": "gold"}) == "§6"


def test_formatting_flags_become_codes() -> None:
    assert sigma_codes_for({"bold": True}) == "§l"
    assert sigma_codes_for({"italic": True}) == "§o"


def test_colour_comes_before_formatting() -> None:
    """§ 的顏色碼會重設格式，所以顏色必須先寫。

    `§l§c文字` 的粗體會被 `§c` 洗掉，`§c§l文字` 才是紅色粗體。
    """
    assert sigma_codes_for({"bold": True, "color": "red"}) == "§c§l"


def test_a_legacy_segment_carries_its_codes_through() -> None:
    assert sigma_codes_for({"codes": "§c§l"}) == "§c§l"


def test_no_style_means_no_codes() -> None:
    assert sigma_codes_for({}) == ""


def test_an_unknown_colour_is_dropped_rather_than_guessed() -> None:
    """`#ff8800` 這種十六進位顏色沒有 § 碼。猜一個最接近的會改變視覺結果。"""
    assert sigma_codes_for({"color": "#ff8800"}) == ""


# --- 塌縮（collapsible = true）--------------------------------------------


def test_a_single_segment_unit_becomes_one_entry() -> None:
    lang = build_lang([(unit(), "歡迎光臨")])

    assert lang == {"mcmt.sign.0123456789abcdef": "歡迎光臨"}


def test_styles_become_sigma_codes_in_the_value() -> None:
    u = unit(segments=2, styles=[{"color": "green"}, {"color": "red"}])

    lang = build_lang([(u, "[[0]]綠字[[1]]紅字")])

    assert lang[u["key"]] == "§a綠字§c紅字"


def test_a_reordered_translation_keeps_each_style_with_its_own_text() -> None:
    """譯者把順序調換時，樣式要跟著它的那段文字走，不是跟著位置走。"""
    u = unit(segments=2, styles=[{"color": "green"}, {"color": "red"}])

    lang = build_lang([(u, "[[1]]紅字在前[[0]]綠字在後")])

    assert lang[u["key"]] == "§c紅字在前§a綠字在後"


def test_an_escaped_literal_is_restored_in_the_value() -> None:
    r"""`[[\0]]` 是使用者看得到的字，寫進 lang 值時要還原成 `[[0]]`。"""
    lang = build_lang([(unit(), "按 [[\\0]] 繼續")])

    assert lang["mcmt.sign.0123456789abcdef"] == "按 [[0]] 繼續"


# --- 重建（collapsible = false）------------------------------------------


def test_a_non_collapsible_unit_becomes_one_entry_per_segment() -> None:
    u = unit(collapsible=False, segments=2, styles=[{}, {"color": "gold"}])

    lang = build_lang([(u, "[[0]]價格：[[1]]五枚金幣")])

    assert lang == {
        "mcmt.sign.0123456789abcdef.0": "價格：",
        "mcmt.sign.0123456789abcdef.1": "五枚金幣",
    }


def test_a_non_collapsible_value_carries_no_sigma_codes() -> None:
    """樣式由重建出來的樹自己帶，不是塞進 lang 值裡。"""
    u = unit(collapsible=False, segments=2, styles=[{"color": "red"}, {"bold": True}])

    lang = build_lang([(u, "[[0]]甲[[1]]乙")])

    assert all("§" not in value for value in lang.values())


def test_a_non_collapsible_single_segment_still_gets_a_segment_key() -> None:
    """`collapsible` 為 false 時一律逐段——寫入層照 `<key>.<n>` 去找。"""
    u = unit(collapsible=False, segments=1)

    lang = build_lang([(u, "點我")])

    assert lang == {"mcmt.sign.0123456789abcdef.0": "點我"}


# --- 拒絕 -----------------------------------------------------------------


def test_the_minecraft_namespace_is_never_written() -> None:
    """**永不覆寫 `minecraft.*`。** 那會改掉原版所有語言的文字。"""
    with pytest.raises(ValueError) as exc:
        build_lang([(unit(key="minecraft.block.stone"), "石頭")])

    assert "minecraft" in str(exc.value)


def test_an_untranslated_unit_is_left_out(caplog) -> None:
    """空譯文不寫進 lang——寫了會把告示牌洗成空白。"""
    assert build_lang([(unit(), "")]) == {}


def test_a_translation_with_leftover_placeholders_is_refused() -> None:
    """塌縮的值裡殘留 `[[n]]` 代表段落數對不上，寫出去玩家會看到那串記號。"""
    u = unit(segments=1)

    with pytest.raises(ValueError) as exc:
        build_lang([(u, "[[0]]甲[[1]]乙")])

    assert "[[1]]" in str(exc.value)


# --- 輸出格式 -------------------------------------------------------------


def test_keys_are_sorted_for_stable_diffs() -> None:
    from mcmt.backends.resourcepack.lang import dump_lang

    text = dump_lang({"mcmt.b": "乙", "mcmt.a": "甲"})

    assert text.index('"mcmt.a"') < text.index('"mcmt.b"')


def test_output_is_strict_json_without_ascii_escapes() -> None:
    from mcmt.backends.resourcepack.lang import dump_lang

    text = dump_lang({"mcmt.a": "中文"})

    assert json.loads(text) == {"mcmt.a": "中文"}
    assert "中文" in text
