# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串。**尚未實作，明確拒絕。**

指令字串裡哪一段是可翻譯的文字，需要指令語法解析——架構計畫把它列為「工作量最難
估」的一項，datapack `.mcfunction` 也因此移出 v1。

掃描層目前根本不去找 `Command` 欄位，所以這個 codec 沒有呼叫端。留一個「猜著做」
的實作，等於等著某天有人用它寫壞別人的指令方塊——[實測] MP2 有 692 個指令方塊，
而且三層巢狀（指令含 NBT、NBT 含 component）確實存在。

理由與 `.mcc`、1.12 舊結構相同：**未測過的寫入路徑比拒絕處理危險得多。**
"""

from typing import Any

NAME = "command"
faithful_round_trip = False

_MESSAGE = (
    "指令 codec 尚未實作。指令裡哪一段是可翻譯的文字需要語法解析，"
    "掃描廣度（M13）處理到指令方塊時才會做。"
)


def decode(text: str) -> Any:
    raise NotImplementedError(_MESSAGE)


def encode(value: Any) -> str:
    raise NotImplementedError(_MESSAGE)
