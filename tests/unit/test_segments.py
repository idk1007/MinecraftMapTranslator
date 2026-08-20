# SPDX-License-Identifier: GPL-3.0-or-later
"""M5.3 component 樹攤平（`model/segments.py`）。

**§ 舊碼與結構化格式是同一套佔位符機制的兩種輸入，不是兩條路**（CLAUDE.md 三節）。
兩者都變成 segment，都在 `text` 裡以同一種 `[[n]]` 標記開頭，LLM 看到的是不透明記號。

[實測] MP2 可翻譯路徑上有 2,261 個帶 `extra` 的 component 樹，最大巢狀深度 3，
extra 元素數長尾至 34，其中 84% 的子元素自帶格式屬性。所以「extra 就是格式，原封
搬運就好」是錯的——要攤平＋重建。
"""

import pytest

from mcmt.model.segments import flatten


# --- 最單純的情況 ---------------------------------------------------------


def test_a_plain_string_is_one_unstyled_segment() -> None:
    result = flatten("歡迎光臨")

    assert result.text == "歡迎光臨"
    assert result.plain == "歡迎光臨"
    assert [s.kind for s in result.segments] == ["none"]
    assert result.collapsible is True


def test_plain_keeps_the_text_exactly_including_whitespace() -> None:
    """告示牌用前導空白做置中排版，折疊空白會讓排版全毀（CLAUDE.md 三節）。"""
    result = flatten("  歡迎  ")

    assert result.plain == "  歡迎  "
    assert result.text == "  歡迎  "


def test_a_text_compound_flattens_like_a_string() -> None:
    assert flatten({"text": "歡迎"}).plain == "歡迎"


def test_an_empty_key_compound_flattens_like_a_string() -> None:
    """[遊戲實測 M4-2] `{\"\": …}` 是 Mojang NbtOps 的標準輸出。"""
    assert flatten({"": "歡迎"}).plain == "歡迎"


# --- § 舊碼 ---------------------------------------------------------------


def test_sigma_codes_open_segments() -> None:
    result = flatten("§a綠色§c紅色")

    assert result.text == "[[0]]綠色[[1]]紅色"
    assert result.plain == "綠色紅色"
    assert [s.kind for s in result.segments] == ["legacy", "legacy"]
    assert result.styles == [{"codes": "§a"}, {"codes": "§c"}]


def test_text_before_the_first_sigma_code_is_its_own_unstyled_segment() -> None:
    result = flatten("一般§c紅色")

    assert result.text == "[[0]]一般[[1]]紅色"
    assert [s.kind for s in result.segments] == ["none", "legacy"]
    assert result.styles == [{}, {"codes": "§c"}]


def test_consecutive_sigma_codes_open_a_single_segment() -> None:
    """`§c§l` 是一段紅色粗體，不是兩段。"""
    result = flatten("§c§l紅色粗體")

    assert result.text == "紅色粗體"  # 只有一段就不插標記
    assert result.styles == [{"codes": "§c§l"}]


def test_sigma_codes_stay_out_of_the_translatable_text() -> None:
    """譯者看到的是 `[[n]]`，不是 `§c`——少一個 § 碼會染到整行結尾。"""
    result = flatten("§c紅色")

    assert "§" not in result.text
    assert "§" not in result.plain


def test_a_trailing_sigma_code_with_no_text_still_records_the_segment() -> None:
    result = flatten("文字§r")

    assert result.plain == "文字"
    assert [s.kind for s in result.segments] == ["none", "legacy"]


# --- extra 樹 -------------------------------------------------------------


def test_extra_children_are_flattened_in_render_order() -> None:
    tree = {"text": "父", "extra": [{"text": "子一"}, {"text": "子二"}]}

    result = flatten(tree)

    assert result.plain == "父子一子二"
    assert len(result.segments) == 3


