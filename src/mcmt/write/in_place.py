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

## 舊世代的形狀不是「順便支援」，是必要的

DV < 4325 的 chunk 裡 DataFixerUpper 會解析這個欄位，所以那裡的問題不是「它解不解析」
而是「它接受哪一種」。[遊戲實測 2026-08-21] 在 DV 3700 的 `CustomName` 上：

    '"譯文"'                  JSON 純量    → 正確顯示譯文
    '{"translate":"…"}'       JSON 物件    → 正確解出資源包的譯文
    '譯文'                    非 JSON 裸字串 → **顯示原版預設名，欄位整個被丟掉**

第三個是反面證據，而且比前兩個重要：**在舊世代換掉節點的形狀會悄無聲息地弄丟名字。**
所以「保留既有形狀」在這裡不是保守的選擇，是唯一不會壞事的選擇。

**沒有列在下面的 encoding 一律拒絕。** 猜一個形狀寫下去，錯了就是別人的地圖壞了。
"""

import json
from typing import Any

import amulet_nbt

from mcmt.model.strategy import IN_PLACE_ENCODINGS
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


def _json_scalar(text: str) -> amulet_nbt.StringTag:
    return amulet_nbt.StringTag(json.dumps(text, ensure_ascii=False))


def _json_object(text: str) -> amulet_nbt.StringTag:
    # compact 形式：[實測] 真實資料 78/78 的 JSON component 都是 compact，
    # 加空格會讓一個只改了文字的節點看起來整個被重寫過。
    return amulet_nbt.StringTag(
        json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":"))
    )


_SHAPES = {
    # 裸字串。[遊戲實測 M0-3 / M11-3] native chunk 的 TAG_String 就是字面文字。
    "bare_string": _bare,
    # 這個欄位根本不是 component（LevelName / 書名 / 作者 / 草稿書頁）。
    "plain_string": _bare,
    # 官方文件記載的形狀。
    "text_compound": _text_compound,
    # [遊戲實測 M4-2] Mojang NbtOps 存回磁碟時自己產生的形狀。
    "empty_key_compound": _empty_key_compound,
    # --- 以下兩種只會出現在 DV < 4325 的 chunk，那裡 DataFixerUpper 會解析欄位。
    # [遊戲實測 2026-08-21] 兩種都在 DV 3700 的 CustomName 上寫過並看過結果。
    "json_string_scalar": _json_scalar,
    "json_string_object": _json_object,
}

SUPPORTED_ENCODINGS = frozenset(_SHAPES)


# **這裡與 `model/strategy.py` 不能漂移。** 那邊是「哪些形狀有實測依據」的宣告，
# extract 用它決定要不要排除；這邊是那些形狀的實作。少一邊就會出現「extract 說可以
# 寫、寫入層卻拒絕」或更糟的反向。
assert SUPPORTED_ENCODINGS == IN_PLACE_ENCODINGS, (
    f"寫入層與 model 的 in_place 形狀清單對不上："
    f"{SUPPORTED_ENCODINGS ^ IN_PLACE_ENCODINGS}"
)


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
