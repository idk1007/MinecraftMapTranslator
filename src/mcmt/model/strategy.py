# SPDX-License-Identifier: GPL-3.0-or-later
"""`unit.strategy` 的唯一權威——由 **category** 決定，不是由 encoding 決定。

大部分文字走 `translate_key`：節點換成 `{translate: key}`，譯文住在資源包的 lang
檔裡。那是這個工具的主路徑，也是唯一能讓一份存檔同時支援多語言的路徑。

但有些欄位**不吃 translate key**——把 key 放進去，玩家看到的是 key 本身或字面文字：

| category | 證據 |
|---|---|
| `level_name` | 世界清單顯示的是原始 key |
| `book_title` / `book_author` | 同上，書名 `title.raw` 顯示原始 key |
| `draft_book_page` | 草稿書頁不是 component |
| `block_entity_name` | [遊戲實測 M11-3] native chunk 的 `CustomName` 寫入 SNBT 的 `{translate:…}`，容器 GUI 顯示**字面的大括號**——與告示牌 `messages[]` 在 M0-3 的行為完全一致 |

這幾個只能走 `in_place`：**把譯文直接寫進節點**，而且**保留節點既有的 NBT 形狀**。
不把 `TAG_String` 提升成 compound——那個提升對 `CustomName` 從未實測過，而未測過的
寫入路徑比拒絕處理危險（CLAUDE.md 一之四的同一條理由）。

`block_entity_name` 為什麼由 category 而不是 encoding 決定，有一個容易誤判的地方：
它嗅探出來是 `bare_string`，而告示牌的某一行也可能是 `bare_string`。同一個形狀、
兩種結論——差別在**欄位**，不在**值**。告示牌那邊整個 list 可以提升成 compound
（[遊戲實測 M11-1] 已經跑過），`CustomName` 那邊沒有這條退路。

**預設是 `translate_key`。** M13 補掃描廣度時會冒出新的 category；要例外得明確加進
下面的集合，而那個集合與合約的 `if/then` 由 `tests/unit/test_strategy.py` 綁死。
"""

__all__ = ["IN_PLACE_CATEGORIES", "strategy_for"]

IN_PLACE_CATEGORIES = frozenset(
    {
        "level_name",
        "book_title",
        "book_author",
        "draft_book_page",
        "block_entity_name",
    }
)


def strategy_for(category: str) -> str:
    """這個 category 的譯文該用什麼方式寫回去。"""
    return "in_place" if category in IN_PLACE_CATEGORIES else "translate_key"
