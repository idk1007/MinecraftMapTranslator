# SPDX-License-Identifier: GPL-3.0-or-later
"""M11.1 兩套寫入值（`write/legacy.py` 與 `write/native.py`）。

**不對稱是規格層級的，不是可以抽象掉的重複**（CLAUDE.md 二節）。具體差在哪：

| | legacy chunk（DV < 4325） | native chunk（DV ≥ 4325） |
|---|---|---|
| 寫什麼 | **JSON 字串**（[遊戲實測 M4-1] 有效） | **NBT compound**（[遊戲實測 M0-3] JSON 字串會被當字面文字算繪） |
| list 型別 | 仍是 `TAG_String`，**不必提升** | 目標是 compound，String list **非整個提升不可** |

list 提升不是選擇：`TAG_List` 在 NBT 格式層帶單一元素型別，把 `CompoundTag` 塞進
`list_data_type=8` 的 list 會直接 `TypeError`。
"""

import json

import amulet_nbt
import pytest

from mcmt.write import legacy, native


TRANSLATE = {"kind": "translate", "key": "mcmt.sign.0123456789abcdef", "style": None}


def messages(*values):
    return amulet_nbt.ListTag([amulet_nbt.StringTag(v) for v in values])


def compounds(*values):
    return amulet_nbt.ListTag(
        [amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(v)}) for v in values]
    )


# --- legacy：寫 JSON 字串 -------------------------------------------------


def test_legacy_writes_a_json_string() -> None:
    """[遊戲實測 M4-1] 在 DV 3700 的 chunk 裡，這個形狀顯示正確。"""
    tag = legacy.value_tag(TRANSLATE)

    assert isinstance(tag, amulet_nbt.StringTag)
    assert json.loads(str(tag)) == {"translate": "mcmt.sign.0123456789abcdef"}


def test_legacy_keeps_the_list_type_so_no_promotion_is_needed() -> None:
    lst = messages('"原文"', '""', '""', '""')

    result = legacy.apply_to_list(lst, 0, legacy.value_tag(TRANSLATE))

    assert result.promoted is False
    assert result.list.list_data_type == 8  # TAG_String，沒變


def test_legacy_leaves_the_other_lines_byte_identical() -> None:
    """單點替換，不動其他行。"""
    lst = messages('"原文"', '"第二行"', '""', '""')

    result = legacy.apply_to_list(lst, 0, legacy.value_tag(TRANSLATE))

    assert [str(x) for x in result.list[1:]] == ['"第二行"', '""', '""']


def test_legacy_writes_style_into_the_component() -> None:
    tag = legacy.value_tag({**TRANSLATE, "style": {"color": "gold"}})

    assert json.loads(str(tag))["color"] == "gold"


def test_legacy_writes_a_literal_as_a_json_string() -> None:
    tag = legacy.value_tag({"kind": "literal", "text": "純文字", "style": None})

    assert json.loads(str(tag)) == {"text": "純文字"}


def test_legacy_writes_a_rebuilt_tree_as_a_json_string() -> None:
    tree = {"translate": "k.0", "extra": [{"translate": "k.1"}]}
    tag = legacy.value_tag({"kind": "component", "tree": tree})

    assert json.loads(str(tag)) == tree


def test_legacy_output_is_compact_json() -> None:
    """[實測] 真實地圖的舊式 JSON 就是 compact 形式，78/78 位元組一致。"""
    tag = legacy.value_tag(TRANSLATE)

    assert ", " not in str(tag)


# --- native：寫 compound --------------------------------------------------


def test_native_writes_a_compound() -> None:
    tag = native.value_tag(TRANSLATE)

    assert isinstance(tag, amulet_nbt.CompoundTag)
    assert str(tag["translate"]) == "mcmt.sign.0123456789abcdef"


def test_native_writes_style_onto_the_compound() -> None:
    tag = native.value_tag({**TRANSLATE, "style": {"color": "gold", "bold": True}})

    assert str(tag["color"]) == "gold"
    assert bool(tag["bold"]) is True


def test_native_writes_a_literal_as_a_text_compound() -> None:
    """寫入一律用 `{"text": …}`——官方文件記載的形狀。"""
    tag = native.value_tag({"kind": "literal", "text": "純文字", "style": None})

    assert set(map(str, tag.keys())) == {"text"}
    assert str(tag["text"]) == "純文字"


# --- native：list 提升 ----------------------------------------------------


def test_native_promotes_a_string_list_and_says_so() -> None:
    """告示牌四行只要有一行變成 compound，其餘三行就不能是裸字串。"""
    lst = messages("原文", "第二行", "", "")

    result = native.apply_to_list(lst, 0, native.value_tag(TRANSLATE))

    assert result.promoted is True
    assert result.list.list_data_type == 10  # TAG_Compound
    assert len(result.list) == 4


def test_the_other_lines_keep_their_exact_text_after_promotion() -> None:
    """提升不是重寫內容——其餘三行的字要一模一樣。"""
    lst = messages("原文", "第二行", "  置中  ", "")

    result = native.apply_to_list(lst, 0, native.value_tag(TRANSLATE))

    assert [str(x["text"]) for x in result.list[1:]] == ["第二行", "  置中  ", ""]


def test_legacy_json_siblings_keep_rendering_the_same_after_promotion() -> None:
    """native chunk 裡的 `'\"\"'` 是**字面的兩個引號**（[遊戲實測 M0-4]）。

    提升時把它包成 `{"text": '\"\"'}`，玩家看到的還是那兩個引號——沒有被我們
    「順手修好」，那正是規範要求的。
    """
    lst = messages("原文", '""', "", "")

    result = native.apply_to_list(lst, 0, native.value_tag(TRANSLATE))

    assert str(result.list[1]["text"]) == '""'


def test_an_already_compound_list_needs_no_promotion() -> None:
    lst = compounds("原文", "第二行", "", "")

    result = native.apply_to_list(lst, 0, native.value_tag(TRANSLATE))

    assert result.promoted is False
    assert str(result.list[1]["text"]) == "第二行"


def test_only_the_target_element_changes_in_a_compound_list() -> None:
    lst = compounds("原文", "第二行", "", "")

    result = native.apply_to_list(lst, 1, native.value_tag(TRANSLATE))

    assert "translate" in result.list[1]
    assert str(result.list[0]["text"]) == "原文"


def test_promotion_of_an_empty_list_is_still_coherent() -> None:
    lst = amulet_nbt.ListTag()

    result = native.apply_to_list(lst, 0, native.value_tag(TRANSLATE))

    assert len(result.list) == 1
    assert result.list.list_data_type == 10


# --- 兩邊都不接受的東西 ---------------------------------------------------


@pytest.mark.parametrize("module", [legacy, native])
def test_a_literal_with_placeholder_residue_is_refused(module) -> None:
    """殘留 `[[n]]` 代表上游算錯了。**拒絕整份 plan，不是跳過這一筆。**"""
    from mcmt.errors import PlaceholderResidueError

    with pytest.raises(PlaceholderResidueError):
        module.value_tag({"kind": "literal", "text": "還有 [[0]] 沒處理", "style": None})


@pytest.mark.parametrize("module", [legacy, native])
def test_an_unknown_value_kind_is_refused(module) -> None:
    with pytest.raises(ValueError):
        module.value_tag({"kind": "沒看過這種", "text": "x"})
