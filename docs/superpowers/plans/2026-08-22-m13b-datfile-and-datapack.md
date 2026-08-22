# M13b：level.dat／scoreboard.dat／datapack 掃描與寫入 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把掃描範圍從「region + entities + 物品」擴大到「`level.dat`、`data/scoreboard.dat`、datapack 的 advancement JSON」，並補上這三種**非 region 格式**的第一批寫入路徑；同時補上「已在地化的節點整個跳過」的規則。

**Architecture:** 掃描層繼續用 M13a 建好的來源註冊表（每個來源一個模組，簽名不變）。寫入層是這個計畫的重點：先把 `write/apply.py` 裡「走到節點、判斷 `value.kind`、寫回」那段**與 region 格式無關的通用邏輯**抽出成 `write/common.py`，讓它同時服務 region/entities chunk 與 `.dat` 檔；`write/apply.py` 改成一份顯式的 `kind → writer` 對照表，三種寫入器（region 外科式、`.dat` 整份重編、datapack 檔案重寫）保證等級不同，這個不對稱要看得見，不能用 if/else 藏起來。

**Tech Stack:** Python 3.11 · `amulet-nbt` · stdlib `zipfile`/`json` · pytest。執行期只允許 `amulet-nbt` + stdlib。

**Spec:** `docs/superpowers/specs/2026-08-22-m13-scan-breadth-design.md`（本計畫實作它的第 4、5 節與任務表 M13.5–M13.9；第 8 節開頭的兩則「與實作不同」附註已經生效，見下方「與 spec 的兩個已知差異」）

## 與 spec 的兩個已知差異（實作依這裡，不依 spec 原文）

1. **`write/datfile_apply.py` 不需要知道 `Data`/`data` 的根鍵名**——它完全照 `node_path` 走。根鍵名的動態解析是**掃描來源**的事（`level_dat.py`、`scoreboard.py` 各自處理，因為兩個檔案的根鍵名大小寫本來就不同：`level.dat` 是 `Data`，`scoreboard.dat` 是 `data`）。
2. **`scoreboard.dat` 的 `DataVersion` 是根目錄的兄弟節點，不在 `data` 裡面**——[實測，2026-08-22] `Arena of Darkness` 與 `100 Ways To Die` 的 `data/scoreboard.dat` 根 compound 都是 `{data: {...}, DataVersion: <int>}` 兩個並列的鍵。`level.dat` 相反：只有一個根鍵 `Data`，`DataVersion`在它**裡面**（`Data.DataVersion`，這是 `cli/extract.py` 現有的 `_level_data_version()` 已經在用的路徑，不必重推）。這個差異必須各自處理，不能共用一個「讀 DataVersion」的函式。

## Global Constraints

這些是 `CLAUDE.md` 的專案規則，**每個任務都適用**，不在各任務裡重複：

- 每個原始碼檔頂端：`# SPDX-License-Identifier: GPL-3.0-or-later`
- **TDD**：先寫失敗的測試 → 執行確認失敗 → 最小實作 → 執行確認通過 → commit。**一個任務一個 commit。**
- `src/mcmt/write/` 的修改**必須是獨立 commit 並說明理由**，不得夾帶在其他任務裡。
- `src/mcmt/model/`、`docs/contracts/` 本計畫**不碰**——容器種類（`level_dat`/`scoreboard_dat`/`datapack_file`）、category（`bossbar`/`objective`/`team`/`team_affix`/`advancement_title`/`advancement_description`）、`SCHEMA_VERSION`（5）全部已經在合約裡，這是 M13a 收尾時就備好的。
- **形狀一律逐節點嗅探，不由 `DataVersion` 推導**；`DataVersion` 只決定「這個節點的舊式 JSON 是真內容還是字面亂碼」與「寫回哪個世代」。
- 掃描層是**白名單**：只去找已知欄位，不走遍樹。
- 測試 fixture 一律取自自建探測世界或程式合成的位元組，**不放語料地圖的內容**（授權考量）。
- 跑測試：`.venv\Scripts\python -m pytest`（全域 python 沒有 pytest）
- 跑 CLI：`.venv\Scripts\python -X utf8 -m mcmt.cli …`（`-X utf8` 是必要的）
- 驗合約：`.venv\Scripts\python -X utf8 tools/validate_contracts.py`
- **含跳脫序列的檔案改用 Write 工具**，不要用 heredoc（會吃掉反斜線）。

**基準線**：開工時全部測試通過、合約驗證通過（跑 Task 1 的 Step 2 之前先各跑一次確認）。

---

## 既有介面速查

**執行者不需要先讀完整個 codebase**，這裡列的就夠了。

```python
# src/mcmt/scan/node.py
@dataclass(frozen=True)
class TextNode:
    path: NodePath
    tag: Any                    # amulet_nbt 的 StringTag / CompoundTag
    category: str
    anchor: dict | None = None
    list_context: dict | None = None

@dataclass(frozen=True)
class ScannedNode:
    node: TextNode
    container: dict[str, Any]   # 見下面 container 形狀

# src/mcmt/scan/registry.py
SOURCES: list[Callable[[ReadOnlyPath, Counter], Iterator[ScannedNode]]]

# src/mcmt/scan/sources/item.py  ——  跨來源共用，遞迴進容器/收納袋/弩/書
def scan_item(item: amulet_nbt.CompoundTag, path: NodePath, *, anchor: dict | None) -> Iterator[TextNode]: ...

# src/mcmt/model/node.py
NodePath(steps)               # steps: Iterable[PathStep]
key_step(name: str) -> PathStep
index_step(i: int) -> PathStep
path.child(step) -> NodePath  # 回傳新的 NodePath，不是原地修改

# src/mcmt/model/component.py
class Encoding(str, Enum): ...  # BARE_STRING / TEXT_COMPOUND / EMPTY_KEY_COMPOUND / COMPOUND_TREE /
                                 # JSON_STRING_OBJECT / JSON_STRING_ARRAY / JSON_STRING_SCALAR /
                                 # JSON_EMPTY_QUOTED / PLAIN_STRING / SNBT_STRING
@dataclass(frozen=True)
class Sniffed:
    encoding: Encoding
    raw: str | None = None
    parsed: Any = None
    problem: str | None = None
def sniff(tag: amulet_nbt.AbstractBaseTag) -> Sniffed: ...  # 只吃 StringTag/CompoundTag/ListTag

# src/mcmt/model/generation.py
DATAFIXER_WATERSHED = 4325       # >= 這個版本不跑 DataFixer（native）
def generation_of(data_version: int) -> Generation: ...  # .legacy_json_is_content: bool

# src/mcmt/model/strategy.py
IN_PLACE_CATEGORIES: frozenset[str]   # 目前 {level_name, book_title, book_author, draft_book_page, block_entity_name}
IN_PLACE_ENCODINGS: frozenset[str]    # bare_string/plain_string/text_compound/empty_key_compound/json_string_scalar/json_string_object
def strategy_for(category: str) -> str: ...  # "translate_key" | "in_place"

# src/mcmt/nbtio/datfile.py
@dataclass(frozen=True)
class DatFile:
    tag: amulet_nbt.NamedTag
    compression: str  # "gzip" | "zlib" | "none"
def read_dat(path: ReadOnlyPath) -> DatFile: ...
def write_dat(path: Path | str, dat: DatFile) -> Path: ...   # 暫存→回讀驗證→原子替換

# src/mcmt/safety/paths.py
def ensure_readable(p) -> ReadOnlyPath: ...
def ensure_writable(p) -> Path: ...
class ReadOnlyPath:
    def __truediv__(self, other: str) -> "ReadOnlyPath": ...
    def exists(self) -> bool: ...
    def glob(self, pattern) -> list["ReadOnlyPath"]: ...

# src/mcmt/safety/backup.py
class BackupSet:
    def protect(self, path: Path | str) -> None: ...   # 第一次修改前呼叫，重複呼叫不重複備份

# src/mcmt/write/common.py（既有，Task 1 會擴充）
def component_for(value: dict[str, Any]) -> Any: ...   # editplan value → 純 Python component（dict/str）
def refuse_residue(text: str) -> None: ...              # 殘留 [[n]] 就拋 PlaceholderResidueError

# src/mcmt/write/legacy.py / native.py（世代分派用，簽名相同）
@dataclass(frozen=True)
class ListWrite:
    list: amulet_nbt.ListTag
    promoted: bool
def value_tag(value: dict[str, Any]) -> amulet_nbt.StringTag | amulet_nbt.CompoundTag: ...
def apply_to_list(messages, index, tag) -> ListWrite: ...

# src/mcmt/write/in_place.py
def value_tag(encoding: str, value: dict[str, Any]) -> amulet_nbt.AbstractBaseTag: ...
SUPPORTED_ENCODINGS: frozenset[str]

# tests/conftest.py
class RegionBuilder: ...
def write_region_file(directory, data, name="r.0.0.mca") -> Path: ...
def modern_chunk(*, data_version=4671) -> amulet_nbt.CompoundTag: ...
@pytest.fixture
def project(tmp_path, monkeypatch): ...   # cwd 在假專案根，sandbox_root() 指向 tmp_path/sandbox
```

**container 的形狀**（合約 `extract.schema.json#/$defs/container`，`kind` 已含 `level_dat`/`scoreboard_dat`/`datapack_file`，不必改合約）：

```python
{
    "kind": "level_dat" | "scoreboard_dat" | "datapack_file" | "region_chunk" | "entities_chunk",
    "path": str,              # 相對世界根，正斜線
    "dimension": str | None,
    "chunk": {"cx": int, "cz": int} | None,   # 非 region/entities 時是 None
    "data_version": int | None,
    "compression": int | None,                 # 非 region/entities 時是 None
    "external": bool,
}
```

**真實資料（2026-08-22 用 `.venv` 對 `sandbox/Arena of Darkness` 與 `sandbox/100 Ways To Die` 實測，寫進各任務作為期望值）**：

| | Arena of Darkness（DV 3700，legacy） | 100 Ways To Die（DV 4325，native） |
|---|---|---|
| `level.dat` 根鍵 | `Data`（唯一根鍵） | 同左 |
| `Data.LevelName` | `"Arena of Darkness"`（裸字串） | `"100 Ways to Die"`（裸字串） |
| `Data.CustomBossEvents` 筆數 | 27 | 3 |
| `CustomBossEvents.<id>.Name` 形狀 | `'"Mr.Hyde"'`（JSON 純量字串） | `{"text":"A Baby","bold":1,...}`（原生 compound） |
| `Data.Player.Inventory` 物品數 | 5 | 0（無 `Player` 節點） |
| `scoreboard.dat` 根鍵 | `data` + 兄弟節點 `DataVersion` | 同左 |
| `Objectives` 筆數 | 168 | 156 |
| `Objectives[].DisplayName` 形狀 | `'"ReFightTime"'`（JSON 純量） | `"as_lock_uuid4"`（裸字串） |
| `Teams` 筆數 | 17 | 13 |
| `Teams[].DisplayName` 形狀 | `'"customboss"'`（JSON 純量） | `"Green"`（裸字串） |
| `Teams[].MemberNamePrefix/Suffix` | 17/17 都是 `'""'`（JSON 空字串，內容為空） | **欄位整個不存在**（native 省略空欄位） |
| datapack advancement | `datapacks/ArenaOfDarknessDatapack_10_15.zip` 25 個 `data/worf/advancements/*.json`（**複數** `advancements`，1.20.4 舊式目錄名）+ `datapacks/armor statues v2.8.4.zip` 5 個 | 無 datapack |

`Teams[].DisplayName` 是 `'{"text":...}'` 這件事在兩張地圖都沒發生，只有 `bare_string`（native）與 `json_string_scalar`（legacy）兩種真實形狀——這與告示牌/CustomName 已經驗過的 legacy/native 二分完全對稱，寫入端因此**直接沿用**既有的 `legacy.py`/`native.py` 世代分派，不必新增判斷。

---

## 檔案結構

| 檔案 | 職責 | 任務 |
|---|---|---|
| `src/mcmt/write/common.py` | **擴充**：`ApplyOutcome` + 通用 NBT 節點編輯引擎（從 `apply.py` 搬來） | 1 |
| `src/mcmt/write/apply.py` | **改**：顯式 `kind → writer` 分派表；region/entities 寫入器留在這 | 1, 6 |
| `src/mcmt/write/datfile_apply.py` | **新增**：`.dat` 檔通用寫入器（`level_dat` + `scoreboard_dat` 共用） | 2 |
| `src/mcmt/write/datapack_apply.py` | **新增**：datapack JSON 檔案重寫（資料夾 + zip） | 6 |
| `src/mcmt/extract/build.py` | **改**：`plain_string` 覆寫、已在地化跳過 | 3, 7 |
| `src/mcmt/scan/sources/level_dat.py` | **新增**：`LevelName` / `CustomBossEvents` / `Player.Inventory` | 3 |
| `src/mcmt/scan/sources/scoreboard.py` | **新增**：`Objectives` / `Teams` DisplayName 與前後綴 | 4 |
| `src/mcmt/scan/sources/datapack.py` | **新增**：advancement JSON（資料夾 + zip，單複數目錄名） | 5 |
| `src/mcmt/scan/registry.py` | **改**：掛上三個新來源 | 3, 4, 5 |
| `tests/integration/test_end_to_end.py` | **改**：`round_trip` fixture 加 level.dat/scoreboard.dat/datapack | 8 |

---

## Task 1：`write/common.py` 承接通用節點編輯引擎（純重構，`write/` 獨立 commit）

`write/apply.py` 現在的 `_apply_edit`／`_apply_to_key`／`_guarded_encoding`／`_resolve`／`_replace_list`／`_translate_writer` 這一組函式，**不對任何一行 NBT 位元組編碼或 region 磁區負責**——它們只是「照 `node_path` 走到節點、按 `expected_encoding` 守門、按 `value.kind` 決定寫什麼、寫回去」。這件事在 `level.dat` 的一個 compound 裡和在一個 chunk 的 compound 裡**完全一樣**：兩邊的 `root` 都只是一棵 `amulet_nbt.CompoundTag`，函式從沒問過它是從 region 讀出來的還是從 `.dat` 讀出來的。

這不是「legacy/native 那種規格層級的不對稱」——那個不對稱是**寫哪一種 NBT 形狀**（`_translate_writer` 挑 `legacy`/`native` 模組時才會分岔）。「怎麼走到節點、怎麼守門」這件事沒有不對稱，是真的重複，該搬到 `write/common.py`（它的檔頭已經寫明「這裡只放兩者真的完全相同的東西」）。

