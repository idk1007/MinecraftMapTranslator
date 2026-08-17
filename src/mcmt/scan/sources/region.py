# SPDX-License-Identifier: GPL-3.0-or-later
"""從 chunk 掃出文字節點（M5.5）。

這一層只做一件事：**找到節點，記下它在哪裡**。形狀交給 `model/component.py` 嗅探、
攤平交給 `model/segments.py`、要不要翻交給 M6 的規則引擎。分開的理由是每一層都有
自己的唯一權威，混在一起就會出現第二份判斷邏輯。

每個節點帶一條 `node_path`，寫入層之後靠它走回同一個位置。

## v1 掃到的

* 告示牌（`minecraft:*sign`）的 `front_text` / `back_text` 的 `messages[]` 四行，
  **含空行**——NBT list 同型規則要知道整個 list 長什麼樣。
* 方塊實體的 `CustomName`。

## 還沒掃的（M13 掃描廣度）

容器裡的物品（`Items[]` 的 `custom_name` / `lore` / 書本內容）、實體（在
`entities/` 而不是 `region/`）、`level.dat`、記分板、進度、指令方塊的 `Command`、
datapack 的 `.mcfunction`、`hover_event` 內的文字。**不是忘了，是還沒做。**

## 刻意不去找的

`LastOutput`（[實測] MP2 有 719 筆，執行期產物且含原版 key）、`custom_data`、
`palette[].Name` 這些。真正的 denylist 是規則引擎的職責，但掃描層本來就不主動去找
它們——少一個機會出錯。
"""

from dataclasses import dataclass
from typing import Any, Iterator

import amulet_nbt

from mcmt.model.node import NodePath, index_step, key_step

__all__ = ["TextNode", "scan_chunk"]

_SIGN_FACES = ("front_text", "back_text")
_MESSAGES = "messages"


@dataclass(frozen=True)
class TextNode:
    """一個等著被判形狀的文字節點，以及它在世界裡的位置。"""

    path: NodePath
    tag: Any
    category: str
    anchor: dict[str, Any] | None = None
    list_context: dict[str, Any] | None = None


def scan_chunk(root: amulet_nbt.CompoundTag) -> Iterator[TextNode]:
    """走過一個 chunk 的方塊實體，yield 裡面的文字節點。"""
    entities = root.get("block_entities")
    if not isinstance(entities, amulet_nbt.ListTag):
        return

    base = NodePath([key_step("block_entities")])
    for position, entity in enumerate(entities):
        if not isinstance(entity, amulet_nbt.CompoundTag):
            continue
        path = base.child(index_step(position))
        yield from _scan_block_entity(entity, path)


def _scan_block_entity(
    entity: amulet_nbt.CompoundTag, path: NodePath
) -> Iterator[TextNode]:
    block_id = str(entity.get("id", ""))
    anchor = _anchor(entity, block_id)

    if "sign" in block_id:
        category = "hanging_sign" if "hanging_sign" in block_id else "sign"
        for face in _SIGN_FACES:
            side = entity.get(face)
            if not isinstance(side, amulet_nbt.CompoundTag):
                continue
            messages = side.get(_MESSAGES)
            if not isinstance(messages, amulet_nbt.ListTag):
                continue
            face_path = path.child(key_step(face)).child(key_step(_MESSAGES))
            element_type = _element_type(messages)
            for index, message in enumerate(messages):
                yield TextNode(
                    path=face_path.child(index_step(index)),
                    tag=message,
                    category=category,
                    anchor=anchor,
                    list_context={
                        "list_size": len(messages),
                        "index": index,
                        "element_type": element_type,
                        # 告示牌四行只要有一行是結構化 component，其餘三行就不能
                        # 是裸字串（CLAUDE.md 二節）。
                        "homogeneity_required": True,
                    },
                )

    custom_name = entity.get("CustomName")
    if isinstance(custom_name, (amulet_nbt.StringTag, amulet_nbt.CompoundTag)):
        yield TextNode(
            path=path.child(key_step("CustomName")),
            tag=custom_name,
            category="block_entity_name",
            anchor=anchor,
        )


def _anchor(entity: amulet_nbt.CompoundTag, block_id: str) -> dict[str, Any]:
    def coordinate(name: str) -> int | None:
        value = entity.get(name)
        return int(value) if isinstance(value, amulet_nbt.AbstractBaseIntTag) else None

    return {
        "kind": "block",
        "id": block_id or None,
        "x": coordinate("x"),
        "y": coordinate("y"),
        "z": coordinate("z"),
        "uuid": None,
    }


def _element_type(messages: amulet_nbt.ListTag) -> str:
    """這個 list 現在裝的是什麼——寫入層的同型判斷要用。"""
    for element in messages:
        if isinstance(element, amulet_nbt.CompoundTag):
            return "compound"
        if isinstance(element, amulet_nbt.StringTag):
            return "string"
    return "empty"
