# SPDX-License-Identifier: GPL-3.0-or-later
"""實體裡的文字（M13.4）。

實體從 1.17 起存在 `entities/*.mca` 而不是 `region/*.mca`。**只掃 `region/` 會漏掉
所有具名生物、盔甲座、展示框與 `text_display` 的浮空文字**——[實測] `100 Ways To Die`
有 184 個 text_display 節點（169 個相異），`Arena of Darkness` 有 333 個具名實體。

格式與 region 完全一樣（同一套 header、同一套壓縮），所以讀寫都沿用
`read_region` / `write_region`，**寫入層一行都不必改**。差別只在裡面裝的是
`Entities[]` 而不是 `block_entities[]`。

## 白名單

    CustomName          具名生物、盔甲座
    text                text_display（1.19.4+）
    Passengers[]        遞迴——[實測] 100WTD 有 102 個 text_display 掛在載具上
    Item / item         展示框、掉落物
    ArmorItems[] / HandItems[] / equipment / weapon   身上的裝備
    Inventory[]         馬、驢、羊駝身上的箱子

其餘一律不碰。[實測] `Tags[]` 在 100WTD 有 96,168 個，全是識別碼；`variant`、
`profession`、`MainGene`、`billboard`、`Attributes[].Name` 同理。
"""

from collections import Counter
from typing import Any, Iterator

import amulet_nbt

from mcmt.errors import FormatError
from mcmt.model.node import NodePath, index_step, key_step
from mcmt.nbtio.region import entities_files, read_region
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root
from mcmt.safety.paths import ReadOnlyPath
from mcmt.scan.node import ScannedNode, TextNode
from mcmt.scan.sources.item import scan_item
from mcmt.scan.sources.region import dimension_of

__all__ = ["scan", "scan_entities_chunk"]

# 身上帶物品的欄位 → 它是單一物品還是物品清單。
_SINGLE_ITEM_KEYS = ("Item", "item", "weapon")
_ITEM_LIST_KEYS = ("ArmorItems", "HandItems", "Inventory")
# `equipment` 是 1.21.5+ 的形狀：{head: item, chest: item, ...}
_EQUIPMENT_KEY = "equipment"


def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    """走過世界的每一張實體 region。

    一張 region 讀不下去時記錄並跳過，不讓整次 extract 消失——壞掉的世界更需要
    能先掃出能掃的部分。**不能先 `list()` 整份收集完再迭代**：`read_region` 是
    產生器，`list()` 對一個中途拋例外的產生器不會回傳部分結果，已經成功讀到的
    chunk 會連同壞掉的一起被丟棄（同 `sources/region.py` 的理由，見
    `tests/unit/test_scan_registry.py` 的
    `test_a_clean_chunk_before_a_broken_one_is_not_lost`）。所以這裡跟 region 來源
    一樣，把 try 包住整個 for 迴圈本體。
    """
    for path in entities_files(world):
        try:
            for raw in read_region(path):
                if raw.is_external:
                    stats["skipped_external_chunk"] += 1
                    continue
                try:
                    root = load_chunk_root(raw)
                    data_version = ensure_supported_structure(root, chunk_index=raw.index)
                except (FormatError, amulet_nbt.NBTLoadError):
                    stats["skipped_chunk"] += 1
                    continue
                stats["entity_chunks"] += 1
                container = _container(path, raw, data_version, world)
                for node in scan_entities_chunk(root):
                    yield ScannedNode(node=node, container=container)
        except FormatError:
            stats["skipped_region"] += 1


def _container(path, raw, data_version: int, world: ReadOnlyPath) -> dict:
    """一個 chunk 的容器描述。

    **回傳的 dict 是同一個 chunk 裡所有節點共用的一份**（呼叫端每個 chunk 只建一次，
    然後把同一個物件掛到每個 `ScannedNode` 上）。下游要改容器欄位就複製一份再改，
    **不要就地修改**——就地改會連同那個 chunk 裡其他所有節點一起改掉。
    """
    relative = path.relative_to(world).replace("\\", "/")
    return {
        "kind": "entities_chunk",
        "path": relative,
        "dimension": dimension_of(relative),
        "chunk": {"cx": raw.local_x, "cz": raw.local_z},
        "data_version": data_version,
        "compression": raw.compression_type,
        "external": raw.is_external,
    }