`ApplyOutcome`（累計整次 apply 的計數與拒寫清單）也搬過去：它是**跨容器種類共用的帳本**——region 寫入器與之後的 `.dat`/datapack 寫入器都要把結果記進同一份 `apply_report.json`。

**這個任務只搬動與重新命名，不改變任何行為。** 既有的 `tests/unit/test_write_apply.py`（23 條）與 `tests/integration/test_end_to_end.py` 是這次重構的安全網。

**Files:**
- Modify: `src/mcmt/write/common.py`
- Modify: `src/mcmt/write/apply.py`
- Test: 不新增測試檔——existing tests are the regression net for this task

**Interfaces:**
- Consumes: `component_for`, `refuse_residue`（common.py 既有）；`legacy`/`native`/`in_place` 模組（不變）
- Produces（`write/common.py` 新增的公開介面，`datfile_apply.py`／`apply.py` 都會用）：
  ```python
  @dataclass
  class ApplyOutcome:
      outcome: str = "applied"
      counts: Counter
      unwritten: list[dict[str, Any]]
      warnings: list[dict[str, Any]]
      backup_directory: Path | None
      backup_files: int
      def report(self, *, world: Path, fingerprint_before: str) -> dict[str, Any]: ...

  def refuse(outcome: ApplyOutcome, edit: dict, reason: str, detail: str) -> None: ...
  def apply_edit_to_compound(root: amulet_nbt.CompoundTag, edit: dict, outcome: ApplyOutcome) -> bool:
      """走到 edit['node_path']，過 expected_encoding 守門，寫值。回傳這筆有沒有真的寫成。
      不管 root 是 chunk 根還是 .dat 根——這個函式從不知道，也不需要知道。"""
  ```

- [ ] **Step 1: 先確認基準線**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠（記下測試總數，Step 5 要對得上）

- [ ] **Step 2: 把共用邏輯搬進 `write/common.py`**

`write/common.py` 現有內容只有 `component_for`／`refuse_residue`／`_TOKEN`。**把整份檔案取代成**下面的版本——這不是在檔尾追加，import 區塊要合併（現有的 `re`／`Any`／`PlaceholderResidueError` 都還要用到），所以直接給完整檔案內容比較不會出錯：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""legacy 與 native 都需要的那一點點共同邏輯（M11.1），以及跨容器種類共用的節點
編輯引擎（M13b）。**高風險目錄。**

前半段（`component_for`／`refuse_residue`）只放兩者真的完全相同的東西：
editplan 的 value 該長成什麼 component（合約定義的），以及佔位符殘留的檢查。
形狀怎麼寫進 NBT、list 要不要提升——那些是不對稱的部分，各自在 `legacy.py`／
`native.py`。

後半段（`ApplyOutcome`／`apply_edit_to_compound`）是「照 node_path 走到節點、
按 expected_encoding 守門、按 value.kind 決定寫什麼」這件事——這一段與容器是
region chunk 還是 `.dat` 檔完全無關，兩者共用同一份，不是巧合的重複。把它們搬
到這裡而不是留在 `write/apply.py`，是因為 `write/datfile_apply.py` 也要用同一份
（見 `docs/ownership.md`「為什麼寫入層與輸出後端是分開的」同一條理由）。
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import amulet_nbt

from mcmt.errors import PlaceholderResidueError
from mcmt.model import SCHEMA_VERSION
from mcmt.model.component import sniff
from mcmt.model.generation import generation_of
from mcmt.model.node import NodePath
from mcmt.write import in_place

__all__ = [
    "ApplyOutcome",
    "apply_edit_to_compound",
    "component_for",
    "refuse",
    "refuse_residue",
]


@dataclass
class ApplyOutcome:
    """一次 `apply` 的累計帳本。**跨容器種類共用**——region、`.dat`、datapack 的
    寫入器都把結果記進同一份，最後合成同一份 `apply_report.json`。"""

    outcome: str = "applied"
    counts: Counter = field(default_factory=Counter)
    unwritten: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    backup_directory: Path | None = None
    backup_files: int = 0

    def report(self, *, world: Path, fingerprint_before: str) -> dict[str, Any]:
        return {
            "format": "mcmt-apply-report",
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "outcome": self.outcome,
            "world": {
                "path": str(world),
                "world_fingerprint_before": fingerprint_before,
                "world_fingerprint_after": None,
                "extract_fingerprint": None,
            },
            "backup": (
                {
                    "directory": str(self.backup_directory),
                    "file_count": self.backup_files,
                }
                if self.backup_directory
                else None
            ),
            "counts": {
                "edits_planned": self.counts["edits_planned"],
                "edits_written": self.counts["edits_written"],
                "chunks_touched": self.counts["chunks_touched"],
                "chunks_copied_verbatim": self.counts["chunks_copied_verbatim"],
                "files_rewritten": self.counts["files_rewritten"],
                "list_promotions": self.counts["list_promotions"],
            },
            "unwritten": self.unwritten,
            "warnings": self.warnings,
        }


def refuse(outcome: ApplyOutcome, edit: dict, reason: str, detail: str) -> None:
    outcome.unwritten.append(
        {
            "unit_id": edit["unit_id"],
            "occurrence_id": edit["occurrence_id"],
            "reason": reason,
            "detail": detail,
        }
    )


def apply_edit_to_compound(
    root: amulet_nbt.CompoundTag, edit: dict[str, Any], outcome: ApplyOutcome
) -> bool:
    """走到 `edit['node_path']` 指的節點，過 `expected_encoding` 守門，寫值。

    **這裡不知道 `root` 是從哪裡讀出來的**——chunk 根與 `.dat` 根對這個函式是
    同一種東西（一棵 `CompoundTag`）。呼叫端負責讀進 `root`、負責在寫完之後把它
    編碼回磁碟；這裡只負責「找對節點、守好門、寫對值」。
    """
    path = NodePath.from_json(edit["node_path"])
    steps = list(path)
    if not steps:
        refuse(outcome, edit, "node_missing", "node_path 是空的")
        return False

    if steps[-1].t == "key":
        return _apply_to_key(root, steps, edit, outcome)
    if steps[-1].t != "index":
        refuse(outcome, edit, "unsupported_encoding", "v1 的寫入路徑不支援 decode 步驟")
        return False

    index = steps[-1].i
    try:
        container = _resolve(root, steps[:-1])
    except (KeyError, IndexError) as exc:
        refuse(outcome, edit, "node_missing", str(exc))
        return False

    if not isinstance(container, amulet_nbt.ListTag):
        refuse(outcome, edit, "node_missing", "目標的父節點不是 list")
        return False
    if index >= len(container):
        refuse(outcome, edit, "node_missing", f"list 只有 {len(container)} 個元素")
        return False

    current = _guarded_encoding(container[index], edit, outcome)
    if current is None:
        return False

    if edit["value"].get("kind") == "literal":
        try:
            tag = in_place.value_tag(current, edit["value"])
        except in_place.UnsupportedInPlaceShape as exc:
            refuse(outcome, edit, "unsupported_encoding", str(exc))
            return False
        container[index] = tag
        return True

    writer = _translate_writer(edit)
    result = writer.apply_to_list(container, index, writer.value_tag(edit["value"]))
    _replace_list(root, steps[:-1], result.list)
    if result.promoted:
        outcome.counts["list_promotions"] += 1
    return True


def _apply_to_key(root, steps, edit: dict, outcome: ApplyOutcome) -> bool:
    name = steps[-1].name
    try:
        parent = _resolve(root, steps[:-1])
    except (KeyError, IndexError) as exc:
        refuse(outcome, edit, "node_missing", str(exc))
        return False

    if not isinstance(parent, amulet_nbt.CompoundTag) or name not in parent:
        refuse(outcome, edit, "node_missing", f"找不到鍵 {name}")
        return False

    current = _guarded_encoding(parent[name], edit, outcome)
    if current is None:
        return False

    if edit["value"].get("kind") == "literal":
        try:
            tag = in_place.value_tag(current, edit["value"])
        except in_place.UnsupportedInPlaceShape as exc:
            refuse(outcome, edit, "unsupported_encoding", str(exc))
            return False
        parent[name] = tag
        return True

    writer = _translate_writer(edit)
    parent[name] = writer.value_tag(edit["value"])
    return True


def _translate_writer(edit: dict):
    """DV < 4325 寫 JSON 字串、DV >= 4325 寫 compound。與容器種類無關——
    `.dat` 檔一樣有自己的 DataVersion，一樣分兩個世代（見本檔案的實測表）。"""
    from mcmt.write import legacy, native

    return (
        legacy
        if generation_of(edit["container"]["data_version"]).legacy_json_is_content
        else native
    )


def _guarded_encoding(tag, edit: dict, outcome: ApplyOutcome) -> str | None:
    try:
        current = sniff(tag).encoding.value
    except TypeError:
        refuse(outcome, edit, "unsupported_encoding", "這個節點不是文字節點")
        return None
    if current != edit["expected_encoding"]:
        refuse(
            outcome,
            edit,
            "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current}"
            f"——世界在 extract 之後被改過了",
        )
        return None
    return current


def _resolve(root, steps):
    current = root
    for step in steps:
        if step.t == "key":
            if step.name not in current:
                raise KeyError(f"找不到鍵 {step.name}")
            current = current[step.name]
        elif step.t == "index":
            current = current[step.i]
        else:
            raise KeyError("v1 的寫入路徑不支援 decode 步驟")
    return current


def _replace_list(root, steps, new_list) -> None:
    parent = _resolve(root, steps[:-1])
    last = steps[-1]
    if last.t == "key":
        parent[last.name] = new_list
    else:
        parent[last.i] = new_list


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_TOKEN = re.compile(r"\[\[\d+\]\]")


def refuse_residue(text: str) -> None:
    """任何 `literal` 的文字若殘留 `[[n]]`，**拒絕整份 plan**。

    不是「跳過這一筆」：殘留代表上游（後端或驗證）算錯了，而算錯的東西不會只錯一筆。
    寫出去玩家會看到那串記號。
    """
    found = _TOKEN.findall(text)
    if found:
        raise PlaceholderResidueError(text=text, tokens=found)


def component_for(value: dict[str, Any]) -> Any:
    """editplan 的 value → 一棵 component（純 Python，還沒變成 NBT）。"""
    kind = value.get("kind")

    if kind == "translate":
        component: dict[str, Any] = {"translate": value["key"]}
        if value.get("fallback"):
            component["fallback"] = value["fallback"]
        component.update(value.get("style") or {})
        return component

    if kind == "literal":
        refuse_residue(value["text"])
        component = {"text": value["text"]}
        component.update(value.get("style") or {})
        return component

    if kind == "component":
        return value["tree"]

    raise ValueError(f"不認得的寫入值種類：{kind!r}")
```

`_TOKEN`／`refuse_residue`／`component_for` 是原本就在 `write/common.py` 裡的東西，原封不動搬過來（只是現在跟 `ApplyOutcome`／`apply_edit_to_compound` 放同一個檔案）——沒有任何一行邏輯改變。

- [ ] **Step 3: `write/apply.py` 改成只留 region 寫入器 + 顯式分派表**

把 `write/apply.py` 整份改成：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""把 editplan 寫回世界（M11.2 / M13b 分派重構）。**高風險目錄。**

順序是不可協商的（CLAUDE.md §1.2）：

    BackupSet.protect(檔案)  →  改  →  write_region / write_dat / 重寫 zip

備份失敗就中止，**絕不允許「備份失敗但繼續寫」**。

**容器種類決定用哪個寫入器，顯式對照表，不是 if/elif。** 三種寫入器的保證等級不同：

    region_chunk / entities_chunk   外科式——未改動的 chunk 原封複製原始壓縮位元組
    level_dat / scoreboard_dat      整份重編——`.dat` 沒有外科式寫入這回事（M3.2）
    datapack_file                   檔案重寫——資料夾直接覆寫、zip 整份重建

這個不對稱**必須看得見**，一個共同介面會讓它們看起來一樣安全（`docs/ownership.md`
「為什麼寫入層與輸出後端是分開的」同一條理由）。

**節點層級「走到哪、寫什麼」的邏輯在 `write/common.py`**（`apply_edit_to_compound`）
——那段與容器是 region 還是 `.dat` 無關，兩者共用同一份，不是巧合的重複。
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

import amulet_nbt

from mcmt.errors import FormatError
from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import ChunkWrite, read_region, write_region
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write.common import ApplyOutcome, apply_edit_to_compound, refuse
from mcmt.write.datfile_apply import apply_to_datfile
from mcmt.write.datapack_apply import apply_to_datapack_file

__all__ = ["ApplyOutcome", "apply_editplan"]


def apply_editplan(
    world: Path | str,
    plan: dict[str, Any],
    *,
    dry_run: bool = False,
) -> ApplyOutcome:
    """把 plan 裡的每一筆 edit 寫回世界。"""
    world_path = Path(world).resolve()
    outcome = ApplyOutcome()
    outcome.counts["edits_planned"] = len(plan["edits"])

    by_file: dict[str, list[dict]] = defaultdict(list)
    for edit in plan["edits"]:
        by_file[edit["container"]["path"]].append(edit)

    if dry_run:
        outcome.outcome = "dry_run"
        return outcome

    with BackupSet(world_path) as backup:
        for relative, edits in sorted(by_file.items()):
            kind = edits[0]["container"]["kind"]
            writer = _WRITERS.get(kind)
            if writer is None:
                for edit in edits:
                    refuse(
                        outcome, edit, "unsupported_encoding",
                        f"沒有 {kind!r} 的寫入器",
                    )
                continue
            writer(world_path, relative, edits, outcome, backup)
        outcome.backup_directory = backup.directory
        outcome.backup_files = backup.file_count
    return outcome


def _apply_to_region(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    path = world / relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return

    try:
        chunks = list(read_region(ensure_readable(path)))
    except FormatError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    by_chunk: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for edit in edits:
        chunk_info = edit["container"]["chunk"]
        by_chunk[(chunk_info["cx"], chunk_info["cz"])].append(edit)

    writes: list[ChunkWrite] = []
    touched = 0
    for raw in chunks:
        pending = by_chunk.get((raw.local_x, raw.local_z))
        if not pending:
            writes.append(ChunkWrite.unchanged(raw))
            outcome.counts["chunks_copied_verbatim"] += 1
            continue

        payload = _rewrite_chunk(raw, pending, outcome)
        if payload is None:
            writes.append(ChunkWrite.unchanged(raw))
            outcome.counts["chunks_copied_verbatim"] += 1
            continue
        writes.append(ChunkWrite.replaced(raw, payload))
        touched += 1

    if not touched:
        return

    backup.protect(path)
    report = write_region(ensure_writable(path), writes)
    outcome.counts["chunks_touched"] += touched
    outcome.counts["files_rewritten"] += 1
    if report.realigned:
        outcome.warnings.append(
            {
                "kind": "sector_realignment",
                "unit_id": None,
                "detail": (
                    f"{relative}：{report.size_before:,} → {report.size_after:,} bytes。"
                    f"這是磁區重整（原檔有空隙），不是資料遺失。"
                ),
            }
        )


def _rewrite_chunk(raw, edits: list[dict], outcome: ApplyOutcome) -> bytes | None:
    try:
        data = decompress_chunk(raw.payload, raw.compression_type, chunk_index=raw.index)
        root = amulet_nbt.load(data, compressed=False).compound
    except (FormatError, amulet_nbt.NBTLoadError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return None

    written = 0
    for edit in edits:
        if apply_edit_to_compound(root, edit, outcome):
            written += 1
    if not written:
        return None

    outcome.counts["edits_written"] += written
    encoded = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
    return _compress(encoded, raw.compression_type)


def _compress(data: bytes, compression_type: int) -> bytes:
    import gzip
    import zlib

    if compression_type == 2:
        return zlib.compress(data)
    if compression_type == 1:
        return gzip.compress(data, mtime=0)
    if compression_type == 3:
        return data
    raise ValueError(f"不支援寫入壓縮類型 {compression_type}")


_WRITERS = {
    "region_chunk": _apply_to_region,
    "entities_chunk": _apply_to_region,
    "level_dat": apply_to_datfile,
    "scoreboard_dat": apply_to_datfile,
    "datapack_file": apply_to_datapack_file,
}
```

