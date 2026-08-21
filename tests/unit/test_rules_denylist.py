# SPDX-License-Identifier: GPL-3.0-or-later
"""M6 denylist（`rules/sets/denylist.py`）。

[實測] 這些路徑是掃描時真的會踩到的陷阱，每一條都有它自己的災難：

| 路徑 | 翻了會怎樣 |
|---|---|
| `LastOutput` | 執行期產物，含原版 key。MP2 有 719 筆 |
| `profile.properties[].value` | base64 皮膚材質，翻了頭顱貼圖破掉。412 個 |
| `palette[].Name` | **方塊 ID，翻了毀掉地形**。113,228 個 |
| `custom_data` | 地圖自訂資料，常放 quest id |
| `Objectives[].Name` / `CriteriaName` | 內部識別碼，指令會引用 |
| `Teams[].Name` / `PlayerScores[].Name` | 同上 |
| `DisplaySlots.*` | 同上 |

**這些是識別碼不是文字。** 和「不想翻的人名」完全不同類——人名翻了只是難看，這些
翻了地圖會壞。所以這裡是 hard deny，不是警告。
"""

import pytest

from mcmt.rules.engine import Subject, label
from mcmt.rules.sets.denylist import DENY_LABEL, RULES, deny_reason


def labels_for(*keys: str, value: str = "文字") -> frozenset[str]:
    return label(Subject(key_path=keys, value=value), RULES)


def denied(*keys: str) -> bool:
    return DENY_LABEL in labels_for(*keys)


# --- 每一條都要擋 ---------------------------------------------------------


@pytest.mark.parametrize(
    "keys",
    [
        ("block_entities", "LastOutput"),
        ("block_entities", "profile", "properties", "value"),
        ("sections", "block_states", "palette", "Name"),
        ("block_entities", "components", "minecraft:custom_data"),
        ("Objectives", "Name"),
        ("Objectives", "CriteriaName"),
        ("Teams", "Name"),
        ("PlayerScores", "Name"),
        ("DisplaySlots", "sidebar"),
    ],
)
def test_the_denylist_blocks_every_known_trap(keys) -> None:
    assert denied(*keys)


def test_the_reason_is_machine_readable() -> None:
    """報告要說得出「為什麼這個節點沒被翻」，不能只有一個布林值。"""
    reasons = {deny_reason(labels_for("block_entities", "LastOutput")),
               deny_reason(labels_for("sections", "block_states", "palette", "Name"))}

    assert None not in reasons
    assert len(reasons) == 2  # 兩種陷阱不同因、不同說明


def test_a_denied_node_is_never_also_translatable() -> None:
    """一個節點不能同時是「可翻」與「絕不翻」。"""
    result = labels_for("block_entities", "LastOutput")

    assert "translatable" not in result


# --- 不能誤傷 -------------------------------------------------------------


@pytest.mark.parametrize(
    "keys",
    [
        ("block_entities", "front_text", "messages"),
        ("block_entities", "CustomName"),
        ("Objectives", "DisplayName"),
        ("Teams", "DisplayName"),
        ("Teams", "prefix"),
        ("block_entities", "components", "minecraft:custom_name"),
    ],
)
def test_the_lookalikes_that_really_are_text_get_through(keys) -> None:
    """`Objectives[].Name` 是識別碼，`Objectives[].DisplayName` 是給人看的字。

    差一個字，一個翻了地圖壞掉、一個不翻就等於沒翻。
    """
    assert not denied(*keys)


def test_a_key_named_name_somewhere_harmless_is_not_denied() -> None:
    """`palette[].Name` 要擋，但不是任何叫 Name 的東西都要擋。"""
    assert not denied("block_entities", "Name")


def test_matching_is_on_the_tail_of_the_path() -> None:
    """`palette` 在哪一層都算——但 `Name` 必須真的在 `palette` 底下。"""
    assert denied("sections", "palette", "Name")
    assert denied("這層", "那層", "palette", "Name")
    assert not denied("palette", "Properties", "facing")


# --- 引擎整合 -------------------------------------------------------------


def test_the_denylist_converges() -> None:
    """denylist 規則本身不能讓引擎跑不完。"""
    for keys in [("LastOutput",), ("front_text", "messages"), ()]:
        assert isinstance(labels_for(*keys), frozenset)


def test_the_deny_label_is_derived_not_hand_written() -> None:
    """`deny:*` 是原因，`do_not_translate` 是結論——結論由規則推導出來。

    這是不動點迭代在這裡真正的用途：加原因的規則不必知道結論怎麼算。
    """
    result = labels_for("block_entities", "LastOutput")

    assert DENY_LABEL in result
    assert any(name.startswith("deny:") for name in result)


# --- 清點三張真實地圖時發現的漏洞 -------------------------------------------
#
# 本檔已在上方定義 `denied(*keys)`（見 `labels_for`）。下面沿用既有的那個，
# 不重複定義——brief 給的版本行為等價（denylist 規則只看 key_path，value
# 從不參與判斷，engine.py 的 `_deny_by_tail`/`_deny_by_presence` 都只讀
# `subject.key_path`），重複定義只會多一份要維護的程式碼。


