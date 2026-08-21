# SPDX-License-Identifier: GPL-3.0-or-later
"""物品裡的文字（M13.3）——**跨來源的共用元件**。

物品同時出現在三個地方：方塊實體的 `Items[]`、實體的
`ArmorItems[]`/`equipment`/`item`/`weapon`、`level.dat` 的 `Player.Inventory[]`。
三邊各寫一份遞迴是最該避免的事——[實測] 三層巢狀真的存在（`Arena of Darkness` 的
`Items[] → BlockEntityTag/Items[] → tag/display/Name`），而漏掉一層的症狀是「有些
物品名沒被抽出來」，沒有例外也沒有紅字。

## 兩套格式，由物品自己說了算

1.20.5（DV 3837）把物品的 NBT 從 `tag` 換成 `components`。**分水嶺與 chunk 結構的
4325 不是同一條線**，而且我們不看 DataVersion——看物品身上有 `components` 還是
`tag`（CLAUDE.md 二節：形狀一律逐節點嗅探）。

[實測] 真實語料各佔一套：`Arena of Darkness`（1.20.4）全是 `tag`，
`100 Ways To Die`（1.21.5）全是 `components`。

## 嚴格白名單

只抽下面列的欄位，**其餘一律忽略，也不遞迴進去**。不是「走遍物品的樹再靠 denylist
擋」——物品底下的機制標籤多到列不完。白名單的代價是「新版本加了新的文字組件我們不
會自動抽到」，那個代價是對的方向：**漏抽看得見**（節點數對不上清點），**誤翻看不見**
（地圖壞掉時已經來不及）。
"""

from typing import Any, Iterator

import amulet_nbt

from mcmt.model.node import NodePath, index_step, key_step
from mcmt.scan.node import TextNode

__all__ = ["scan_item"]

# 組件名 → category。**這份表就是白名單。**
_NAME_COMPONENTS = {
    "minecraft:custom_name": "custom_name",
    "minecraft:item_name": "item_name",
}

_LORE_COMPONENT = "minecraft:lore"
_WRITTEN_BOOK = "minecraft:written_book_content"
_WRITABLE_BOOK = "minecraft:writable_book_content"

# 遞迴進去的容器組件 → 元素裡哪個鍵是物品（None 代表元素本身就是物品）。
_CONTAINER_COMPONENTS = {
    "minecraft:container": "item",
    "minecraft:bundle_contents": None,
    "minecraft:charged_projectiles": None,
}


def scan_item(
    item: amulet_nbt.CompoundTag, path: NodePath, *, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    """一個物品裡所有可翻譯的文字節點。自己遞迴進容器。"""
    if not isinstance(item, amulet_nbt.CompoundTag):
        return
    components = item.get("components")
    if isinstance(components, amulet_nbt.CompoundTag):
        yield from _scan_components(components, path.child(key_step("components")), anchor)


def _scan_components(
    components: amulet_nbt.CompoundTag, path: NodePath, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    for name, category in _NAME_COMPONENTS.items():
        value = components.get(name)
        if value is not None:
            yield TextNode(
                path=path.child(key_step(name)),
                tag=value,
                category=category,
                anchor=anchor,
            )

    lore = components.get(_LORE_COMPONENT)
    if isinstance(lore, amulet_nbt.ListTag):
        lore_path = path.child(key_step(_LORE_COMPONENT))
        for index, line in enumerate(lore):
            yield TextNode(
                path=lore_path.child(index_step(index)),
                tag=line,
                category="lore",
                anchor=anchor,
            )

    book = components.get(_WRITTEN_BOOK)
    if isinstance(book, amulet_nbt.CompoundTag):
        yield from _scan_written_book(book, path.child(key_step(_WRITTEN_BOOK)), anchor)

    draft = components.get(_WRITABLE_BOOK)
    if isinstance(draft, amulet_nbt.CompoundTag):
        yield from _scan_pages(
            draft, path.child(key_step(_WRITABLE_BOOK)), anchor, "draft_book_page"
        )

    for name, item_key in _CONTAINER_COMPONENTS.items():
        contents = components.get(name)
        if not isinstance(contents, amulet_nbt.ListTag):
            continue
        contents_path = path.child(key_step(name))
        for index, entry in enumerate(contents):
            entry_path = contents_path.child(index_step(index))
            if item_key is None:
                yield from scan_item(entry, entry_path, anchor=anchor)
            elif isinstance(entry, amulet_nbt.CompoundTag):
                inner = entry.get(item_key)
                if inner is not None:
                    yield from scan_item(
                        inner, entry_path.child(key_step(item_key)), anchor=anchor
                    )


def _scan_written_book(
    book: amulet_nbt.CompoundTag, path: NodePath, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    """成書。**`title.raw` 與 `author` 只吃字串，`pages[].raw` 吃完整 component。**

    [遊戲實測] 同一本書的 `pages[].raw` 底下存 `{translate: …}` 會正常翻譯，
    `title.raw` 底下卻直接顯示原始 key。所以 category 必須分開——那個不對稱是
    `strategy` 的依據。
    """
    title = book.get("title")
    if isinstance(title, amulet_nbt.CompoundTag) and "raw" in title:
        yield TextNode(
            path=path.child(key_step("title")).child(key_step("raw")),
            tag=title["raw"],
            category="book_title",
            anchor=anchor,
        )

    author = book.get("author")
    if author is not None:
        yield TextNode(
            path=path.child(key_step("author")),
            tag=author,
            category="book_author",
            anchor=anchor,
        )

    yield from _scan_pages(book, path, anchor, "book_page")


def _scan_pages(
    book: amulet_nbt.CompoundTag,
    path: NodePath,
    anchor: dict[str, Any] | None,
    category: str,
) -> Iterator[TextNode]:
    pages = book.get("pages")
    if not isinstance(pages, amulet_nbt.ListTag):
        return
    pages_path = path.child(key_step("pages"))
    for index, page in enumerate(pages):
        page_path = pages_path.child(index_step(index))
        if isinstance(page, amulet_nbt.CompoundTag) and "raw" in page:
            yield TextNode(
                path=page_path.child(key_step("raw")),
                tag=page["raw"],
                category=category,
                anchor=anchor,
            )