def test_a_child_with_its_own_formatting_becomes_a_structural_segment() -> None:
    """[實測] 84% 的 extra 子元素自帶格式屬性。"""
    tree = {"text": "價格：", "extra": [{"text": "5 金幣", "color": "gold"}]}

    result = flatten(tree)

    assert result.text == "[[0]]價格：[[1]]5 金幣"
    assert [s.kind for s in result.segments] == ["none", "structural"]
    assert result.styles[1] == {"color": "gold"}


def test_the_italic_suppression_idiom_survives() -> None:
    """`{\"text\":\"\",\"extra\":[{\"text\":\"X\",\"italic\":false}]}` 是壓掉物品名
    預設斜體的慣用法。重建時漏掉 `italic:false`，物品名會變回斜體。"""
    tree = {"text": "", "extra": [{"text": "寶劍", "italic": False}]}

    result = flatten(tree)

    assert result.plain == "寶劍"
    assert {"italic": False} in result.styles


def test_nesting_three_deep_is_flattened() -> None:
    """[實測] 最大巢狀深度是 3。"""
    tree = {
        "text": "一",
        "extra": [{"text": "二", "extra": [{"text": "三", "bold": True}]}],
    }

    result = flatten(tree)

    assert result.plain == "一二三"
    assert len(result.segments) == 3


def test_the_json_array_form_treats_the_first_element_as_the_parent() -> None:
    """[實測] `[\"\", {...}, {...}]`：`100 Ways To Die` 66 筆、`Questioning` 40 筆。"""
    result = flatten(["", {"text": "甲"}, {"text": "乙", "color": "red"}])

    assert result.plain == "甲乙"
    assert result.styles[-1] == {"color": "red"}


# --- translate 節點 -------------------------------------------------------


def test_a_translate_node_contributes_its_fallback_text() -> None:
    """MP2 自己的中文化系統就長這樣，我們必須讀得懂並重建。"""
    tree = {"translate": "mcp.Cost_", "fallback": "Cost:"}

    result = flatten(tree)

    assert result.plain == "Cost:"
    assert result.styles[0] == {"translate": "mcp.Cost_", "fallback": "Cost:"}


def test_a_translate_node_is_not_sigma_expressible() -> None:
    """lang 檔的值裡沒辦法再放一個 translate，所以這種樹不能塌縮。"""
    result = flatten({"translate": "mcp.Cost_", "fallback": "Cost:"})

    assert result.segments[0].sigma_expressible is False
    assert result.collapsible is False


def test_the_real_mp2_case_flattens_as_the_contract_sample_says() -> None:
    tree = {
        "translate": "mcp.Cost_",
        "fallback": "Cost:",
        "extra": [
            {
                "translate": "mcp.CenterParkSlotMachineCost",
                "fallback": " 5 Coins",
                "color": "gold",
            }
        ],
    }

    result = flatten(tree)

    assert result.text == "[[0]]Cost:[[1]] 5 Coins"
    assert result.plain == "Cost: 5 Coins"
    assert result.collapsible is False
    assert result.skeleton == {
        "type": "translate",
        "segment": 0,
        "extra": [{"type": "translate", "segment": 1}],
    }


# --- collapsible 的判定 ---------------------------------------------------


@pytest.mark.parametrize("field", ["click_event", "hover_event", "font", "insertion"])
def test_these_fields_make_a_segment_non_sigma_expressible(field: str) -> None:
    """§ 碼表達不了這些，所以整棵樹不能塌成一個 lang 值。"""
    result = flatten({"text": "點我", field: {"anything": 1}})

    assert result.segments[0].sigma_expressible is False
    assert result.collapsible is False


@pytest.mark.parametrize(
    "style", [{"color": "gold"}, {"bold": True}, {"italic": False}, {"obfuscated": True}]
)
def test_plain_formatting_stays_collapsible(style: dict) -> None:
    """顏色與粗斜體都寫得成 § 碼，所以塌縮後樣式進 lang 檔的值。"""
    result = flatten({"text": "文字", **style})

    assert result.segments[0].sigma_expressible is True
    assert result.collapsible is True


