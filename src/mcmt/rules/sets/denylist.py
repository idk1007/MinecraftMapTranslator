# SPDX-License-Identifier: GPL-3.0-or-later
"""絕不翻譯的路徑（M6）。

[實測] 這幾條是掃描時真的會踩到的陷阱，每一條都有自己的災難——最兇的是
`palette[].Name`：那是方塊 ID，MP2 有 113,228 個，翻了**毀掉地形**。

**這些是識別碼不是文字。** 和「不想翻的人名」完全不是同一類：人名翻了只是難看，
這些翻了地圖會壞。所以是 hard deny，不是警告。

規則只加標籤、不刪標籤（`engine` 的收斂前提）。所以「不翻」的表達方式是加一個
`deny:<原因>`，再由一條獨立的規則把任何 `deny:*` 推導成 `do_not_translate`——
加原因的規則不必知道結論怎麼算，而結論的定義只有一處。
"""

from mcmt.rules.engine import Subject

__all__ = ["DENY_LABEL", "RULES", "deny_reason"]

DENY_LABEL = "do_not_translate"
_PREFIX = "deny:"

# 路徑尾巴 → 原因。比對的是**鍵名序列的尾巴**（索引已經拿掉），所以
# `sections[3].block_states.palette[7].Name` 的尾巴就是 ("palette", "Name")。
_DENIED_TAILS: dict[tuple[str, ...], str] = {
    # [實測] 生態域調色盤是**字串 list**，不是像方塊調色盤那樣的 compound——所以
    # ("palette", "Name") 完全認不到它。自建探測世界的 30 個 chunk 裡有 720 個。
    ("biomes", "palette"): "block_id",
    ("palette", "Properties"): "block_id",
    # chunk 的產生狀態（minecraft:full 之類）與方塊實體型別，都是識別碼。
    ("Status",): "identifier",
    ("id",): "identifier",
    ("palette", "Name"): "block_id",
    ("Objectives", "Name"): "identifier",
    ("Objectives", "CriteriaName"): "identifier",
    ("Teams", "Name"): "identifier",
    ("PlayerScores", "Name"): "identifier",
    # 盔甲紋飾：材質與圖案都是識別碼，不是給人看的字。
    ("Trim", "material"): "identifier",
    ("Trim", "pattern"): "identifier",
}

# 這幾個是「出現在路徑任何位置就擋」，不看尾巴。
_DENIED_ANYWHERE: dict[str, str] = {
    "minecraft:custom_data": "custom_data",
    "custom_data": "custom_data",
    "DisplaySlots": "identifier",
    # `sections` 底下是方塊與生態域資料，**沒有任何給人看的字**。方塊實體是
    # chunk 根的兄弟節點，不在這裡面。整段擋掉比逐條列舉可靠——[實測] 逐條列舉時
    # 漏掉了 biomes.palette。
    "sections": "block_id",
    # [實測] 尾巴比對只擋得到結尾正好是 LastOutput 的節點；`LastOutput/text` 與
    # `LastOutput/extra[]/translate` 全漏，100 Ways To Die 有 6,000 多個，而且
    # 它們含原版 translate key。指令方塊的執行期輸出整段都不是內容。
    "LastOutput": "runtime_output",
    # 1.20.5+ 的鍵名帶命名空間，原本的 ("profile","properties","value") 認不到
    # `minecraft:profile`。整段擋掉——那底下沒有任何給人看的字。
    "profile": "skin_texture",
    "minecraft:profile": "skin_texture",
    "SkullOwner": "skin_texture",
    # **容器鎖。** [實測] Arena of Darkness 有 107 個。值必須與鑰匙物品的名字
    # 完全相同才能開箱，翻了它箱子永遠打不開，而症狀離原因很遠。
    "Lock": "container_lock",
    "minecraft:lock": "container_lock",
    # 戰利品表與它的種子，是識別碼。
    "LootTable": "identifier",
    "LootTableSeed": "identifier",
    "BlockStateTag": "block_id",
    "block_state": "block_id",
    # 藥水：舊格式是 `tag.Potion`，1.20.5+ 是
    # `components."minecraft:potion_contents".potion`。兩個鍵名都擋。
    "Potion": "identifier",
    "minecraft:potion_contents": "identifier",
    "CanDestroy": "block_id",
    "CanPlaceOn": "block_id",
    "can_destroy": "block_id",
    "can_place_on": "block_id",
}

_REASON_TEXT = {
    "runtime_output": "指令方塊的執行期輸出，含原版 translate key",
    "skin_texture": "base64 皮膚材質，翻了頭顱貼圖會破",
    "block_id": "方塊 ID，翻了毀掉地形",
    "custom_data": "地圖自訂資料，常放 quest id 之類的識別碼",
    "identifier": "內部識別碼，指令會引用它",
    "container_lock": "容器鎖，值必須與鑰匙物品的名字完全相同——翻了箱子永遠打不開",
}


def _deny_by_tail(subject: Subject) -> set[str]:
    path = subject.key_path
    for tail, reason in _DENIED_TAILS.items():
        if len(path) >= len(tail) and tuple(path[-len(tail):]) == tail:
            return {_PREFIX + reason}
    return set()


def _deny_by_presence(subject: Subject) -> set[str]:
    found = {
        reason for key, reason in _DENIED_ANYWHERE.items() if key in subject.key_path
    }
    return {_PREFIX + reason for reason in found}


def _conclude(subject: Subject) -> set[str]:
    """任何 `deny:*` 都推導出 `do_not_translate`。

    結論的定義只有這一處。加原因的規則不必知道結論怎麼算——這就是不動點迭代在這裡
    的用途。
    """
    if any(name.startswith(_PREFIX) for name in subject.labels):
        return {DENY_LABEL}
    return set()


_deny_by_tail.rule_name = "denylist:路徑尾巴"
_deny_by_presence.rule_name = "denylist:路徑含有"
_conclude.rule_name = "denylist:推導結論"

RULES = [_deny_by_tail, _deny_by_presence, _conclude]


def deny_reason(labels) -> str | None:
    """從標籤集合取出「為什麼不翻」，供報告使用。"""
    for name in sorted(labels):
        if name.startswith(_PREFIX):
            reason = name[len(_PREFIX):]
            return _REASON_TEXT.get(reason, reason)
    return None
