# M13a 掃描廣度：物品與實體 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓掃描範圍從「告示牌 + 方塊實體 CustomName」擴大到「物品名／lore／書本（新舊兩套格式、含容器遞迴）＋ `entities/*.mca` 的實體」，並補掉 denylist 的三個真漏洞。

**Architecture:** 掃描層改成**來源註冊表**（一份函式清單，每個來源一個模組）；物品抽成**跨來源的共用元件**，被方塊實體、實體裝備、玩家背包三處呼叫。寫入層這一份計畫**完全不動**——`entities/*.mca` 就是 region 格式，現有的外科式寫入路徑直接可用。

**Tech Stack:** Python 3.11 · `amulet-nbt` · pytest。執行期只允許 `amulet-nbt` + stdlib（`jsonschema` 是 dev 相依）。

**Spec:** `docs/superpowers/specs/2026-08-22-m13-scan-breadth-design.md`

## Global Constraints

這些是 `CLAUDE.md` 的專案規則，**每個任務都適用**，不會在各任務裡重複：

- 每個原始碼檔頂端：`# SPDX-License-Identifier: GPL-3.0-or-later`
- **TDD**：先寫失敗的測試 → 執行確認失敗 → 最小實作 → 執行確認通過 → commit。**一個任務一個 commit。**
- `src/mcmt/write/` 與 `src/mcmt/safety/` 的修改**必須是獨立 commit 並說明理由**。（本計畫不碰這兩個目錄。）
- `src/mcmt/model/` 與 `docs/contracts/` 同上。（本計畫不碰。）
- **形狀一律逐節點嗅探，永不由 `DataVersion` 推導**。
- 掃描層是**白名單**：只去找已知的可翻譯欄位，不走遍樹。
- 測試 fixture 一律取自自建探測世界，**不放語料地圖的內容**（授權考量）。
- 跑測試：`.venv\Scripts\python -m pytest`（全域 python 沒有 pytest）
- 跑 CLI：`.venv\Scripts\python -X utf8 -m mcmt.cli …`（`-X utf8` 是必要的）
- 驗合約：`.venv\Scripts\python -X utf8 tools/validate_contracts.py`
- **含跳脫序列的檔案改用 Write 工具**，不要用 heredoc（會吃掉反斜線）。

**基準線**：開工時 `588 passed`、合約 `47 passed`。

---

## 既有介面速查

這份計畫的程式碼會用到這些既有的東西。**執行者不需要先讀完整個 codebase**，這裡列的就夠了。

```python
# src/mcmt/scan/sources/region.py
@dataclass(frozen=True)
class TextNode:
    path: NodePath              # 從 chunk 根走到這個節點的指路
    tag: Any                    # amulet_nbt 的 StringTag / CompoundTag
    category: str               # "sign" / "block_entity_name" / ...
    anchor: dict | None = None  # {"kind","id","x","y","z","uuid"}
    list_context: dict | None = None

def scan_chunk(root: amulet_nbt.CompoundTag) -> Iterator[TextNode]: ...

# src/mcmt/model/node.py
NodePath([key_step("block_entities")]).child(index_step(3)).child(key_step("Items"))
key_step(name: str) -> PathStep
index_step(i: int) -> PathStep

# src/mcmt/nbtio/region.py
def region_files(world: ReadOnlyPath) -> list[ReadOnlyPath]:
    """所有名為 `region` 的目錄底下的 *.mca，依路徑排序。"""
def read_region(path: ReadOnlyPath) -> Iterator[RawChunk]: ...

@dataclass(frozen=True)
class RawChunk:
    index: int; local_x: int; local_z: int
    payload: bytes              # 磁碟上的原始壓縮位元組，未解壓
    compression_type: int; is_external: bool; timestamp: int

# src/mcmt/nbtio/structure.py
def load_chunk_root(raw: RawChunk) -> amulet_nbt.CompoundTag: ...
def ensure_supported_structure(root, *, chunk_index: int) -> int:
    """回傳這個 chunk 自己的 DataVersion；結構不支援時拋 UnsupportedWorldStructureError。"""

# src/mcmt/nbtio/datfile.py
@dataclass(frozen=True)
class DatFile:
    tag: amulet_nbt.NamedTag
    compression: str            # "gzip" | "zlib" | "none"
def read_dat(path: ReadOnlyPath) -> DatFile: ...
def write_dat(path: Path | str, dat: DatFile) -> Path: ...

# src/mcmt/safety/paths.py
def ensure_readable(p) -> ReadOnlyPath: ...
def ensure_writable(p) -> Path: ...

# tests/conftest.py  （測試用）
RegionBuilder().add_chunk_nbt(index, root).build() -> bytearray
write_region_file(directory, data, name="r.0.0.mca") -> Path
modern_chunk(data_version=4671) -> CompoundTag   # 只有 DataVersion 的最小 chunk
project  # pytest fixture：建一個假專案根，cwd 設在它底下，sandbox 指向 tmp_path/sandbox
```

---

## 檔案結構

| 檔案 | 職責 | 任務 |
|---|---|---|
| `src/mcmt/nbtio/datfile.py` | **修改**：`write_dat` 加回讀驗證 | 1 |
| `src/mcmt/rules/sets/denylist.py` | **修改**：三項修正 + 物品陷阱路徑 | 2 |
| `src/mcmt/fingerprint.py` | **修改**：指紋納入 `entities/` | 3 |
| `src/mcmt/nbtio/region.py` | **修改**：新增 `entities_files()` | 3 |
| `src/mcmt/scan/node.py` | **新增**：`TextNode` 與 `ScannedNode` 的家 | 4 |
| `src/mcmt/scan/registry.py` | **新增**：`SOURCES` 函式清單 | 4 |
| `src/mcmt/scan/sources/region.py` | **修改**：加 `scan(world, stats)` 進入點 | 4 |
| `src/mcmt/extract/build.py` | **修改**：改成跑過註冊表 | 4 |
| `src/mcmt/scan/sources/item.py` | **新增**：跨來源共用的物品掃描 | 5, 6 |
| `src/mcmt/scan/sources/entities.py` | **新增**：`entities/*.mca` | 8 |

---

## Task 1: `write_dat` 加回讀驗證

`.dat` 是**整份重編**的（M3.2 已確認「這裡沒有外科式寫入這回事」），編壞了就是整個 `level.dat` 沒了，而那是世界的中樞。region 那邊不需要這一步，因為外科式寫入把未改動的位元組原封送回，壞掉的只可能是我們自己編的那一個 chunk。

**Files:**
- Modify: `src/mcmt/nbtio/datfile.py`（`write_dat`）
- Test: `tests/unit/test_datfile.py`

**Interfaces:**
- Consumes: `DatFile`, `read_dat`, `write_dat`（既有）
- Produces: `write_dat` 的行為不變（同樣回傳 `Path`），但寫入前多一道驗證；驗證失敗拋 `DatWriteVerificationError`（新，繼承 `FormatError`）

- [ ] **Step 1: 寫失敗的測試**

加到 `tests/unit/test_datfile.py` 末尾：

```python
def test_a_corrupt_encode_leaves_the_original_untouched(tmp_path, monkeypatch) -> None:
    """**整份重編的東西編壞了，原檔一個位元都不能動。**

    `.dat` 沒有外科式寫入這回事——`level.dat` 是一份檔案，改一個欄位就得整份重編。
    所以「寫壞」的後果是整個世界的中樞沒了，不是一個 chunk 壞掉。
    """
    import amulet_nbt

    from mcmt.errors import DatWriteVerificationError
    from mcmt.nbtio import datfile

    target = tmp_path / "level.dat"
    original = amulet_nbt.NamedTag(
        amulet_nbt.CompoundTag({"Data": amulet_nbt.CompoundTag(
            {"LevelName": amulet_nbt.StringTag("原本的世界")}
        )}),
        "",
    )
    datfile.write_dat(target, datfile.DatFile(tag=original, compression="gzip"))
    before = target.read_bytes()

    # 讓編碼器吐出讀不回來的位元組。
    monkeypatch.setattr(
        datfile, "_encode", lambda dat, target: b"\x0a\xff\xff not nbt at all"
    )
    replacement = amulet_nbt.NamedTag(
        amulet_nbt.CompoundTag({"Data": amulet_nbt.CompoundTag(
            {"LevelName": amulet_nbt.StringTag("新的世界")}
        )}),
        "",
    )

    with pytest.raises(DatWriteVerificationError):
        datfile.write_dat(target, datfile.DatFile(tag=replacement, compression="gzip"))

    assert target.read_bytes() == before


def test_no_temporary_file_is_left_behind_when_verification_fails(
    tmp_path, monkeypatch
) -> None:
    """失敗時不留垃圾——下一次寫入不該撞到上一次的殘骸。"""
    import amulet_nbt

    from mcmt.errors import DatWriteVerificationError
    from mcmt.nbtio import datfile

    target = tmp_path / "level.dat"
    tag = amulet_nbt.NamedTag(
        amulet_nbt.CompoundTag({"Data": amulet_nbt.CompoundTag({})}), ""
    )
    datfile.write_dat(target, datfile.DatFile(tag=tag, compression="none"))

    monkeypatch.setattr(datfile, "_encode", lambda dat, target: b"garbage")
    with pytest.raises(DatWriteVerificationError):
        datfile.write_dat(target, datfile.DatFile(tag=tag, compression="none"))

    assert list(tmp_path.glob("*.mcmt-tmp")) == []


def test_a_good_write_still_round_trips(tmp_path) -> None:
    """驗證那一步不能把正常的寫入擋下來。"""
    import amulet_nbt

    from mcmt.nbtio import datfile
    from mcmt.safety.paths import ensure_readable

    target = tmp_path / "level.dat"
    tag = amulet_nbt.NamedTag(
        amulet_nbt.CompoundTag({"Data": amulet_nbt.CompoundTag(
            {"LevelName": amulet_nbt.StringTag("測試世界")}
        )}),
        "",
    )
    datfile.write_dat(target, datfile.DatFile(tag=tag, compression="gzip"))

    read_back = datfile.read_dat(ensure_readable(target))
    assert str(read_back.tag.compound["Data"]["LevelName"]) == "測試世界"
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_datfile.py -q`
Expected: FAIL — `ImportError: cannot import name 'DatWriteVerificationError'`