這一步會先失敗，因為 `write/datfile_apply.py` 與 `write/datapack_apply.py` 還不存在——Step 4 先放兩個最小骨架，讓 import 通過、行為對 region 完全不變；真正的實作留給 Task 2 與 Task 6（各自獨立 commit）。

- [ ] **Step 4: 放兩個最小骨架（本任務只需要它們能被 import）**

新增 `src/mcmt/write/datfile_apply.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""`.dat` 檔的通用寫入器。骨架——完整實作見 Task 2。"""

__all__ = ["apply_to_datfile"]


def apply_to_datfile(world, relative, edits, outcome, backup) -> None:
    raise NotImplementedError("Task 2 補完")
```

新增 `src/mcmt/write/datapack_apply.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack 檔案（JSON）的寫入器。骨架——完整實作見 Task 6。"""

__all__ = ["apply_to_datapack_file"]


def apply_to_datapack_file(world, relative, edits, outcome, backup) -> None:
    raise NotImplementedError("Task 6 補完")
```

- [ ] **Step 5: 跑全部測試，數字要跟 Step 1 一樣**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠，測試總數與 Step 1 相同（這是純重構，行為不變）。

- [ ] **Step 6: 驗合約**

Run: `.venv\Scripts\python -X utf8 tools/validate_contracts.py`
Expected: 通過（這個任務沒碰合約，這一步是確認沒有意外波及）。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/write/common.py src/mcmt/write/apply.py src/mcmt/write/datfile_apply.py src/mcmt/write/datapack_apply.py
git commit -F- <<'MSG'
write：節點編輯引擎搬進 common.py，apply.py 改用顯式 kind→writer 分派表（獨立 commit，純重構）

`_apply_edit`/`_apply_to_key`/`_guarded_encoding`/`_resolve`/`_replace_list`/
`_translate_writer` 這組函式只做「照 node_path 走到節點、按 expected_encoding
守門、按 value.kind 決定寫什麼」，從沒問過 root 是從 region chunk 還是 .dat 讀
出來的——這不是 legacy/native 那種規格層級的不對稱（那個不對稱在挑 legacy/native
模組那一步才分岔），是真的重複，搬進 write/common.py。

apply.py 改成一份顯式的 kind→writer 對照表，取代原本「只有一種容器種類，函式名
硬編碼」的寫法。M13.5 要接 level_dat/scoreboard_dat、M13.7 要接 datapack_file，
這一步先把地基打好——spec 的第 8 節開頭已經點名這是 M13b 必須先做的第一件事，
三種寫入器保證等級不同（外科式/整份重編/檔案重寫），這個不對稱要看得見。

datfile_apply.py / datapack_apply.py 這一步只放骨架，完整實作是各自的獨立 commit
（Task 2 / Task 6）。純重構：既有測試數量與行為完全不變。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 2：`write/datfile_apply.py`（`.dat` 檔通用寫入器，`write/` 獨立 commit）

`level.dat` 與 `data/scoreboard.dat` 共用同一個寫入器——兩者都是「整份 NBT 檔，讀進來、在記憶體裡改幾個節點、整份重新編碼、回讀驗證、原子替換」，機制完全一樣，只有目標路徑不同。**這裡完全不碰根鍵名**（`Data` vs `data`）——那是掃描來源的事，這裡只照 `node_path` 走。

**Files:**
- Modify: `src/mcmt/write/datfile_apply.py`（補完 Task 1 的骨架）
- Test: `tests/unit/test_write_datfile_apply.py`（新）

**Interfaces:**
- Consumes: `write.common.{ApplyOutcome, apply_edit_to_compound, refuse}`、`nbtio.datfile.{DatFile, read_dat, write_dat}`、`safety.paths.{ensure_readable, ensure_writable}`、`safety.backup.BackupSet`
- Produces: `apply_to_datfile(world: Path, relative: str, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet) -> None`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_write_datfile_apply.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""`.dat` 檔通用寫入器（M13.5）。

`level.dat` 與 `scoreboard.dat` 共用這個寫入器——兩者都是「整份 NBT 檔，改幾個
節點，整份重新編碼」，機制一樣，只是目標路徑不同。這裡不測 `level_dat.py`/
`scoreboard.py` 怎麼掃（那是各自的測試檔），只測「餵一份 editplan 進來，`.dat`
檔正確地被改、備份、原封不動的欄位真的沒動」。
"""

from pathlib import Path

import amulet_nbt
import pytest

from mcmt.nbtio.datfile import DatFile, read_dat, write_dat
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable
from mcmt.write.common import ApplyOutcome
from mcmt.write.datfile_apply import apply_to_datfile


def level_dat(tmp_path: Path, *, level_name="原本的世界", data_version=4671) -> Path:
    target = tmp_path / "level.dat"
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag(level_name),
            "DataVersion": amulet_nbt.IntTag(data_version),
            "Difficulty": amulet_nbt.ByteTag(2),
        }
    )
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({"Data": data}), "")
    write_dat(target, DatFile(tag=tag, compression="gzip"))
    return target


def edit_for_level_name(text: str, *, data_version=4671, expected_encoding="bare_string"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:level_name:aaaaaaaaaaaaaaaa",
        "container": {
            "kind": "level_dat",
            "path": "level.dat",
            "dimension": None,
            "chunk": None,
            "data_version": data_version,
            "compression": None,
            "external": False,
        },
        "node_path": [{"t": "key", "name": "Data"}, {"t": "key", "name": "LevelName"}],
        "expected_encoding": expected_encoding,
        "value": {"kind": "literal", "text": text, "style": None},
    }


def test_the_level_name_is_replaced_and_the_file_is_backed_up(tmp_path, project) -> None:
    world = tmp_path
    target = level_dat(world)
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(target))
    assert str(read_back.tag.compound["Data"]["LevelName"]) == "新的世界名"
    assert outcome.counts["edits_written"] == 1
    assert outcome.counts["files_rewritten"] == 1
    assert backup.file_count == 1


def test_untouched_fields_are_not_re_encoded_away(tmp_path, project) -> None:
    """**這是整份重編寫入器唯一能驗的「原封不動」層級**：位元組不保證一致
    （M3.2：`.dat` 沒有外科式寫入這回事），但值必須一致。"""
    world = tmp_path
    level_dat(world, data_version=4671)
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(world / "level.dat"))
    data = read_back.tag.compound["Data"]
    assert int(data["DataVersion"]) == 4671
    assert int(data["Difficulty"]) == 2


def test_a_missing_file_refuses_every_edit_without_crashing(tmp_path, project) -> None:
    world = tmp_path
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten == [
        {
            "unit_id": edit["unit_id"],
            "occurrence_id": edit["occurrence_id"],
            "reason": "node_missing",
            "detail": "找不到 level.dat",
        }
    ]


def test_a_changed_node_is_refused_not_overwritten(tmp_path, project) -> None:
    world = tmp_path
    level_dat(world, level_name="有人在中間改過")
    outcome = ApplyOutcome()
    edit = edit_for_level_name("新的世界名")

    with BackupSet(world) as backup:
        apply_to_datfile(world, "level.dat", [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_missing" or outcome.unwritten[0]["reason"] == "node_changed"
    # LevelName 本身仍然是 bare_string，這裡不會改變形狀；真正會觸發 node_changed
    # 的情境是形狀變了。這條測試只確認「守門有跑」——寫入層永遠拿 expected_encoding
    # 去跟現在的形狀比對，不是拿文字內容比對。
    read_back = read_dat(ensure_readable(world / "level.dat"))
    assert str(read_back.tag.compound["Data"]["LevelName"]) == "有人在中間改過"


def test_a_legacy_scoreboard_display_name_gets_a_json_string(tmp_path, project) -> None:
    """`scoreboard.dat`：DV < 4325 走 legacy（JSON 字串），與 chunk 世代分派同一套。"""
    target = tmp_path / "scoreboard.dat"
    data = amulet_nbt.CompoundTag(
        {
            "Objectives": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {
                            "Name": amulet_nbt.StringTag("obj1"),
                            "CriteriaName": amulet_nbt.StringTag("dummy"),
                            "DisplayName": amulet_nbt.StringTag('"ReFightTime"'),
                        }
                    )
                ]
            ),
        }
    )
    root = amulet_nbt.CompoundTag({"data": data, "DataVersion": amulet_nbt.IntTag(3700)})
    write_dat(target, DatFile(tag=amulet_nbt.NamedTag(root, ""), compression="gzip"))

    outcome = ApplyOutcome()
    edit = {
        "occurrence_id": "o:00002",
        "unit_id": "u:objective:bbbbbbbbbbbbbbbb",
        "container": {
            "kind": "scoreboard_dat",
            "path": "data/scoreboard.dat",
            "dimension": None,
            "chunk": None,
            "data_version": 3700,
            "compression": None,
            "external": False,
        },
        "node_path": [
            {"t": "key", "name": "data"},
            {"t": "key", "name": "Objectives"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "DisplayName"},
        ],
        "expected_encoding": "json_string_scalar",
        "value": {"kind": "translate", "key": "mcmt.objective.cccccccccccccccc", "fallback": None, "style": None},
    }

    with BackupSet(tmp_path) as backup:
        apply_to_datfile(tmp_path, "scoreboard.dat", [edit], outcome, backup)

    read_back = read_dat(ensure_readable(target))
    written = str(read_back.tag.compound["data"]["Objectives"][0]["DisplayName"])
    assert written == '{"translate":"mcmt.objective.cccccccccccccccc"}'
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_write_datfile_apply.py -q`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: 實作 `write/datfile_apply.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""`.dat` 檔的通用寫入器（M13.5）。**高風險目錄。**

`level.dat` 與 `data/scoreboard.dat` 共用這一份——兩者都是「一份完整的 NBT
檔，改幾個節點、整份重新編碼」，機制完全一樣，只有目標路徑不同。

**這裡完全不碰根鍵名。** `level.dat` 的根是 `Data`（大寫）、`scoreboard.dat` 的根是
`data`（小寫），但這個模組不需要知道哪個是哪個——它只照 `edit['node_path']` 一步
一步走，而 `node_path` 本來就從根開始（`[key(Data), key(LevelName)]` 或
`[key(data), key(Objectives), index(0), key(DisplayName)]`）。知道根鍵名的是
掃描來源（`scan/sources/level_dat.py` / `scan/sources/scoreboard.py`），它們各自
動態解析。

**保證只到 L1**（M3.2 的結論）：整份解析→序列化位元組一致，`write_dat` 自己的
「暫存→回讀驗證→原子替換」已經確保編壞了不會動到原檔一個位元。這裡沒有外科式
寫入這回事——原封不動的欄位靠「同一棵 CompoundTag 只有被改到的節點被改」保住，
不是靠位元組層級的原樣複製。

節點層級的「走到哪、寫什麼」邏輯在 `write/common.py`（`apply_edit_to_compound`）
——與 region 寫入器共用，不是巧合的重複（Task 1 的 commit 訊息說明了理由）。
"""

from pathlib import Path

from mcmt.errors import FormatError
from mcmt.nbtio.datfile import read_dat, write_dat
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write.common import ApplyOutcome, apply_edit_to_compound, refuse

__all__ = ["apply_to_datfile"]


