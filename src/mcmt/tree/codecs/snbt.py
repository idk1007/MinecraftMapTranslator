# SPDX-License-Identifier: GPL-3.0-or-later
"""SNBT 文件（指令方塊的 NBT 引數之類）。

**這個 codec 的往返不忠實。** `amulet_nbt.to_snbt()` 會把 compound 的鍵**排序**：

    輸入 {text:"hi",count:3b,items:[1,2]}
    輸出 {count: 3b, items: [1, 2], text: "hi"}

所以 SNBT 文件**不能整份重編**——那會改到一堆沒被要求改的地方，違反「除了要改的
地方以外什麼都沒動」。寫入層必須改用 `decode.span` 做位移替換，而位移替換要求同一
父字串的編輯由後往前（`model/node.span_order`）。

這件事寫在這裡而不是留給呼叫端發現，是因為它看起來能用——`decode` 與 `encode` 都
不會報錯，只是安靜地改掉別的東西。
"""

from typing import Any

import amulet_nbt

from mcmt.errors import CodecError

NAME = "snbt"
faithful_round_trip = False


def decode(text: str) -> Any:
    try:
        return amulet_nbt.from_snbt(text)
    except Exception as exc:  # amulet-nbt 的 SNBTParseError 之外還有別的
        raise CodecError(codec=NAME, detail=str(exc)) from exc


def encode(value: Any) -> str:
    return value.to_snbt()