- [ ] **Step 3: 加例外類別**

在 `src/mcmt/errors.py` 裡，緊接在既有的 `FormatError` 家族後面加：

```python
class DatWriteVerificationError(FormatError):
    """`.dat` 寫出去的位元組讀不回來——原檔沒有被動過。

    `.dat` 是整份重編的（不像 region 有外科式寫入），所以「編壞了」的後果是整個
    檔案沒了。寫入前先回讀驗證，失敗就中止並保留原檔。
    """
```

- [ ] **Step 4: 把編碼抽成 `_encode` 並加驗證**

改 `src/mcmt/nbtio/datfile.py`。先把既有 `write_dat` 裡的編碼那兩行抽成一個模組層級的函式（測試要 monkeypatch 它）：

```python
def _encode(dat: DatFile, target: Path) -> bytes:
    """把一份 `DatFile` 編成磁碟上的位元組。

    抽成函式是為了讓驗證測試替換得掉它——不然沒有辦法製造「編碼器吐出壞位元組」
    這個情境，而那正是要驗的那一件事。`target` 只在壓縮形式不認得時用來組錯誤訊息。
    """
    payload = dat.tag.save_to(compressed=False)
    return _compress(payload, dat.compression, target)
```

然後把 `write_dat` 改成：

```python
def write_dat(path: Path | str, dat: DatFile) -> Path:
    """整份重新編碼寫出去：**暫存 → 回讀驗證 → 原子替換**。

    中間那一步是這裡與 `write_region` 最大的差別。region 是外科式的——未改動的
    chunk 帶著磁碟上的原始位元組原封送回，所以編壞了最多壞一個 chunk。`.dat`
    是一份檔案整份重編，編壞了就是整個 `level.dat` 沒了，而那是世界的中樞。

    驗證失敗時**原檔一個位元都沒有被動過**，因為 `os.replace` 還沒發生。
    """
    target = ensure_writable(path)
    data = _encode(dat, target)

    temporary = ensure_writable(target.with_name(target.name + ".mcmt-tmp"))
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_bytes(data)
        _verify(temporary, target)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def _verify(temporary: Path, target: Path) -> None:
    """回讀剛寫出去的暫存檔，確認它真的解析得回來。"""
    try:
        read_back = read_dat(ensure_readable(temporary))
    except Exception as exc:  # noqa: BLE001 —— 任何讀不回來的理由都一樣致命
        raise DatWriteVerificationError(
            f"寫出去的位元組讀不回來，已中止：{target}。"
            f"原檔沒有被動過。原因：{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(read_back.tag.compound, amulet_nbt.CompoundTag):
        raise DatWriteVerificationError(
            f"寫出去的位元組解析出來不是 TAG_Compound，已中止：{target}。原檔沒有被動過。"
        )
```

`_compress(payload, compression, path)` 的第三個參數只在「壓縮形式不認得」時用來組
錯誤訊息，所以 `_encode` 把 `target` 原樣傳下去即可，不必改 `_compress`。

檔頭 import 補上：

```python
from mcmt.errors import DatWriteVerificationError
```

- [ ] **Step 5: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_datfile.py tests/integration/test_datfile_roundtrip.py -q`
Expected: PASS（含既有的 round-trip 測試——真實 `level.dat` 的 L1 保證不能被這次改動破壞）

- [ ] **Step 6: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/errors.py src/mcmt/nbtio/datfile.py tests/unit/test_datfile.py
git commit -F- <<'MSG'
nbtio：write_dat 加回讀驗證（暫存 → 驗證 → 原子替換）

`.dat` 是整份重編的，沒有外科式寫入這回事（M3.2 的結論）——編壞了就是整個
`level.dat` 沒了，而那是世界的中樞。region 那邊不需要這一步，因為外科式寫入把
未改動的 chunk 原封送回，壞掉的只可能是我們自己編的那一個。

改成寫完暫存檔之後回讀、重新解析、確認根節點是 TAG_Compound，通過才 os.replace。
失敗拋 DatWriteVerificationError 並刪掉暫存檔，**原檔一個位元都沒有被動過**。

M13 會第一次真的用 write_dat 改別人的存檔（level.dat 的 LevelName 與
CustomBossEvents、scoreboard.dat 的 DisplayName），所以這一步要走在前面。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 2: denylist 三項修正 + 物品陷阱路徑

清點三張真實地圖時發現的。**`Lock` 那一項是最兇的**：值必須與鑰匙物品的名字完全相同才能開箱，翻了它箱子永遠打不開，而症狀離原因很遠。

**Files:**
- Modify: `src/mcmt/rules/sets/denylist.py`
- Test: `tests/unit/test_rules_denylist.py`

**Interfaces:**
- Consumes: `Subject(key_path=…, value=None)`, `label(subject, RULES)`, `DENY_LABEL`（既有）
- Produces: 規則集行為改變，公開 API 不變

- [ ] **Step 1: 寫失敗的測試**

加到 `tests/unit/test_rules_denylist.py` 末尾：

```python
def denied(*keys: str) -> bool:
    """這條路徑會不會被擋。"""
    from mcmt.rules.engine import Subject, label
    from mcmt.rules.sets.denylist import DENY_LABEL, RULES

    return DENY_LABEL in label(Subject(key_path=keys, value=None), RULES)


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
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_rules_denylist.py -q`
Expected: FAIL — `test_last_output_is_denied_at_every_depth`、`test_a_namespaced_profile_texture_is_denied`、`test_a_container_lock_is_denied`、`test_item_mechanic_tags_are_denied` 四條紅

- [ ] **Step 3: 改 denylist**

`src/mcmt/rules/sets/denylist.py`：

從 `_DENIED_TAILS` 移除這兩行：

```python
    ("LastOutput",): "runtime_output",
    ("profile", "properties", "value"): "skin_texture",
```

`_DENIED_TAILS` 加入（`SkullOwner` 不放這裡——它整段都要擋，見下面的
`_DENIED_ANYWHERE`）：

```python
    ("Trim", "material"): "identifier",
    ("Trim", "pattern"): "identifier",
```

`_DENIED_ANYWHERE` 加入：

```python
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
```

`_REASON_TEXT` 加入：

```python
    "container_lock": "容器鎖，值必須與鑰匙物品的名字完全相同——翻了箱子永遠打不開",
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_rules_denylist.py tests/integration/test_denylist_regression.py -q`
Expected: PASS

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠。**若 `test_denylist_regression.py` 變紅**，看它報的數字——擋掉的節點變多是預期的，把測試裡的期望值照新的數字更新，但要逐條確認多擋的都是識別碼。

- [ ] **Step 6: Commit**

```bash
git add src/mcmt/rules/sets/denylist.py tests/unit/test_rules_denylist.py
git commit -F- <<'MSG'
denylist：修掉尾巴比對的兩個漏洞，並補上物品遞迴路上的陷阱

清點三張真實地圖時發現的（走遍每個字串節點、過一次 denylist、看沒被擋的還剩什麼）。

**三項修正：**

* `LastOutput` 原本在「路徑尾巴」清單，只擋得到結尾正好是它的節點。
  `LastOutput/text` 與 `LastOutput/extra[]/translate` 全漏——[實測] 100 Ways To Die
  有 6,000 多個，而且它們含原版 translate key。改成「路徑含有」。
* `("profile","properties","value")` 認不到 1.20.5+ 的 `minecraft:profile`
  （鍵名帶命名空間）。[實測] 100WTD 漏掉 26 個 base64 皮膚材質。整段擋掉。
* **`Lock` / `minecraft:lock` 是新發現的，而且最兇。** [實測] Arena of Darkness
  有 107 個。容器鎖的值必須與鑰匙物品的名字完全相同才能開箱——翻了它箱子永遠
  打不開，而症狀離原因非常遠。SPIKE_RESULT 的排除清單裡沒有它。

另外補上物品遞迴路上會碰到的識別碼：SkullOwner、BlockStateTag、Potion、Trim、
CanDestroy/CanPlaceOn、LootTable。掃描層是白名單本來就不會去找它們，但第二道
防線的意義就在於第一道漏掉的時候。

一併加了一條反面的對照測試：擋過頭的症狀是「有些東西沒被抽出來」，和「本來就
沒有」長得一模一樣。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 3: 世界指紋納入 `entities/`

`nbtio/region.py` 的 docstring 早就預告了這件事：掃描範圍擴大到 entities 時，「什麼算這個世界的內容」要一起重新定義。不改的話，「使用者玩過一次、動了盔甲座」不會讓指紋改變，`extract_fingerprint` 會說「世界沒變」而實際上變了。

**Files:**
- Modify: `src/mcmt/nbtio/region.py`（新增 `entities_files`）
- Modify: `src/mcmt/fingerprint.py`
- Test: `tests/unit/test_fingerprint.py`, `tests/unit/test_region.py`

**Interfaces:**
- Consumes: `region_files(world) -> list[ReadOnlyPath]`（既有）
- Produces: `entities_files(world: ReadOnlyPath) -> list[ReadOnlyPath]` — 所有名為 `entities` 的目錄底下的 `*.mca`，依路徑排序

- [ ] **Step 1: 寫失敗的測試**

加到 `tests/unit/test_region.py`：

```python
def test_entities_files_finds_every_dimension(tmp_path) -> None:
    """`entities/` 和 `region/` 一樣，每個維度各有一份。"""
    from mcmt.nbtio.region import entities_files
    from mcmt.safety.paths import ensure_readable

    world = tmp_path / "world"
    for relative in ("entities", "DIM-1/entities", "DIM1/entities"):
        write_region_file(world / relative, RegionBuilder().build())
    write_region_file(world / "region", RegionBuilder().build())
    write_region_file(world / "poi", RegionBuilder().build())

    found = [str(p).replace("\\", "/") for p in entities_files(ensure_readable(world))]

    assert len(found) == 3
    assert all("/entities/" in p for p in found)
    assert not any("/poi/" in p or "/region/" in p for p in found)
```

加到 `tests/unit/test_fingerprint.py`：

