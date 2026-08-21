# SPDX-License-Identifier: GPL-3.0-or-later
"""物品掃描（M13.3）——**跨來源的共用元件**。

物品同時出現在方塊實體的 `Items[]`、實體的 `ArmorItems[]`/`equipment`/`item`、
以及 `level.dat` 的 `Player.Inventory[]`。三邊各寫一份遞迴是最該避免的事：
[實測] 三層巢狀真的存在（Arena of Darkness 的
`Items[] → BlockEntityTag/Items[] → tag/display/Name`，7 個），而漏掉一層的症狀是
「有些物品名沒被抽出來」，沒有例外也沒有紅字。

**嚴格白名單。** 只抽表列欄位，其餘忽略也不遞迴進去——物品底下的機制標籤多到列
不完（Enchantments、AttributeModifiers、Trim、Potion、CanPlaceOn、BlockStateTag、
SkullOwner、custom_data…）。白名單的代價是「新版本的新文字組件不會自動抽到」，
那個方向是對的：**漏抽看得見**（節點數對不上清點），**誤翻看不見**（地圖壞掉時
已經來不及）。
"""

import amulet_nbt

from mcmt.model.node import NodePath, key_step
from mcmt.scan.sources.item import scan_item


def paths_and_categories(item, *, anchor=None):
    found = list(scan_item(item, NodePath([key_step("Items")]), anchor=anchor))
    return {
        "/".join(
            step.name if step.t == "key" else f"[{step.i}]" for step in node.path
        ): node.category
        for node in found
    }


def component_item(**components):
    item = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:stone")})
    item["components"] = amulet_nbt.CompoundTag(components)
    return item


def test_a_custom_name_component_is_found():
    item = component_item(
        **{"minecraft:custom_name": amulet_nbt.StringTag("補給箱")}
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:custom_name": "custom_name"
    }


def test_an_item_name_component_is_found():
    item = component_item(**{"minecraft:item_name": amulet_nbt.StringTag("聖劍")})

    assert paths_and_categories(item) == {
        "Items/components/minecraft:item_name": "item_name"
    }


