# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 裡的文字（M13.7）。

進度**定義**在 datapack 檔案裡（`data/<ns>/advancement/*.json` 的 `display.title`
與 `display.description`），不在世界 NBT 裡；世界自己的 `advancements/<uuid>.json`
只存玩家已達成狀態，沒有顯示文字，不需處理（這裡指的是**世界根目錄**的
`advancements/`，與 datapack 裡定義進度的目錄同名但完全是兩回事，不要混淆）。

**目錄名單複數都要認**：1.21 起改成單數 `advancement/`，1.20 及以前是複數
`advancements/`（[實測 2026-08-22] `Arena of Darkness`，1.20.4，用的就是複數）。

**datapack 可以是資料夾也可以是 zip 檔，兩種都要支援**（[實測] `Arena of
Darkness` 全部是 zip）。

## 為什麼把 JSON 值包成 amulet_nbt 標籤

`display.title`/`display.description` 的值本身就是一個 JSON 值——可能是裸字串、
component 物件、或陣列。這與 NBT 裡「字串內容剛好是一份 JSON 文件」不同：這裡沒
有「外層字串」，值直接就是 JSON 型別。

包成對應的 `amulet_nbt` 標籤（`str`→`StringTag`、`dict`→`CompoundTag`、
`list`→`ListTag`）之後，既有的 `sniff()`/`flatten()`/規則引擎完全不必改——一個
裸字串包成 `StringTag` 就會被判成 `bare_string`，只有 `text` 鍵的 dict 包成
`CompoundTag` 就會被判成 `text_compound`。這不是新的 encoding，是既有八種形狀
分類本來就涵蓋的東西，只是這次的輸入是 JSON 檔而不是 NBT chunk。

## 寫入端不需要 amulet_nbt