```python
def test_changing_an_entity_changes_the_fingerprint(tmp_path) -> None:
    """[預告於 nbtio/region.py] 掃描範圍擴大到 entities 之後，

    「什麼算這個世界的內容」就得包含它。不含的話，使用者在遊戲裡動了盔甲座、
    指紋卻不變，`extract_fingerprint` 會說「世界沒變」而實際上變了。
    """
    import amulet_nbt

    from mcmt.fingerprint import world_fingerprint

    def build(name: str) -> Path:
        world = tmp_path / name
        write_region_file(
            world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
        )
        root = modern_chunk()
        root["Entities"] = amulet_nbt.ListTag(
            [amulet_nbt.CompoundTag({"CustomName": amulet_nbt.StringTag(name)})]
        )
        write_region_file(
            world / "entities", RegionBuilder().add_chunk_nbt(0, root).build()
        )
        return world

    assert world_fingerprint(build("a")) != world_fingerprint(build("b"))


def test_the_same_world_still_fingerprints_the_same(tmp_path) -> None:
    """穩定性沒有被破壞——同樣的內容算兩次要一樣。"""
    import amulet_nbt

    from mcmt.fingerprint import world_fingerprint

    def build(name: str) -> Path:
        world = tmp_path / name
        write_region_file(
            world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
        )
        root = modern_chunk()
        root["Entities"] = amulet_nbt.ListTag(
            [amulet_nbt.CompoundTag({"CustomName": amulet_nbt.StringTag("同樣的")})]
        )
        write_region_file(
            world / "entities", RegionBuilder().add_chunk_nbt(0, root).build()
        )
        return world

    assert world_fingerprint(build("x")) == world_fingerprint(build("y"))
```

`tests/unit/test_fingerprint.py` 的檔頭若還沒有，補上 import：

```python
from pathlib import Path

from conftest import RegionBuilder, modern_chunk, write_region_file
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_region.py tests/unit/test_fingerprint.py -q`
Expected: FAIL — `ImportError: cannot import name 'entities_files'`，以及指紋那條因為 entities 沒被算進去而相等

- [ ] **Step 3: 加 `entities_files`**

`src/mcmt/nbtio/region.py`，緊接在 `region_files` 後面：

```python
def entities_files(world: ReadOnlyPath) -> list[ReadOnlyPath]:
    """世界底下所有的實體 region 檔，依路徑排序。

    `entities/` 從 1.17 起與 `region/` 分開存放，格式完全一樣（同一套 header、
    同一套壓縮），所以讀寫都能沿用 `read_region` / `write_region`。差別只在裡面
    裝的是 `Entities[]` 而不是 `block_entities[]`。

    `poi/` 底下也是 `.mca`，但那是興趣點索引，沒有任何給人看的字。
    """
    return sorted(
        (
            path
            for directory in world.rglob("entities")
            if directory.is_dir()
            for path in directory.glob("*.mca")
        ),
        key=str,
    )
```

把 `region_files` 的 docstring 最後那段預告改成已完成：

```python
    `entities/` 與 `poi/` 底下也是 `.mca`，但那不是方塊 chunk。實體由
    `entities_files()` 負責（M13），`poi/` 沒有文字所以不看。
```

`__all__` 加上 `"entities_files"`。

- [ ] **Step 4: 指紋納入 entities**

`src/mcmt/fingerprint.py`：

import 改成：

```python
from mcmt.nbtio.region import entities_files, read_region, region_files
```

`world_fingerprint` 裡那個 `for path in region_files(readable):` 改成：

```python
    # **region 與 entities 都算。** [預告於 nbtio/region.py] 掃描範圍擴大到實體
    # 之後，「什麼算這個世界的內容」就得包含它們——不然使用者在遊戲裡動了盔甲座，
    # 指紋不變，extract_fingerprint 會說「世界沒變」而實際上變了。
    #
    # 兩份清單分開取再串起來（而不是 rglob 一次抓兩種），是為了讓順序穩定且
    # 與各自的 *_files() 定義一致——指紋對順序敏感。
    for path in [*region_files(readable), *entities_files(readable)]:
```

在模組 docstring 的「刻意不餵進去的三樣東西」那段之前，加一段：

```
**涵蓋 `region/` 與 `entities/`**（M13）。實體從 1.17 起分開存放，但它一樣是這個
世界的內容——具名生物、盔甲座、`text_display` 的浮空文字都在那裡。漏掉它的症狀
是「使用者玩過一次、動了實體，指紋卻說世界沒變」，而 `extract_fingerprint` 正是
靠指紋判斷譯文還適不適用。
```

- [ ] **Step 5: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_region.py tests/unit/test_fingerprint.py -q`
Expected: PASS

- [ ] **Step 6: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠。指紋值本身變了，但沒有測試寫死它的字面值（都是比較「相同/不同」）。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/nbtio/region.py src/mcmt/fingerprint.py tests/unit/test_region.py tests/unit/test_fingerprint.py
git commit -F- <<'MSG'
指紋納入 entities/：掃到實體之後，「什麼算這個世界的內容」就變了

`nbtio/region.py` 的 docstring 早就預告了這件事。指紋原本只涵蓋 region/ 的 chunk，
M13 掃 entities/ 之後，「使用者玩過一次、動了盔甲座」不會讓指紋改變，於是
extract_fingerprint 會說「世界沒變」而實際上變了。

新增 `entities_files()`（與 region_files 對稱，一樣走每個維度），指紋把兩份清單
串起來算。順序穩定：分別取再串，而不是 rglob 一次抓兩種。

**代價**：所有既有的 extract 產物立刻失效。那會走 `_check_binding` 的明確錯誤
訊息（「請重新產生」），不會安靜地對錯節點；per-node 的 expected_encoding 守門
仍是最後一道關。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 4: 掃描來源註冊表（純重構，行為不變）

`extract/build.py` 現在硬編碼「走 region 檔 → `read_region` → `scan_chunk`」。這一步把它改成跑過一份來源清單，**行為完全不變**——既有測試就是這次重構的安全網。

**Files:**
- Create: `src/mcmt/scan/node.py`
- Create: `src/mcmt/scan/registry.py`
- Modify: `src/mcmt/scan/sources/region.py`
- Modify: `src/mcmt/extract/build.py`
- Test: `tests/unit/test_scan_registry.py`（新）

**Interfaces:**
- Produces:
  - `scan/node.py`：`TextNode`（從 `region.py` 搬過來，欄位不變）、
    `ScannedNode(node: TextNode, container: dict[str, Any])`
  - `scan/registry.py`：`SOURCES: list[Callable[[ReadOnlyPath, Counter], Iterator[ScannedNode]]]`
  - `scan/sources/region.py`：`scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_scan_registry.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""掃描來源註冊表（M13.2）。

M13 之前 `extract/build.py` 自己硬編碼了「走 region 檔」。那在只有一個來源時看不出
問題，加到七個之後它就變成「每加一個來源都要改的那個函式」。

**來源之間是同型的**——每一個都只做「找到文字節點、記下它在哪」，讀出來之後交給
同一套嗅探／攤平／規則引擎。所以這裡抽象沒有藏起任何東西。（寫入器不同型，那邊
維持顯式分派。）
"""

from collections import Counter

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.safety.paths import ensure_readable
from mcmt.scan import registry
from mcmt.scan.node import ScannedNode
from mcmt.scan.sources import region


def sign(*lines, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag(
        [amulet_nbt.StringTag(line) for line in lines]
    )
    tag["front_text"] = face
    return tag


def world_with(tmp_path, *entities, name="world"):
    world = tmp_path / name
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag(list(entities))
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())
    return ensure_readable(world)


def test_every_source_is_callable_with_the_same_signature():
    """註冊表的價值就在於「加一個來源不必改別的地方」。

    簽名一旦漂移，那個價值就沒了——而漂移的症狀是某個來源安靜地不被呼叫。
    """
    assert registry.SOURCES
    for source in registry.SOURCES:
        assert callable(source)


def test_the_region_source_yields_scanned_nodes(tmp_path) -> None:
    world = world_with(tmp_path, sign("歡迎光臨", "", "", ""))
    stats = Counter()

    found = list(region.scan(world, stats))

    assert found
    assert all(isinstance(item, ScannedNode) for item in found)


def test_a_scanned_node_carries_its_container(tmp_path) -> None:
    """container 是寫回去的地址。來源自己產生它——只有來源知道自己讀的是什麼檔案。"""
    world = world_with(tmp_path, sign("歡迎光臨", "", "", ""))

    (first, *_) = list(region.scan(world, Counter()))

    assert first.container["kind"] == "region_chunk"
    assert first.container["path"] == "region/r.0.0.mca"
    assert first.container["data_version"] == 4671
    assert first.container["chunk"] == {"cx": 0, "cz": 0}


def test_an_unreadable_region_is_counted_not_fatal(tmp_path) -> None:
    """一張 region 讀不下去時要記錄並跳過，不讓整次 extract 消失。"""
    world = tmp_path / "broken"
    (world / "region").mkdir(parents=True)
    (world / "region" / "r.0.0.mca").write_bytes(b"not a region file")
    stats = Counter()

    found = list(region.scan(ensure_readable(world), stats))

    assert found == []
    assert stats["skipped_region"] == 1
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcmt.scan.node'`

- [ ] **Step 3: 建 `scan/node.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""掃描層的兩個資料形狀。

`TextNode` 原本住在 `sources/region.py`，M13 把它搬出來——七個來源都要用它，
留在其中一個來源裡會讓其他六個 import 一個「別人的」模組。

`ScannedNode` 是 `TextNode` 加上**它在哪個容器裡**。容器由來源自己產生，因為只有
來源知道自己讀的是什麼檔案、那個檔案的 DataVersion 是多少、它算 region chunk 還是
level.dat。
"""

from dataclasses import dataclass
from typing import Any

from mcmt.model.node import NodePath

__all__ = ["ScannedNode", "TextNode"]


@dataclass(frozen=True)
class TextNode:
    """一個等著被判形狀的文字節點，以及它在世界裡的位置。"""

    path: NodePath
    tag: Any
    category: str
    anchor: dict[str, Any] | None = None
    list_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class ScannedNode:
    """一個文字節點 + 它所在的容器（寫回去的地址）。"""

    node: TextNode
    container: dict[str, Any]
```

- [ ] **Step 4: 改 `sources/region.py`**

檔頭改成從 `scan/node.py` 取 `TextNode`（**保留 re-export**，既有測試 import 它）：

```python
from mcmt.scan.node import ScannedNode, TextNode

