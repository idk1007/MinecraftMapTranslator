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
        # **`**` 不能省。** `glob` 的 `*` 不跨目錄分隔符，而原版自己的進度就是分
        # 在 `story/`、`nether/`、`end/` 這些子資料夾裡；只寫 `*.json` 的話那些
        # 檔案對資料夾式資料包**完全隱形**，症狀和「這個資料包沒有進度」一模
        # 一樣。zip 那邊本來就是遞迴找得到的，兩種形式必須是同一條規則。
        for path in pack_dir.glob(f"data/*/{dir_name}/**/*.json"):
            relative = path.relative_to(world)
            try:
                document = json.loads(path.read_bytes().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                stats["skipped_advancement_unparseable"] += 1
                continue
            yield from _scan_one(document, _container(relative), stats)


def _scan_zip_pack(world, zip_path: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    zip_relative = zip_path.relative_to(world)
    try:
        with zipfile.ZipFile(str(zip_path)) as archive:
            names = [name for name in archive.namelist() if _is_advancement_entry(name)]
            for name in sorted(names):
                try:
                    document = json.loads(archive.read(name).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    stats["skipped_advancement_unparseable"] += 1
                    continue
                yield from _scan_one(document, _container(f"{zip_relative}/{name}"), stats)
    except (zipfile.BadZipFile, OSError):
        stats["skipped_datapack_zip"] += 1


def _is_advancement_entry(name: str) -> bool:
    """zip 條目路徑是不是 `data/<ns>/advancement(s)/…/*.json`。

    **比對的是路徑片段，不是子字串。** 原本寫的是
    `any(f"/{d}/" in f"/{name}" …)`，那會讓
    `data/n/advancement_helpers/advancements/x.json` 這種名字裡剛好含有
    `/advancement…/` 的路徑一起中獎；更重要的是它和資料夾式那邊的
    `data/*/<dir>/…` 不是同一條規則，兩種形式對同一個資料包會給出不同的答案。
    """
    parts = name.split("/")
    return (
        name.endswith(".json")
        and len(parts) >= 4
        and parts[0] == "data"
        and parts[2] in _ADVANCEMENT_DIR_NAMES
    )


def _scan_one(document, container: dict, stats: Counter) -> Iterator[ScannedNode]:
    """掃一個 advancement 檔案，**把它的例外關在自己這一個檔案裡**。

    `sources/region.py` 對一張讀不下去的 region 就是這樣處理的：壞掉的世界更
    需要能先掃出能掃的部分。這裡的具體風險是 `_to_amulet()` 的 `ListTag` 建構
    ——`amulet_nbt` 要求 list 元素同型，而文字 component 陣列語法天生允許異質。
    同質化已經把已知的形狀處理掉了，但「一個沒想到的形狀就帶走整個資料包的
    掃描」這個結構本身才是問題，所以這裡接住的是任何例外，不是某一種。

    `scan_advancement` 是產生器，例外會在迭代當下才浮出來，所以要一個一個取。
    例外之前已經 yield 出去的節點（例如 title 好的、description 壞的）保留，
    這和 `list()` 整份收集完再迭代的差別正是 CLAUDE.md 點名過的那一條。
    """
    stats["advancement_files"] += 1
    iterator = scan_advancement(document)
    while True:
        try:
            node = next(iterator)
        except StopIteration:
            return
        except Exception:  # noqa: BLE001 —— 任何轉不出去的形狀都一樣：算一筆，跳過
            stats["skipped_advancement_shape"] += 1
            return
        yield ScannedNode(node=node, container=container)


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

    做法：先照常遞迴轉換每個元素；若轉換後的清單**不同質**，把每個不是
    `CompoundTag` 的元素升格成 `CompoundTag`，讓整份清單都是 `CompoundTag`
    之後再建構 `ListTag`。

    升格有兩種，兩種都是語意無損的：

    * **裸字串** `s` → `{"text": s}`。`model/segments.py` 的 `_walk()` 對兩者
      的處理完全等價——`style` 都算出空字典、`inherited_sigma` 也不變，最終都
      呼叫 `_emit_string(literal=s, style={}, node_type="text")`。
    * **巢狀陣列** `[p, *rest]` → 它本來就是一棵 component 樹（第一元素是父級、
      其餘是 extra），所以升格成「父級 + `extra`」的 compound 形式。這是原本
      漏掉的一種：Task 5 的條件寫成「同時含有 `CompoundTag` 與其他型別」，而
      `["a", ["b"]]` 的型別集合是 `{StringTag, ListTag}`——沒有 `CompoundTag`，
      條件不成立，於是原封不動地送進 `ListTag(...)` 當場 `TypeError`，而且
      **沒有任何一層接得住**，一個檔案就帶走整個資料包的掃描。
    """
    if isinstance(value, str):
        return amulet_nbt.StringTag(value)
    if isinstance(value, dict):
        return amulet_nbt.CompoundTag({str(k): _to_amulet(v) for k, v in value.items()})
    if isinstance(value, list):
        elements = [_to_amulet(v) for v in value]
        if len({type(e) for e in elements}) > 1:
            elements = [_as_component_compound(e) for e in elements]
        return amulet_nbt.ListTag(elements)
    return amulet_nbt.StringTag(str(value))


def _as_component_compound(tag):
    """任一個文字 component 標籤 → `CompoundTag` 形式，攤平結果不變。

    巢狀陣列那一支要特別小心父級**自己也有 `extra`** 的情況：
    `[{"text":"x","extra":[A]}, B]` 的 `A` 與 `B` 都會被 `_walk()` 走到、都會
    貢獻文字，所以合併時要 `A` 在前、`B` 在後，不能用 `B` 蓋掉 `A`——蓋掉的話
    `A` 那段文字就從 `source.text` 裡消失了，而那是地圖作者寫的字。
    """
    if isinstance(tag, amulet_nbt.CompoundTag):
        return tag
    if isinstance(tag, amulet_nbt.StringTag):
        return amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(str(tag))})
    if isinstance(tag, amulet_nbt.ListTag):
        elements = list(tag)
        if not elements:
            return amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("")})
        parent = _as_component_compound(elements[0])
        extra = [_as_component_compound(e) for e in parent.get("extra", []) or []]
        extra += [_as_component_compound(e) for e in elements[1:]]
        merged = amulet_nbt.CompoundTag({str(k): v for k, v in parent.items()})
        if extra:
            merged["extra"] = amulet_nbt.ListTag(extra)
        return merged
    return amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(str(tag))})


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
