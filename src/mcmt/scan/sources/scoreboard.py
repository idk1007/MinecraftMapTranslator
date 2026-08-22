# SPDX-License-Identifier: GPL-3.0-or-later
"""`data/scoreboard.dat` 裡的文字（M13.6）。

四個欄位（[實測 2026-08-22]，見計畫檔開頭的真實資料表）：

    data.Objectives[].DisplayName        text component（[全部遊戲實測]）
    data.Teams[].DisplayName             text component（[全部遊戲實測]）
    data.Teams[].MemberNamePrefix        text component（**未單獨遊戲實測**，
    data.Teams[].MemberNameSuffix         見 SPIKE_RESULT.md 尚待驗證表）

`Objectives[].Name`／`CriteriaName`／`Teams[].Name` 是識別碼，denylist 在 M13a
就擋好了（`_DENIED_TAILS` 裡三條），這裡完全不去碰它們——白名單本來就不掃。

**根的形狀與 `level.dat` 不同**：`DataVersion` 是根的兄弟節點，不在 `data` 裡面
——[實測] `Arena of Darkness` 與 `100 Ways To Die` 的 `scoreboard.dat` 根都是
`{data: {...}, DataVersion: <int>}`。這個差異是實測出來的，不能跟 `level.dat`
共用同一個「讀 DataVersion」的讀法。

**`MemberNamePrefix`/`MemberNameSuffix` 在 native 世代常常整個不存在**（不是空
字串，是欄位本身省略）——[實測] `100 Ways To Die` 的 13 支隊伍全部沒有這兩個鍵；
`Arena of Darkness`（legacy）的 17 支隊伍都有，但值全部是空的 `'""'`。所以這個
分類在兩張語料地圖上都不會產生任何非空譯文——記在這裡是因為它是可預期的「這個
分類看起來沒用」疑問來源，不是 bug。
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

__all__ = ["scan", "scan_data"]

_ANCHOR = {"kind": "global", "id": None, "x": None, "y": None, "z": None, "uuid": None}


def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    path = world / "data" / "scoreboard.dat"
    if not path.exists():
        return

    try:
        dat = read_dat(path)
    except FormatError:
        stats["skipped_scoreboard_dat"] += 1
        return

    root = dat.tag.compound
    data = root.get("data")
    if not isinstance(data, amulet_nbt.CompoundTag):
        stats["skipped_scoreboard_dat"] += 1
        return

    container = {
        "kind": "scoreboard_dat",
        "path": "data/scoreboard.dat",
        "dimension": None,
        "chunk": None,
        "data_version": _data_version(root),
        "compression": None,
        "external": False,
    }
    stats["scoreboard_dat_files"] += 1
    for node in scan_data(data):
        yield ScannedNode(node=node, container=container)


def scan_data(data: amulet_nbt.CompoundTag) -> Iterator[TextNode]:
    base = NodePath([key_step("data")])

    objectives = data.get("Objectives")
    if isinstance(objectives, amulet_nbt.ListTag):
        objectives_path = base.child(key_step("Objectives"))
        for index, entry in enumerate(objectives):
            if not isinstance(entry, amulet_nbt.CompoundTag):
                continue
            display = entry.get("DisplayName")
            if display is not None:
                yield TextNode(
                    path=objectives_path.child(index_step(index)).child(key_step("DisplayName")),
                    tag=display,
                    category="objective",
                    anchor=_ANCHOR,
                )

    teams = data.get("Teams")
    if isinstance(teams, amulet_nbt.ListTag):
        teams_path = base.child(key_step("Teams"))
        for index, entry in enumerate(teams):
            if not isinstance(entry, amulet_nbt.CompoundTag):
                continue
            entry_path = teams_path.child(index_step(index))
            display = entry.get("DisplayName")
            if display is not None:
                yield TextNode(
                    path=entry_path.child(key_step("DisplayName")),
                    tag=display,
                    category="team",
                    anchor=_ANCHOR,
                )
            for field in ("MemberNamePrefix", "MemberNameSuffix"):
                value = entry.get(field)
                if value is not None:
                    yield TextNode(
                        path=entry_path.child(key_step(field)),
                        tag=value,
                        category="team_affix",
                        anchor=_ANCHOR,
                    )


def _data_version(root: amulet_nbt.CompoundTag) -> int:
    """`scoreboard.dat` 的 `DataVersion` 是根的兄弟節點，不在 `data` 裡面——
    與 `level.dat`（巢狀在根鍵裡）不同，這是實測出來的真實差異。"""
    version = root.get("DataVersion")
    try:
        return int(version) if version is not None else TARGET_DATA_VERSION
    except (TypeError, ValueError):
        return TARGET_DATA_VERSION
