# SPDX-License-Identifier: GPL-3.0-or-later
"""`in_place` 寫入：譯文直接進節點（M11.4）。**高風險目錄。**

有些欄位**不吃 translate key**——放進去，玩家看到的是 key 本身或字面文字。
[遊戲實測 M11-3] `CustomName` 是其中之一：在 native chunk 寫進 SNBT 的
`{translate:…}`，容器 GUI 顯示的是字面的大括號，行為與告示牌 `messages[]` 在
M0-3 完全一致。那類欄位只能把譯文直接寫進節點。

## 這一份為什麼不是第三份 legacy/native 實作

`legacy.py` 與 `native.py` 的不對稱是**世代**的：DV < 4325 寫 JSON 字串、
DV ≥ 4325 寫 NBT compound，因為遊戲會不會跑 DataFixerUpper 是世代決定的。

`in_place` 完全不做那個判斷，因為它**什麼形狀都不選**——它保留節點原本的形狀，
只換裡面的字。所以分派的依據是 `encoding` 而不是 `data_version`，這是第三種操作，
不是把那兩份合起來。

## 保留形狀，兩條理由

1. **不把 `TAG_String` 提升成 compound。** 告示牌那邊整個 list 提升過（M11-1 實測
   過），`CustomName` 沒有那條退路——把單一 String 換成 Compound 會改掉欄位的 NBT
   型別，而那個提升從沒進過遊戲。未測過的寫入路徑比拒絕處理危險。
2. **兩種 compound 形式互不正規化。** 路過的 `{"": …}` 順手改成 `{"text": …}` 就是
   重新編碼一個沒被要求改的欄位（CLAUDE.md 二節）。`{"": …}` 是 Mojang `NbtOps`
   自己的輸出形狀（[遊戲實測 M4-2]），不是某個工具的怪癖。

樣式不另外掛在節點上：`in_place` 的多段樣式在後端就已經轉成行內 § 碼了（`lang.py`
的 `inline_text`），這裡收到的就是最終要顯示的那串字。所以 compound 只留文字那一個
鍵——原本的 `color` 之類已經在那串字裡了，留著會疊第二次。

**沒有列在下面的 encoding 一律拒絕。** 猜一個形狀寫下去，錯了就是別人的地圖壞了。
"""

from typing import Any

import amulet_nbt

from mcmt.write.common import refuse_residue

__all__ = ["SUPPORTED_ENCODINGS", "UnsupportedInPlaceShape", "value_tag"]


class UnsupportedInPlaceShape(Exception):
    """這個節點的形狀（或這個寫入值）沒有實測依據可以照著寫。"""


def _bare(text: str) -> amulet_nbt.StringTag:
    return amulet_nbt.StringTag(text)


def _text_compound(text: str) -> amulet_nbt.CompoundTag:
    return amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(text)})


def _empty_key_compound(text: str) -> amulet_nbt.CompoundTag:
    return amulet_nbt.CompoundTag({"": amulet_nbt.StringTag(text)})


_SHAPES = {
    # 裸字串。[遊戲實測 M0-3 / M11-3] native chunk 的 TAG_String 就是字面文字。
    "bare_string": _bare,
    # 這個欄位根本不是 component（LevelName / 書名 / 作者 / 草稿書頁）。
    "plain_string": _bare,
    # 官方文件記載的形狀。
    "text_compound": _text_compound,
    # [遊戲實測 M4-2] Mojang NbtOps 存回磁碟時自己產生的形狀。
    "empty_key_compound": _empty_key_compound,
}

SUPPORTED_ENCODINGS = frozenset(_SHAPES)


def value_tag(encoding: str, value: dict[str, Any]) -> amulet_nbt.AbstractBaseTag:
    """editplan 的 value → 一個保留原形狀的 NBT 節點。

    `encoding` 是**節點現在的形狀**（呼叫端剛剛嗅探過、也剛剛過完 `expected_encoding`
    守門），不是我們想要的形狀。
    """
    kind = value.get("kind")
    if kind != "literal":
        # translate key 放進這種欄位，玩家看到的是 key 本身（[遊戲實測 M11-3]）。
        # 後端不會產生這種計畫，但寫入層不靠上游的自律。
        raise UnsupportedInPlaceShape(
            f"in_place 的節點只收 literal，收到 {kind!r}"
            f"——這個欄位不吃 translate key"
        )

    text = value["text"]
    # 殘留 [[n]] 是**拒絕整份 plan**，不是跳過這一筆（CLAUDE.md 三節）。
    refuse_residue(text)

    shape = _SHAPES.get(encoding)
    if shape is None:
        raise UnsupportedInPlaceShape(
            f"沒有 {encoding!r} 形狀的實測依據，拒寫。"
            f"目前有依據的是：{'、'.join(sorted(SUPPORTED_ENCODINGS))}"
        )
    return shape(text)