def test_last_output_is_denied_at_every_depth():
    """**尾巴比對漏掉了子路徑。**

    `LastOutput` 原本寫在「路徑尾巴」清單，所以只擋結尾正好是 `LastOutput` 的
    節點。[實測] `100 Ways To Die` 的 `LastOutput/text`、
    `LastOutput/extra[]/translate` 全部漏掉——6,000 多個，而且它們含原版 key。
    """
    assert denied("block_entities", "LastOutput")
    assert denied("block_entities", "LastOutput", "text")
    assert denied("block_entities", "LastOutput", "extra", "translate")
    assert denied("block_entities", "LastOutput", "extra", "with", "hover_event", "name")


def test_a_namespaced_profile_texture_is_denied():
    """1.20.5+ 的真實鍵名帶命名空間，規則寫的是 `profile` 所以認不到。

    [實測] `100 Ways To Die` 的
    `equipment/head/components/minecraft:profile/properties[]/value` 26 個漏掉，
    那是 base64 皮膚材質，翻了頭顱貼圖會破。
    """
    assert denied("profile", "properties", "value")
    assert denied(
        "equipment", "head", "components", "minecraft:profile", "properties", "value"
    )
    assert denied("Items", "components", "minecraft:profile", "name")


def test_a_container_lock_is_denied():
    """**這是清點新發現的、最兇的一條。**

    [實測] `Arena of Darkness` 有 107 個 `block_entities[].Lock`（值 `"Locked"`）。
    容器鎖的值必須與鑰匙物品的名字**完全相同**才能開箱——翻了它，箱子永遠打不開，
    而症狀（「這個箱子開不了」）離原因（「我們翻了一個看起來像文字的欄位」）非常遠。
    """
    assert denied("block_entities", "Lock")
    assert denied("block_entities", "Items", "components", "minecraft:lock")


def test_item_mechanic_tags_are_denied():
    """物品遞迴路上會碰到的識別碼。掃描層是白名單、本來就不會去找它們，

    但 denylist 是第二道防線，而第二道防線的意義就在於第一道漏掉的時候。
    """
    assert denied("Items", "tag", "SkullOwner", "Name")
    assert denied("Items", "tag", "SkullOwner", "Properties", "textures", "Value")
    assert denied("Items", "tag", "SkullOwner", "Properties", "textures", "Signature")
    assert denied("Items", "tag", "BlockStateTag", "delay")
    assert denied("Items", "tag", "Potion")
    assert denied("Items", "tag", "Trim", "material")
    assert denied("Items", "tag", "Trim", "pattern")
    assert denied("Items", "tag", "CanDestroy")
    assert denied("Items", "tag", "CanPlaceOn")
    assert denied("block_entities", "LootTable")
    assert denied("block_entities", "LootTableSeed")


def test_item_mechanic_tags_new_namespaced_format_are_denied():
    """[code review finding, M13a task-2] 上一版只認舊裸鍵名，認不到 1.20.5+

    實際使用的 `minecraft:*` 命名空間鍵名——同一個 commit 裡 `profile`/`Lock`/
    `Potion` 都正確處理了新舊兩種鍵名，但 `CanDestroy`/`CanPlaceOn`/
    `BlockStateTag`/`Trim` 這四類漏掉了新格式，而且原本補的裸小寫替代品
    （`can_destroy`、`can_place_on`、`block_state`）根本不是任何版本真正用過的
    鍵名，是永遠不會命中的死條目。真正的新格式鍵名是
    `minecraft:can_break`（不是 `can_destroy` 的直譯）、
    `minecraft:can_place_on`、`minecraft:block_state`、`minecraft:trim`。
    """
    assert denied("Items", "components", "minecraft:block_state", "facing")
    assert denied("Items", "components", "minecraft:can_break", "blocks")
    assert denied("Items", "components", "minecraft:can_place_on", "blocks")
    assert denied("Items", "components", "minecraft:trim", "material")
    assert denied("Items", "components", "minecraft:trim", "pattern")
    # 死條目移除後，裸小寫版本不該再是「湊巧擋到」——它們本來就不該出現在真實
    # 存檔裡，這裡只是確認移除沒有留下任何殘餘的巧合命中。
    assert not denied("Items", "components", "can_destroy")
    assert not denied("Items", "components", "can_place_on")
    assert not denied("Items", "components", "block_state")


def test_the_translatable_fields_are_still_allowed():
    """**對照組。** 擋過頭的症狀是「有些東西沒被抽出來」，和「本來就沒有」

    長得一模一樣，所以每次動 denylist 都要有一條反面的測試。
    """
    assert not denied("block_entities", "front_text", "messages")
    assert not denied("block_entities", "CustomName")
    assert not denied("Items", "tag", "display", "Name")
    assert not denied("Items", "tag", "display", "Lore")
    assert not denied("Items", "components", "minecraft:custom_name")
    assert not denied("Items", "components", "minecraft:item_name")
    assert not denied("Items", "components", "minecraft:lore")
    assert not denied("Entities", "CustomName")
    assert not denied("Entities", "text")
    assert not denied(
        "Items", "components", "minecraft:written_book_content", "pages", "raw"
    )
    assert not denied("Items", "tag", "pages")
    assert not denied("Items", "tag", "title")
    assert not denied("Items", "tag", "author")
