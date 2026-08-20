# SPDX-License-Identifier: GPL-3.0-or-later
"""舊世代 chunk 的寫入（M11.1）。**高風險目錄。**

DataVersion < 4325 的 chunk 會被 DataFixerUpper 處理，所以文字節點寫成**JSON 字串**
——[遊戲實測 M4-1] 在 DV 3700 的 chunk 裡寫 `'{"translate":"mcmt.test.legacy"}'`，
1.21.11 由資源包解出並正確顯示。

**因此這裡不需要 list 提升。** 原本的 list 是 `TAG_String`，我們寫進去的也是
`TAG_String`，型別沒變、其餘元素一個位元都不動。這就是 `legacy.py` 與 `native.py`
必須是兩份實作的原因：native 那邊非提升不可，這邊完全不必。

`write/native.py` 是另一份。**不要用一套邏輯硬套**——這是規格層級的不對稱。
"""

import json
from dataclasses import dataclass
from typing import Any

import amulet_nbt

from mcmt.errors import PlaceholderResidueError
from mcmt.write.common import component_for, refuse_residue

__all__ = ["ListWrite", "apply_to_list", "value_tag"]


@dataclass(frozen=True)
class ListWrite:
    list: amulet_nbt.ListTag
    promoted: bool


def value_tag(value: dict[str, Any]) -> amulet_nbt.StringTag:
    """把 editplan 的 value 變成一個 JSON 字串節點。"""
    component = component_for(value)
    # compact 形式：[實測] 真實地圖的舊式 JSON 就長這樣，78/78 位元組一致。
    return amulet_nbt.StringTag(
        json.dumps(component, ensure_ascii=False, separators=(",", ":"))
    )


def apply_to_list(
    messages: amulet_nbt.ListTag, index: int, tag: amulet_nbt.StringTag
) -> ListWrite:
    """單點替換。其餘元素原封不動——**型別沒變，所以不必碰它們**。"""
    if not isinstance(tag, amulet_nbt.StringTag):
        raise TypeError(
            f"舊世代的 list 只收 StringTag，收到 {type(tag).__name__}——"
            f"寫錯邊了，這種節點該走 write/native.py"
        )
    updated = amulet_nbt.ListTag(list(messages)) if len(messages) else amulet_nbt.ListTag()
    while len(updated) <= index:
        updated.append(amulet_nbt.StringTag('""'))
    updated[index] = tag
    return ListWrite(list=updated, promoted=False)