def scan_entities_chunk(root: amulet_nbt.CompoundTag) -> Iterator[TextNode]:
    """一張實體 chunk 裡的文字節點。"""
    entities = root.get("Entities")
    if not isinstance(entities, amulet_nbt.ListTag):
        return
    base = NodePath([key_step("Entities")])
    for position, entity in enumerate(entities):
        if not isinstance(entity, amulet_nbt.CompoundTag):
            continue
        yield from _scan_entity(entity, base.child(index_step(position)))


def _scan_entity(entity: amulet_nbt.CompoundTag, path: NodePath) -> Iterator[TextNode]:
    anchor = _anchor(entity)

    # **型別檢查而不是 `is not None`**，與 `region.py` 的 `CustomName` 一致：
    # `is not None` 收得下 IntTag / ListTag / ByteArrayTag，而嗅探器對它們拋
    # `TypeError`，那個例外沒有人接。實務上會不會有實體把這兩個鍵放成別的型別
    # 不知道——「不知道」正是該用白名單型別的理由。
    custom_name = entity.get("CustomName")
    if isinstance(custom_name, (amulet_nbt.StringTag, amulet_nbt.CompoundTag)):
        yield TextNode(
            path=path.child(key_step("CustomName")),
            tag=custom_name,
            category="entity_name",
            anchor=anchor,
        )

    text = entity.get("text")
    if isinstance(text, (amulet_nbt.StringTag, amulet_nbt.CompoundTag)):
        yield TextNode(
            path=path.child(key_step("text")),
            tag=text,
            category="text_display",
            anchor=anchor,
        )

    for key in _SINGLE_ITEM_KEYS:
        held = entity.get(key)
        if isinstance(held, amulet_nbt.CompoundTag):
            yield from scan_item(held, path.child(key_step(key)), anchor=anchor)

    for key in _ITEM_LIST_KEYS:
        items = entity.get(key)
        if not isinstance(items, amulet_nbt.ListTag):
            continue
        items_path = path.child(key_step(key))
        for index, item in enumerate(items):
            yield from scan_item(
                item, items_path.child(index_step(index)), anchor=anchor
            )

    equipment = entity.get(_EQUIPMENT_KEY)
    if isinstance(equipment, amulet_nbt.CompoundTag):
        equipment_path = path.child(key_step(_EQUIPMENT_KEY))
        for slot, item in equipment.items():
            yield from scan_item(
                item, equipment_path.child(key_step(str(slot))), anchor=anchor
            )

    # 載具上的實體。[實測] 100 Ways To Die 有 102 個 text_display 掛在這裡，
    # 只掃頂層會整批漏掉。
    passengers = entity.get("Passengers")
    if isinstance(passengers, amulet_nbt.ListTag):
        passengers_path = path.child(key_step("Passengers"))
        for index, passenger in enumerate(passengers):
            if isinstance(passenger, amulet_nbt.CompoundTag):
                yield from _scan_entity(
                    passenger, passengers_path.child(index_step(index))
                )


def _anchor(entity: amulet_nbt.CompoundTag) -> dict[str, Any]:
    """實體的座標在 `Pos`（三個 double），不是 x/y/z。

    合約的 `context.position` 刻意是 number 而不是 integer，就是因為 text_display
    routinely 落在非整數座標上。
    """
    position = entity.get("Pos")
    coordinates: list[float | None] = [None, None, None]
    if isinstance(position, amulet_nbt.ListTag) and len(position) >= 3:
        coordinates = [float(position[i]) for i in range(3)]
    return {
        "kind": "entity",
        "id": str(entity.get("id", "")) or None,
        "x": coordinates[0],
        "y": coordinates[1],
        "z": coordinates[2],
        "uuid": None,
    }