__all__ = ["TextNode", "scan", "scan_chunk"]
```

刪掉檔案裡原本的 `@dataclass class TextNode: ...` 定義。

在檔案末尾加上來源進入點（把 `extract/build.py` 的 `_chunks_of` 與 `_container` 搬過來）：

```python
def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    """走過世界的每一張方塊 region，yield 裡面的文字節點。

    一張 region 讀不下去時記錄並跳過，不讓整次 extract 消失——壞掉的世界更需要
    能先掃出能掃的部分。
    """
    for path in region_files(world):
        try:
            chunks = list(read_region(path))
        except FormatError:
            stats["skipped_region"] += 1
            continue

        for raw in chunks:
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
            for node in scan_chunk(root):
                yield ScannedNode(node=node, container=container)


def _container(path, raw, data_version: int, world: ReadOnlyPath) -> dict:
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
```

檔頭補 import：

```python
from collections import Counter

from mcmt.errors import FormatError
from mcmt.nbtio.region import read_region, region_files
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root
from mcmt.safety.paths import ReadOnlyPath
```

`__all__` 改成 `["TextNode", "dimension_of", "scan", "scan_chunk"]`。

- [ ] **Step 5: 建 `scan/registry.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""掃描來源的清單（M13.2）。

**來源之間是同型的**——每一個都只做「找到文字節點、記下它在哪」，讀出來之後交給
同一套嗅探／攤平／規則引擎。所以這個抽象沒有藏起任何東西。

寫入器**不**同型（外科式 vs 整份重編 vs 檔案重寫，保證等級不一樣），那邊維持
顯式分派——那個不對稱必須看得見。理由見
`docs/superpowers/specs/2026-08-22-m13-scan-breadth-design.md` 第 2 節。

形式沿用 `rules/sets/denylist.py` 的 `RULES`：就是一份函式清單，不是 Protocol 或
基底類別。每個來源的簽名是

    scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]

`stats` 由來源直接累加（`skipped_region`、`skipped_chunk`…），因為「這次掃描跳過了
什麼」是報告的一部分，不能只存在於某個來源的內部。
"""

from mcmt.scan.sources import region

__all__ = ["SOURCES"]

SOURCES = [
    region.scan,
]
```

- [ ] **Step 6: 改 `extract/build.py` 走註冊表**

`build_units` 裡那兩層迴圈：

```python
    for path in region_files(readable):
        for raw_chunk, root, data_version in _chunks_of(path, result):
            for node in scan_chunk(root):
```

換成：

```python
    for source in SOURCES:
        for scanned in source(readable, result.stats):
            node = scanned.node
```

底下 `result.text_nodes += 1` 之後那段沿用，只有兩處要改：

- `_consider(node, data_version, result)` → `_consider(node, scanned.container["data_version"], result)`
- `container=_container(path, raw_chunk, data_version, readable)` → `container=scanned.container`

刪掉 `build.py` 裡的 `_chunks_of`、`_container`、`_dimension_of`（已經搬去 `region.py`），以及不再需要的 import。

`result.chunks` 現在由來源寫進 `stats["chunks"]`，所以 `ExtractResult.chunks` 改成從 stats 讀：在 `build_units` 回傳前加一行

```python
    result.chunks = result.stats["chunks"]
```

檔頭 import 改成：

```python
from mcmt.scan.registry import SOURCES
```

（移除 `from mcmt.scan.sources.region import scan_chunk` 與 `from mcmt.nbtio.region import read_region, region_files`。）

- [ ] **Step 7: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_registry.py -q`
Expected: PASS

- [ ] **Step 8: 跑全部測試（這是重構的安全網）**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠。**這一步是這個任務的重點**——行為完全不變，既有的 588 條測試就是證明。若有紅的，是重構搬錯了東西，不要改測試。

- [ ] **Step 9: 真實地圖確認數字沒變**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/100 Ways To Die" --lang zh_tw --out "sandbox/_refactor_check"
```
Expected: `翻譯單位：937 個`、`掃過 chunk 6,465 個`（與重構前一致）。確認後 `rm -rf "sandbox/_refactor_check"`。

- [ ] **Step 10: Commit**

```bash
git add src/mcmt/scan/node.py src/mcmt/scan/registry.py src/mcmt/scan/sources/region.py src/mcmt/extract/build.py tests/unit/test_scan_registry.py
git commit -F- <<'MSG'
scan：來源註冊表（純重構，行為不變）

`extract/build.py` 原本硬編碼「走 region 檔 → read_region → scan_chunk」。那在只有
一個來源時看不出問題，M13 要加到七個之後它就變成「每加一個來源都要改的那個函式」。

改成一份函式清單，形式沿用 rules/sets/denylist.py 的 RULES——不是 Protocol 也不是
基底類別，這個專案已經有這個模式了。

**來源之間是同型的**（每一個都只做「找到節點、記下位置」，讀出來交給同一套嗅探／
攤平／規則引擎），所以這個抽象沒有藏起任何東西。寫入器不同型（外科式 vs 整份重編
vs 檔案重寫，保證等級不一樣），那邊維持顯式分派——那個不對稱必須看得見。

`TextNode` 從 sources/region.py 搬到 scan/node.py：七個來源都要用它，留在其中一個
來源裡會讓其他六個 import 一個「別人的」模組。新增 `ScannedNode`（節點 + 容器），
容器由來源自己產生，因為只有來源知道自己讀的是什麼檔案。

行為完全不變——既有的 588 條測試就是這次重構的安全網，另外在真實地圖上確認
100 Ways To Die 仍然抽出 937 個單位、掃過 6,465 個 chunk。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 5: `item.py` — 新格式（`components`）

**嚴格白名單**：只抽下表列出的欄位，其餘一律忽略、也不遞迴進去。不是「走遍物品的樹再靠 denylist 擋」——物品底下的機制標籤多到列不完，而漏擋一個的後果是翻掉識別碼。

**Files:**
- Create: `src/mcmt/scan/sources/item.py`
- Test: `tests/unit/test_scan_item.py`（新）

**Interfaces:**
- Consumes: `TextNode`, `NodePath`, `key_step`, `index_step`
- Produces: `scan_item(item: amulet_nbt.CompoundTag, path: NodePath, *, anchor: dict | None) -> Iterator[TextNode]`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_scan_item.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""物品掃描（M13.3）——**跨來源的共用元件**。

物品同時出現在方塊實體的 `Items[]`、實體的 `ArmorItems[]`/`equipment`/`item`、
以及 `level.dat` 的 `Player.Inventory[]`。三邊各寫一份遞迴是最該避免的事：
[實測] 三層巢狀真的存在（Arena of Darkness 的
`Items[] → BlockEntityTag/Items[] → tag/display/Name`，7 個），而漏掉一層的症狀是
「有些物品名沒被抽出來」，沒有例外也沒有紅字。

**嚴格白名單。** 只抽表列欄位，其餘忽略也不遞迴進去——物品底下的機制標籤多到列
不完（Enchantments、AttributeModifiers、Trim、Potion、CanPlaceOn、BlockStateTag、
SkullOwner、custom_data…）。白名單的代價是「新版本的新文字組件不會自動抽到」，
那個方向是對的：**漏抽看得見**（節點數對不上清點），**誤翻看不見**（地圖壞掉時
已經來不及）。
"""

import amulet_nbt

from mcmt.model.node import NodePath, key_step
from mcmt.scan.sources.item import scan_item


def paths_and_categories(item, *, anchor=None):
    found = list(scan_item(item, NodePath([key_step("Items")]), anchor=anchor))
    return {
        "/".join(
            step.name if step.t == "key" else f"[{step.i}]" for step in node.path
        ): node.category
        for node in found
    }


def component_item(**components):
    item = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:stone")})
    item["components"] = amulet_nbt.CompoundTag(components)
    return item


def test_a_custom_name_component_is_found():
    item = component_item(
        **{"minecraft:custom_name": amulet_nbt.StringTag("補給箱")}
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:custom_name": "custom_name"
    }


def test_an_item_name_component_is_found():
    item = component_item(**{"minecraft:item_name": amulet_nbt.StringTag("聖劍")})

    assert paths_and_categories(item) == {
        "Items/components/minecraft:item_name": "item_name"
    }


