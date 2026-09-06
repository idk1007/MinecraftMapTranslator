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
* 容器裡的物品（`Items[]`）與講台的書（`Book`），遞迴交給 `item.py`。
* 指令方塊的 `Command`——白名單動詞解析交給共用的 `scan/command.py`。

實體不在這裡——它們從 1.17 起住在 `entities/*.mca`，由 `sources/entities.py` 負責。

## 還沒掃的

`level.dat`、記分板、進度、`hover_event` 內的文字由其他 `sources/` 模組負責；
datapack 的 `.mcfunction` 由 `sources/mcfunction.py` 掃、指令方塊的 `Command`
在上面「v1 掃到的」已列（白名單動詞解析在 `scan/command.py`，2026-09-05）。

**掃描來源本身沒有整類缺口了，但指令文字這條路上還有三個已知缺口**（都不是
安全問題，都有 pinned 測試釘住現狀，完整說明見 `docs/STATUS.md` 已知缺口）：

* `give`／`item` 的**命名空間組件鍵**（`minecraft:custom_name=…`）比不到，整條
  指令計入 `skipped_command_unsupported_shape` 後略過（缺口 A，掃描層）。
* `data merge` 的「SNBT 字串常值包一段 JSON」訊息，寫入前的重新解碼是壞的，
  這筆合法的翻譯會被守門拒寫（缺口 B，`write/common.py`）。
* `.mcfunction` 的寫入守門只做到長度比對，還沒有跟 region／entities 完全對齊的
  `raw_snapshot` 逐位元組守門（缺口 C，`write/mcfunction_apply.py`）。

## 刻意不去找的

`LastOutput`（[實測] MP2 有 719 筆，執行期產物且含原版 key）、`custom_data`、
`palette[].Name` 這些。真正的 denylist 是規則引擎的職責，但掃描層本來就不主動去找
它們——少一個機會出錯。
"""

from collections import Counter
from typing import Any, Iterator

import amulet_nbt

from mcmt.errors import FormatError
from mcmt.model.node import NodePath, index_step, key_step
from mcmt.nbtio.region import read_region, region_files
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root
from mcmt.safety.paths import ReadOnlyPath
from mcmt.scan.command import scan_command_string
from mcmt.scan.node import ScannedNode, TextNode
from mcmt.scan.sources.item import scan_item

__all__ = ["dimension_of", "scan", "scan_chunk"]

_SIGN_FACES = ("front_text", "back_text")
_MESSAGES = "messages"


def scan_chunk(
    root: amulet_nbt.CompoundTag, stats: Counter | None = None
) -> Iterator[TextNode]:
    """走過一個 chunk 的方塊實體，yield 裡面的文字節點。"""
    if stats is None:
        stats = Counter()
    entities = root.get("block_entities")
    if not isinstance(entities, amulet_nbt.ListTag):
        return

    base = NodePath([key_step("block_entities")])
    for position, entity in enumerate(entities):
        if not isinstance(entity, amulet_nbt.CompoundTag):
            continue
        path = base.child(index_step(position))
        yield from _scan_block_entity(entity, path, stats)


def _scan_block_entity(
    entity: amulet_nbt.CompoundTag, path: NodePath, stats: Counter
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

    # 容器裡的物品。**遞迴交給 `item.py`**——同一份遞迴被方塊實體、實體裝備、
    # 玩家背包三處共用，各寫一份是漏掉一層的最短路徑。
    items = entity.get("Items")
    if isinstance(items, amulet_nbt.ListTag):
        items_path = path.child(key_step("Items"))
        for index, item in enumerate(items):
            yield from scan_item(
                item, items_path.child(index_step(index)), anchor=anchor
            )

    # [實測] 講台的書在 `Book` 而不是 `Items[]`（Arena of Darkness 有 126 頁）。
    book = entity.get("Book")
    if isinstance(book, amulet_nbt.CompoundTag):
        yield from scan_item(book, path.child(key_step("Book")), anchor=anchor)

    # 指令方塊的 `Command`——共用的純函式解析,見 `mcmt.scan.command`。
    command = entity.get("Command")
    if isinstance(command, amulet_nbt.StringTag):
        yield from scan_command_string(
            str(command),
            base_path=path.child(key_step("Command")),
            anchor=anchor,
            stats=stats,
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


def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    """走過世界的每一張方塊 region，yield 裡面的文字節點。

    一張 region 讀不下去時記錄並跳過，不讓整次 extract 消失——壞掉的世界更需要
    能先掃出能掃的部分。
    """
    for path in region_files(world):
        try:
            # `read_region` 是產生器，這裡不能先 `list()` 整份收集完再迭代——
            # `list()` 對一個中途拋例外的產生器不會回傳部分結果，已經成功讀到的
            # chunk 會連同壞掉的一起被丟棄（見 tests/unit/test_region.py 的
            # `test_chunks_are_yielded_before_a_later_chunk_fails`）。峰值記憶體
            # 要維持單一 chunk，所以 for 迴圈本體要直接吃產生器、把 try 包住整個
            # 迴圈，才能在例外真的發生時仍保留之前已經 yield 出去的結果。
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
                stats["chunks"] += 1
                container = _container(path, raw, data_version, world)
                for node in scan_chunk(root, stats):
                    yield ScannedNode(node=node, container=container)
        except FormatError:
            stats["skipped_region"] += 1


def _container(path, raw, data_version: int, world: ReadOnlyPath) -> dict:
    """一個 chunk 的容器描述。

    **回傳的 dict 是同一個 chunk 裡所有節點共用的一份**（上面每個 chunk 只建一次，
    然後把同一個物件掛到每個 `ScannedNode` 上）。下游要改容器欄位就複製一份再改，
    **不要就地修改**——就地改會連同那個 chunk 裡其他所有節點一起改掉。
    """
    relative = path.relative_to(world).replace("\\", "/")
    return {
        "kind": "region_chunk",
        "path": relative,
        "dimension": dimension_of(relative),
        "chunk": {"cx": raw.local_x, "cz": raw.local_z},
        "data_version": data_version,
        "compression": raw.compression_type,
        "external": raw.is_external,
    }


def dimension_of(relative: str) -> str:
    """從 region 檔的相對路徑推維度名。`entities/` 的來源也用這個。"""
    if relative.startswith("DIM-1/"):
        return "minecraft:the_nether"
    if relative.startswith("DIM1/"):
        return "minecraft:the_end"
    if relative.startswith("dimensions/"):
        parts = relative.split("/")
        if len(parts) >= 3:
            return f"{parts[1]}:{parts[2]}"
    return "minecraft:overworld"