def test_every_lore_line_is_found_separately():
    """lore 是陣列，每一行是獨立的 component——也是獨立的翻譯單位。"""
    item = component_item(
        **{
            "minecraft:lore": amulet_nbt.ListTag(
                [amulet_nbt.StringTag("第一行"), amulet_nbt.StringTag("第二行")]
            )
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:lore/[0]": "lore",
        "Items/components/minecraft:lore/[1]": "lore",
    }


def test_a_written_book_yields_title_author_and_pages():
    """[遊戲實測] `title.raw` 與 `author` 只吃字串（走 in_place），

    `pages[].raw` 底下卻是完整的 component（走 translate key）。同一本書裡的
    不對稱，category 分開才表達得出來。
    """
    item = component_item(
        **{
            "minecraft:written_book_content": amulet_nbt.CompoundTag(
                {
                    "title": amulet_nbt.CompoundTag(
                        {"raw": amulet_nbt.StringTag("我的書")}
                    ),
                    "author": amulet_nbt.StringTag("作者"),
                    "pages": amulet_nbt.ListTag(
                        [
                            amulet_nbt.CompoundTag(
                                {"raw": amulet_nbt.StringTag("第一頁")}
                            )
                        ]
                    ),
                }
            )
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:written_book_content/title/raw": "book_title",
        "Items/components/minecraft:written_book_content/author": "book_author",
        "Items/components/minecraft:written_book_content/pages/[0]/raw": "book_page",
    }


def test_a_writable_book_page_is_a_draft_page():
    """草稿書頁是無包裝的 TAG_String，只能 in_place。"""
    item = component_item(
        **{
            "minecraft:writable_book_content": amulet_nbt.CompoundTag(
                {
                    "pages": amulet_nbt.ListTag(
                        [
                            amulet_nbt.CompoundTag(
                                {"raw": amulet_nbt.StringTag("草稿")}
                            )
                        ]
                    )
                }
            )
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:writable_book_content/pages/[0]/raw": "draft_book_page"
    }


def test_a_container_recurses_into_its_items():
    """潛影盒裡的物品。**[實測] 三層巢狀真的存在。**"""
    inner = component_item(
        **{"minecraft:custom_name": amulet_nbt.StringTag("裡面的東西")}
    )
    outer = component_item(
        **{
            "minecraft:container": amulet_nbt.ListTag(
                [amulet_nbt.CompoundTag({"slot": amulet_nbt.IntTag(0), "item": inner})]
            )
        }
    )

    assert paths_and_categories(outer) == {
        "Items/components/minecraft:container/[0]/item/components/minecraft:custom_name": "custom_name"
    }


def test_a_bundle_recurses_into_its_contents():
    """收納袋——邊緣容器，但它就是個物品清單。"""
    inner = component_item(**{"minecraft:custom_name": amulet_nbt.StringTag("袋內")})
    outer = component_item(
        **{"minecraft:bundle_contents": amulet_nbt.ListTag([inner])}
    )

    assert paths_and_categories(outer) == {
        "Items/components/minecraft:bundle_contents/[0]/components/minecraft:custom_name": "custom_name"
    }


def test_charged_projectiles_recurse():
    """弩上的箭也是物品。"""
    inner = component_item(**{"minecraft:custom_name": amulet_nbt.StringTag("魔法箭")})
    outer = component_item(
        **{"minecraft:charged_projectiles": amulet_nbt.ListTag([inner])}
    )

    assert paths_and_categories(outer) == {
        "Items/components/minecraft:charged_projectiles/[0]/components/minecraft:custom_name": "custom_name"
    }


def test_mechanic_components_are_ignored_entirely():
    """**白名單的核心測試。**

    不在清單裡的組件連碰都不碰——不是「抽出來再靠 denylist 擋」。
    """
    item = component_item(
        **{
            "minecraft:custom_name": amulet_nbt.StringTag("要抽的"),
            "minecraft:enchantments": amulet_nbt.CompoundTag(
                {"minecraft:sharpness": amulet_nbt.IntTag(5)}
            ),
            "minecraft:lock": amulet_nbt.StringTag("Locked"),
            "minecraft:custom_data": amulet_nbt.CompoundTag(
                {"quest": amulet_nbt.StringTag("q_042")}
            ),
            "minecraft:profile": amulet_nbt.CompoundTag(
                {"name": amulet_nbt.StringTag("TheWorfer27")}
            ),
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:custom_name": "custom_name"
    }


def test_an_item_with_nothing_translatable_yields_nothing():
    assert paths_and_categories(component_item()) == {}


def test_the_anchor_is_carried_down_into_nested_items():
    """巢狀物品的座標就是最外層容器的座標——譯者要走得到現場。"""
    inner = component_item(**{"minecraft:custom_name": amulet_nbt.StringTag("裡面")})
    outer = component_item(
        **{
            "minecraft:container": amulet_nbt.ListTag(
                [amulet_nbt.CompoundTag({"item": inner})]
            )
        }
    )
    anchor = {"kind": "block", "id": "minecraft:chest", "x": 1, "y": 2, "z": 3, "uuid": None}

    (node,) = list(scan_item(outer, NodePath([key_step("Items")]), anchor=anchor))

    assert node.anchor == anchor


# --- 舊格式（1.20.5 之前）---------------------------------------------------


def tag_item(item_id="minecraft:stone", **tag):
    item = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag(item_id)})
    item["tag"] = amulet_nbt.CompoundTag(tag)
    return item


def test_an_old_display_name_is_found():
    """[實測] Arena of Darkness 有 3,696 個，值是 JSON 字串。"""
    item = tag_item(
        display=amulet_nbt.CompoundTag(
            {"Name": amulet_nbt.StringTag('{"text":"Xyphia"}')}
        )
    )

    assert paths_and_categories(item) == {
        "Items/tag/display/Name": "custom_name"
    }


def test_old_lore_lines_are_found():
    item = tag_item(
        display=amulet_nbt.CompoundTag(
            {
                "Lore": amulet_nbt.ListTag(
                    [
                        amulet_nbt.StringTag('{"text":"第一行"}'),
                        amulet_nbt.StringTag('{"text":"第二行"}'),
                    ]
                )
            }
        )
    )

    assert paths_and_categories(item) == {
        "Items/tag/display/Lore/[0]": "lore",
        "Items/tag/display/Lore/[1]": "lore",
    }


def test_an_old_written_book_yields_title_author_and_pages():
    """舊格式的成書：title/author 是純字串，pages[] 是 JSON 字串。"""
    item = tag_item(
        "minecraft:written_book",
        title=amulet_nbt.StringTag("Base Notes"),
        author=amulet_nbt.StringTag("TheWorfer27"),
        pages=amulet_nbt.ListTag([amulet_nbt.StringTag('{"text":"第一頁"}')]),
    )

    assert paths_and_categories(item) == {
        "Items/tag/title": "book_title",
        "Items/tag/author": "book_author",
        "Items/tag/pages/[0]": "book_page",
    }


def test_an_old_writable_book_is_a_draft_not_a_written_book():
    """**成書與草稿書共用 `tag.pages[]`。**

    差別在物品 id，不在路徑。只看路徑會把草稿書當成書處理，而草稿書頁是無包裝的
    TAG_String，只能 in_place——搞錯的話會往它寫一個 translate key，玩家看到的是
    key 本身。
    """
    item = tag_item(
        "minecraft:writable_book",
        pages=amulet_nbt.ListTag([amulet_nbt.StringTag("草稿內容")]),
    )

    assert paths_and_categories(item) == {"Items/tag/pages/[0]": "draft_book_page"}


def test_an_old_shulker_box_recurses_into_its_items():
    """[實測] Arena of Darkness 的三層巢狀就是這條路徑。"""
    inner = tag_item(
        display=amulet_nbt.CompoundTag(
            {"Name": amulet_nbt.StringTag('{"text":"Ultra Health Potion"}')}
        )
    )
    outer = tag_item(
        BlockEntityTag=amulet_nbt.CompoundTag(
            {"Items": amulet_nbt.ListTag([inner])}
        )
    )

    assert paths_and_categories(outer) == {
        "Items/tag/BlockEntityTag/Items/[0]/tag/display/Name": "custom_name"
    }


def test_an_old_block_entity_tag_custom_name_is_found():
    """[實測] Arena of Darkness 有 1 個——物品形式的容器自己也有名字。"""
    outer = tag_item(
        BlockEntityTag=amulet_nbt.CompoundTag(
            {"CustomName": amulet_nbt.StringTag('{"text":"箱子"}')}
        )
    )

    assert paths_and_categories(outer) == {
        "Items/tag/BlockEntityTag/CustomName": "block_entity_name"
    }


def test_an_old_bundle_recurses():
    """舊格式的收納袋用 `tag.Items`。"""
    inner = tag_item(
        display=amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag('{"text":"袋內"}')})
    )
    outer = tag_item(Items=amulet_nbt.ListTag([inner]))

    assert paths_and_categories(outer) == {
        "Items/tag/Items/[0]/tag/display/Name": "custom_name"
    }


def test_old_mechanic_tags_are_ignored_entirely():
    """白名單在舊格式一樣嚴格。"""
    item = tag_item(
        display=amulet_nbt.CompoundTag(
            {"Name": amulet_nbt.StringTag('{"text":"要抽的"}')}
        ),
        SkullOwner=amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag("TheWorfer27")}),
        Potion=amulet_nbt.StringTag("minecraft:water"),
        BlockStateTag=amulet_nbt.CompoundTag({"delay": amulet_nbt.StringTag("4")}),
        CanDestroy=amulet_nbt.ListTag([amulet_nbt.StringTag("minecraft:red_bed")]),
    )

    assert paths_and_categories(item) == {"Items/tag/display/Name": "custom_name"}


def test_an_item_with_both_shapes_prefers_components():
    """理論上不該同時存在，但真的碰到時要有個確定的答案。

    `components` 是新的，它才是遊戲會讀的那一份。
    """
    item = component_item(
        **{"minecraft:custom_name": amulet_nbt.StringTag("新的")}
    )
    item["tag"] = amulet_nbt.CompoundTag(
        {"display": amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag("舊的")})}
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:custom_name": "custom_name"
    }