def test_every_lore_line_is_found_separately():
    """lore 是陣列，每一行是獨立的 component——也是獨立的翻譯單位。"""
    item = component_item(
        **{
            "minecraft:lore": amulet_nbt.ListTag(
                [amulet_nbt.StringTag("第一行"), amulet_nbt.StringTag("第二行")]
            )
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:lore/[0]": "lore",
        "Items/components/minecraft:lore/[1]": "lore",
    }


def test_a_written_book_yields_title_author_and_pages():
    """[遊戲實測] `title.raw` 與 `author` 只吃字串（走 in_place），

    `pages[].raw` 底下卻是完整的 component（走 translate key）。同一本書裡的
    不對稱，category 分開才表達得出來。
    """
    item = component_item(
        **{
            "minecraft:written_book_content": amulet_nbt.CompoundTag(
                {
                    "title": amulet_nbt.CompoundTag(
                        {"raw": amulet_nbt.StringTag("我的書")}
                    ),
                    "author": amulet_nbt.StringTag("作者"),
                    "pages": amulet_nbt.ListTag(
                        [
                            amulet_nbt.CompoundTag(
                                {"raw": amulet_nbt.StringTag("第一頁")}
                            )
                        ]
                    ),
                }
            )
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:written_book_content/title/raw": "book_title",
        "Items/components/minecraft:written_book_content/author": "book_author",
        "Items/components/minecraft:written_book_content/pages/[0]/raw": "book_page",
    }


def test_a_writable_book_page_is_a_draft_page():
    """草稿書頁是無包裝的 TAG_String，只能 in_place。"""
    item = component_item(
        **{
            "minecraft:writable_book_content": amulet_nbt.CompoundTag(
                {
                    "pages": amulet_nbt.ListTag(
                        [
                            amulet_nbt.CompoundTag(
                                {"raw": amulet_nbt.StringTag("草稿")}
                            )
                        ]
                    )
                }
            )
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:writable_book_content/pages/[0]/raw": "draft_book_page"
    }


def test_a_container_recurses_into_its_items():
    """潛影盒裡的物品。**[實測] 三層巢狀真的存在。**"""
    inner = component_item(
        **{"minecraft:custom_name": amulet_nbt.StringTag("裡面的東西")}
    )
    outer = component_item(
        **{
            "minecraft:container": amulet_nbt.ListTag(
                [amulet_nbt.CompoundTag({"slot": amulet_nbt.IntTag(0), "item": inner})]
            )
        }
    )

    assert paths_and_categories(outer) == {
        "Items/components/minecraft:container/[0]/item/components/minecraft:custom_name": "custom_name"
    }


def test_a_bundle_recurses_into_its_contents():
    """收納袋——邊緣容器，但它就是個物品清單。"""
    inner = component_item(**{"minecraft:custom_name": amulet_nbt.StringTag("袋內")})
    outer = component_item(
        **{"minecraft:bundle_contents": amulet_nbt.ListTag([inner])}
    )

    assert paths_and_categories(outer) == {
        "Items/components/minecraft:bundle_contents/[0]/components/minecraft:custom_name": "custom_name"
    }


def test_charged_projectiles_recurse():
    """弩上的箭也是物品。"""
    inner = component_item(**{"minecraft:custom_name": amulet_nbt.StringTag("魔法箭")})
    outer = component_item(
        **{"minecraft:charged_projectiles": amulet_nbt.ListTag([inner])}
    )

    assert paths_and_categories(outer) == {
        "Items/components/minecraft:charged_projectiles/[0]/components/minecraft:custom_name": "custom_name"
    }


def test_mechanic_components_are_ignored_entirely():
    """**白名單的核心測試。**

    不在清單裡的組件連碰都不碰——不是「抽出來再靠 denylist 擋」。
    """
    item = component_item(
        **{
            "minecraft:custom_name": amulet_nbt.StringTag("要抽的"),
            "minecraft:enchantments": amulet_nbt.CompoundTag(
                {"minecraft:sharpness": amulet_nbt.IntTag(5)}
            ),
            "minecraft:lock": amulet_nbt.StringTag("Locked"),
            "minecraft:custom_data": amulet_nbt.CompoundTag(
                {"quest": amulet_nbt.StringTag("q_042")}
            ),
            "minecraft:profile": amulet_nbt.CompoundTag(
                {"name": amulet_nbt.StringTag("TheWorfer27")}
            ),
        }
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:custom_name": "custom_name"
    }


def test_an_item_with_nothing_translatable_yields_nothing():
    assert paths_and_categories(component_item()) == {}


def test_the_anchor_is_carried_down_into_nested_items():
    """巢狀物品的座標就是最外層容器的座標——譯者要走得到現場。"""
    inner = component_item(**{"minecraft:custom_name": amulet_nbt.StringTag("裡面")})
    outer = component_item(
        **{
            "minecraft:container": amulet_nbt.ListTag(
                [amulet_nbt.CompoundTag({"item": inner})]
            )
        }
    )
    anchor = {"kind": "block", "id": "minecraft:chest", "x": 1, "y": 2, "z": 3, "uuid": None}

    (node,) = list(scan_item(outer, NodePath([key_step("Items")]), anchor=anchor))

    assert node.anchor == anchor
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_item.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcmt.scan.sources.item'`

- [ ] **Step 3: 實作新格式**

新增 `src/mcmt/scan/sources/item.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""物品裡的文字（M13.3）——**跨來源的共用元件**。

物品同時出現在三個地方：方塊實體的 `Items[]`、實體的
`ArmorItems[]`/`equipment`/`item`/`weapon`、`level.dat` 的 `Player.Inventory[]`。
三邊各寫一份遞迴是最該避免的事——[實測] 三層巢狀真的存在（`Arena of Darkness` 的
`Items[] → BlockEntityTag/Items[] → tag/display/Name`），而漏掉一層的症狀是「有些
物品名沒被抽出來」，沒有例外也沒有紅字。

## 兩套格式，由物品自己說了算

1.20.5（DV 3837）把物品的 NBT 從 `tag` 換成 `components`。**分水嶺與 chunk 結構的
4325 不是同一條線**，而且我們不看 DataVersion——看物品身上有 `components` 還是
`tag`（CLAUDE.md 二節：形狀一律逐節點嗅探）。

[實測] 真實語料各佔一套：`Arena of Darkness`（1.20.4）全是 `tag`，
`100 Ways To Die`（1.21.5）全是 `components`。

## 嚴格白名單

只抽下面列的欄位，**其餘一律忽略，也不遞迴進去**。不是「走遍物品的樹再靠 denylist
擋」——物品底下的機制標籤多到列不完。白名單的代價是「新版本加了新的文字組件我們不
會自動抽到」，那個代價是對的方向：**漏抽看得見**（節點數對不上清點），**誤翻看不見**
（地圖壞掉時已經來不及）。
"""

from typing import Any, Iterator

import amulet_nbt

from mcmt.model.node import NodePath, index_step, key_step
from mcmt.scan.node import TextNode

__all__ = ["scan_item"]

# 組件名 → category。**這份表就是白名單。**
_NAME_COMPONENTS = {
    "minecraft:custom_name": "custom_name",
    "minecraft:item_name": "item_name",
}

_LORE_COMPONENT = "minecraft:lore"
_WRITTEN_BOOK = "minecraft:written_book_content"
_WRITABLE_BOOK = "minecraft:writable_book_content"

# 遞迴進去的容器組件 → 元素裡哪個鍵是物品（None 代表元素本身就是物品）。
_CONTAINER_COMPONENTS = {
    "minecraft:container": "item",
    "minecraft:bundle_contents": None,
    "minecraft:charged_projectiles": None,
}


def scan_item(
    item: amulet_nbt.CompoundTag, path: NodePath, *, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    """一個物品裡所有可翻譯的文字節點。自己遞迴進容器。"""
    if not isinstance(item, amulet_nbt.CompoundTag):
        return
    components = item.get("components")
    if isinstance(components, amulet_nbt.CompoundTag):
        yield from _scan_components(components, path.child(key_step("components")), anchor)


def _scan_components(
    components: amulet_nbt.CompoundTag, path: NodePath, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    for name, category in _NAME_COMPONENTS.items():
        value = components.get(name)
        if value is not None:
            yield TextNode(
                path=path.child(key_step(name)),
                tag=value,
                category=category,
                anchor=anchor,
            )

    lore = components.get(_LORE_COMPONENT)
    if isinstance(lore, amulet_nbt.ListTag):
        lore_path = path.child(key_step(_LORE_COMPONENT))
        for index, line in enumerate(lore):
            yield TextNode(
                path=lore_path.child(index_step(index)),
                tag=line,
                category="lore",
                anchor=anchor,
            )

    book = components.get(_WRITTEN_BOOK)
    if isinstance(book, amulet_nbt.CompoundTag):
        yield from _scan_written_book(book, path.child(key_step(_WRITTEN_BOOK)), anchor)

    draft = components.get(_WRITABLE_BOOK)
    if isinstance(draft, amulet_nbt.CompoundTag):
        yield from _scan_pages(
            draft, path.child(key_step(_WRITABLE_BOOK)), anchor, "draft_book_page"
        )

    for name, item_key in _CONTAINER_COMPONENTS.items():
        contents = components.get(name)
        if not isinstance(contents, amulet_nbt.ListTag):
            continue
        contents_path = path.child(key_step(name))
        for index, entry in enumerate(contents):
            entry_path = contents_path.child(index_step(index))
            if item_key is None:
                yield from scan_item(entry, entry_path, anchor=anchor)
            elif isinstance(entry, amulet_nbt.CompoundTag):
                inner = entry.get(item_key)
                if inner is not None:
                    yield from scan_item(
                        inner, entry_path.child(key_step(item_key)), anchor=anchor
                    )


def _scan_written_book(
    book: amulet_nbt.CompoundTag, path: NodePath, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    """成書。**`title.raw` 與 `author` 只吃字串，`pages[].raw` 吃完整 component。**

    [遊戲實測] 同一本書的 `pages[].raw` 底下存 `{translate: …}` 會正常翻譯，
    `title.raw` 底下卻直接顯示原始 key。所以 category 必須分開——那個不對稱是
    `strategy` 的依據。
    """
    title = book.get("title")
    if isinstance(title, amulet_nbt.CompoundTag) and "raw" in title:
        yield TextNode(
            path=path.child(key_step("title")).child(key_step("raw")),
            tag=title["raw"],
            category="book_title",
            anchor=anchor,
        )

    author = book.get("author")
    if author is not None:
        yield TextNode(
            path=path.child(key_step("author")),
            tag=author,
            category="book_author",
            anchor=anchor,
        )

    yield from _scan_pages(book, path, anchor, "book_page")


def _scan_pages(
    book: amulet_nbt.CompoundTag,
    path: NodePath,
    anchor: dict[str, Any] | None,
    category: str,
) -> Iterator[TextNode]:
    pages = book.get("pages")
    if not isinstance(pages, amulet_nbt.ListTag):
        return
    pages_path = path.child(key_step("pages"))
    for index, page in enumerate(pages):
        page_path = pages_path.child(index_step(index))
        if isinstance(page, amulet_nbt.CompoundTag) and "raw" in page:
            yield TextNode(
                path=page_path.child(key_step("raw")),
                tag=page["raw"],
                category=category,
                anchor=anchor,
            )
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_item.py -q`
Expected: PASS（11 條）

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add src/mcmt/scan/sources/item.py tests/unit/test_scan_item.py
git commit -F- <<'MSG'
scan/sources/item.py：物品裡的文字（新格式），跨來源共用

物品同時出現在方塊實體的 Items[]、實體的裝備欄、玩家背包三個地方。三邊各寫一份
遞迴是最該避免的事——[實測] 三層巢狀真的存在（Arena of Darkness 的
Items[] → BlockEntityTag/Items[] → tag/display/Name），而漏掉一層的症狀是「有些
物品名沒被抽出來」，沒有例外也沒有紅字。

這一個 commit 只做 1.20.5+ 的 components 格式，舊的 tag 格式下一個。

**嚴格白名單**：只抽 custom_name / item_name / lore / 成書 / 草稿書 / 三種容器
（container、bundle_contents、charged_projectiles），其餘一律忽略也不遞迴進去。
不是「走遍物品的樹再靠 denylist 擋」——物品底下的機制標籤多到列不完，而漏擋一個
的後果是翻掉識別碼。有一條測試專門守著這件事（enchantments / lock / custom_data /
profile 放在同一個物品上，只有 custom_name 被抽出來）。

成書的 title.raw / author 與 pages[].raw 分成三個 category：[遊戲實測] 同一本書的
pages[].raw 底下存 {translate:…} 會正常翻譯，title.raw 底下卻直接顯示原始 key。
那個不對稱是 strategy 的依據，category 分開才表達得出來。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 6: `item.py` — 舊格式（`tag`）

[實測] `Arena of Darkness`（1.20.4）全是這一套：`Items[].tag.display.Name` 3,696 個。**由物品自己有 `components` 還是 `tag` 決定，不看 DataVersion。**

**Files:**
- Modify: `src/mcmt/scan/sources/item.py`
- Test: `tests/unit/test_scan_item.py`

**Interfaces:**
- Consumes: `scan_item`（Task 5）
- Produces: `scan_item` 現在也認得 `tag` 格式；公開簽名不變

- [ ] **Step 1: 寫失敗的測試**

加到 `tests/unit/test_scan_item.py` 末尾：

```python
# --- 舊格式（1.20.5 之前）---------------------------------------------------


def tag_item(item_id="minecraft:stone", **tag):
    item = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag(item_id)})
    item["tag"] = amulet_nbt.CompoundTag(tag)
    return item


def test_an_old_display_name_is_found():
    """[實測] Arena of Darkness 有 3,696 個，值是 JSON 字串。"""
    item = tag_item(
        display=amulet_nbt.CompoundTag(
            {"Name": amulet_nbt.StringTag('{"text":"Xyphia"}')}
        )
    )

    assert paths_and_categories(item) == {
        "Items/tag/display/Name": "custom_name"
    }


def test_old_lore_lines_are_found():
    item = tag_item(
        display=amulet_nbt.CompoundTag(
            {
                "Lore": amulet_nbt.ListTag(
                    [
                        amulet_nbt.StringTag('{"text":"第一行"}'),
                        amulet_nbt.StringTag('{"text":"第二行"}'),
                    ]
                )
            }
        )
    )

    assert paths_and_categories(item) == {
        "Items/tag/display/Lore/[0]": "lore",
        "Items/tag/display/Lore/[1]": "lore",
    }


def test_an_old_written_book_yields_title_author_and_pages():
    """舊格式的成書：title/author 是純字串，pages[] 是 JSON 字串。"""
    item = tag_item(
        "minecraft:written_book",
        title=amulet_nbt.StringTag("Base Notes"),
        author=amulet_nbt.StringTag("TheWorfer27"),
        pages=amulet_nbt.ListTag([amulet_nbt.StringTag('{"text":"第一頁"}')]),
    )

    assert paths_and_categories(item) == {
        "Items/tag/title": "book_title",
        "Items/tag/author": "book_author",
        "Items/tag/pages/[0]": "book_page",
    }


def test_an_old_writable_book_is_a_draft_not_a_written_book():
    """**成書與草稿書共用 `tag.pages[]`。**

    差別在物品 id，不在路徑。只看路徑會把草稿書當成書處理，而草稿書頁是無包裝的
    TAG_String，只能 in_place——搞錯的話會往它寫一個 translate key，玩家看到的是
    key 本身。
    """
    item = tag_item(
        "minecraft:writable_book",
        pages=amulet_nbt.ListTag([amulet_nbt.StringTag("草稿內容")]),
    )

    assert paths_and_categories(item) == {"Items/tag/pages/[0]": "draft_book_page"}


def test_an_old_shulker_box_recurses_into_its_items():
    """[實測] Arena of Darkness 的三層巢狀就是這條路徑。"""
    inner = tag_item(
        display=amulet_nbt.CompoundTag(
            {"Name": amulet_nbt.StringTag('{"text":"Ultra Health Potion"}')}
        )
    )
    outer = tag_item(
        BlockEntityTag=amulet_nbt.CompoundTag(
            {"Items": amulet_nbt.ListTag([inner])}
        )
    )

    assert paths_and_categories(outer) == {
        "Items/tag/BlockEntityTag/Items/[0]/tag/display/Name": "custom_name"
    }


def test_an_old_block_entity_tag_custom_name_is_found():
    """[實測] Arena of Darkness 有 1 個——物品形式的容器自己也有名字。"""
    outer = tag_item(
        BlockEntityTag=amulet_nbt.CompoundTag(
            {"CustomName": amulet_nbt.StringTag('{"text":"箱子"}')}
        )
    )

    assert paths_and_categories(outer) == {
        "Items/tag/BlockEntityTag/CustomName": "block_entity_name"
    }


def test_an_old_bundle_recurses():
    """舊格式的收納袋用 `tag.Items`。"""
    inner = tag_item(
        display=amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag('{"text":"袋內"}')})
    )
    outer = tag_item(Items=amulet_nbt.ListTag([inner]))

    assert paths_and_categories(outer) == {
        "Items/tag/Items/[0]/tag/display/Name": "custom_name"
    }


def test_old_mechanic_tags_are_ignored_entirely():
    """白名單在舊格式一樣嚴格。"""
    item = tag_item(
        display=amulet_nbt.CompoundTag(
            {"Name": amulet_nbt.StringTag('{"text":"要抽的"}')}
        ),
        SkullOwner=amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag("TheWorfer27")}),
        Potion=amulet_nbt.StringTag("minecraft:water"),
        BlockStateTag=amulet_nbt.CompoundTag({"delay": amulet_nbt.StringTag("4")}),
        CanDestroy=amulet_nbt.ListTag([amulet_nbt.StringTag("minecraft:red_bed")]),
    )

    assert paths_and_categories(item) == {"Items/tag/display/Name": "custom_name"}


def test_an_item_with_both_shapes_prefers_components():
    """理論上不該同時存在，但真的碰到時要有個確定的答案。

    `components` 是新的，它才是遊戲會讀的那一份。
    """
    item = component_item(
        **{"minecraft:custom_name": amulet_nbt.StringTag("新的")}
    )
    item["tag"] = amulet_nbt.CompoundTag(
        {"display": amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag("舊的")})}
    )

    assert paths_and_categories(item) == {
        "Items/components/minecraft:custom_name": "custom_name"
    }
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_item.py -q`
Expected: FAIL — 9 條新測試全紅（舊格式還沒實作，`paths_and_categories` 回傳 `{}`）

- [ ] **Step 3: 實作舊格式**

改 `src/mcmt/scan/sources/item.py`。

`scan_item` 改成：

```python
def scan_item(
    item: amulet_nbt.CompoundTag, path: NodePath, *, anchor: dict[str, Any] | None
) -> Iterator[TextNode]:
    """一個物品裡所有可翻譯的文字節點。自己遞迴進容器。

    **由物品自己有 `components` 還是 `tag` 決定走哪一套，不看 DataVersion。**
    兩者同時存在時以 `components` 為準——它是新的，也是遊戲會讀的那一份。
    """
    if not isinstance(item, amulet_nbt.CompoundTag):
        return

    components = item.get("components")
    if isinstance(components, amulet_nbt.CompoundTag):
        yield from _scan_components(
            components, path.child(key_step("components")), anchor
        )
        return

    tag = item.get("tag")
    if isinstance(tag, amulet_nbt.CompoundTag):
        yield from _scan_tag(tag, path.child(key_step("tag")), anchor, _item_id(item))


def _item_id(item: amulet_nbt.CompoundTag) -> str:
    return str(item.get("id", ""))
```

在檔案末尾加舊格式的實作：

```python
# --- 舊格式（1.20.5 之前的 `tag`）-----------------------------------------
#
# [實測] `Arena of Darkness`（1.20.4）全是這一套，`Items[].tag.display.Name` 3,696 個。
# 值是 JSON 字串（`{"text":"Xyphia"}`），嗅探層會判成 json_string_object。

_OLD_CONTAINER_KEYS = ("Items",)  # 收納袋。潛影盒走 BlockEntityTag.Items


def _scan_tag(
    tag: amulet_nbt.CompoundTag,
    path: NodePath,
    anchor: dict[str, Any] | None,
    item_id: str,
) -> Iterator[TextNode]:
    display = tag.get("display")
    if isinstance(display, amulet_nbt.CompoundTag):
        display_path = path.child(key_step("display"))
        name = display.get("Name")
        if name is not None:
            yield TextNode(
                path=display_path.child(key_step("Name")),
                tag=name,
                category="custom_name",
                anchor=anchor,
            )
        lore = display.get("Lore")
        if isinstance(lore, amulet_nbt.ListTag):
            lore_path = display_path.child(key_step("Lore"))
            for index, line in enumerate(lore):
                yield TextNode(
                    path=lore_path.child(index_step(index)),
                    tag=line,
                    category="lore",
                    anchor=anchor,
                )

    yield from _scan_old_book(tag, path, anchor, item_id)

    # 物品形式的容器（潛影盒、箱子）自己的名字與內容物。
    block_entity = tag.get("BlockEntityTag")
    if isinstance(block_entity, amulet_nbt.CompoundTag):
        be_path = path.child(key_step("BlockEntityTag"))
        custom_name = block_entity.get("CustomName")
        if custom_name is not None:
            yield TextNode(
                path=be_path.child(key_step("CustomName")),
                tag=custom_name,
                category="block_entity_name",
                anchor=anchor,
            )
        yield from _scan_old_item_list(block_entity, be_path, anchor, "Items")

    for key in _OLD_CONTAINER_KEYS:
        yield from _scan_old_item_list(tag, path, anchor, key)


def _scan_old_item_list(
    parent: amulet_nbt.CompoundTag,
    path: NodePath,
    anchor: dict[str, Any] | None,
    key: str,
) -> Iterator[TextNode]:
    items = parent.get(key)
    if not isinstance(items, amulet_nbt.ListTag):
        return
    items_path = path.child(key_step(key))
    for index, entry in enumerate(items):
        yield from scan_item(entry, items_path.child(index_step(index)), anchor=anchor)


def _scan_old_book(
    tag: amulet_nbt.CompoundTag,
    path: NodePath,
    anchor: dict[str, Any] | None,
    item_id: str,
) -> Iterator[TextNode]:
    """舊格式的書。

    **成書與草稿書共用 `tag.pages[]`**，差別在物品 id：`written_book` 的頁是 JSON
    字串，`writable_book` 的頁是無包裝的純字串（只能 in_place）。只看路徑會把草稿書
    當成書處理，往它寫一個 translate key，而玩家看到的會是 key 本身。
    """
    is_draft = item_id.endswith("writable_book")

    if not is_draft:
        title = tag.get("title")
        if title is not None:
            yield TextNode(
                path=path.child(key_step("title")),
                tag=title,
                category="book_title",
                anchor=anchor,
            )
        author = tag.get("author")
        if author is not None:
            yield TextNode(
                path=path.child(key_step("author")),
                tag=author,
                category="book_author",
                anchor=anchor,
            )

    pages = tag.get("pages")
    if not isinstance(pages, amulet_nbt.ListTag):
        return
    pages_path = path.child(key_step("pages"))
    category = "draft_book_page" if is_draft else "book_page"
    for index, page in enumerate(pages):
        yield TextNode(
            path=pages_path.child(index_step(index)),
            tag=page,
            category=category,
            anchor=anchor,
        )
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_item.py -q`
Expected: PASS（20 條）

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add src/mcmt/scan/sources/item.py tests/unit/test_scan_item.py
git commit -F- <<'MSG'
scan/sources/item.py：舊格式（1.20.5 之前的 tag）

[實測] Arena of Darkness（1.20.4）全是這一套，Items[].tag.display.Name 3,696 個，
值是 JSON 字串。真實語料新舊各佔一套，所以兩套都要支援不是防禦性寫法。

**由物品自己有 components 還是 tag 決定，不看 DataVersion**（CLAUDE.md 二節）。
分水嶺是 DV 3837（1.20.5），和 chunk 結構的 4325 不是同一條線——用世代推導這件事
本來就是錯的。兩者同時存在時以 components 為準，它是遊戲會讀的那一份。

**一個會踩到的坑**：成書與草稿書**共用 tag.pages[]**，差別在物品 id
（written_book vs writable_book）與值的形狀（JSON 字串 vs 純字串）。只看路徑會把
草稿書當成書處理，往它寫一個 translate key，而 [遊戲實測] 草稿書頁是無包裝的
TAG_String——玩家看到的會是 key 本身。有一條測試專門守著。

放同一個模組而不是拆成 legacy/native 兩份：那個不對稱只是「讀進來的路徑不同」，
讀完之後都是同一種 component，交給同一套嗅探與攤平；寫回去靠 node_path 走回原位，
寫入層不需要知道它來自哪一套。和 write/legacy.py vs write/native.py 的不對稱
（寫出去的形狀不同）不是同一類。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 7: 把物品接進 region 來源

到目前為止 `item.py` 還沒有任何呼叫端。這一步讓方塊實體的 `Items[]` 與講台的 `Book` 走進去。

**Files:**
- Modify: `src/mcmt/scan/sources/region.py`
- Test: `tests/unit/test_scan_region.py`

**Interfaces:**
- Consumes: `scan_item(item, path, *, anchor)`（Task 5/6）
- Produces: `scan_chunk` 現在也 yield 物品裡的節點

- [ ] **Step 1: 寫失敗的測試**

加到 `tests/unit/test_scan_region.py` 末尾：

```python
# --- 容器裡的物品（M13.3）--------------------------------------------------


def chest_with_items(*items, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:chest")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    tag["Items"] = amulet_nbt.ListTag(list(items))
    return tag


def named_item(name):
    item = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:stone")})
    item["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag(name)}
    )
    return item


def test_items_inside_a_container_are_scanned() -> None:
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag(
        [chest_with_items(named_item("聖劍"), named_item("盾牌"))]
    )

    names = {
        str(node.tag) for node in scan_chunk(root) if node.category == "custom_name"
    }

    assert names == {"聖劍", "盾牌"}


def test_an_item_node_carries_the_containers_coordinates() -> None:
    """譯者要走得到現場，而物品自己沒有座標——它在容器裡。"""
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag(
        [chest_with_items(named_item("聖劍"), x=10, y=20, z=30)]
    )

    (node,) = [n for n in scan_chunk(root) if n.category == "custom_name"]

    assert (node.anchor["x"], node.anchor["y"], node.anchor["z"]) == (10, 20, 30)


def test_the_item_path_starts_from_the_chunk_root() -> None:
    """node_path 是寫回去的指路，必須從 chunk 根一路走得到。"""
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([chest_with_items(named_item("聖劍"))])

    (node,) = [n for n in scan_chunk(root) if n.category == "custom_name"]
    steps = [
        step.name if step.t == "key" else f"[{step.i}]" for step in node.path
    ]

    assert steps == [
        "block_entities",
        "[0]",
        "Items",
        "[0]",
        "components",
        "minecraft:custom_name",
    ]


def test_a_lectern_book_is_scanned() -> None:
    """[實測] 講台的書在 `Book` 而不是 `Items[]`——Arena of Darkness 有 126 頁。"""
    lectern = amulet_nbt.CompoundTag()
    lectern["id"] = amulet_nbt.StringTag("minecraft:lectern")
    for name in ("x", "y", "z"):
        lectern[name] = amulet_nbt.IntTag(1)
    book = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:written_book")})
    book["components"] = amulet_nbt.CompoundTag(
        {
            "minecraft:written_book_content": amulet_nbt.CompoundTag(
                {
                    "pages": amulet_nbt.ListTag(
                        [amulet_nbt.CompoundTag({"raw": amulet_nbt.StringTag("第一頁")})]
                    )
                }
            )
        }
    )
    lectern["Book"] = book
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([lectern])

    pages = [n for n in scan_chunk(root) if n.category == "book_page"]

    assert [str(n.tag) for n in pages] == ["第一頁"]


def test_a_container_without_items_is_fine() -> None:
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([chest_with_items()])

    assert list(scan_chunk(root)) == []
```

檔頭若還沒 import `scan_chunk` 與 `amulet_nbt`，補上。

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_region.py -q`
Expected: FAIL — 前四條紅（物品還沒被掃到）

- [ ] **Step 3: 接上**

`src/mcmt/scan/sources/region.py` 的 `_scan_block_entity`，在 `custom_name` 那段後面加：

```python
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
```

檔頭補 import：

```python
from mcmt.scan.sources.item import scan_item
```

模組 docstring 的「v1 掃到的」那段補一行：

```
* 容器裡的物品（`Items[]`）與講台的書（`Book`），遞迴交給 `item.py`。
```

並把「還沒掃的」那段裡的「容器裡的物品」刪掉。

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_region.py -q`
Expected: PASS

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠

- [ ] **Step 6: 真實地圖驗證**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/Arena of Darkness" --lang zh_tw --out "sandbox/_items_check"
```

Expected: `by_category` 出現 `custom_name`、`lore`、`book_page`、`book_title`、`book_author`。單位數應該比重構前的 607 明顯增加（清點預期物品名 140 相異、書本 60 相異）。

**把實際數字記下來**，Task 8 之後要寫進 STATUS。確認後 `rm -rf "sandbox/_items_check"`。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/scan/sources/region.py tests/unit/test_scan_region.py
git commit -F- <<'MSG'
scan：方塊實體的 Items[] 與講台的 Book 接進物品掃描

item.py 到目前為止還沒有任何呼叫端，這一步讓它真的被用到。

兩個入口：容器的 `Items[]`（箱子、發射器、潛影盒方塊…）與講台的 `Book`——
[實測] 講台的書在 `Book` 而不是 `Items[]`，Arena of Darkness 有 126 頁在那裡，
只掃 Items[] 會整批漏掉。

物品節點的 anchor 用容器的座標：物品自己沒有座標，而譯者要走得到現場。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## Task 8: `entities/*.mca` 掃描來源

**寫入層完全不用改。** `write/apply.py` 的 `_apply_to_region` 是用 `container["path"]` 去 `world / relative` 讀寫的，而 `entities/r.0.0.mca` 就是 region 格式——現有的外科式寫入路徑直接可用。這一步的最後一個測試就是證明它真的通。

**Files:**
- Create: `src/mcmt/scan/sources/entities.py`
- Modify: `src/mcmt/scan/registry.py`
- Test: `tests/unit/test_scan_entities.py`（新）
- Test: `tests/unit/test_write_apply.py`（加一條 entities 的整合驗證）

**Interfaces:**
- Consumes: `scan_item`, `TextNode`, `ScannedNode`, `entities_files`（Task 3）, `dimension_of`（Task 4）
- Produces: `scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]`、
  `scan_entities_chunk(root: amulet_nbt.CompoundTag) -> Iterator[TextNode]`

- [ ] **Step 1: 寫失敗的測試**

新增 `tests/unit/test_scan_entities.py`：

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""實體掃描（M13.4）。

實體從 1.17 起存在 `entities/*.mca` 而不是 `region/*.mca`。**只掃 region/ 會漏掉
所有具名生物、盔甲座、展示框與 `text_display` 的浮空文字**——[實測] 100 Ways To Die
有 184 個 text_display 節點（169 個相異），Arena of Darkness 有 333 個具名實體。

格式與 region 完全一樣（同一套 header、同一套壓縮），所以讀寫都沿用
`read_region` / `write_region`。差別只在裡面裝的是 `Entities[]`。
"""

from collections import Counter

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources.entities import scan, scan_entities_chunk


def entity(entity_id="minecraft:armor_stand", **fields):
    tag = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag(entity_id)})
    tag["Pos"] = amulet_nbt.ListTag(
        [amulet_nbt.DoubleTag(1.5), amulet_nbt.DoubleTag(2.5), amulet_nbt.DoubleTag(3.5)]
    )
    for name, value in fields.items():
        tag[name] = value
    return tag


def chunk_with(*entities, data_version=4671):
    root = modern_chunk(data_version=data_version)
    root["Entities"] = amulet_nbt.ListTag(list(entities))
    return root


def categories_of(root):
    return {node.category for node in scan_entities_chunk(root)}


def test_a_named_entity_is_found():
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "entity_name"
    assert str(node.tag) == "守衛"


def test_a_text_display_is_found():
    """[實測] 現代冒險地圖大量用 text_display 取代盔甲座做浮空文字。"""
    root = chunk_with(
        entity("minecraft:text_display", text=amulet_nbt.StringTag("歡迎光臨"))
    )

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "text_display"
    assert str(node.tag) == "歡迎光臨"


def test_passengers_are_scanned_too():
    """[實測] 100 Ways To Die 有 102 個 text_display 掛在載具上。

    只掃頂層實體會整批漏掉。
    """
    passenger = entity("minecraft:text_display", text=amulet_nbt.StringTag("分數"))
    root = chunk_with(
        entity(Passengers=amulet_nbt.ListTag([passenger]))
    )

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "text_display"
    assert str(node.tag) == "分數"


def test_items_on_an_entity_are_scanned():
    """展示框裡的物品、盔甲座身上的裝備。"""
    held = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:stone")})
    held["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag("聖劍")}
    )
    root = chunk_with(entity("minecraft:item_frame", Item=held))

    (node,) = list(scan_entities_chunk(root))

    assert node.category == "custom_name"
    assert str(node.tag) == "聖劍"


def test_old_armor_items_are_scanned():
    """[實測] Arena of Darkness 的 `ArmorItems[]/tag/display/Name` 有 32 個。"""
    helmet = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:player_head")})
    helmet["tag"] = amulet_nbt.CompoundTag(
        {"display": amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag('{"text":"Steve"}')})}
    )
    root = chunk_with(
        entity(ArmorItems=amulet_nbt.ListTag([helmet]))
    )

    assert categories_of(root) == {"custom_name"}


def test_an_entity_anchor_carries_its_position():
    """實體的座標在 `Pos`，不是 x/y/z。"""
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))

    (node,) = list(scan_entities_chunk(root))

    assert node.anchor["kind"] == "entity"
    assert (node.anchor["x"], node.anchor["y"], node.anchor["z"]) == (1.5, 2.5, 3.5)


def test_mechanic_fields_are_ignored():
    """**白名單。** [實測] `Tags[]` 在 100 Ways To Die 有 96,168 個，全是識別碼。"""
    root = chunk_with(
        entity(
            CustomName=amulet_nbt.StringTag("守衛"),
            Tags=amulet_nbt.ListTag([amulet_nbt.StringTag("SpotlightMarker")]),
            variant=amulet_nbt.StringTag("minecraft:tabby"),
        )
    )

    assert categories_of(root) == {"entity_name"}


def test_the_source_reads_every_entities_file(tmp_path) -> None:
    world = tmp_path / "world"
    root = chunk_with(entity(CustomName=amulet_nbt.StringTag("守衛")))
    write_region_file(
        world / "entities", RegionBuilder().add_chunk_nbt(0, root).build()
    )

    found = list(scan(ensure_readable(world), Counter()))

    assert len(found) == 1
    assert found[0].container["kind"] == "entities_chunk"
    assert found[0].container["path"] == "entities/r.0.0.mca"
    assert found[0].container["data_version"] == 4671


def test_the_source_ignores_region_files(tmp_path) -> None:
    """`region/` 是另一個來源的事。兩邊都掃會讓每個節點出現兩次。"""
    world = tmp_path / "world"
    write_region_file(
        world / "region",
        RegionBuilder().add_chunk_nbt(0, chunk_with(
            entity(CustomName=amulet_nbt.StringTag("不該被這個來源看到"))
        )).build(),
    )

    assert list(scan(ensure_readable(world), Counter())) == []
```

加到 `tests/unit/test_write_apply.py` 末尾（**證明寫入層真的不用改**）：

```python
def test_an_entities_chunk_is_written_by_the_same_surgical_path(project) -> None:
    """**`entities/*.mca` 不需要新的寫入器。**

    它就是 region 格式——同一套 header、同一套壓縮——所以 `write_region` 直接可用，
    外科式保證原封不動。`_apply_to_region` 是用 container["path"] 去
    `world / relative` 讀寫的，`entities/r.0.0.mca` 就這樣走進同一條路。
    """
    world = project / "sandbox" / "world"
    root = modern_chunk(data_version=4671)
    holder = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:armor_stand")})
    holder["CustomName"] = amulet_nbt.StringTag("守衛")
    root["Entities"] = amulet_nbt.ListTag([holder])
    write_region_file(
        world / "entities", RegionBuilder().add_chunk_nbt(0, root).build(), "r.0.0.mca"
    )

    plan_document = {
        "edits": [
            {
                "occurrence_id": "o:00001",
                "unit_id": "u:entity_name:0123456789abcdef",
                "container": {
                    "kind": "entities_chunk",
                    "path": "entities/r.0.0.mca",
                    "dimension": "minecraft:overworld",
                    "chunk": {"cx": 0, "cz": 0},
                    "data_version": 4671,
                    "compression": 2,
                    "external": False,
                },
                "node_path": [
                    {"t": "key", "name": "Entities"},
                    {"t": "index", "i": 0},
                    {"t": "key", "name": "CustomName"},
                ],
                "expected_encoding": "bare_string",
                "value": {"kind": "literal", "text": "衛兵", "style": None},
            }
        ],
        "unwritten": [],
    }

    outcome = apply_editplan(world, plan_document)

    chunk = next(
        c
        for c in read_region(ensure_readable(world / "entities" / "r.0.0.mca"))
        if c.index == 0
    )
    data = decompress_chunk(chunk.payload, chunk.compression_type, chunk_index=chunk.index)
    written = amulet_nbt.load(data, compressed=False).compound
    assert outcome.counts["edits_written"] == 1
    assert str(written["Entities"][0]["CustomName"]) == "衛兵"
```

- [ ] **Step 2: 執行確認失敗**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_entities.py tests/unit/test_write_apply.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcmt.scan.sources.entities'`。
**`test_an_entities_chunk_is_written_by_the_same_surgical_path` 應該是綠的**——那正是這個任務要證明的事（寫入層不用改）。若它是紅的，先停下來查原因。

- [ ] **Step 3: 實作**

新增 `src/mcmt/scan/sources/entities.py`：

```python
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
    """走過世界的每一張實體 region。"""
    for path in entities_files(world):
        try:
            chunks = list(read_region(path))
        except FormatError:
            stats["skipped_region"] += 1
            continue

        for raw in chunks:
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
            relative = path.relative_to(world).replace("\\", "/")
            container = {
                "kind": "entities_chunk",
                "path": relative,
                "dimension": dimension_of(relative),
                "chunk": {"cx": raw.local_x, "cz": raw.local_z},
                "data_version": data_version,
                "compression": raw.compression_type,
                "external": raw.is_external,
            }
            for node in scan_entities_chunk(root):
                yield ScannedNode(node=node, container=container)


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

    custom_name = entity.get("CustomName")
    if custom_name is not None:
        yield TextNode(
            path=path.child(key_step("CustomName")),
            tag=custom_name,
            category="entity_name",
            anchor=anchor,
        )

    text = entity.get("text")
    if text is not None:
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
```

`src/mcmt/scan/registry.py` 改成：

```python
from mcmt.scan.sources import entities, region

__all__ = ["SOURCES"]

SOURCES = [
    region.scan,
    entities.scan,
]
```

- [ ] **Step 4: 執行確認通過**

Run: `.venv\Scripts\python -m pytest tests/unit/test_scan_entities.py tests/unit/test_write_apply.py -q`
Expected: PASS

- [ ] **Step 5: 跑全部測試**

Run: `.venv\Scripts\python -m pytest`
Expected: 全綠

- [ ] **Step 6: 真實地圖驗證**

Run:
```
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/Arena of Darkness" --lang zh_tw --out "sandbox/_m13a_aod"
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox/100 Ways To Die" --lang zh_tw --out "sandbox/_m13a_100"
```

Expected（對照清點的相異數，允許小幅出入——攤平會把某些節點合併或拆開）：

| | AoD | 100WTD |
|---|---|---|
| `custom_name` | ~147 | ~20 |
| `book_page` / `book_title` / `book_author` | ~60 | ~176 |
| `entity_name` | ~56 | ~12 |
| `text_display` | ~43 | ~169 |

**數字差很多就停下來查**——差異的方向會告訴你問題在哪：抽太少代表白名單漏了一個
路徑，抽太多代表 denylist 漏了一個識別碼。

確認後 `rm -rf "sandbox/_m13a_aod" "sandbox/_m13a_100"`。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/scan/sources/entities.py src/mcmt/scan/registry.py tests/unit/test_scan_entities.py tests/unit/test_write_apply.py
git commit -F- <<'MSG'
scan/sources/entities.py：實體裡的文字

實體從 1.17 起存在 entities/*.mca 而不是 region/*.mca。只掃 region/ 會漏掉所有
具名生物、盔甲座、展示框與 text_display 的浮空文字——[實測] 100 Ways To Die 有
184 個 text_display 節點（169 相異），Arena of Darkness 有 333 個具名實體。

**寫入層一行都沒改。** entities/*.mca 就是 region 格式（同一套 header、同一套
壓縮），`_apply_to_region` 用 container["path"] 去 world/relative 讀寫，所以現有的
外科式寫入路徑直接就通。加了一條測試證明它，而不是假設它。

白名單：CustomName、text、Passengers[]（遞迴——[實測] 100WTD 有 102 個 text_display
掛在載具上，只掃頂層會整批漏掉）、Item/item/weapon、ArmorItems/HandItems/Inventory、
equipment。其餘不碰：[實測] Tags[] 在 100WTD 有 96,168 個，全是識別碼。

實體的座標在 Pos（三個 double）不是 x/y/z——合約的 context.position 刻意是 number
而不是 integer，就是因為 text_display 常落在非整數座標上。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

## 完成條件

- [ ] `.venv\Scripts\python -m pytest` 全綠
- [ ] `.venv\Scripts\python -X utf8 tools/validate_contracts.py` → `47 passed, 0 failed`
- [ ] 三張真實地圖各跑一次 extract，抽出的單位數與清點的相異數對得上
- [ ] `docs/STATUS.md` 更新：M13a 完成、記下新的單位數、下一步是 M13b

**這份計畫結束時工具是可用的**：物品與實體都能抽、能翻、能寫回，端到端測試涵蓋它們。
`level.dat` / 記分板 / datapack 留給 M13b（`docs/superpowers/plans/` 底下的下一份計畫）。