寫回去的時候（`write/datapack_apply.py`）直接在**原始 Python dict** 上操作，不
透過 amulet_nbt——advancement JSON 檔本來就是 JSON，往裡面塞一個
`{"translate": key}` 純 Python dict 就是最終要 `json.dump` 出去的東西，不需要
先轉成 NBT 再轉回來。掃描端包成 amulet_nbt 只是為了借用既有管線的判斷邏輯，
不代表寫入端也要走 NBT。
"""

import json
import zipfile
from collections import Counter
from typing import Any, Iterator

import amulet_nbt

from mcmt.model.node import NodePath, index_step, key_step
from mcmt.safety.paths import ReadOnlyPath
from mcmt.scan.node import ScannedNode, TextNode

__all__ = ["scan", "scan_advancement"]

_ADVANCEMENT_DIR_NAMES = ("advancement", "advancements")
_ANCHOR = {"kind": "file", "id": None, "x": None, "y": None, "z": None, "uuid": None}


def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    root = world / "datapacks"
    if not root.exists():
        return

    for entry in root.glob("*"):
        if entry.is_dir():
            yield from _scan_folder_pack(world, entry, stats)
        elif entry.name.endswith(".zip"):
            yield from _scan_zip_pack(world, entry, stats)


def _scan_folder_pack(world, pack_dir: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    for dir_name in _ADVANCEMENT_DIR_NAMES:
        for path in pack_dir.glob(f"data/*/{dir_name}/*.json"):
            relative = path.relative_to(world)
            try:
                document = json.loads(path.read_bytes().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                stats["skipped_advancement_unparseable"] += 1
                continue
            container = _container(relative)
            stats["advancement_files"] += 1
            for node in scan_advancement(document):
                yield ScannedNode(node=node, container=container)


def _scan_zip_pack(world, zip_path: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    zip_relative = zip_path.relative_to(world)
    try:
        with zipfile.ZipFile(str(zip_path)) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith(".json")
                and any(f"/{d}/" in f"/{name}" for d in _ADVANCEMENT_DIR_NAMES)
                and name.split("/")[0] == "data"
            ]
            for name in sorted(names):
                try:
                    document = json.loads(archive.read(name).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    stats["skipped_advancement_unparseable"] += 1
                    continue
                container = _container(f"{zip_relative}/{name}")
                stats["advancement_files"] += 1
                for node in scan_advancement(document):
                    yield ScannedNode(node=node, container=container)
    except (zipfile.BadZipFile, OSError):
        stats["skipped_datapack_zip"] += 1


def scan_advancement(document: dict[str, Any]) -> Iterator[TextNode]:
    display = document.get("display") if isinstance(document, dict) else None
    if not isinstance(display, dict):
        return
    base = NodePath([key_step("display")])

    title = display.get("title")
    if title is not None:
        yield TextNode(
            path=base.child(key_step("title")),
            tag=_to_amulet(title),
            category="advancement_title",
            anchor=_ANCHOR,
        )

    description = display.get("description")
    if description is not None:
        yield TextNode(
            path=base.child(key_step("description")),
            tag=_to_amulet(description),
            category="advancement_description",
            anchor=_ANCHOR,
        )


def _to_amulet(value: Any):
    """一個原生 JSON 值（`str`/`dict`/`list`）→ 對應的 `amulet_nbt` 標籤，
    好讓既有的 `sniff()`/`flatten()` 管線原封不動地吃得下它。

    **`list` 分支需要同質化。** `amulet_nbt.ListTag` 在建構當下要求所有元素是
    同一個 NBT 型別；而 Minecraft 官方的文字 component 陣列語法
    `["", {...}, {...}]`（第一個元素是父級裸字串或物件、其餘是 extra 物件）本來
    就允許異質陣列——裸字串與物件混在一起。直接逐元素轉換再塞進 `ListTag` 建構
    子在真實資料上會立刻炸掉（`TypeError: Invalid type CompoundTag for
    ListTag(list_data_type=8)`）。

    做法：先照常遞迴轉換每個元素；若轉換後的清單同時含有 `CompoundTag` 與其他
    型別（也就是還不同質），把清單裡的 `StringTag` 元素升格成
    `CompoundTag({"text": <原字串內容>})`，讓整份清單都是 `CompoundTag` 之後
    再建構 `ListTag`。這個升格語意無損：`model/segments.py` 的 `_walk()` 對
    `{"text": s}`（沒有其他鍵）與裸字串 `s` 的處理完全等價——兩者的 `style`
    都算出空字典、`inherited_sigma` 也不變，最終都呼叫
    `_emit_string(literal=s, style={}, node_type="text")`，`flatten()` 輸出
    位元組相同。
    """
    if isinstance(value, str):
        return amulet_nbt.StringTag(value)
    if isinstance(value, dict):
        return amulet_nbt.CompoundTag({str(k): _to_amulet(v) for k, v in value.items()})
    if isinstance(value, list):
        elements = [_to_amulet(v) for v in value]
        types = {type(e) for e in elements}
        if len(types) > 1 and amulet_nbt.CompoundTag in types:
            elements = [
                amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(str(e))})
                if isinstance(e, amulet_nbt.StringTag)
                else e
                for e in elements
            ]
        return amulet_nbt.ListTag(elements)
    return amulet_nbt.StringTag(str(value))


def _container(relative_path) -> dict:
    return {
        "kind": "datapack_file",
        "path": str(relative_path).replace("\\", "/"),
        "dimension": None,
        "chunk": None,
        # datapack 檔案沒有 DataVersion 這回事——它不是版本化的 NBT 文件，是
        # 一份普通 JSON。null 是合法值（合約 `data_version` 型別是
        # `["integer","null"]`），而且 _consider() 的舊式 JSON 判斷只在
        # encoding 是四種 json_* 之一時才會用到這個值，advancement 的值永遠是
        # bare_string/text_compound/compound_tree，走不到那個分支。
        "data_version": None,
        "compression": None,
        "external": False,
    }
