# SPDX-License-Identifier: GPL-3.0-or-later
"""M5.7 codec（`tree/codecs/`）。

`node_path` 的 `decode` 步驟說「這裡以下是另一份文件」；codec 就是那份文件的
讀寫器。寫入層由內往外逐層重新編碼，所以每個 codec 都必須誠實回答一件事：
**重新編碼之後，還是同一串位元組嗎？**

不是的話，寫入層就不能整份重編（那會改到沒被要求改的地方），只能用 span 做
位移替換——而位移替換又要求同一父字串的編輯由後往前。
"""

import amulet_nbt
import pytest

from mcmt.errors import CodecError
from mcmt.model.node import Codec
from mcmt.tree.codecs import codec_for, registry


# --- 與合約綁死 -----------------------------------------------------------


def test_every_codec_in_the_contract_has_an_implementation() -> None:
    """enum 裡有、registry 裡沒有 = 執行到一半才發現不支援。"""
    assert set(registry()) == set(Codec)


# --- json_component -------------------------------------------------------


def test_json_round_trips_byte_for_byte() -> None:
    """[實測] 真實地圖的 78 個舊式 JSON 節點，compact 形式 78/78 位元組一致。"""
    raw = '{"text":"文字","color":"red"}'
    codec = codec_for(Codec.JSON_COMPONENT)

    assert codec.encode(codec.decode(raw)) == raw


def test_json_encodes_compactly_because_that_is_what_mojang_writes() -> None:
    """[實測] 帶空格的 `json.dumps` 預設形式在真實資料上 0/78 一致。"""
    codec = codec_for(Codec.JSON_COMPONENT)

    assert codec.encode({"text": "x", "bold": True}) == '{"text":"x","bold":true}'


def test_json_keeps_chinese_literal() -> None:
    """`ensure_ascii=True` 會把中文轉義成跳脫序列，那不是 Mojang 寫出來的樣子。"""
    assert codec_for(Codec.JSON_COMPONENT).encode({"text": "中文"}) == '{"text":"中文"}'


def test_json_preserves_key_order() -> None:
    """鍵序變了就是改到沒被要求改的地方。"""
    raw = '{"color":"red","text":"x","bold":true}'
    codec = codec_for(Codec.JSON_COMPONENT)

    assert codec.encode(codec.decode(raw)) == raw


def test_json_reports_its_round_trip_as_faithful() -> None:
    assert codec_for(Codec.JSON_COMPONENT).faithful_round_trip is True


def test_broken_json_raises_a_codec_error() -> None:
    with pytest.raises(CodecError) as exc:
        codec_for(Codec.JSON_COMPONENT).decode('{"text":')

    assert "json_component" in str(exc.value)


# --- snbt -----------------------------------------------------------------


def test_snbt_decodes_to_nbt() -> None:
    value = codec_for(Codec.SNBT).decode('{text:"hi",count:3b}')

    assert isinstance(value, amulet_nbt.CompoundTag)
    assert str(value["text"]) == "hi"


def test_snbt_round_trip_is_not_faithful() -> None:
    """**amulet-nbt 的 `to_snbt()` 會把鍵排序。**

    輸入 `{text,count,items}` 出來是 `{count,items,text}`。所以 SNBT 文件不能整份
    重編——那會改到一堆沒被要求改的地方。寫入層必須改用 span 做位移替換，而那正是
    `decode.span` 與「同一父字串的編輯由後往前」存在的理由。
    """
    codec = codec_for(Codec.SNBT)
    raw = '{text:"hi",count:3b,items:[1,2]}'

    assert codec.encode(codec.decode(raw)) != raw
    assert codec.faithful_round_trip is False


def test_broken_snbt_raises_a_codec_error() -> None:
    with pytest.raises(CodecError):
        codec_for(Codec.SNBT).decode("{text:")


# --- command --------------------------------------------------------------


