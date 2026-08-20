# SPDX-License-Identifier: GPL-3.0-or-later
"""資源包的 lang 檔。**讀寬容、寫嚴格。**

[實測] MP2 的 5 個語言檔**全部**無法通過 `json.loads`。既有 pack 讀不進來就沒辦法
合併，所以讀取端要容忍；但我們**輸出**的一律是嚴格 JSON：無註解、無尾逗號、
UTF-8 無 BOM、`ensure_ascii=False`、鍵排序（diff 穩定）。

**為什麼是掃描器而不是正則。** 初版用正則去掉 `//` 註解與尾逗號，在真實檔案上
0/5 通過，三個破口都是正則做不到的：

* `"mcp.Ztar": "Ztar", //An "anti star"` —— **註解裡有雙引號**，吃到第一個引號就
  停的正則會留下半截。
* `// 1: "ClashAssassin", 2: "Loominardy"` —— 註解裡有冒號、逗號與引號。
* `zh_cn.json` 以 **UTF-8 BOM** 開頭。

而「去掉尾逗號」用正則也會誤傷字串內容裡的逗號（`"你好, 世界"`）。要正確就得知道
「現在在不在字串裡」，那就是掃描器。
"""

import json
from typing import Any

from mcmt.errors import CodecError

NAME = "lang_json"
faithful_round_trip = False  # 寬容讀進來的東西寫出去一定不一樣（註解沒了）


def decode(text: str) -> Any:
    try:
        return json.loads(_clean(text.lstrip("\ufeff")))
    except ValueError as exc:
        raise CodecError(codec=NAME, detail=str(exc)) from exc


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _clean(text: str) -> str:
    """去掉註解與尾逗號，**字串內容一個字都不動**。"""
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False

    while index < length:
        char = text[index]

        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length:
            following = text[index + 1]
            if following == "/":
                newline = text.find("\n", index)
                index = length if newline == -1 else newline
                continue
            if following == "*":
                end = text.find("*/", index + 2)
                index = length if end == -1 else end + 2
                continue

        if char in "}]":
            _drop_trailing_comma(out)

        out.append(char)
        index += 1

    return "".join(out)


def _drop_trailing_comma(out: list[str]) -> None:
    """往回看，跳過空白，把緊鄰結尾括號的那個逗號拿掉。"""
    position = len(out) - 1
    while position >= 0 and out[position].isspace():
        position -= 1
    if position >= 0 and out[position] == ",":
        del out[position]
