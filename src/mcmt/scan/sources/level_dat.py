# SPDX-License-Identifier: GPL-3.0-or-later
"""`level.dat` 裡的文字（M13.5）。

三個欄位（[實測 2026-08-22]，見計畫檔開頭的真實資料表）：

    Data.LevelName                  純字串，不是 component（in_place）
    Data.CustomBossEvents.<id>.Name text component（translate_key，[全部遊戲實測]）
    Data.Player.Inventory[]         玩家背包，走 scan_item 的共用遞迴

**`CustomBossEvents` 是用 boss id 當鍵的 compound，不是 list**——`Arena of
Darkness` 的 27 個、`100 Ways To Die` 的 3 個都是這個形狀，不要被記號
`CustomBossEvents[].Name` 騙了以為要用 index_step。

根鍵名（`Data`）**動態解析**：先看 compound 裡有沒有這個鍵，不寫死。理由見計畫檔
的「與 spec 的兩個已知差異」——`level.dat` 只有一個根鍵，但這個檔案的鍵名大小寫
本身就是跨版本改過一次的例子，寫死的症狀是「這個檔案掃出 0 個節點」，看起來和
「這個檔案本來就沒有可翻譯的東西」一模一樣。
"""

from collections import Counter
from typing import Iterator

import amulet_nbt

from mcmt.errors import FormatError
from mcmt.model.generation import TARGET_DATA_VERSION
from mcmt.model.node import NodePath, index_step, key_step
from mcmt.nbtio.datfile import read_dat
from mcmt.safety.paths import ReadOnlyPath
from mcmt.scan.node import ScannedNode, TextNode
from mcmt.scan.sources.item import scan_item

__all__ = ["scan", "scan_data"]

_ROOT_CANDIDATES = ("Data", "data")

_FILE_ANCHOR = {"kind": "file", "id": None, "x": None, "y": None, "z": None, "uuid": None}
_PLAYER_ANCHOR = {"kind": "player", "id": None, "x": None, "y": None, "z": None, "uuid": None}


def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    """`level.dat` 裡的文字。世界沒有這個檔案是合法狀態（雖然罕見），不算錯誤。"""
    path = world / "level.dat"
    if not path.exists():
        return

    try:
        dat = read_dat(path)
    except FormatError:
        stats["skipped_level_dat"] += 1
        return

    found = _root(dat.tag.compound)
    if found is None:
        stats["skipped_level_dat"] += 1
        return
    root_name, data = found

    container = {
        "kind": "level_dat",
        "path": "level.dat",
        "dimension": None,
        "chunk": None,
        "data_version": _data_version(data),
        "compression": None,
        "external": False,
    }
    stats["level_dat_files"] += 1
    for node in scan_data(data, root_name):
        yield ScannedNode(node=node, container=container)


def scan_data(data: amulet_nbt.CompoundTag, root_name: str) -> Iterator[TextNode]:
    base = NodePath([key_step(root_name)])

    level_name = data.get("LevelName")
    if level_name is not None:
        yield TextNode(
            path=base.child(key_step("LevelName")),
            tag=level_name,
            category="level_name",
            anchor=_FILE_ANCHOR,
        )

    events = data.get("CustomBossEvents")
    if isinstance(events, amulet_nbt.CompoundTag):
        events_path = base.child(key_step("CustomBossEvents"))
        for event_id, event in events.items():
            if not isinstance(event, amulet_nbt.CompoundTag):
                continue
            name = event.get("Name")
            if name is not None:
                yield TextNode(
                    path=events_path.child(key_step(str(event_id))).child(key_step("Name")),
                    tag=name,
                    category="bossbar",
                    anchor=_FILE_ANCHOR,
                )

    player = data.get("Player")
    if isinstance(player, amulet_nbt.CompoundTag):
        inventory = player.get("Inventory")
        if isinstance(inventory, amulet_nbt.ListTag):
            inventory_path = base.child(key_step("Player")).child(key_step("Inventory"))
            for index, item in enumerate(inventory):
                yield from scan_item(
                    item, inventory_path.child(index_step(index)), anchor=_PLAYER_ANCHOR
                )


def _root(root: amulet_nbt.CompoundTag):
    for name in _ROOT_CANDIDATES:
        value = root.get(name)
        if isinstance(value, amulet_nbt.CompoundTag):
            return name, value
    return None


def _data_version(data: amulet_nbt.CompoundTag) -> int:
    """`level.dat` 的 `DataVersion` 在根鍵**裡面**（`Data.DataVersion`）——
    與 `scoreboard.dat`（根鍵的兄弟節點）不同，這是兩個檔案實測出來的真實差異，
    不能共用同一個讀法。"""
    version = data.get("DataVersion")
    try:
        return int(version) if version is not None else TARGET_DATA_VERSION
    except (TypeError, ValueError):
        return TARGET_DATA_VERSION