def test_the_command_codec_is_a_transparent_marker_layer() -> None:
    """指令 codec 是標記層：真正的解析在掃描層（extract）與寫入層（apply）。

    codec 本身只需要讓 `codec_for("command")` 不再 raise NotImplementedError，
    以滿足合約允許「command」這個 codec 值的事實。decode/encode 都是 identity。
    """
    codec = codec_for(Codec.COMMAND)
    assert codec.decode("say hi") == "say hi"
    assert codec.encode("say hello") == "say hello"


def test_lang_json_round_trips_tolerantly() -> None:
    """[實測] MP2 的 5 個語言檔**全部**無法通過 `json.loads`——有註解與尾逗號。

    讀取要寬容、輸出要嚴格（CLAUDE.md 二節）。
    """
    codec = codec_for(Codec.LANG_JSON)

    value = codec.decode('{\n  // 註解\n  "a.b": "文字",\n}')

    assert value == {"a.b": "文字"}
    assert codec.encode(value) == '{\n  "a.b": "文字"\n}'


# --- lang_json 的寬容度（真實 lang 檔逼出來的）----------------------------


def test_a_comment_containing_quotes_is_stripped() -> None:
    """[實測] MP2 的 en_us.json 有 `"mcp.Ztar": "Ztar", //An "anti star"`。

    註解裡有雙引號。用「吃到第一個引號為止」的正則會留下半截，整份檔案就解析不了。
    """
    raw = """{
  "mcp.Cooldown": "Cooldown",
  "mcp.Ztar": "Ztar", //An "anti star"
  "mcp.Gold": "Gold"
}"""

    value = codec_for(Codec.LANG_JSON).decode(raw)

    assert value == {
        "mcp.Cooldown": "Cooldown",
        "mcp.Ztar": "Ztar",
        "mcp.Gold": "Gold",
    }


def test_a_comment_with_colons_and_quotes_is_stripped() -> None:
    """[實測] ru_ru.json：`// 1: "ClashAssassin", 2: "Loominardy"`。"""
    value = codec_for(Codec.LANG_JSON).decode(
        '{"mcp.hub_tick.2": "От %1$s и %2$s" // 1: "A", 2: "B"\n}'
    )

    assert value == {"mcp.hub_tick.2": "От %1$s и %2$s"}


def test_a_double_slash_inside_a_string_is_not_a_comment() -> None:
    """網址不是註解。"""
    value = codec_for(Codec.LANG_JSON).decode('{"a": "https://example.com/x"}')

    assert value == {"a": "https://example.com/x"}


def test_a_byte_order_mark_is_tolerated() -> None:
    """[實測] MP2 的 zh_cn.json 以 EF BB BF 開頭。"""
    value = codec_for(Codec.LANG_JSON).decode('\ufeff{"a": "b"}')

    assert value == {"a": "b"}


def test_trailing_commas_are_tolerated() -> None:
    value = codec_for(Codec.LANG_JSON).decode('{"a": "b", "c": ["d", "e",],}')

    assert value == {"a": "b", "c": ["d", "e"]}


def test_a_comma_inside_a_string_is_left_alone() -> None:
    """去尾逗號不能去到字串內容裡的逗號。"""
    value = codec_for(Codec.LANG_JSON).decode('{"a": "你好, 世界"}')

    assert value == {"a": "你好, 世界"}


def test_a_block_comment_is_stripped() -> None:
    value = codec_for(Codec.LANG_JSON).decode('{/* 說明 */ "a": "b"}')

    assert value == {"a": "b"}


def test_an_escaped_quote_does_not_end_the_string() -> None:
    value = codec_for(Codec.LANG_JSON).decode('{"a": "他說 \\"哈囉\\" 就走了"}')

    assert value == {"a": '他說 "哈囉" 就走了'}


def test_output_is_strict_json_with_sorted_keys() -> None:
    """輸出一律嚴格：無註解、無尾逗號、鍵排序（diff 穩定）。"""
    out = codec_for(Codec.LANG_JSON).encode({"b.key": "乙", "a.key": "甲"})

    assert out == '{\n  "a.key": "甲",\n  "b.key": "乙"\n}'
    assert "//" not in out
