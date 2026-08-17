# SPDX-License-Identifier: GPL-3.0-or-later
"""M5.1 節點形狀嗅探（`model/component.py`）。

`occurrence.encoding` 是**唯一權威**，由逐節點嗅探實際值的形狀決定，**不是**由
`container.data_version` 推導——[實測] DV 4556 的 chunk 裡有 2,340 個舊式 JSON
空字串。這份測試存在的理由就是把那條規則釘死。

JSON 解析失敗**不是**裸文字：標成 `unparseable_json` 跳過並計數，絕不靜默當純文字
翻掉（翻了會寫回非法 JSON，而遊戲對非法 JSON 的行為未定義）。
"""

import json
from pathlib import Path

import amulet_nbt
import pytest

from mcmt.model import SCHEMA_VERSION
from mcmt.model.component import Encoding, sniff

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


# --- 與合約綁死 -----------------------------------------------------------


def contract_enum(name: str) -> list[str]:
    schema = json.loads((CONTRACTS / "extract.schema.json").read_text("utf-8"))
    return schema["$defs"]["occurrence"]["properties"][name]["enum"]


def test_the_encoding_enum_is_exactly_the_contracts():
    """`model/` 是 schema 的程式碼投影，所以這兩者只要能漂移就一定會漂移。

    有這條測試，`Encoding` 與合約的 enum 之間就沒有「安靜地對不上」的空間——
    比 bump 一次 `SCHEMA_VERSION` 有效得多，因為版本號不會告訴你哪裡不一樣。
    """
    assert {e.value for e in Encoding} == set(contract_enum("encoding"))


def test_schema_version_matches_every_contract() -> None:
    """四份合約共用同一個版本號（CLAUDE.md §四）。"""
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        schema = json.loads(path.read_text("utf-8"))
        const = schema["properties"]["schema_version"]["const"]
        assert const == SCHEMA_VERSION, f"{path.name} 的 schema_version 是 {const}"


# --- 原生形狀 -------------------------------------------------------------


def test_a_bare_string_is_a_bare_string() -> None:
    """[實測] 純文字 component 會被 Mojang 折疊成裸字串。"""
    assert sniff(amulet_nbt.StringTag("歡迎光臨")).encoding is Encoding.BARE_STRING


def test_an_empty_native_string_is_a_bare_string_not_an_empty_quoted_one() -> None:
    """`''`（0 字元）與 `'\"\"'`（2 字元）是兩件事。

    [實測] MP2 有 39,106 個原生零長度與 2,340 個舊式 `'\"\"'`，而且同存於 DV 4556。
    混為一談會讓 2,340 個「顯示成字面引號的壞掉節點」被當成空白略過。
    """
    assert sniff(amulet_nbt.StringTag("")).encoding is Encoding.BARE_STRING


def test_an_empty_key_compound_is_recognised() -> None:
    """[遊戲實測 M4-2] 這是 Mojang `NbtOps` 的標準輸出，不是某個工具的怪癖。"""
    tag = amulet_nbt.CompoundTag({"": amulet_nbt.StringTag("文字")})

    assert sniff(tag).encoding is Encoding.EMPTY_KEY_COMPOUND


def test_a_text_compound_is_recognised() -> None:
    tag = amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("文字")})

    assert sniff(tag).encoding is Encoding.TEXT_COMPOUND


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "文字", "color": "gold"},
        {"text": "", "extra": []},
        {"translate": "mcp.Cost_", "fallback": "Cost:"},
        {"": "文字", "bold": 1},
    ],
)
def test_a_compound_with_structure_is_a_tree(payload: dict) -> None:
    """多一個鍵就是有結構——`{\"text\":\"\",\"extra\":[…]}` 是壓掉物品名斜體的慣用法。"""
    tag = amulet_nbt.CompoundTag(
        {
            k: (amulet_nbt.StringTag(v) if isinstance(v, str)
                else amulet_nbt.ListTag() if isinstance(v, list)
                else amulet_nbt.ByteTag(v))
            for k, v in payload.items()
        }
    )

    assert sniff(tag).encoding is Encoding.COMPOUND_TREE


def test_a_native_list_is_a_tree() -> None:
    tag = amulet_nbt.ListTag([amulet_nbt.StringTag("a"), amulet_nbt.StringTag("b")])

    assert sniff(tag).encoding is Encoding.COMPOUND_TREE


# --- 舊式 JSON 字串 -------------------------------------------------------