def test_one_bad_segment_makes_the_whole_tree_non_collapsible() -> None:
    tree = {"text": "好", "extra": [{"text": "壞", "font": "minecraft:alt"}]}

    assert flatten(tree).collapsible is False


# --- 骨架 -----------------------------------------------------------------


def test_the_skeleton_replaces_text_with_segment_indices() -> None:
    tree = {"text": "父", "extra": [{"text": "子", "color": "red"}]}

    assert flatten(tree).skeleton == {
        "type": "text",
        "segment": 0,
        "extra": [{"type": "text", "segment": 1}],
    }


def test_a_bare_string_has_a_skeleton_too() -> None:
    assert flatten("文字").skeleton == {"type": "text", "segment": 0}


# --- 字面 [[n]] 的轉義 ----------------------------------------------------


def test_literal_placeholder_text_is_escaped_and_recorded() -> None:
    """原文自己含 `[[0]]` 時不轉義，佔位符驗證會把它算成我們的標記。"""
    result = flatten("看這裡 [[0]] 這樣")

    assert "[[\\0]]" in result.text
    assert result.escaped_literals == ["[[0]]"]


def test_text_without_literal_placeholders_records_none() -> None:
    assert flatten("一般文字").escaped_literals == []


# --- translate 的參數（with）----------------------------------------------


def test_translate_arguments_are_carried_not_flattened() -> None:
    """[實測] MP2 的告示牌有 `with` 參數，內容是玩家名、分數這類**執行期產物**。

    v1 不把 `with` 裡的文字攤進 `text`：那些不是地圖作者寫的字，是遊戲執行時填進去
    的值，翻它沒有意義。但它必須原樣被帶走，否則重建時整個參數會消失。
    """
    tree = {
        "translate": "mcp.Greet",
        "fallback": "哈囉 %s",
        "with": [{"text": "ClashAssassin"}],
    }

    result = flatten(tree)

    assert result.plain == "哈囉 %s"
    assert "ClashAssassin" not in result.text
    assert result.styles[0]["with"] == [{"text": "ClashAssassin"}]


def test_a_click_event_sign_is_not_collapsible() -> None:
    """[實測] MP2 有 1,694 個帶 click_event 的告示牌節點——那是小遊戲的 UI。

    § 碼表達不了 click_event，所以這類樹只能重建、不能塌縮。這不是我們的選擇，
    是格式的限制。
    """
    tree = {"click_event": {"action": "run_command", "command": "/function mcp:x"}, "text": " "}

    assert flatten(tree).collapsible is False


# --- 單一段落不插標記（M7 的人工編輯需求）--------------------------------


def test_a_single_segment_carries_no_placeholder_at_all() -> None:
    """純文字就是純文字。

    待翻檔是人直接編輯的，每一行都掛一個無意義的 `[[0]]` 前綴是雜訊，而且很容易
    被順手刪掉——刪掉之後佔位符驗證會硬失敗，卻是我們自己造成的。
    [實測] MP2 的 5,344 棵樹裡有 4,871 棵只有一個段落。
    """
    result = flatten("歡迎光臨")

    assert result.text == "歡迎光臨"
    assert result.text == result.plain
    assert len(result.segments) == 1


def test_a_single_styled_segment_also_carries_no_placeholder() -> None:
    """整串都是同一個樣式時也不需要標記——樣式的範圍就是整串。"""
    result = flatten({"text": "紅色的字", "color": "red"})

    assert result.text == "紅色的字"
    assert result.styles == [{"color": "red"}]


def test_two_segments_bring_the_placeholders_back() -> None:
    result = flatten({"text": "價格：", "extra": [{"text": "5 金幣", "color": "gold"}]})

    assert result.text == "[[0]]價格：[[1]]5 金幣"


def test_an_escaped_literal_survives_even_with_no_segments_marked() -> None:
    """單段落不插標記，但原文自己含的 `[[0]]` 還是要轉義。"""
    result = flatten("按 [[0]] 繼續")

    assert result.text == r"按 [[\0]] 繼續"
    assert result.escaped_literals == ["[[0]]"]
