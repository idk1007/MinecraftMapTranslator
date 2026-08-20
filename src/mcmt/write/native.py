# SPDX-License-Identifier: GPL-3.0-or-later
"""新世代 chunk 的寫入（M11.1）。**高風險目錄。**

DataVersion ≥ 4325 的 chunk **不跑 DataFixerUpper**，所以 `TAG_String` 就是字面文字
——[遊戲實測 M0-3] 寫 `'{"translate":"…"}'` 進去，玩家看到的是字面的大括號。因此這
一邊**必須寫 NBT compound**。

**而那就強制了 list 提升。** `TAG_List` 在 NBT 格式層帶單一元素型別；告示牌的
`messages` 若是 `TAG_String` 的 list，把 compound 塞進去會直接 `TypeError`。唯一的做法
是**整個 list 換成 compound 的 list**，其餘三行包成 `{"text": 原字串}`。

包成 `{"text": 原字串}` 而不是解析它：native chunk 裡的 `'""'` 是**字面的兩個引號**
（[遊戲實測 M0-4]），包起來之後玩家看到的還是那兩個引號。**不「順手修好」別人地圖的
顯示瑕疵**——那超出翻譯工具的職責，而且會重新編碼一個沒被要求改的節點。

`write/legacy.py` 是另一份。**不要用一套邏輯硬套**——這是規格層級的不對稱。
"""

from dataclasses import dataclass
from typing import Any

import amulet_nbt

from mcmt.write.common import component_for

__all__ = ["ListWrite", "apply_to_list", "value_tag"]


@dataclass(frozen=True)
class ListWrite:
    list: amulet_nbt.ListTag
    promoted: bool


def value_tag(value: dict[str, Any]) -> amulet_nbt.CompoundTag:
    """把 editplan 的 value 變成一個 compound 節點。"""
    return _to_nbt(component_for(value))


def apply_to_list(
    messages: amulet_nbt.ListTag, index: int, tag: amulet_nbt.CompoundTag
) -> ListWrite:
    """把 compound 寫進 list，必要時**整個 list 提升**。"""
    if not isinstance(tag, amulet_nbt.CompoundTag):
        raise TypeError(
            f"新世代的 list 只收 CompoundTag，收到 {type(tag).__name__}——"
            f"寫錯邊了，這種節點該走 write/legacy.py"
        )

    already_compound = len(messages) > 0 and all(
        isinstance(element, amulet_nbt.CompoundTag) for element in messages
    )
    if already_compound:
        updated = amulet_nbt.ListTag(list(messages))
        while len(updated) <= index:
            updated.append(amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("")}))
        updated[index] = tag
        return ListWrite(list=updated, promoted=False)

    # 提升：其餘元素包成 {"text": 原字串}，一個字都不改。
    promoted: list[amulet_nbt.CompoundTag] = []
    for position in range(max(len(messages), index + 1)):
        if position == index:
            promoted.append(tag)
            continue
        original = messages[position] if position < len(messages) else None
        promoted.append(_wrap(original))
    return ListWrite(list=amulet_nbt.ListTag(promoted), promoted=True)


def _wrap(element: Any) -> amulet_nbt.CompoundTag:
    if isinstance(element, amulet_nbt.CompoundTag):
        return element
    text = str(element) if isinstance(element, amulet_nbt.StringTag) else ""
    return amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(text)})


def _to_nbt(value: Any) -> Any:
    """純 Python component → NBT。"""
    if isinstance(value, dict):
        return amulet_nbt.CompoundTag(
            {str(key): _to_nbt(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return amulet_nbt.ListTag([_to_nbt(item) for item in value])
    if isinstance(value, bool):
        return amulet_nbt.ByteTag(1 if value else 0)
    if isinstance(value, int):
        return amulet_nbt.IntTag(value)
    return amulet_nbt.StringTag(str(value))