def test_the_two_character_empty_quoted_string_has_its_own_encoding() -> None:
    """[實測] MP2 有 2,340 筆，且 585 面告示牌四行全是這個。"""
    assert sniff(amulet_nbt.StringTag('""')).encoding is Encoding.JSON_EMPTY_QUOTED


def test_a_json_scalar_is_recognised_and_parsed() -> None:
    """[實測] `Arena of Darkness` 的告示牌就是這個形狀。"""
    result = sniff(amulet_nbt.StringTag('"Queue Refight"'))

    assert result.encoding is Encoding.JSON_STRING_SCALAR
    assert result.parsed == "Queue Refight"


def test_a_json_object_is_recognised_and_parsed() -> None:
    result = sniff(amulet_nbt.StringTag('{"text":"文字","color":"red"}'))

    assert result.encoding is Encoding.JSON_STRING_OBJECT
    assert result.parsed == {"text": "文字", "color": "red"}


def test_a_json_array_is_recognised_and_parsed() -> None:
    """[實測] `100 Ways To Die` 66 筆、`Questioning` 40 筆的 `[\"\", {...}]` 形式。"""
    result = sniff(amulet_nbt.StringTag('["",{"text":"a"},{"text":"b"}]'))

    assert result.encoding is Encoding.JSON_STRING_ARRAY
    assert result.parsed == ["", {"text": "a"}, {"text": "b"}]


def test_leading_whitespace_does_not_hide_the_json_shape() -> None:
    result = sniff(amulet_nbt.StringTag('  {"text":"文字"}'))

    assert result.encoding is Encoding.JSON_STRING_OBJECT
    assert result.raw == '  {"text":"文字"}'  # 原始值不被修剪


# --- 解析失敗 -------------------------------------------------------------


def test_malformed_json_is_flagged_not_treated_as_plain_text() -> None:
    result = sniff(amulet_nbt.StringTag('{"text":'))

    assert result.problem == "unparseable_json"
    assert result.encoding is Encoding.JSON_STRING_OBJECT  # 看起來的形狀仍要記
    assert result.parsed is None


def test_a_sign_that_merely_starts_with_a_brace_is_also_flagged() -> None:
    """`{Team A}` 這種字面文字會被判成解析失敗而跳過。

    這是**刻意的保守**：規範說「絕不靜默當作裸文字翻掉」。代價是這類字面文字不會
    被翻譯，但它會進 `stats.skipped_unparseable` 並列進報告，看得見；反過來猜錯
    寫回非法 JSON 是看不見的，而且遊戲對非法 JSON 的行為未定義。
    """
    result = sniff(amulet_nbt.StringTag("{Team A}"))

    assert result.problem == "unparseable_json"


def test_text_that_only_contains_a_quote_is_not_json() -> None:
    """`他說「"」` 這種字不該被當成 JSON 純量。"""
    result = sniff(amulet_nbt.StringTag('說了一句 " 就走了'))

    assert result.encoding is Encoding.BARE_STRING
    assert result.problem is None


def test_a_line_that_merely_starts_with_a_quote_is_plain_text() -> None:
    """[實測] `100 Ways To Die` 有一行告示牌是 `"looks like you`。

    那是一句跨行的英文引述（下一行結尾才有收尾引號），不是壞掉的 JSON。前導引號
    在散文裡太常見，不足以當成「這是 JSON」的證據——**真的是 JSON 純量的話它會
    解析成功**（`'\"Queue Refight\"'` 就成功了）。

    `{` 與 `[` 開頭維持保守處理（見下一條）：散文極少那樣開頭，所以解析失敗時
    「這本來想當 JSON」仍是最合理的解釋。
    """
    result = sniff(amulet_nbt.StringTag('"looks like you'))

    assert result.encoding is Encoding.BARE_STRING
    assert result.problem is None


# --- 不是 component 的東西 -------------------------------------------------


def test_a_numeric_tag_is_refused(project) -> None:
    """數字不是文字節點。嗅探器不該對它有意見，而是明確拒絕。"""
    with pytest.raises(TypeError):
        sniff(amulet_nbt.IntTag(4671))


def test_plain_string_and_snbt_are_not_value_sniffable() -> None:
    """這兩個 encoding 由**欄位**決定，不是由值的形狀決定。

    `LevelName` 的值和一行裸字串告示牌長得一模一樣；差別在它根本不是 component
    （`plain_string`），而那只有掃描層知道自己在讀哪個欄位。
    """
    assert Encoding.PLAIN_STRING.value == "plain_string"
    assert Encoding.SNBT_STRING.value == "snbt_string"
    assert sniff(amulet_nbt.StringTag("TT_WORLD")).encoding is Encoding.BARE_STRING