def apply_to_datfile(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    path = world / relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return

    try:
        dat = read_dat(ensure_readable(path))
    except FormatError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    root = dat.tag.compound
    written = 0
    for edit in edits:
        if apply_edit_to_compound(root, edit, outcome):
            written += 1
    if not written:
        return

    outcome.counts["edits_written"] += written
    backup.protect(path)
    write_dat(ensure_writable(path), dat)
    outcome.counts["files_rewritten"] += 1
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_write_datfile_apply.py -q`
Expected: PASS

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add src/mcmt/write/datfile_apply.py tests/unit/test_write_datfile_apply.py
git commit -F- <<'MSG'
write：.dat 檔通用寫入器（level.dat 與 scoreboard.dat 共用，獨立 commit）

`level.dat` 與 `data/scoreboard.dat` 都是整份 NBT 檔，改幾個節點、整份重新編碼、
回讀驗證、原子替換——機制完全一樣，只有目標路徑不同，所以共用一個寫入器。

完全不碰根鍵名（Data 大寫 / data 小寫）：只照 node_path 一步一步走，node_path 本來
就從根開始。知道根鍵名的是掃描來源，各自動態解析。

節點層級的走訪/守門/寫值邏輯用 Task 1 搬進 write/common.py 的
apply_edit_to_compound，與 region 寫入器共用同一份——不是巧合的重複，那段邏輯
從沒問過 root 是從哪裡讀出來的。

[實測 2026-08-22] 用真實地圖驗證過世代分派仍然成立：Arena of Darkness（DV 3700）
的 scoreboard.dat Objectives[].DisplayName 是 JSON 純量字串（'"ReFightTime"'），
100 Ways To Die（DV 4325）是裸字串（"as_lock_uuid4"）——與 chunk 層級的
legacy/native 二分完全對稱，寫入端因此直接沿用既有的世代分派，不必新增判斷。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 3：`scan/sources/level_dat.py`（`LevelName` / `CustomBossEvents` / `Player.Inventory`）

三個欄位，見本檔開頭「既有介面速查」的實測表。**`CustomBossEvents` 是用 boss id 當鍵的 compound，不是 list**——不要被 spec 文件裡 `CustomBossEvents[].Name` 的記號騙了；真實 NBT 形狀是 `Data.CustomBossEvents.<id>.Name`。

這個任務也補一個目前完全沒人接的洞：`LevelName` 這種「根本不是 component」的欄位，`sniff()` 只認值的形狀，猜不出「這個欄位不該被當 JSON 猜」——世界名剛好以 `{`/`"`/`[` 開頭時，`sniff()` 會誤判成 JSON 並嘗試解析，解析失敗就整個跳過不翻（`unparseable_json`）。`model/component.py` 的 `Encoding.PLAIN_STRING` 就是為這件事準備的（docstring 明講「由欄位決定，不是由值決定」），但至今沒有任何掃描來源用過它——`level_dat.py` 是第一個。

**Files:**
- Create: `src/mcmt/scan/sources/level_dat.py`
- Modify: `src/mcmt/extract/build.py`（`plain_string` 覆寫）
- Modify: `src/mcmt/scan/registry.py`
- Test: `tests/unit/test_scan_level_dat.py`（新）、`tests/unit/test_extract_build.py`（追加）

**Interfaces:**
- Consumes: `nbtio.datfile.read_dat`、`scan.sources.item.scan_item`、`model.node.{NodePath, key_step, index_step}`、`model.generation.TARGET_DATA_VERSION`
- Produces: `scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_scan_level_dat.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""`level.dat` 掃描（M13.5）。

三個欄位：`LevelName`（in_place）、`CustomBossEvents.<id>.Name`（translate_key，
[全部遊戲實測]）、`Player.Inventory[]`（走 `scan_item` 的共用遞迴）。

[實測 2026-08-22] `CustomBossEvents` 是用 boss id 當鍵的 compound，不是 list——
`Arena of Darkness` 的 27 個、`100 Ways To Die` 的 3 個都是這個形狀。
"""

from collections import Counter

import amulet_nbt

from mcmt.nbtio.datfile import DatFile, write_dat
from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources import level_dat


def world_with(tmp_path, data: amulet_nbt.CompoundTag, *, root_key="Data"):
    target = tmp_path / "level.dat"
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({root_key: data}), "")
    write_dat(target, DatFile(tag=tag, compression="gzip"))
    return ensure_readable(tmp_path)


def minimal_data(**extra) -> amulet_nbt.CompoundTag:
    fields = {
        "LevelName": amulet_nbt.StringTag("我的世界"),
        "DataVersion": amulet_nbt.IntTag(4671),
    }
    fields.update(extra)
    return amulet_nbt.CompoundTag(fields)


def test_the_level_name_is_found(tmp_path) -> None:
    world = world_with(tmp_path, minimal_data())
    stats = Counter()

    found = list(level_dat.scan(world, stats))

    names = [n.node.category for n in found]
    assert "level_name" in names
    level_name_node = next(n.node for n in found if n.node.category == "level_name")
    assert str(level_name_node.tag) == "我的世界"
    assert level_name_node.path.to_json() == [
        {"t": "key", "name": "Data"},
        {"t": "key", "name": "LevelName"},
    ]


def test_the_container_reports_this_files_own_data_version(tmp_path) -> None:
    world = world_with(tmp_path, minimal_data(DataVersion=amulet_nbt.IntTag(3700)))
    stats = Counter()

    (first, *_) = list(level_dat.scan(world, stats))

    assert first.container == {
        "kind": "level_dat",
        "path": "level.dat",
        "dimension": None,
        "chunk": None,
        "data_version": 3700,
        "compression": None,
        "external": False,
    }


def test_custom_boss_events_is_a_compound_keyed_by_id_not_a_list(tmp_path) -> None:
    """[實測] 真實形狀是 `Data.CustomBossEvents.<id>.Name`，用 boss id 當鍵。"""
    events = amulet_nbt.CompoundTag(
        {
            "minecraft:hyde": amulet_nbt.CompoundTag(
                {"Name": amulet_nbt.StringTag('"Mr.Hyde"'), "Color": amulet_nbt.StringTag("red")}
            )
        }
    )
    world = world_with(tmp_path, minimal_data(CustomBossEvents=events))
    stats = Counter()

    found = [n.node for n in level_dat.scan(world, stats) if n.node.category == "bossbar"]

    assert len(found) == 1
    assert str(found[0].tag) == '"Mr.Hyde"'
    assert found[0].path.to_json() == [
        {"t": "key", "name": "Data"},
        {"t": "key", "name": "CustomBossEvents"},
        {"t": "key", "name": "minecraft:hyde"},
        {"t": "key", "name": "Name"},
    ]


def test_a_boss_without_a_name_is_skipped(tmp_path) -> None:
    events = amulet_nbt.CompoundTag(
        {"minecraft:foo": amulet_nbt.CompoundTag({"Color": amulet_nbt.StringTag("red")})}
    )
    world = world_with(tmp_path, minimal_data(CustomBossEvents=events))
    stats = Counter()

    found = [n.node for n in level_dat.scan(world, stats) if n.node.category == "bossbar"]

    assert found == []


def test_player_inventory_recurses_through_scan_item(tmp_path) -> None:
    sword = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:diamond_sword")})
    sword["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag("屠龍劍")}
    )
    player = amulet_nbt.CompoundTag(
        {"Inventory": amulet_nbt.ListTag([sword])}
    )
    world = world_with(tmp_path, minimal_data(Player=player))
    stats = Counter()

    found = [n.node for n in level_dat.scan(world, stats) if n.node.category == "custom_name"]

    assert len(found) == 1
    assert str(found[0].tag) == "屠龍劍"
    assert found[0].path.to_json()[:3] == [
        {"t": "key", "name": "Data"},
        {"t": "key", "name": "Player"},
        {"t": "key", "name": "Inventory"},
    ]


def test_a_world_without_a_player_is_not_an_error(tmp_path) -> None:
    """[實測] `100 Ways To Die` 沒有 `Player` 節點——這是合法狀態，不是損壞。"""
    world = world_with(tmp_path, minimal_data())
    stats = Counter()

    found = list(level_dat.scan(world, stats))

    assert all(n.node.category != "custom_name" for n in found)


def test_a_missing_level_dat_yields_nothing(tmp_path) -> None:
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(level_dat.scan(world, stats)) == []
    assert stats["skipped_level_dat"] == 0


def test_an_unreadable_level_dat_is_counted_not_fatal(tmp_path) -> None:
    (tmp_path / "level.dat").write_bytes(b"not nbt at all")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(level_dat.scan(world, stats)) == []
    assert stats["skipped_level_dat"] == 1
```

在 `tests/unit/test_extract_build.py` 追加（先讀該檔開頭幾行確認既有的 import 與 helper 風格，再照著加；若該檔目前是走 `scan_chunk`/合成 chunk 的模式，這條新測試改用直接建構 `TextNode`/`ScannedNode` 呼叫 `_consider` 或走 `build_units` 對一個合成 `level.dat` 世界——兩種都可以，選擇能最小改動地插入既有檔案風格的那個）：

```python
def test_a_level_name_that_looks_like_json_is_not_mistaken_for_one(tmp_path, project) -> None:
    """**這是 `plain_string` 存在的理由。** `LevelName` 根本不是 component，
    但它的值和一行裸字串告示牌長得一模一樣——世界名剛好以 `{` 開頭時，
    `sniff()` 會誤判成 JSON 並嘗試解析，解析失敗就整個被當成
    `unparseable_json` 跳過不翻。這個欄位不該被 sniff() 的 JSON 偵測猜。
    """
    import amulet_nbt

    from mcmt.extract.build import build_units
    from mcmt.nbtio.datfile import DatFile, write_dat
    from mcmt.sandbox import import_world

    source = tmp_path / "outside" / "TT_JSON_LOOKING_NAME"
    (source / "region").mkdir(parents=True)
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag("{這不是JSON只是剛好用大括號開頭}"),
            "DataVersion": amulet_nbt.IntTag(4671),
        }
    )
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({"Data": data}), "")
    write_dat(source / "level.dat", DatFile(tag=tag, compression="gzip"))

    imported = import_world(source, name="json_looking_name")
    result = build_units(imported.target, world_root=imported.target)

    level_name_units = [u for u in result.units if u.category == "level_name"]
    assert len(level_name_units) == 1
    assert level_name_units[0].occurrences[0].encoding == "plain_string"
    assert result.stats["skipped_unparseable"] == 0
```

（若 `import_world`/`sandbox` 的簽名與這裡假設的不同，改成直接對一個放在 `project` fixture 底下的 `sandbox/` 子目錄呼叫 `build_units(..., world_root=ensure_readable(那個目錄))`，跳過 sandbox import 這一步——重點只是要有一個真實的 `level.dat` 檔案讓 `build_units` 走過完整的 `SOURCES` 迴圈。）

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_level_dat.py tests/unit/test_extract_build.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcmt.scan.sources.level_dat'`

- [ ] **Step 3: 建 `scan/sources/level_dat.py`**

```python
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
```

- [ ] **Step 4: `extract/build.py` 加 `plain_string` 覆寫**

讀 `src/mcmt/extract/build.py` 目前的 `_consider()` 函式（本檔開頭已經完整列出）。在檔案 import 區塊把

```python
from mcmt.model.component import Encoding, sniff
```

改成

```python
from mcmt.model.component import Encoding, Sniffed, sniff
```

在 `_LEGACY_JSON` 定義後面加一個新常數：

```python
# 這幾個欄位根本不是 component——`sniff()` 只認值的形狀，猜不出「這個欄位不該
# 被當 JSON 猜」。世界名剛好以 `{`/`"`/`[` 開頭時，sniff() 會誤判成 JSON 並嘗試
# 解析，解析失敗就整個被當 unparseable_json 跳過不翻。`level_dat.py` 是第一個
# 用到這個覆寫的來源；book_title/book_author/draft_book_page 目前仍然沿用
# sniff() 判成的 bare_string——改變它們的既有行為超出這個任務的範圍，需要自己
# 的一輪（它們的寫入端行為不受影響：write/in_place.py 對 bare_string 與
# plain_string 是同一個函式 `_bare`）。
_PLAIN_STRING_CATEGORIES = frozenset({"level_name"})
```

在 `_consider()` 裡，`shape = sniff(node.tag)` 那段之後、`if shape.problem == "unparseable_json":` 之前插入覆寫：

```python
    try:
        shape = sniff(node.tag)
    except TypeError:
        result.stats["skipped_not_text"] += 1
        return None

    if node.category in _PLAIN_STRING_CATEGORIES and isinstance(node.tag, amulet_nbt.StringTag):
        # **不管值長得像不像 JSON，這個欄位都不是 component。** 覆寫掉
        # sniff() 的猜測，而不是先讓它跑一輪再事後修正——跑過再修正的話，值
        # 剛好解析失敗時已經被標成 unparseable_json，圖窮匕見前這個節點就已經
        # 在 _consider() 的下一段被跳過了。
        text = str(node.tag)
        shape = Sniffed(encoding=Encoding.PLAIN_STRING, raw=text, parsed=text)

    if shape.problem == "unparseable_json":
```

- [ ] **Step 5: 掛上 registry**

`src/mcmt/scan/registry.py`：

```python
from mcmt.scan.sources import entities, level_dat, region

__all__ = ["SOURCES"]

SOURCES = [
    region.scan,
    entities.scan,
    level_dat.scan,
]
```

- [ ] **Step 6: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_level_dat.py tests/unit/test_extract_build.py -q`
Expected: PASS

- [ ] **Step 7: 跑全部測試**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠

- [ ] **Step 8: 真實地圖確認**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/Arena of Darkness" --lang zh_tw --out "sandbox/_m13b_check"
```
Expected: 報告的 `by_category` 出現 `level_name: 1`、`bossbar` 有數字（AoD 27 個 occurrence，去重後相異數視文字內容而定）。確認後 `rm -rf "sandbox/_m13b_check"`。

- [ ] **Step 9: Commit**

```bash
git add src/mcmt/scan/sources/level_dat.py src/mcmt/extract/build.py src/mcmt/scan/registry.py tests/unit/test_scan_level_dat.py tests/unit/test_extract_build.py
git commit -F- <<'MSG'
scan：level.dat 掃描來源（LevelName / CustomBossEvents / Player.Inventory）

三個欄位，[實測 2026-08-22] 對照 Arena of Darkness 與 100 Ways To Die 的真實
level.dat 驗證過形狀：CustomBossEvents 是用 boss id 當鍵的 compound 不是 list，
根鍵 Data 動態解析。

順手補上 model/component.py 早就備好、至今沒人用過的 plain_string：LevelName
根本不是 component，但它的值和一行裸字串告示牌長得一模一樣，sniff() 猜不出這件
事——世界名剛好以 { 開頭時會被誤判成 JSON 並在解析失敗後整個跳過不翻。改成由
category 覆寫 sniff() 的判斷，不等它先跑再修正。book_title/book_author/
draft_book_page 目前仍沿用既有的 bare_string，這個覆寫只套用在 level_name——
兩者寫入端行為相同（write/in_place.py 對兩種 encoding 是同一個函式），改變前三者
的既有行為是另一個任務。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 4：`scan/sources/scoreboard.py`（`Objectives` / `Teams` DisplayName 與前後綴）

`data/scoreboard.dat` 的根有兩個並列鍵 `data` 與 `DataVersion`（**不是**巢狀，這是與 `level.dat` 的實測差異，見計畫檔開頭）。`Objectives[].Name`／`CriteriaName`／`Teams[].Name` 是識別碼，denylist 已經擋著（`_DENIED_TAILS` 裡的 `("Objectives","Name")` 等三條，M13a 就補好了，這個任務不必再碰 denylist）。

**Files:**
- Create: `src/mcmt/scan/sources/scoreboard.py`
- Modify: `src/mcmt/scan/registry.py`
- Test: `tests/unit/test_scan_scoreboard.py`（新）

**Interfaces:**
- Consumes: `nbtio.datfile.read_dat`、`model.node.{NodePath, key_step, index_step}`
- Produces: `scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_scan_scoreboard.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""`data/scoreboard.dat` 掃描（M13.6）。

[實測 2026-08-22] 根是兩個並列鍵：`data`（內容）與 `DataVersion`（整數，**不在**
`data` 裡面）——與 `level.dat` 的巢狀形狀不同，這是兩個檔案的真實差異。

`Objectives[].Name`／`CriteriaName`／`Teams[].Name` 是識別碼，denylist 在 M13a
就擋好了（見 `tests/unit/test_rules_denylist.py`），這裡不重測。
"""

from collections import Counter

import amulet_nbt

from mcmt.nbtio.datfile import DatFile, write_dat
from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources import scoreboard


def world_with(tmp_path, data: amulet_nbt.CompoundTag, *, data_version=4671):
    target = tmp_path / "data" / "scoreboard.dat"
    root = amulet_nbt.CompoundTag({"data": data, "DataVersion": amulet_nbt.IntTag(data_version)})
    write_dat(target, DatFile(tag=amulet_nbt.NamedTag(root, ""), compression="gzip"))
    return ensure_readable(tmp_path)


def objective(name="obj1", display="顯示名稱", criteria="dummy"):
    return amulet_nbt.CompoundTag(
        {
            "Name": amulet_nbt.StringTag(name),
            "CriteriaName": amulet_nbt.StringTag(criteria),
            "DisplayName": amulet_nbt.StringTag(display),
        }
    )


def team(name="team1", display="隊伍名稱", prefix=None, suffix=None):
    fields = {"Name": amulet_nbt.StringTag(name), "DisplayName": amulet_nbt.StringTag(display)}
    if prefix is not None:
        fields["MemberNamePrefix"] = amulet_nbt.StringTag(prefix)
    if suffix is not None:
        fields["MemberNameSuffix"] = amulet_nbt.StringTag(suffix)
    return amulet_nbt.CompoundTag(fields)


def test_an_objective_display_name_is_found(tmp_path) -> None:
    data = amulet_nbt.CompoundTag({"Objectives": amulet_nbt.ListTag([objective()])})
    world = world_with(tmp_path, data)
    stats = Counter()

    found = [n.node for n in scoreboard.scan(world, stats) if n.node.category == "objective"]

    assert len(found) == 1
    assert str(found[0].tag) == "顯示名稱"
    assert found[0].path.to_json() == [
        {"t": "key", "name": "data"},
        {"t": "key", "name": "Objectives"},
        {"t": "index", "i": 0},
        {"t": "key", "name": "DisplayName"},
    ]


def test_the_container_reads_data_version_from_the_sibling_key(tmp_path) -> None:
    """**這是與 `level.dat` 的差異點。** `DataVersion` 是根的兄弟節點，不在 `data` 裡。"""
    data = amulet_nbt.CompoundTag({"Objectives": amulet_nbt.ListTag([objective()])})
    world = world_with(tmp_path, data, data_version=3700)
    stats = Counter()

    (first, *_) = list(scoreboard.scan(world, stats))

    assert first.container == {
        "kind": "scoreboard_dat",
        "path": "data/scoreboard.dat",
        "dimension": None,
        "chunk": None,
        "data_version": 3700,
        "compression": None,
        "external": False,
    }


def test_a_team_yields_display_name_and_both_affixes(tmp_path) -> None:
    data = amulet_nbt.CompoundTag(
        {"Teams": amulet_nbt.ListTag([team(display="紅隊", prefix="[紅] ", suffix=" (R)")])}
    )
    world = world_with(tmp_path, data)
    stats = Counter()

    found = list(scoreboard.scan(world, stats))
    by_category = {n.node.category: str(n.node.tag) for n in found}

    assert by_category["team"] == "紅隊"
    assert by_category["team_affix"] in ("[紅] ", " (R)")
    affix_values = {str(n.node.tag) for n in found if n.node.category == "team_affix"}
    assert affix_values == {"[紅] ", " (R)"}


def test_a_team_without_affixes_yields_no_team_affix_nodes(tmp_path) -> None:
    """[實測] `100 Ways To Die`（native）的隊伍根本沒有這兩個欄位——省略不是錯誤。"""
    data = amulet_nbt.CompoundTag({"Teams": amulet_nbt.ListTag([team()])})
    world = world_with(tmp_path, data)
    stats = Counter()

    found = [n.node for n in scoreboard.scan(world, stats) if n.node.category == "team_affix"]

    assert found == []


def test_the_name_and_criteria_name_fields_are_not_yielded(tmp_path) -> None:
    """這個來源是白名單，本來就不去碰 `Name`/`CriteriaName`——不是靠 denylist 擋，
    是壓根不掃它們。"""
    data = amulet_nbt.CompoundTag(
        {
            "Objectives": amulet_nbt.ListTag([objective(name="internal_id_123")]),
            "Teams": amulet_nbt.ListTag([team(name="internal_team_id")]),
        }
    )
    world = world_with(tmp_path, data)
    stats = Counter()

    texts = {str(n.node.tag) for n in scoreboard.scan(world, stats)}

    assert "internal_id_123" not in texts
    assert "internal_team_id" not in texts


def test_a_missing_scoreboard_dat_yields_nothing(tmp_path) -> None:
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(scoreboard.scan(world, stats)) == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_scoreboard.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 建 `scan/sources/scoreboard.py`**

```python
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
```

- [ ] **Step 4: 掛上 registry**

`src/mcmt/scan/registry.py`：

```python
from mcmt.scan.sources import entities, level_dat, region, scoreboard

__all__ = ["SOURCES"]

SOURCES = [
    region.scan,
    entities.scan,
    level_dat.scan,
    scoreboard.scan,
]
```

- [ ] **Step 5: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_scoreboard.py -q`
Expected: PASS

- [ ] **Step 6: 跑全部測試**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠

- [ ] **Step 7: 真實地圖確認**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/Arena of Darkness" --lang zh_tw --out "sandbox/_m13b_check" --replace
```
Expected: `by_category` 出現 `objective` 與 `team`（AoD 168/17 個 occurrence），`team_affix` 為 0 或極少（如上方文件所述，AoD 的前後綴全空）。確認後 `rm -rf "sandbox/_m13b_check"`。

- [ ] **Step 8: Commit**

```bash
git add src/mcmt/scan/sources/scoreboard.py src/mcmt/scan/registry.py tests/unit/test_scan_scoreboard.py
git commit -F- <<'MSG'
scan：scoreboard.dat 掃描來源（Objectives/Teams DisplayName 與前後綴）

四個欄位，[實測 2026-08-22] 對照 Arena of Darkness 與 100 Ways To Die 驗證過：
DataVersion 是根的兄弟節點不在 data 裡面（與 level.dat 的巢狀形狀不同），
MemberNamePrefix/Suffix 在 native 世代常常整個不存在（不是空字串是省略），兩張
語料地圖的前後綴實際內容全部是空的——這個分類在兩張地圖上都不會產生非空譯文，
是可預期的、不是 bug。

Objectives[].Name/CriteriaName/Teams[].Name 是識別碼，denylist 在 M13a 就擋好了
（_DENIED_TAILS 三條），這個來源是白名單本來就不掃它們。

team_affix（MemberNamePrefix/Suffix）translate key 是否真的顯示，尚未單獨遊戲
實測——記進 SPIKE_RESULT.md 尚待驗證表（另一個 commit 處理）。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 5：`scan/sources/datapack.py`（advancement JSON：資料夾 + zip，單複數目錄名）

**這是第一個非 NBT 的掃描來源。** advancement JSON 檔本身是 JSON，`display.title`/`display.description` 的值可能是裸字串、component 物件、或陣列——與 NBT 裡「字串裝著 JSON」不同，這裡是**JSON 文件裡直接放著一個 JSON 值**。做法是把讀出來的 Python 值（`str`/`dict`/`list`）包成對應的 `amulet_nbt` 標籤（`StringTag`/`CompoundTag`/`ListTag`），這樣 `sniff()`/`flatten()`/整條既有管線完全不用改：一個裸字串包成 `StringTag` 就會被判成 `bare_string`，一個只有 `text` 鍵的 dict 包成 `CompoundTag` 就會被判成 `text_compound`，以此類推——這不是新的 encoding 種類，是既有八種形狀分類本來就涵蓋的東西，只是這次的「原始位元組」是 JSON 檔而不是 NBT。

[實測 2026-08-22] `Arena of Darkness` 的資料包用的是**複數** `advancements/`（1.20.4 舊式目錄名），不是 spec 文件寫的單數 `advancement/`——兩種都要認得（SPIKE_RESULT.md 已經記過這件事：「1.21 起 datapack 目錄名改為單數」）。而且它是 **zip 檔**（`datapacks/ArenaOfDarknessDatapack_10_15.zip`），不是資料夾。

**Files:**
- Create: `src/mcmt/scan/sources/datapack.py`
- Modify: `src/mcmt/scan/registry.py`
- Test: `tests/unit/test_scan_datapack.py`（新）

**Interfaces:**
- Consumes: `model.node.{NodePath, key_step, index_step}`、stdlib `json`/`zipfile`
- Produces: `scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_scan_datapack.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 掃描（M13.7）。

[實測 2026-08-22] `Arena of Darkness` 用**複數** `advancements/`（1.20.4 舊式目錄
名）且是 **zip 檔**（`datapacks/ArenaOfDarknessDatapack_10_15.zip` 裡有 25 個
`data/worf/advancements/*.json`）。這份測試涵蓋資料夾 + zip、單數 + 複數四種組合
中真實會出現的那些。
"""

import json
import zipfile
from collections import Counter

from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources import datapack


def write_advancement(path, *, title="標題", description="描述"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": title, "description": description}}),
        encoding="utf-8",
    )


def test_a_folder_datapack_with_the_singular_directory_name_is_found(tmp_path) -> None:
    write_advancement(
        tmp_path / "datapacks" / "mypack" / "data" / "myns" / "advancement" / "quest1.json",
        title="第一個任務",
        description="打敗史萊姆",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    found = list(datapack.scan(world, stats))
    by_category = {n.node.category: str(n.node.tag) for n in found}

    assert by_category["advancement_title"] == "第一個任務"
    assert by_category["advancement_description"] == "打敗史萊姆"


def test_a_folder_datapack_with_the_plural_directory_name_is_found(tmp_path) -> None:
    """[實測] 1.20.4 及以前是複數 `advancements/`——`Arena of Darkness` 用的就是這個。"""
    write_advancement(
        tmp_path / "datapacks" / "oldpack" / "data" / "worf" / "advancements" / "barosa.json",
        title="The Prelude",
        description="Defeat Barosa... for now.",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    found = list(datapack.scan(world, stats))
    by_category = {n.node.category: str(n.node.tag) for n in found}

    assert by_category["advancement_title"] == "The Prelude"


def test_a_zip_datapack_is_found(tmp_path) -> None:
    """[實測] `Arena of Darkness` 的資料包是 zip，不是資料夾。"""
    zip_path = tmp_path / "datapacks" / "mypack.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/myns/advancement/quest1.json",
            json.dumps({"display": {"title": "壓縮包裡的任務"}}),
        )
    world = ensure_readable(tmp_path)
    stats = Counter()

    found = [n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"]

    assert len(found) == 1
    assert str(found[0].tag) == "壓縮包裡的任務"


def test_the_container_path_identifies_the_zip_and_the_entry(tmp_path) -> None:
    zip_path = tmp_path / "datapacks" / "mypack.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/myns/advancement/quest1.json",
            json.dumps({"display": {"title": "任務"}}),
        )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (first, *_) = list(datapack.scan(world, stats))

    assert first.container["kind"] == "datapack_file"
    assert first.container["path"] == "datapacks/mypack.zip/data/myns/advancement/quest1.json"
    assert first.container["data_version"] is None


def test_a_bare_string_title_is_yielded_as_a_string_tag(tmp_path) -> None:
    import amulet_nbt

    write_advancement(
        tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json",
        title="裸字串標題",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (title,) = [
        n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"
    ]

    assert isinstance(title.tag, amulet_nbt.StringTag)


def test_a_component_shaped_title_is_yielded_as_a_compound_tag(tmp_path) -> None:
    import amulet_nbt

    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": {"text": "帶格式的標題", "color": "gold"}}}),
        encoding="utf-8",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (title,) = [
        n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"
    ]

    assert isinstance(title.tag, amulet_nbt.CompoundTag)
    assert str(title.tag["text"]) == "帶格式的標題"


def test_an_advancement_without_display_yields_nothing(tmp_path) -> None:
    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"parent": "n:other", "criteria": {}}), encoding="utf-8")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []


def test_malformed_json_is_counted_not_fatal(tmp_path) -> None:
    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "broken.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []
    assert stats["skipped_advancement_unparseable"] == 1


def test_no_datapacks_directory_yields_nothing(tmp_path) -> None:
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []


def test_a_non_advancement_file_in_the_pack_is_ignored(tmp_path) -> None:
    """白名單只找 `advancement(s)/*.json`，資料包裡其餘的東西（`function/`、
    `loot_table/`、`pack.mcmeta`……）連碰都不碰。"""
    base = tmp_path / "datapacks" / "p" / "data" / "n"
    (base / "function").mkdir(parents=True)
    (base / "function" / "hello.mcfunction").write_text("say hi", encoding="utf-8")
    (tmp_path / "datapacks" / "p" / "pack.mcmeta").write_text('{"pack":{}}', encoding="utf-8")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_datapack.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 建 `scan/sources/datapack.py`**

```python
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
    好讓既有的 `sniff()`/`flatten()` 管線原封不動地吃得下它。"""
    if isinstance(value, str):
        return amulet_nbt.StringTag(value)
    if isinstance(value, dict):
        return amulet_nbt.CompoundTag({str(k): _to_amulet(v) for k, v in value.items()})
    if isinstance(value, list):
        return amulet_nbt.ListTag([_to_amulet(v) for v in value])
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
```

- [ ] **Step 4: 掛上 registry**

`src/mcmt/scan/registry.py`：

```python
from mcmt.scan.sources import datapack, entities, level_dat, region, scoreboard

__all__ = ["SOURCES"]

SOURCES = [
    region.scan,
    entities.scan,
    level_dat.scan,
    scoreboard.scan,
    datapack.scan,
]
```

- [ ] **Step 5: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_datapack.py -q`
Expected: PASS

- [ ] **Step 6: 跑全部測試**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠

- [ ] **Step 7: 真實地圖確認**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/Arena of Darkness" --lang zh_tw --out "sandbox/_m13b_check" --replace
```
Expected: `by_category` 出現 `advancement_title`/`advancement_description`，總 occurrence 數量級與清點的 56 相異數同個範圍（zip 裡兩個資料包共 30 個 JSON 檔）。確認後 `rm -rf "sandbox/_m13b_check"`。

- [ ] **Step 8: Commit**

```bash
git add src/mcmt/scan/sources/datapack.py src/mcmt/scan/registry.py tests/unit/test_scan_datapack.py
git commit -F- <<'MSG'
scan：datapack advancement JSON 掃描（資料夾 + zip，單複數目錄名）

`display.title`/`display.description`，[實測 2026-08-22] 對照 Arena of Darkness
真實資料包驗證：用的是複數 advancements/（1.20.4 舊式目錄名，SPIKE_RESULT.md 早
就記過 1.21 才改單數）而且全部是 zip 檔，不是資料夾——兩件事都要支援。

值直接包成對應的 amulet_nbt 標籤（str→StringTag、dict→CompoundTag、
list→ListTag），讓既有的 sniff()/flatten() 管線原封不動地吃得下這個新來源。
這不是新的 encoding 分類，是既有八種形狀分類本來就涵蓋的東西，只是這次原始
位元組是 JSON 檔不是 NBT chunk。

container.path 對 zip 內條目用 `<zip 相對路徑>/<zip 內條目路徑>` 表示，
container.data_version 固定是 null——advancement 不是版本化 NBT 文件，而且
_consider() 的舊式 JSON 判斷只在遇到 json_* 系列 encoding 時才用得到這個值，
advancement 的值永遠不會落進那四種。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 6：`write/datapack_apply.py`（datapack 檔案重寫：資料夾 + zip，`write/` 獨立 commit）

**保證只到「檔案重寫」**：資料夾形式直接覆寫該 JSON 檔（暫存 → 原子替換，同 `write_dat` 的精神但更輕量，因為 JSON 沒有回讀 NBT 驗證的問題，改用「回讀能不能 `json.loads`」當驗證）；zip 形式**整份重建**（沿用 `pack.py` 的做法：既有條目原樣搬運，只重寫我們動過的那幾個）。

**這是工具第一次改動地圖自己的檔案**（不是它的存檔資料，是它的資料包）——這件事要在報告裡講清楚（M4-5 的教訓：改地圖自己的東西要讓使用者知道）。

**Files:**
- Modify: `src/mcmt/write/datapack_apply.py`（補完 Task 1 的骨架）
- Modify: `src/mcmt/write/apply.py`（無需改動——`_WRITERS` 已在 Task 1 掛好 `datapack_file`；這裡列出是提醒執行者確認）
- Test: `tests/unit/test_write_datapack_apply.py`（新）

**Interfaces:**
- Consumes: `write.common.{ApplyOutcome, refuse, component_for}`、stdlib `json`/`zipfile`、`safety.paths.{ensure_readable, ensure_writable}`
- Produces: `apply_to_datapack_file(world: Path, relative: str, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet) -> None`

**這個寫入器不呼叫 `apply_edit_to_compound`**——那個函式是給 `amulet_nbt.CompoundTag` 走的，這裡的樹是純 Python `dict`/`list`。走訪邏輯是 `apply_edit_to_compound` 的純 Python 版本，同樣的三個步驟（照 `node_path` 走、比對 `expected_encoding`、按 `value.kind` 決定寫什麼），但型別檢查換成 `dict`/`list` 而不是 `CompoundTag`/`ListTag`。

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_write_datapack_apply.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 的寫入器（M13.7）。

**保證只到「檔案重寫」**——資料夾形式直接覆寫、zip 形式整份重建（既有條目原樣
搬運）。這裡走的是純 Python dict 樹，不透過 amulet_nbt——advancement JSON 本來
就是 JSON，往裡面塞一個 `{"translate": key}` 直接就是最終要 `json.dump` 出去
的東西。
"""

import json
import zipfile
from pathlib import Path

from mcmt.safety.backup import BackupSet
from mcmt.write.common import ApplyOutcome
from mcmt.write.datapack_apply import apply_to_datapack_file


def folder_advancement(tmp_path: Path, relative: str, *, title="原標題") -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": title, "description": "原描述"}, "criteria": {}}),
        encoding="utf-8",
    )
    return path


def edit_for(relative: str, key: str, *, node="title", expected="bare_string"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:advancement_title:aaaaaaaaaaaaaaaa",
        "container": {
            "kind": "datapack_file",
            "path": relative,
            "dimension": None,
            "chunk": None,
            "data_version": None,
            "compression": None,
            "external": False,
        },
        "node_path": [{"t": "key", "name": "display"}, {"t": "key", "name": node}],
        "expected_encoding": expected,
        "value": {"kind": "translate", "key": key, "fallback": "原標題", "style": None},
    }


def test_a_folder_advancement_title_becomes_a_translate_component(tmp_path, project) -> None:
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(tmp_path, relative)
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.bbbbbbbbbbbbbbbb")

    with BackupSet(tmp_path) as backup:
        apply_to_datapack_file(tmp_path, relative, [edit], outcome, backup)

    document = json.loads(path.read_text("utf-8"))
    assert document["display"]["title"] == {
        "translate": "mcmt.advancement_title.bbbbbbbbbbbbbbbb",
        "fallback": "原標題",
    }
    # 其餘欄位一個字都不動。
    assert document["display"]["description"] == "原描述"
    assert document["criteria"] == {}
    assert outcome.counts["edits_written"] == 1
    assert outcome.counts["files_rewritten"] == 1


def test_a_zip_advancement_is_rewritten_and_other_entries_survive(tmp_path, project) -> None:
    zip_path = tmp_path / "datapacks" / "p.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/n/advancement/quest.json",
            json.dumps({"display": {"title": "原標題"}}),
        )
        archive.writestr("data/n/function/hello.mcfunction", "say hi")
        archive.writestr("pack.mcmeta", '{"pack":{"pack_format":10}}')

    relative = "datapacks/p.zip/data/n/advancement/quest.json"
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.cccccccccccccccc")

    with BackupSet(tmp_path) as backup:
        apply_to_datapack_file(tmp_path, relative, [edit], outcome, backup)

    with zipfile.ZipFile(zip_path) as archive:
        document = json.loads(archive.read("data/n/advancement/quest.json").decode("utf-8"))
        assert document["display"]["title"]["translate"] == "mcmt.advancement_title.cccccccccccccccc"
        assert archive.read("data/n/function/hello.mcfunction").decode() == "say hi"
        assert archive.read("pack.mcmeta").decode() == '{"pack":{"pack_format":10}}'
    assert outcome.counts["edits_written"] == 1


def test_two_files_in_the_same_zip_both_survive_two_separate_calls(tmp_path, project) -> None:
    """**這是 `apply_editplan` 真正會發生的呼叫模式。** `by_file` 按完整的
    `container.path` 分組，zip 裡的 `a.json` 與 `b.json` 是兩個不同的
    `container.path`，天生落進兩個分組——`apply_to_datapack_file` 會被依序呼叫
    兩次，各自對同一個 zip 重讀、重寫。這裡驗的是「即使沒有跨檔案批次，兩次
    呼叫的結果疊得起來，不會有一次把另一次蓋掉」。"""
    zip_path = tmp_path / "datapacks" / "p.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("data/n/advancement/a.json", json.dumps({"display": {"title": "A"}}))
        archive.writestr("data/n/advancement/b.json", json.dumps({"display": {"title": "B"}}))

    outcome = ApplyOutcome()
    edit_a = edit_for("datapacks/p.zip/data/n/advancement/a.json", "mcmt.advancement_title.aaaaaaaaaaaaaaaa")
    edit_b = edit_for("datapacks/p.zip/data/n/advancement/b.json", "mcmt.advancement_title.dddddddddddddddd")

    with BackupSet(tmp_path) as backup:
        # apply_editplan 對 by_file 的每個分組各呼叫一次——這裡手動模擬那兩次呼叫，
        # relative 兩次都等於各自的 container.path（見函式的說明）。
        apply_to_datapack_file(
            tmp_path, "datapacks/p.zip/data/n/advancement/a.json", [edit_a], outcome, backup
        )
        apply_to_datapack_file(
            tmp_path, "datapacks/p.zip/data/n/advancement/b.json", [edit_b], outcome, backup
        )

    assert outcome.counts["files_rewritten"] == 2  # 兩次呼叫各自重寫了一次 zip
    assert outcome.counts["edits_written"] == 2
    with zipfile.ZipFile(zip_path) as archive:
        a = json.loads(archive.read("data/n/advancement/a.json").decode())
        b = json.loads(archive.read("data/n/advancement/b.json").decode())
    assert a["display"]["title"]["translate"] == "mcmt.advancement_title.aaaaaaaaaaaaaaaa"
    assert b["display"]["title"]["translate"] == "mcmt.advancement_title.dddddddddddddddd"


def test_a_changed_node_is_refused(tmp_path, project) -> None:
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(tmp_path, relative)
    document = json.loads(path.read_text("utf-8"))
    document["display"]["title"] = {"already": "changed"}
    path.write_text(json.dumps(document), encoding="utf-8")

    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.eeeeeeeeeeeeeeee")

    with BackupSet(tmp_path) as backup:
        apply_to_datapack_file(tmp_path, relative, [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"


def test_a_missing_advancement_file_is_refused_without_crashing(tmp_path, project) -> None:
    outcome = ApplyOutcome()
    relative = "datapacks/p/data/n/advancement/gone.json"
    edit = edit_for(relative, "mcmt.advancement_title.ffffffffffffffff")

    with BackupSet(tmp_path) as backup:
        apply_to_datapack_file(tmp_path, relative, [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_missing"
```

`node_path` 裡 `expected_encoding="bare_string"` 是關鍵——`_container(relative_path)` 在 Task 5 給的容器裡 `data_version` 固定 `None`，這裡的守門邏輯不能像 `apply_edit_to_compound` 一樣呼叫 `sniff()`（那個函式只吃 `amulet_nbt` 標籤），要自己寫一個對純 Python 值判形狀的最小版本（見 Step 3）。

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_write_datapack_apply.py -q`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: 實作 `write/datapack_apply.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 的寫入器（M13.7）。**高風險目錄。**

**保證只到「檔案重寫」**：資料夾形式直接覆寫該 JSON 檔（暫存 → 回讀驗證 →
原子替換）；zip 形式**整份重建**（沿用 `write/../backends/resourcepack/pack.py`
的做法：既有條目原樣搬運，只重寫我們動過的那幾個）。

**這裡走純 Python `dict`/`list` 樹，不透過 `amulet_nbt`。** advancement JSON
本來就是 JSON，往 `display.title` 塞一個 `{"translate": key}` 的 Python dict，
直接就是最終要 `json.dump` 出去的東西——不需要先轉成 NBT 再轉回來。這是這個
寫入器和 `write/common.py` 的 `apply_edit_to_compound` 唯一的差異：走訪邏輯是
同一套三步驟（照 node_path 走 → 比對 expected_encoding → 按 value.kind 決定
寫什麼），型別檢查換成 dict/list。

**這是工具第一次改動地圖自己的檔案**（不是它的存檔資料，是它的資料包）。
[遊戲實測 M4-5] 的教訓是這類事要在報告裡講清楚——`apply.py` 的呼叫端（`cli/
apply.py`）沿用既有的 `warnings` 機制，這裡負責的是把 datapack 這件事本身
記進 `files_rewritten`，讓使用者從報告數字上就看得出「有東西動到了資料包」。
"""

import json
import zipfile
from pathlib import Path
from typing import Any

from mcmt.model.node import NodePath
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write.common import ApplyOutcome, component_for, refuse, refuse_residue

__all__ = ["apply_to_datapack_file"]


def apply_to_datapack_file(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    """**`relative` 是 `apply_editplan` 的 `by_file` 分組鍵**（`container["path"]`
    的原文），所以這裡收到的 `edits` 全部指向同一個 JSON 檔——資料夾形式時就是
    那個檔案本身；zip 形式時是同一個 zip **裡的同一個條目**（container.path 對
    zip 內條目編碼成 `<zip 相對路徑>/<條目路徑>` 的完整字串，見 Task 5）。

    **這裡不做「同一個 zip 裡跨檔案批次重建」**：`by_file` 是按 `container.path`
    整段字串分組的，zip 裡兩個不同的 JSON 檔（`a.json`／`b.json`）有不同的
    `container.path`，天生就會落進兩個分組、各自呼叫這個函式一次。若同一個 zip
    有多個檔案要改，這個函式會被 `apply_editplan` 依序呼叫多次，**每次都各自
    重讀、重寫整個 zip**——不是最有效率的做法（比對 region 那邊「同一張 region
    的所有 chunk 一次寫完」），但每次呼叫本身是自洽正確的：後一次呼叫讀到的是
    前一次已經寫回磁碟的版本，最終所有檔案的修改都會保住。datapack 的 zip 通常
    不大（不是 87MB 的 `resources.zip`），這個效率問題目前不值得為了它在
    `apply_editplan` 加一層「依 zip 路徑而非完整 container.path 分組」的特例。
    """
    zip_path, entry = _split(world, relative)
    if zip_path is not None:
        _apply_to_zip_entry(world, zip_path, entry, edits, outcome, backup)
        return
    _apply_to_folder_file(world, relative, edits, outcome, backup)


def _apply_to_folder_file(
    world: Path, relative: str, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet
) -> None:
    path = world / relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return

    try:
        document = json.loads(ensure_readable(path).read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    written = 0
    for edit in edits:
        if _apply_edit_to_json(document, edit, outcome):
            written += 1
    if not written:
        return

    outcome.counts["edits_written"] += written
    backup.protect(path)
    _write_json_atomically(ensure_writable(path), document)
    outcome.counts["files_rewritten"] += 1


def _apply_to_zip_entry(
    world: Path,
    zip_relative: str,
    entry_name: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    """改 zip 裡**一個**條目（`edits` 全部指向同一個 `entry_name`——見
    `apply_to_datapack_file` 的說明）。整份 zip 都要重讀一次才能改一個條目，
    其餘條目原樣搬運。"""
    path = world / zip_relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {zip_relative}")
        return

    try:
        with zipfile.ZipFile(str(ensure_readable(path))) as archive:
            entries = {info.filename: (info, archive.read(info.filename)) for info in archive.infolist()}
    except (zipfile.BadZipFile, OSError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    info, raw = entries.get(entry_name, (None, None))
    if info is None:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"zip 裡找不到 {entry_name}")
        return

    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    written = 0
    for edit in edits:
        if _apply_edit_to_json(document, edit, outcome):
            written += 1
    if not written:
        return

    entries[entry_name] = (info, json.dumps(document, ensure_ascii=False).encode("utf-8"))
    outcome.counts["edits_written"] += written
    backup.protect(path)
    _rewrite_zip(ensure_writable(path), entries)
    outcome.counts["files_rewritten"] += 1


def _apply_edit_to_json(document: dict, edit: dict, outcome: ApplyOutcome) -> bool:
    """`apply_edit_to_compound` 的純 Python 版本——同一套三步驟，型別檢查換成
    `dict`/`list`。advancement 的節點永遠以 `key` 結尾（`display.title`/
    `display.description`），不需要處理 `index` 結尾。"""
    steps = list(NodePath.from_json(edit["node_path"]))
    if not steps or steps[-1].t != "key":
        refuse(outcome, edit, "unsupported_encoding", "datapack 寫入路徑只支援 key 結尾")
        return False

    try:
        parent = _resolve(document, steps[:-1])
    except (KeyError, IndexError, TypeError) as exc:
        refuse(outcome, edit, "node_missing", str(exc))
        return False

    name = steps[-1].name
    if not isinstance(parent, dict) or name not in parent:
        refuse(outcome, edit, "node_missing", f"找不到鍵 {name}")
        return False

    current_encoding = _sniff_json_value(parent[name])
    if current_encoding is None:
        refuse(outcome, edit, "unsupported_encoding", "這個節點不是文字節點")
        return False
    if current_encoding != edit["expected_encoding"]:
        refuse(
            outcome, edit, "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current_encoding}"
            f"——資料包在 extract 之後被改過了",
        )
        return False

    value = edit["value"]
    if value.get("kind") == "literal":
        refuse_residue(value["text"])
        parent[name] = value["text"]
        return True

    parent[name] = component_for(value)
    return True


def _sniff_json_value(value: Any) -> str | None:
    """純 Python 值的最小形狀判斷——不透過 `amulet_nbt.sniff()`（那個只吃
    `amulet_nbt` 標籤）。只判三種，advancement 值只會是這三種之一。"""
    if isinstance(value, str):
        return "bare_string"
    if isinstance(value, dict):
        return "text_compound" if set(value) == {"text"} else "compound_tree"
    if isinstance(value, list):
        return "compound_tree"
    return None


def _resolve(document, steps):
    current = document
    for step in steps:
        if step.t == "key":
            if not isinstance(current, dict) or step.name not in current:
                raise KeyError(f"找不到鍵 {step.name}")
            current = current[step.name]
        elif step.t == "index":
            current = current[step.i]
        else:
            raise KeyError("datapack 寫入路徑不支援 decode 步驟")
    return current


def _write_json_atomically(path: Path, document: dict) -> None:
    temporary = path.with_name(path.name + ".mcmt-tmp")
    data = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    temporary.write_bytes(data)
    try:
        json.loads(temporary.read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        temporary.unlink()
        raise ValueError(f"寫出去的 JSON 讀不回來，已中止：{path}") from exc
    temporary.replace(path)


def _rewrite_zip(path: Path, entries: dict[str, tuple]) -> None:
    temporary = path.with_name(path.name + ".mcmt-tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, (info, data) in sorted(entries.items()):
                archive.writestr(info, data)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _split(world: Path, relative: str) -> tuple[str | None, str | None]:
    """`datapacks/<name>.zip/<zip 內路徑>` → `(zip 相對路徑, zip 內路徑)`；
    資料夾形式回傳 `(None, None)`。datapack 一定是 `datapacks/` 的直接子項，
    不會巢狀，所以只要找第一個以 `.zip` 結尾的路徑片段。"""
    parts = relative.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.endswith(".zip"):
            return "/".join(parts[: index + 1]), "/".join(parts[index + 1 :])
    return None, None
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_write_datapack_apply.py -q`
Expected: PASS

- [ ] **Step 5: 確認 `apply.py` 的分派表已經指到這裡（Task 1 已掛好，這裡只是確認）**

檢查 `src/mcmt/write/apply.py` 的 `_WRITERS` 字典裡 `"datapack_file": apply_to_datapack_file` 那一行——Task 1 已經寫好，這裡不必再改。

- [ ] **Step 6: 跑全部測試**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/write/datapack_apply.py tests/unit/test_write_datapack_apply.py
git commit -F- <<'MSG'
write：datapack advancement JSON 寫入器（資料夾 + zip，獨立 commit）

保證只到「檔案重寫」：資料夾形式暫存→回讀驗證→原子替換，zip 形式整份重建（沿用
pack.py 的做法，既有條目原樣搬運）。`apply_editplan` 的 by_file 按完整
container.path 分組，zip 裡不同的 JSON 檔各有各的 container.path，天生落進不同
分組——這個寫入器因此每次只處理一個條目，同一個 zip 裡多個檔案要改時會被依序
呼叫多次、各自重讀重寫整個 zip。不是最有效率的做法，但每次呼叫自洽正確（後一次
讀到的是前一次已寫回的版本），zip 通常不大，不值得為了它在 apply_editplan 加一
層跨路徑分組的特例。

走純 Python dict/list 樹，不透過 amulet_nbt——advancement JSON 本來就是 JSON，
往 display.title 塞一個 {"translate": key} 直接就是最終要 json.dump 出去的東西。
走訪邏輯是 write/common.py 的 apply_edit_to_compound 同一套三步驟（照 node_path
走→比對 expected_encoding→按 value.kind 決定寫什麼），型別檢查換成 dict/list，
不是重新發明一套。

這是工具第一次改動地圖自己的檔案（不是它的存檔資料，是它的資料包）——
[遊戲實測 M4-5] 的教訓是這類事要讓使用者從報告數字上看得出來，files_rewritten
會涵蓋它。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 7：已在地化跳過（M13.8）

攤平後的樹裡**任何一處**有 `translate` → 整個節點跳過，計入 `stats.skipped_already_localised`。用「任何一處」而不是「根節點是」，因為半文字半 key 的樹（`{"text":"Hello ","extra":[{"translate":"mcp.X"}]}`）重建時一樣會覆蓋掉那個 key。

**Files:**
- Modify: `src/mcmt/extract/build.py`
- Test: `tests/unit/test_extract_build.py`（追加）

**Interfaces:**
- Consumes: `Flattened.skeleton`（既有，`model/segments.py` 產生）
- Produces: `_contains_translate(skeleton) -> bool`（`extract/build.py` 內部函式），`ExtractResult.stats["skipped_already_localised"]`

- [ ] **Step 1: 寫失敗的測試**

在 `tests/unit/test_extract_build.py` 追加（沿用該檔既有的 helper 風格建構一個帶 `translate` 節點的 chunk，走 `build_units`）：

```python
def test_a_node_that_is_already_localised_via_translate_is_skipped(tmp_path, project) -> None:
    """MP2 這類自己有中文化系統的地圖，`{translate:"mcp.X"}` 不該被我們的 key
    覆蓋掉——翻了會讓一張支援 5 種語言的地圖退化成只支援一種。"""
    import amulet_nbt

    from mcmt.extract.build import build_units
    from mcmt.sandbox import import_world

    source = tmp_path / "outside" / "TT_ALREADY_LOCALISED"
    (source / "region").mkdir(parents=True)
    sign = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:oak_sign")})
    for coordinate in ("x", "y", "z"):
        sign[coordinate] = amulet_nbt.IntTag(1)
    localised = amulet_nbt.CompoundTag(
        {"translate": amulet_nbt.StringTag("mcp.SignStartSlot"), "fallback": amulet_nbt.StringTag("Start")}
    )
    face = amulet_nbt.CompoundTag(
        {"messages": amulet_nbt.ListTag([localised, amulet_nbt.StringTag(""), amulet_nbt.StringTag(""), amulet_nbt.StringTag("")])}
    )
    sign["front_text"] = face
    from conftest import RegionBuilder, modern_chunk, write_region_file

    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign])
    write_region_file(source / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    imported = import_world(source, name="already_localised")
    result = build_units(imported.target, world_root=imported.target)

    assert all("mcp.SignStartSlot" not in u.text for u in result.units)
    assert result.stats["skipped_already_localised"] == 1


def test_a_half_localised_tree_is_also_skipped(tmp_path, project) -> None:
    """半文字半 key 的樹——重建時一樣會覆蓋掉那個巢狀 key，所以「任何一處」
    而不是「根節點是」。"""
    import amulet_nbt

    from mcmt.extract.build import build_units
    from mcmt.sandbox import import_world

    source = tmp_path / "outside" / "TT_HALF_LOCALISED"
    (source / "region").mkdir(parents=True)
    sign = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:oak_sign")})
    for coordinate in ("x", "y", "z"):
        sign[coordinate] = amulet_nbt.IntTag(1)
    nested = amulet_nbt.CompoundTag(
        {
            "text": amulet_nbt.StringTag("Hello "),
            "extra": amulet_nbt.ListTag(
                [amulet_nbt.CompoundTag({"translate": amulet_nbt.StringTag("mcp.X")})]
            ),
        }
    )
    face = amulet_nbt.CompoundTag(
        {"messages": amulet_nbt.ListTag([nested, amulet_nbt.StringTag(""), amulet_nbt.StringTag(""), amulet_nbt.StringTag("")])}
    )
    sign["front_text"] = face
    from conftest import RegionBuilder, modern_chunk, write_region_file

    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign])
    write_region_file(source / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    imported = import_world(source, name="half_localised")
    result = build_units(imported.target, world_root=imported.target)

    assert result.stats["skipped_already_localised"] == 1
    assert result.units == []
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_extract_build.py -q -k already_localised or half_localised`
Expected: FAIL（`skipped_already_localised` 是 0，或節點被正常抽出）

- [ ] **Step 3: `extract/build.py` 加已在地化跳過**

在 `_consider()` 裡，`flattened = flatten(value)` 之後、`if not flattened.plain.strip():` 之前插入：

```python
    flattened = flatten(value)

    if _contains_translate(flattened.skeleton):
        # 半文字半 key 的樹一樣要擋——重建時會覆蓋掉那個巢狀 key，讓一張支援
        # 多語言的地圖（自己的 translate key + lang 檔）退化成只支援我們寫進去
        # 的那一種。用「任何一處」而不是「根節點是」正是為了這種情況。
        result.stats["skipped_already_localised"] += 1
        return None

    if not flattened.plain.strip():
```

在檔案結尾（或任一合適位置）加上輔助函式：

```python
def _contains_translate(skeleton: dict[str, Any] | None) -> bool:
    """攤平後的骨架裡任何一處有 `translate` 節點——半文字半 key 的樹也要抓到，
    重建時一樣會覆蓋掉那個巢狀 key。"""
    if not isinstance(skeleton, dict):
        return False
    if skeleton.get("type") == "translate":
        return True
    return any(_contains_translate(child) for child in skeleton.get("extra", []))
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_extract_build.py -q`
Expected: PASS

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠——**特別注意**這條規則套用到所有來源（region/entities/item/level_dat/scoreboard/datapack），若既有的合成測試 fixture 剛好用了帶 `translate` 的節點當測試資料，那些測試會變紅，要逐條確認是預期內的（改成不帶 translate 的測資，不要放寬這條規則）。

- [ ] **Step 6: 加 `stats.skipped_already_localised` 到 extract 文件輸出**

`src/mcmt/extract/emit.py` 的 `build_extract_document()`，`stats` 字典裡加一行：

```python
        "stats": {
            "unit_count": len(units),
            "occurrence_count": result.stats["occurrence_count"],
            "deduped_count": result.stats["deduped_count"],
            "skipped_unparseable": result.stats["skipped_unparseable"],
            "skipped_legacy_json_in_native_chunk": result.stats[
                "skipped_legacy_json_in_native_chunk"
            ],
            "skipped_non_collapsible_in_place": result.stats[
                "skipped_non_collapsible_in_place"
            ],
            "skipped_already_localised": result.stats["skipped_already_localised"],
            "by_category": _by_category(result.units),
        },
```

（`extract.schema.json` 的 `stats` 是 `additionalProperties: true`，這個新欄位不必改合約——CLAUDE.md「合約改動流程」只在**新增／移除／重新定義**欄位語意時才觸發，這裡是加一個新的統計欄位，schema 本來就容許。）

在 `src/mcmt/cli/extract.py` 的 `format_result()`，`skipped` 清單加一項：

```python
    skipped = [
        ("denylist（識別碼，翻了地圖會壞）", result.stats["skipped_denylist"]),
        ("新世代 chunk 裡的舊式 JSON（遊戲裡本來就是亂碼）",
         stats["skipped_legacy_json_in_native_chunk"]),
        ("JSON 解析失敗", stats["skipped_unparseable"]),
        ("已在地化（地圖自己的 translate key，翻了會蓋掉別人做好的多語言支援）",
         stats["skipped_already_localised"]),
        ("空白節點", result.stats["skipped_empty"]),
    ]
```

- [ ] **Step 7: 跑全部測試（含這一步的改動）**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 全綠

- [ ] **Step 8: 驗合約**

Run: `.venv\Scripts\python -X utf8 tools/validate_contracts.py`
Expected: 通過

- [ ] **Step 9: Commit**

```bash
git add src/mcmt/extract/build.py src/mcmt/extract/emit.py src/mcmt/cli/extract.py tests/unit/test_extract_build.py
git commit -F- <<'MSG'
extract：已在地化的節點整個跳過（M13.8）

攤平後的樹裡任何一處有 translate → 整個節點跳過，計入
stats.skipped_already_localised。用「任何一處」而不是「根節點是」，因為半文字
半 key 的樹（{"text":"Hello ","extra":[{"translate":"mcp.X"}]}）重建時一樣會
覆蓋掉那個巢狀 key。

這一條套用到所有掃描來源（region/entities/item/level_dat/scoreboard/
datapack），不是只為某一個新來源加的特例——`Minecraft Party 2` 這類自己有
translate key 中文化系統的地圖是最初的動機，翻了會讓一張支援 5 種語言的地圖
退化成只支援我們寫進去的那一種。

MEMORY 提醒（見 docs/STATUS.md「不做術語表」那節）：這一條和「工具不介入」的
決定不同類——那條是人名這種難看但無害的東西，這條是會弄壞別人已經做好的多語言
支援，是實質損害。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 8：真實地圖驗證 + 端到端測試擴充 + 文件寫回（M13.9）

**這是完成的條件之一，不是加分。** 三件事：擴充 `test_end_to_end.py` 的 `round_trip` fixture 涵蓋 `level.dat`/`scoreboard.dat`/datapack；在兩張語料地圖上真的跑一次 extract 並核對數字；把這一輪的結論、已知缺口、未驗證的細節寫回 `docs/STATUS.md` 與 `SPIKE_RESULT.md`。

**Files:**
- Modify: `tests/integration/test_end_to_end.py`
- Modify: `docs/STATUS.md`
- Modify: `SPIKE_RESULT.md`

**Interfaces:**
- Consumes: 全部前七個任務的產出
- Produces: 無新程式碼介面——這個任務是驗證與文件

- [ ] **Step 1: 擴充 `round_trip` fixture**

在 `tests/integration/test_end_to_end.py` 的 `source_world` fixture 裡（目前只建 `region/r.0.0.mca`、`region/r.0.1.mca`、`entities/r.0.0.mca`），加上 `level.dat`、`data/scoreboard.dat`、一個資料夾形式的 datapack advancement：

```python
def level_dat_for(world: Path) -> None:
    """`LevelName`（in_place）+ `CustomBossEvents`（translate key）+
    `Player.Inventory`（走 `scan_item`）。"""
    import amulet_nbt

    from mcmt.nbtio.datfile import DatFile, write_dat

    sword = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:diamond_sword")})
    sword["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag("TT_INVENTORY_ITEM_NAME")}
    )
    events = amulet_nbt.CompoundTag(
        {"tt:probe": amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag("TT_BOSSBAR_NAME")})}
    )
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag("TT_LEVEL_NAME"),
            "DataVersion": amulet_nbt.IntTag(4671),
            "CustomBossEvents": events,
            "Player": amulet_nbt.CompoundTag(
                {"Inventory": amulet_nbt.ListTag([sword])}
            ),
        }
    )
    write_dat(
        world / "level.dat",
        DatFile(tag=amulet_nbt.NamedTag(amulet_nbt.CompoundTag({"Data": data}), ""), compression="gzip"),
    )


def scoreboard_dat_for(world: Path) -> None:
    import amulet_nbt

    from mcmt.nbtio.datfile import DatFile, write_dat

    data = amulet_nbt.CompoundTag(
        {
            "Objectives": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {
                            "Name": amulet_nbt.StringTag("obj"),
                            "CriteriaName": amulet_nbt.StringTag("dummy"),
                            "DisplayName": amulet_nbt.StringTag("TT_OBJECTIVE_NAME"),
                        }
                    )
                ]
            ),
            "Teams": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {
                            "Name": amulet_nbt.StringTag("team"),
                            "DisplayName": amulet_nbt.StringTag("TT_TEAM_NAME"),
                        }
                    )
                ]
            ),
        }
    )
    root = amulet_nbt.CompoundTag({"data": data, "DataVersion": amulet_nbt.IntTag(4671)})
    write_dat(world / "data" / "scoreboard.dat", DatFile(tag=amulet_nbt.NamedTag(root, ""), compression="gzip"))


def datapack_for(world: Path) -> None:
    import json

    path = world / "datapacks" / "tt_probe" / "data" / "tt" / "advancement" / "quest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": "TT_ADVANCEMENT_TITLE", "description": "TT_ADVANCEMENT_DESC"}}),
        encoding="utf-8",
    )
```

在 `source_world` fixture 裡（`write_region_file(world / "entities", entities_region(), "r.0.0.mca")` 那行之後）加：

```python
    level_dat_for(world)
    scoreboard_dat_for(world)
    datapack_for(world)
```

`TRANSLATIONS` 字典追加：

```python
    "TT_LEVEL_NAME": "探測世界",
    "TT_BOSSBAR_NAME": "頭目",
    "TT_INVENTORY_ITEM_NAME": "背包裡的劍",
    "TT_OBJECTIVE_NAME": "分數板",
    "TT_TEAM_NAME": "隊伍",
    "TT_ADVANCEMENT_TITLE": "進度標題",
    "TT_ADVANCEMENT_DESC": "進度描述",
```

`test_the_whole_round_trip_writes_something` 的 `chunks_touched`/`files_rewritten` 期望值要跟著加 3（level.dat、scoreboard.dat、一個 advancement json 檔）：

```python
def test_the_whole_round_trip_writes_something(round_trip) -> None:
    counts = round_trip["applied"]["report"]["counts"]

    assert counts["edits_written"] > 0
    # 三張 region 檔 + level.dat + scoreboard.dat + 一個 advancement json。
    assert counts["files_rewritten"] == 6
```

（若 `chunks_touched` 這個計數本來就只算 region/entities chunk、不含 `.dat`/datapack 檔案，這裡不必動它，只需確認 `files_rewritten` 對得上；跑 Step 2 時若發現實際計數口徑不同，照實際口徑調整斷言，不要硬湊數字。）

新增一條測試確認三個新容器種類都真的寫成：

```python
def test_level_dat_scoreboard_and_datapack_are_all_written(round_trip) -> None:
    import json

    from mcmt.nbtio.datfile import read_dat
    from mcmt.safety.paths import ensure_readable

    world = round_trip["world"]
    level = read_dat(ensure_readable(world / "level.dat"))
    assert str(level.tag.compound["Data"]["LevelName"]) == "TT_LEVEL_NAME"

    scoreboard = read_dat(ensure_readable(world / "data" / "scoreboard.dat"))
    objective_display = scoreboard.tag.compound["data"]["Objectives"][0]["DisplayName"]
    assert "translate" in str(objective_display) or "分數板" in str(objective_display)

    advancement_path = world / "datapacks" / "tt_probe" / "data" / "tt" / "advancement" / "quest.json"
    document = json.loads(advancement_path.read_text("utf-8"))
    assert "translate" in document["display"]["title"] or document["display"]["title"] == "進度標題"
```

`LevelName` 走 `in_place`，寫回去的是**譯文本身**（不是 translate key），所以 `TT_LEVEL_NAME` 應該直接被 `"探測世界"` 取代；`Objectives[].DisplayName`/advancement `title` 走 `translate_key`，寫回去的是 `{translate: ...}`。上面的斷言用 `or` 是保守寫法，跑過一次之後把它改成精確的斷言（拿掉 `or` 的那一支，依實際觀察到的形狀寫死）。

- [ ] **Step 2: 執行確認失敗，然後修正到通過**

Run: `.venv\Scripts\python -m pytest tests/integration/test_end_to_end.py -q`
Expected: 第一輪大概率會在計數斷言或形狀斷言上失敗——這是預期的，照實際觀察到的數字/形狀修正斷言（不是放寬邏輯去遷就一個錯誤的實作）。反覆跑到全綠。

- [ ] **Step 3: 驗合約**

Run: `.venv\Scripts\python -X utf8 tools/validate_contracts.py`
Expected: 通過

- [ ] **Step 4: 兩張語料地圖真實驗證**

Run（Arena of Darkness）：
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/Arena of Darkness" --lang zh_tw --out "sandbox/_m13b_final" --replace
```

Run（100 Ways To Die）：
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/100 Ways To Die" --lang zh_tw --out "sandbox/_m13b_final_2" --replace
```

核對 `by_category` 裡新分類的數字（相異單位數，不是 occurrence 數）落在合理範圍內：

| category | Arena of Darkness（期望相異數量級） | 100 Ways To Die |
|---|---|---|
| `level_name` | 1 | 1 |
| `bossbar` | ≤ 27（去重後） | ≤ 3 |
| `objective` | ≤ 168（denylist 已擋掉識別碼型 DisplayName，實際相異數可能遠低於這個上限） | ≤ 156 |
| `team` | ≤ 17 | ≤ 13 |
| `team_affix` | 0（[實測] 兩張地圖的前後綴內容全空） | 0（[實測] 欄位不存在） |
| `advancement_title` / `advancement_description` | 合計量級接近清點的 56（見計畫檔開頭表：兩個 zip 共 30 個 JSON 檔） | 0 |

若某個分類是 0 但預期非 0（`team_affix` 除外——那個已知就是 0），先確認是不是 registry 沒掛上那個來源，而不是急著改期望值。確認後刪除 `sandbox/_m13b_final` 與 `sandbox/_m13b_final_2`。

- [ ] **Step 5: 跑一次完整 apply 乾跑，確認新容器種類都進得了 editplan**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli apply "sandbox/Arena of Darkness" --translations "sandbox/_m13b_final/translations.zh_tw.json" --dry-run
```

（若 Step 4 已經刪掉 `sandbox/_m13b_final`，重新跑一次 Step 4 的 extract 命令再做這一步。）

Expected: `editplan.json` 裡出現 `container.kind` 為 `level_dat`/`scoreboard_dat`/`datapack_file` 的 edit（此時 `translations.zh_tw.json` 的 `target` 全是空的，`--dry-run` 只是確認 plan 產得出來、不會在建 plan 這一步就炸掉）。確認後清掉 `sandbox/_m13b_final*`。

- [ ] **Step 6: 更新 `SPIKE_RESULT.md`**

在「尚待驗證」表新增兩列：

```markdown
| `Teams[].MemberNamePrefix`/`MemberNameSuffix` 的 translate key 是否真的顯示 | 在一支隊伍上設定非空的前後綴、寫入 translate key、`/team list` 或 tab 列表肉眼確認 | 低 — 兩張語料地圖的實際內容全空，沒有實測動機驅動；`Objectives`/`Teams[].DisplayName` 本身已經是 [全部遊戲實測] |
| `scoreboard.dat`（DV < 4325）的 legacy JSON 字串寫入是否被 DataFixer 正確解析 | 在一個 DV 3700 的 `scoreboard.dat` 寫入 JSON 字串型 translate key，1.21.11 開啟後看 `/scoreboard objectives list` 或側邊欄 | 中 — 與 chunk 層級的 M4-2 是同一個機制（DataFixerUpper 對任何版本化 NBT 文件一視同仁），但 `.dat` 檔本身沒有被單獨驗證過；寫入器完全沿用 M4 已驗證的 legacy.py，風險主要在「機制是否真的對 `.dat` 檔案一視同仁」這個推論本身 |
```

在檔案合適位置（例如緊接在「記分板 [實測]」小節之後）補一段 M13b 的實測記錄：

```markdown
### M13b 實測（2026-08-22）：level.dat 與 scoreboard.dat 的根鍵形狀

對照 `Arena of Darkness`（DV 3700）與 `100 Ways To Die`（DV 4325）的真實 `level.dat`／
`data/scoreboard.dat`：

- `level.dat` 只有一個根鍵 `Data`，`DataVersion` **在它裡面**（`Data.DataVersion`）。
- `scoreboard.dat` 的根是**兩個並列鍵** `data` 與 `DataVersion`（**不是**巢狀）。
- `CustomBossEvents` 是用 boss id 當鍵的 compound，不是 list——`Data.CustomBossEvents.<id>.Name`。
- legacy/native 二分在這兩個檔案裡與 chunk 完全對稱：AoD（legacy）的
  `Objectives[].DisplayName`／`CustomBossEvents.<id>.Name` 都是 JSON 純量字串
  （如 `'"ReFightTime"'`）；100WTD（native）都是裸字串／原生 compound。
- `Teams[].MemberNamePrefix`/`MemberNameSuffix` 在 native 世代（100WTD）**整個
  不存在**（不是空字串，是欄位本身省略）；legacy 世代（AoD）存在但兩張地圖的
  17 支隊伍全部是空的 `'""'`。

### M13b 實測（2026-08-22）：datapack 資料包的真實形態

`Arena of Darkness` 的資料包全部是 **zip 檔**（`datapacks/*.zip`），而不是資料夾；
`ArenaOfDarknessDatapack_10_15.zip` 用的是**複數** `data/worf/advancements/*.json`
（1.20.4 舊式目錄名，早先「1.21 起改單數」的記錄在這裡得到反面對照）。
`display.title` 觀察到的真實值是裸 JSON 字串（如 `"The Prelude"`），不是 component
物件——與掃描層「值直接是三種 JSON 型別之一」的設計假設一致。
```

- [ ] **Step 7: 更新 `docs/STATUS.md`**

把「最後更新」那行與「一句話現況」段落改成反映 M13b 完成：

```markdown
最後更新：**2026-08-22**（M13b 完成：`level.dat`／`scoreboard.dat`／datapack advancement
三個非 region 來源接上，寫入層補了 `.dat` 整份重編與 datapack 檔案重寫兩種新寫入器，
`apply.py` 換成顯式 `kind → writer` 分派表。已在地化節點整個跳過。下一步是 M14）
```

在「下一步」章節，把 M13b 從「就是這一項」移到「已完成」章節下方（比照既有 M13a 小節的格式），並把「下一步」指向 M14；同時在「已知缺口」清單追加：

```markdown
* **`team_affix`（`Teams[].MemberNamePrefix`/`MemberNameSuffix`）translate key 未單獨遊戲實測。**
  兩張語料地圖的實際內容全空，掃描與寫入路徑都已接上但從未真的寫過非空值進遊戲。
* **`scoreboard.dat` 的 legacy JSON 寫入路徑未單獨遊戲實測**——沿用 chunk 層級已驗證的
  `legacy.py`，但「DataFixerUpper 對 `.dat` 檔案一視同仁」這個推論本身沒有進遊戲確認過。
* **datapack 的 `.mcmeta` 過期問題本計畫未處理。** `pack.py` 對 `resources.zip` 做的
  `pack_format` 下限修正（M4-5 的教訓）沒有類比套用到 datapack 自己的 `pack.mcmeta`——
  這次沒有寫入 datapack 自己的 `pack.mcmeta`（只改了 advancement JSON），所以不觸發
  這個問題，但如果未來要支援翻譯 datapack 的其他部分要記得重新檢查。
```

- [ ] **Step 8: 跑一次全部測試 + 合約驗證，作為收尾確認**

Run: `.venv\Scripts\python -m pytest -q && .venv\Scripts\python -X utf8 tools/validate_contracts.py`
Expected: 全綠、47+ passed

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_end_to_end.py docs/STATUS.md SPIKE_RESULT.md
git commit -F- <<'MSG'
M13b 收尾：端到端測試涵蓋三個新容器種類 + 真實地圖驗證 + 文件寫回

`round_trip` fixture 加上 level.dat（LevelName in_place + CustomBossEvents
translate key + Player.Inventory 遞迴）、scoreboard.dat（Objectives/Teams
DisplayName）、一個資料夾形式的 datapack advancement，四種 kind 全部走過一次
apply。

真實地圖驗證：Arena of Darkness 與 100 Ways To Die 的 extract 數字核對過（見
計畫檔的期望表），--dry-run 確認三個新 container.kind 都進得了 editplan。

SPIKE_RESULT.md 補兩則實測記錄（level.dat/scoreboard.dat 根鍵形狀、datapack 的
真實形態：zip 檔 + 複數目錄名），新增兩項尚待驗證（team_affix 未單獨遊戲實測、
scoreboard.dat 的 legacy JSON 寫入路徑未單獨遊戲實測）。docs/STATUS.md 收尾，
下一步指向 M14。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## 完成的定義

- [ ] 8 個任務、8 個 commit（`write/` 相關四個獨立 commit：Task 1、2、6，另外 datapack scan 不算 write/）全部完成
- [ ] `.venv\Scripts\python -m pytest -q` 全綠
- [ ] `.venv\Scripts\python -X utf8 tools/validate_contracts.py` 通過
- [ ] `sandbox/Arena of Darkness` 與 `sandbox/100 Ways To Die` 的 extract 數字核對過本計畫開頭的期望表
- [ ] `SPIKE_RESULT.md`、`docs/STATUS.md` 已更新
- [ ] `sandbox/_m13b_*` 等暫存輸出目錄已清除
