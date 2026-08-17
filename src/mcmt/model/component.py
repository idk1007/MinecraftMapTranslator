# SPDX-License-Identifier: GPL-3.0-or-later
"""節點形狀的嗅探（M5.1）——`occurrence.encoding` 的**唯一權威**。

形狀由**逐節點嗅探實際值**決定，**不是**由 `container.data_version` 推導。
[實測] DataVersion 4556 的 chunk 裡有 2,340 個舊式 JSON 空字串與 110 個舊式 JSON
物件，所以 DataVersion 預測不了節點形狀（CLAUDE.md §二）。

十種 `encoding` 裡有八種由值的形狀決定，這個模組負責那八種：

    bare_string          裸字串（純文字 component 被折疊）
    empty_key_compound   {"": "文字"}   ← [遊戲實測 M4-2] Mojang NbtOps 的標準輸出
    text_compound        {"text": "文字"}
    compound_tree        帶結構的 compound 或 list（extra / translate / 樣式…）
    json_string_object   '{"text":"文字",…}'
    json_string_array    '["", {...}, {...}]'
    json_string_scalar   '"文字"'
    json_empty_quoted    '""'  ← 2 個字元，與 0 字元的空字串是兩件事

另外兩種**由欄位決定，不是由值決定**，所以不在這裡判斷：

    plain_string   這個欄位根本不是 component（LevelName / title.raw / author /
                   草稿書 pages[].raw）。它的值和一行裸字串告示牌長得一模一樣。
    snbt_string    值是一份 SNBT 文件（指令方塊裡的 NBT 之類）。

**JSON 解析失敗不是裸文字。** 標成 `problem="unparseable_json"`，由呼叫端跳過該
節點並計入 `stats.skipped_unparseable`。翻了會寫回非法 JSON，而遊戲對非法 JSON 的
行為未定義。這條保守做法的代價是像 `{Team A}` 這種字面文字也會被跳過——但那會
出現在報告裡，看得見；猜錯寫回非法 JSON 是看不見的。
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

import amulet_nbt

__all__ = ["Encoding", "Sniffed", "sniff"]


class Encoding(str, Enum):
    """`occurrence.encoding` 的十個值。**與 `extract.schema.json` 的 enum 綁死**
    （`tests/unit/test_component.py` 有一條測試比對兩者，不允許漂移）。"""

    BARE_STRING = "bare_string"
    EMPTY_KEY_COMPOUND = "empty_key_compound"
    TEXT_COMPOUND = "text_compound"
    COMPOUND_TREE = "compound_tree"
    JSON_STRING_OBJECT = "json_string_object"
    JSON_STRING_ARRAY = "json_string_array"
    JSON_STRING_SCALAR = "json_string_scalar"
    JSON_EMPTY_QUOTED = "json_empty_quoted"
    PLAIN_STRING = "plain_string"
    SNBT_STRING = "snbt_string"


@dataclass(frozen=True)
class Sniffed:
    """一次嗅探的結果。

    `encoding` 是**看起來的形狀**，即使解析失敗也照樣填——磁碟上那個節點確實長
    那個樣子，報告裡要講得出是哪一種壞掉。
    """

    encoding: Encoding
    raw: str | None = None
    parsed: Any = None
    problem: str | None = None


_EMPTY_QUOTED = '""'
_JSON_OPENERS = {
    "{": Encoding.JSON_STRING_OBJECT,
    "[": Encoding.JSON_STRING_ARRAY,
    '"': Encoding.JSON_STRING_SCALAR,
}


def sniff(tag: amulet_nbt.AbstractBaseTag) -> Sniffed:
    """判斷一個節點的儲存形狀。"""
    if isinstance(tag, amulet_nbt.StringTag):
        return _sniff_string(str(tag))
    if isinstance(tag, amulet_nbt.CompoundTag):
        return Sniffed(encoding=_sniff_compound(tag))
    if isinstance(tag, amulet_nbt.ListTag):
        # 原生 list 形式的 component（`["", {...}]` 的 NBT 版）也是一棵樹。
        return Sniffed(encoding=Encoding.COMPOUND_TREE)
    raise TypeError(
        f"{type(tag).__name__} 不是文字節點——嗅探器只處理 String / Compound / List"
    )


def _sniff_string(raw: str) -> Sniffed:
    if raw == _EMPTY_QUOTED:
        # 先於 json_string_scalar 判斷：'""' 是它自己的一類，因為它在 native
        # chunk 裡是「顯示成兩個引號的壞掉節點」而不是空白（[遊戲實測 M0-4/M4-3]）。
        return Sniffed(encoding=Encoding.JSON_EMPTY_QUOTED, raw=raw, parsed="")

    stripped = raw.lstrip()
    looks_like = _JSON_OPENERS.get(stripped[:1])
    if looks_like is None:
        return Sniffed(encoding=Encoding.BARE_STRING, raw=raw, parsed=raw)

    try:
        parsed = json.loads(stripped)
    except ValueError:
        if looks_like is Encoding.JSON_STRING_SCALAR:
            # 前導引號不足以當成「這是 JSON」的證據：散文常常這樣開頭。
            # [實測] `100 Ways To Die` 有一行告示牌是 `"looks like you`——一句跨行
            # 的英文引述，收尾引號在下一行。真的是 JSON 純量的話它會解析成功。
            return Sniffed(encoding=Encoding.BARE_STRING, raw=raw, parsed=raw)
        # `{` 與 `[` 開頭維持保守：散文極少那樣開頭，解析失敗時「這本來想當 JSON」
        # 仍是最合理的解釋，而猜錯的代價是寫回非法 JSON。
        return Sniffed(encoding=looks_like, raw=raw, problem="unparseable_json")

    # `json.loads` 對 '"x"' 回傳 str、對 '{…}' 回傳 dict——形狀要以解析結果為準，
    # 不能只看開頭字元（`'"a" '` 之類的邊緣情況）。
    actual = {
        str: Encoding.JSON_STRING_SCALAR,
        dict: Encoding.JSON_STRING_OBJECT,
        list: Encoding.JSON_STRING_ARRAY,
    }.get(type(parsed))
    if actual is None:
        return Sniffed(encoding=looks_like, raw=raw, problem="unparseable_json")
    return Sniffed(encoding=actual, raw=raw, parsed=parsed)


def _sniff_compound(tag: amulet_nbt.CompoundTag) -> Encoding:
    keys = set(map(str, tag.keys()))
    if keys == {""}:
        return Encoding.EMPTY_KEY_COMPOUND
    if keys == {"text"}:
        return Encoding.TEXT_COMPOUND
    # 多一個鍵就是有結構：`{"text":"","extra":[…]}` 是壓掉物品名預設斜體的慣用法，
    # 重建時漏掉那個 `italic:false` 物品名會變回斜體。
    return Encoding.COMPOUND_TREE
