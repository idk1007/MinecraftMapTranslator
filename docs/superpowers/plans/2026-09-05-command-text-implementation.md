# 指令文字（方案 1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 `mcmt extract`/`mcmt apply` 認得指令方塊 `Command` 欄位與 datapack
`.mcfunction` 裡白名單動詞（`tellraw`/`title`/`say`/`data merge`/…）帶的文字，
安全地翻譯並外科式寫回，而不需要完整的指令語法解析器。

**Architecture:** 掃描層用「深度計數的 span 定位器」（不做語意解析）在指令字串裡
找出已知動詞的文字參數，交給既有的 `json_component`/`snbt` codec 解碼成真正的
`amulet_nbt` 樹，餵進**既有的** sniff/flatten/規則引擎/build 管線（零新邏輯）。
寫入層新增一個「由內往外組字、只在最外層 splice 一次」的字串拼裝原語，接上早就
寫好但從沒被呼叫過的 `span_order()`。`.mcfunction` 用同一套機制，物理字串單位是
「一行」，換行符全程當不透明資料。

**Tech Stack:** Python 3.11+、`amulet-nbt`、既有的 `mcmt.tree.codecs`／`mcmt.model.node`
機制，不引入新的相依套件。

**Spec:** `docs/superpowers/specs/2026-09-05-command-text-design.md`（brainstorming
的完整記錄與取捨理由都在那份文件，本計畫只負責拆成任務）。

## 對照 spec 的一處修正（讀真實程式碼發現的）

Spec §2.1 寫「新增 `scan/sources/command_block.py` 掃 `Command` 欄位」，暗示它是一個
獨立的頂層掃描來源。讀了 `scan/sources/region.py`／`scan/sources/entities.py` 的實際
結構後發現：`Command` 只是 `block_entities[]`／`Entities[]` 裡的一個欄位，跟
`CustomName`、`Items[]` 一樣，這兩個檔案本來就會逐一走訪每個 block entity／entity。
如果另外開一個「頂層來源」重新讀一次整個世界的 chunk，就是白白多讀一次磁碟。

**修正**：指令方塊的解析邏輯放在**新檔案 `src/mcmt/scan/command.py`**（純函式，
不自己走訪 chunk），`region.py`／`entities.py` 各自在既有的「走訪一個 block
entity／entity」的函式裡，多檢查一個 `Command` 欄位、呼叫這個共用模組——完全比照
`scan/sources/item.py` 被三處呼叫的既有模式（CLAUDE.md 已經寫過這個道理：「同一份
遞迴被方塊實體、實體裝備、玩家背包三處共用，各寫一份是漏掉一層的最短路徑」）。
`.mcfunction` 沒有這個問題——它本來就不在任何既有的 chunk 走訪迴圈裡，`scan/sources/mcfunction.py`
維持 spec 原本的設計，是一個新的頂層來源。

## Global Constraints

- Python 3.11+，執行期只能用 `amulet-nbt` + stdlib，不得新增相依。
- `src/mcmt/write/` 底下任何檔案的修改，必須是獨立 commit 並在訊息中說明理由
  （CLAUDE.md 硬性禁令）。
- `docs/contracts/*.json` 的改動：獨立 commit、同步 `tests/fixtures/contracts/*.sample.json`、
  bump `SCHEMA_VERSION`（6 → 7）、`tools/validate_contracts.py` 要綠燈才算完成。
- 佔位符 `[[n]]` 驗證仍是 hard fail；規則沒有因為這次擴掃描範圍而放寬。
- 一個任務一個 commit，先寫失敗的測試，跑過確認失敗，再寫最小實作。
- 任何「不猜、跳過並計數」的決定，都要有對應的 `stats.*` 欄位讓使用者從報告上看得到，
  不能靜默漏掉。
- 每個 task 做完之後跑一次 `python -m pytest`，確認既有測試沒有變紅。

---

### Task 1: 合約異動 —— 兩個新分類、一個新容器種類、三個新 stats 欄位

**Files:**
- Modify: `docs/contracts/extract.schema.json`
- Modify: `docs/contracts/editplan.schema.json`
- Modify: `tests/fixtures/contracts/extract.sample.json`
- Modify: `tests/fixtures/contracts/editplan.sample.json`
- Modify: `src/mcmt/model/__init__.py`（或 `SCHEMA_VERSION` 實際定義的檔案——先
  `grep -rn "SCHEMA_VERSION = 6" src/` 找到它）
- Test: `tests/unit/test_contracts.py`（若沒有這個檔案，直接跑
  `.venv/Scripts/python tools/validate_contracts.py` 當驗證步驟）

**Interfaces:**
- Produces: `extract.schema.json` 的 `category` enum 新增 `"command_say_text"`、
  `"command_component_text"`（**移除**佔位用的 `"command_text"`）；`container.kind`
  enum 新增 `"datapack_mcfunction_file"`；`stats` 物件新增
  `skipped_command_unsupported_shape`、`skipped_command_nested_reference`、
  `skipped_command_line_continuation`（都是 `{"type":"integer","minimum":0}`，
  跟既有的 `skipped_unparseable` 等欄位同規格）。`editplan.schema.json` 的
  category→strategy if/then，把 `"command_say_text"` 加進
  `["level_name","book_title","book_author","draft_book_page","block_entity_name"]`
  那個 enum 陣列。

- [ ] **Step 1: 找到並確認目前的 SCHEMA_VERSION**

```bash
grep -rn "SCHEMA_VERSION" src/mcmt/ | grep -v __pycache__
```

把回傳結果裡「定義」那一行的檔案記下來，下面 Step 2 要改的就是它。

- [ ] **Step 2: 改 `extract.schema.json`**

把 `category` 的 enum 陣列從

```json
"sign", "hanging_sign",
"item_name", "custom_name", "lore",
"book_title", "book_author", "book_page", "draft_book_page",
"entity_name", "text_display", "block_entity_name",
"bossbar", "objective", "team", "team_affix",
"advancement_title", "advancement_description",
"level_name",
"command_text",
"hover_text",
"unknown"
```

改成

```json
"sign", "hanging_sign",
"item_name", "custom_name", "lore",
"book_title", "book_author", "book_page", "draft_book_page",
"entity_name", "text_display", "block_entity_name",
"bossbar", "objective", "team", "team_affix",
"advancement_title", "advancement_description",
"level_name",
"command_say_text",
"command_component_text",
"hover_text",
"unknown"
```

`container.kind` enum（`region_chunk`／`entities_chunk`／`poi_chunk`／`level_dat`／
`scoreboard_dat`／`player_dat`／`datapack_file`）加上 `"datapack_mcfunction_file"`。

在 `stats` 物件（`skipped_unparseable`、`skipped_legacy_json_in_native_chunk` 旁邊）
新增三個同規格的欄位：`skipped_command_unsupported_shape`、
`skipped_command_nested_reference`、`skipped_command_line_continuation`。

把檔案裡 `SCHEMA_VERSION` 的常數值（Step 1 找到的那個檔案）從 `6` 改成 `7`。

- [ ] **Step 3: 改 `editplan.schema.json`**

找到這段 if/then（category ⇒ in_place）：

```json
{
  "if": {
    "required": ["category"],
    "properties": {
      "category": { "enum": ["level_name", "book_title", "book_author", "draft_book_page", "block_entity_name"] }
    }
  },
  "then": { ... }
}
```

把 enum 陣列加上 `"command_say_text"`。**不要**加 `"command_component_text"`——
它走預設的 `translate_key`，不需要進這條 if/then。

- [ ] **Step 4: 同步兩份 sample fixture**

`tests/fixtures/contracts/extract.sample.json`、`editplan.sample.json` 裡任何用到
`SCHEMA_VERSION` 數字的地方（通常是頂層一個 `"schema_version": 6` 欄位）改成 `7`。
如果 sample 裡有用到 `command_text` 這個字面值，改成 `command_component_text`。

- [ ] **Step 5: 驗證**

```bash
.venv/Scripts/python tools/validate_contracts.py
```

Expected: 全部 PASS，數量應該跟改動前一樣（沒有新增測試案例，只是 schema 本身
異動）。

- [ ] **Step 6: Commit（獨立 commit，合約改動流程要求）**

```bash
git add docs/contracts/ tests/fixtures/contracts/ src/mcmt/<SCHEMA_VERSION所在檔案>
git commit -m "合約：SCHEMA_VERSION 6 -> 7，加 command_say_text/command_component_text/datapack_mcfunction_file"
```

---

### Task 2: span 定位器（`tree/span_locator.py`）

**Files:**
- Create: `src/mcmt/tree/span_locator.py`
- Test: `tests/unit/test_span_locator.py`

**Interfaces:**
- Produces:
  - `class LocateError(ValueError)`
  - `find_balanced_span(text: str, start: int) -> tuple[int, int]`
  - `find_unquoted_token(text: str, start: int, token: str) -> int`（找不到回傳 `-1`）
  - `locate_path_span(text: str, span: tuple[int, int], path: Sequence[str | int]) -> tuple[int, int]`

- [ ] **Step 1: 寫 `find_balanced_span` 的失敗測試**

```python
# tests/unit/test_span_locator.py
from mcmt.tree.span_locator import LocateError, find_balanced_span


def test_finds_a_simple_compound():
    text = 'tellraw @a {"text":"Hello"}'
    assert find_balanced_span(text, text.index("{")) == (12, len(text))


def test_ignores_braces_inside_a_json_string_value():
    text = 'tellraw @a {"text":"say {hi}"}'
    start = text.index("{")
    assert find_balanced_span(text, start) == (start, len(text))


def test_ignores_an_escaped_quote_inside_the_string():
    text = r'tellraw @a {"text":"say \"hi\""}'
    start = text.index("{")
    assert find_balanced_span(text, start) == (start, len(text))


def test_handles_single_quoted_snbt_strings():
    text = "data merge block ~ ~ ~ {front_text:{messages:['Line 1']}}"
    start = text.index("{")
    assert find_balanced_span(text, start) == (start, len(text))


def test_a_list_span_is_found_too():
    text = 'give @s stone[custom_name={text:"X"}]'
    start = text.index("[")
    assert find_balanced_span(text, start) == (start, len(text))


def test_raises_when_the_bracket_never_closes():
    text = 'tellraw @a {"text":"Hello"'
    with pytest.raises(LocateError):
        find_balanced_span(text, text.index("{"))


def test_raises_when_start_is_not_an_opener():
    with pytest.raises(LocateError):
        find_balanced_span("hello", 0)
```

在檔案最上面補 `import pytest`。

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_span_locator.py -v
```

Expected: FAIL，`ModuleNotFoundError: No module named 'mcmt.tree.span_locator'`

- [ ] **Step 3: 寫 `find_balanced_span` 的實作**

```python
# src/mcmt/tree/span_locator.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""深度計數的 span 定位器——不做語意解析，只數括號、引號、逗號的深度。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §3。這是指令文字
掃描與寫回共用的核心元件：只回答「這段文字在哪裡」，不回答「這段文字是什麼
意思」——語意交給既有的 json_component/snbt codec 處理。
"""

from typing import Sequence

__all__ = [
    "LocateError",
    "find_balanced_span",
    "find_unquoted_token",
    "locate_path_span",
]


class LocateError(ValueError):
    """找不到指定的範圍或路徑。呼叫端把這個當「這次不猜、跳過並計數」的訊號。"""


_OPENERS = {"{": "}", "[": "]"}


def find_balanced_span(text: str, start: int) -> tuple[int, int]:
    """從 `start`（必須是 `{` 或 `[`）開始，回傳 (start, end) 使得
    `text[start:end]` 是一段括號平衡、引號感知的區間（`end` 是配對括號的下一個
    位置）。只數深度，不理解值的意義；`{`/`}`/`[`/`]` 出現在字串常值裡不會被
    誤判成結構字元。"""
    if start >= len(text) or text[start] not in _OPENERS:
        raise LocateError(
            f"位置 {start} 不是 '{{' 或 '[' 開頭：{text[start:start + 20]!r}"
        )
    depth = 0
    i = start
    in_string = False
    quote_char = ""
    escape = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            i += 1
            continue
        if ch in "\"'":
            in_string = True
            quote_char = ch
            i += 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        i += 1
    raise LocateError(f"從位置 {start} 開始找不到配對的括號（原文太短或沒有結尾）")


def find_unquoted_token(text: str, start: int, token: str) -> int:
    """從 `start` 開始找 `token`（例如 `" run "`）第一次出現在括號深度 0、且不在
    引號內的位置；找不到回傳 -1。用來剝 `execute ... run <command>` 的前綴，
    不能用普通字串搜尋——指令文字裡可能真的含有 token 這個子字串
    （`tellraw @a {"text":"run for it"}`）。"""
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    i = start
    n = len(token)
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            i += 1
            continue
        if ch in "\"'":
            in_string = True
            quote_char = ch
            i += 1
            continue
        if ch in "{[":
            depth += 1
            i += 1
            continue
        if ch in "}]":
            depth -= 1
            i += 1
            continue
        if depth == 0 and text.startswith(token, i):
            return i
        i += 1
    return -1


def locate_path_span(
    text: str, span: tuple[int, int], path: Sequence[str | int]
) -> tuple[int, int]:
    """在 `text[span[0]:span[1]]`（必須是一段括號平衡的 compound 或 list 文字）
    裡，沿著 `path`（compound 用字串 key、list 用整數 index）逐層縮小，回傳
    目標值在**原始 `text`** 裡的絕對 `(start, end)`。"""
    start, end = span
    if not path:
        return (start, end)
    body = text[start:end]
    opener = body[0]
    step = path[0]

    if opener == "[":
        if not isinstance(step, int):
            raise LocateError(f"list 需要整數 index，收到 {step!r}")
        elements = _split_top_level(body[1:-1])
        if step >= len(elements):
            raise LocateError(
                f"list index {step} 超出範圍（共 {len(elements)} 個元素）"
            )
        rel_start, rel_end = elements[step]
        abs_start = start + 1 + rel_start
        abs_end = start + 1 + rel_end
    elif opener == "{":
        if not isinstance(step, str):
            raise LocateError(f"compound 需要字串 key，收到 {step!r}")
        found = _find_key_value(body[1:-1], step)
        if found is None:
            raise LocateError(f"compound 裡找不到 key {step!r}")
        rel_start, rel_end = found
        abs_start = start + 1 + rel_start
        abs_end = start + 1 + rel_end
    else:
        raise LocateError(f"span 開頭不是 '{{' 或 '['：{opener!r}")

    remaining = path[1:]
    if not remaining:
        return (abs_start, abs_end)
    if abs_start >= len(text) or text[abs_start] not in _OPENERS:
        raise LocateError("路徑還沒走完，但這個值不是 compound/list，走不下去")
    inner_span = find_balanced_span(text, abs_start)
    return locate_path_span(text, inner_span, remaining)


def _split_top_level(body: str) -> list[tuple[int, int]]:
    """把 `body`（list 拿掉外層 `[`/`]` 之後的內容）依深度 0 的逗號切成元素，
    回傳每個元素相對 `body` 的 `(start, end)`（不含前後空白）。"""
    elements: list[tuple[int, int]] = []
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    elem_start = 0
    i = 0
    n = len(body)
    while i <= n:
        ch = body[i] if i < n else ","  # 補一個假逗號讓最後一個元素也被收進來
        if in_string:
            if i < n:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote_char:
                    in_string = False
            i += 1
            continue
        if i < n and ch in "\"'":
            in_string = True
            quote_char = ch
            i += 1
            continue
        if i < n and ch in "{[":
            depth += 1
            i += 1
            continue
        if i < n and ch in "}]":
            depth -= 1
            i += 1
            continue
        if ch == "," and depth == 0:
            raw = body[elem_start:i]
            stripped_start = elem_start + (len(raw) - len(raw.lstrip()))
            stripped_end = i - (len(raw) - len(raw.rstrip()))
            if stripped_start < stripped_end:
                elements.append((stripped_start, stripped_end))
            elem_start = i + 1
        i += 1
    return elements


def _find_key_value(body: str, key: str) -> tuple[int, int] | None:
    """在 `body`（compound 拿掉外層 `{`/`}` 之後的內容）裡找 `key`（SNBT 無引號
    或 JSON `"key"` 兩種寫法都認），回傳它的值相對 `body` 的 `(start, end)`。"""
    for elem_start, elem_end in _split_top_level(body):
        piece = body[elem_start:elem_end]
        colon = _find_top_level_colon(piece)
        if colon is None:
            continue
        raw_key = piece[:colon].strip().strip("\"'")
        if raw_key == key:
            value = piece[colon + 1 :]
            value_start = elem_start + colon + 1 + (len(value) - len(value.lstrip()))
            value_end = elem_end - (len(value) - len(value.rstrip()))
            return (value_start, value_end)
    return None


def _find_top_level_colon(piece: str) -> int | None:
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    for i, ch in enumerate(piece):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            continue
        if ch in "\"'":
            in_string = True
            quote_char = ch
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == ":" and depth == 0:
            return i
    return None
```

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_span_locator.py -v
```

Expected: 7 個測試全部 PASS。

- [ ] **Step 5: 補 `find_unquoted_token` 與 `locate_path_span` 的測試**

追加到同一個檔案：

```python
from mcmt.tree.span_locator import find_unquoted_token, locate_path_span


def test_find_unquoted_token_finds_the_run_keyword():
    text = "execute as @a at @s run tellraw @s {\"text\":\"hi\"}"
    idx = find_unquoted_token(text, 0, " run ")
    assert text[idx : idx + 5] == " run "


def test_find_unquoted_token_ignores_the_word_inside_a_json_string():
    text = 'tellraw @a {"text":"run for it"}'
    assert find_unquoted_token(text, 0, " run ") == -1


def test_locate_path_span_on_a_native_compound_list_element():
    text = 'data merge block ~ ~ ~ {front_text:{messages:[{text:"Line 1"},{text:"Line 2"}]}}'
    span = find_balanced_span(text, text.index("{"))
    first = locate_path_span(text, span, ["front_text", "messages", 0])
    second = locate_path_span(text, span, ["front_text", "messages", 1])
    assert text[first[0] : first[1]] == '{text:"Line 1"}'
    assert text[second[0] : second[1]] == '{text:"Line 2"}'
    assert first[0] < second[0]  # Line 2 在 Line 1 右邊——降冪排序時要先處理它


def test_locate_path_span_on_a_string_wrapped_json_element():
    text = 'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}'
    span = find_balanced_span(text, text.index("{"))
    element = locate_path_span(text, span, ["messages", 0])
    assert text[element[0] : element[1]] == '"{\\"text\\":\\"Hello\\"}"'


def test_locate_path_span_raises_on_a_missing_key():
    text = "{a:1,b:2}"
    span = find_balanced_span(text, 0)
    with pytest.raises(LocateError):
        locate_path_span(text, span, ["c"])
```

- [ ] **Step 6: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_span_locator.py -v
```

Expected: 全部 PASS（12 個測試）。如果 `test_locate_path_span_on_a_string_wrapped_json_element`
沒過，檢查 `_find_key_value`／`_split_top_level` 對「字串常值本身含逗號」的處理——
這是最容易漏的邊界。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/tree/span_locator.py tests/unit/test_span_locator.py
git commit -m "span 定位器：深度計數找 JSON/SNBT 片段的絕對位移，不做語意解析"
```

---

### Task 3: `command` codec 從「明確拒絕」改成「近乎透明的標記層」

**Files:**
- Modify: `src/mcmt/tree/codecs/command.py`
- Test: `tests/unit/test_codec_command.py`

**Interfaces:**
- Consumes: 無（不依賴前面的任務）
- Produces: `command` codec 的 `decode(text: str) -> str`（identity，只驗證型別）、
  `encode(value: str) -> str`（identity）。**這個 codec 本身不做真正的解析或組字**
  ——那些工作在 span 定位器（Task 2）與 splice 原語（Task 6）裡，這裡只是讓
  `codec_for("command")` 不再對每次呼叫都 `raise NotImplementedError`，滿足合約
  `decode.codec` enum 允許 `"command"` 這個事實。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/unit/test_codec_command.py
import pytest

from mcmt.tree.codecs import command


def test_decode_returns_the_text_unchanged():
    assert command.decode("say hello") == "say hello"


def test_decode_rejects_non_string_input():
    with pytest.raises(TypeError):
        command.decode(123)


def test_encode_returns_the_text_unchanged():
    assert command.encode("say hello") == "say hello"
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_codec_command.py -v
```

Expected: FAIL——目前的 `decode`/`encode` 一律 `raise NotImplementedError`。

- [ ] **Step 3: 改寫 `src/mcmt/tree/codecs/command.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串——標記層，不做真正的解析。

真正的解析（白名單動詞、`execute` 前綴剝除、找出文字參數的範圍）在
`mcmt.scan.command`；把巢狀 SNBT/JSON 值組回可以 splice 的文字在
`mcmt.write.command_span`。這個 codec 只負責讓 `codec_for("command")` 不再
`raise NotImplementedError`——它存在的理由是合約的 `decode.codec` enum 允許
`"command"` 這個值，`node_path` 需要一個真的可以被 `codec_for()` 找到的名字，
但「指令字串」本身沒有一個值得解碼成的中介型別（不像 json_component 解碼成
component 樹），decode/encode 都是近乎透明的 identity。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §3 對這個決定的
完整說明。
"""

NAME = "command"
faithful_round_trip = False


def decode(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"command codec 只接受字串，收到 {type(text).__name__}")
    return text


def encode(value: str) -> str:
    return str(value)
```

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_codec_command.py -v
```

Expected: 3 個測試 PASS。

- [ ] **Step 5: 跑一次全部測試，確認 `tree/codecs/__init__.py` 的 `codec_for("command")` 沒有被其他地方假設會 raise**

```bash
grep -rn "codec_for(\"command\")\|codec_for('command')" src/ tests/
.venv/Scripts/python -m pytest -q
```

Expected: 全部 PASS。如果有測試斷言「`command` codec 呼叫會 raise」，那條測試要
跟著這次改動更新（它驗的是舊行為，這次是刻意改變舊行為）。

- [ ] **Step 6: Commit**

```bash
git add src/mcmt/tree/codecs/command.py tests/unit/test_codec_command.py
git commit -m "command codec：從明確拒絕改成標記層，真正解析交給 scan/write 兩側"
```

---

### Task 4: 策略對照 —— `command_say_text` 加進 `IN_PLACE_CATEGORIES`

**Files:**
- Modify: `src/mcmt/model/strategy.py`
- Test: `tests/unit/test_strategy.py`

**Interfaces:**
- Consumes: Task 1 的合約異動（`command_say_text` 分類已存在於 schema）
- Produces: `strategy_for("command_say_text") == "in_place"`、
  `strategy_for("command_component_text") == "translate_key"`

- [ ] **Step 1: 寫失敗測試**

```python
# 加進 tests/unit/test_strategy.py
def test_command_say_text_is_in_place():
    assert strategy_for("command_say_text") == "in_place"


def test_command_component_text_is_translate_key():
    assert strategy_for("command_component_text") == "translate_key"
```

（若檔案開頭沒有 `from mcmt.model.strategy import strategy_for`，先確認怎麼匯入的，
跟著既有寫法補。）

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_strategy.py -v
```

Expected: `test_command_say_text_is_in_place` FAIL（目前回傳 `"translate_key"`，
因為預設就是這個）。`test_command_component_text_is_translate_key` 會直接 PASS
（本來就是預設值）——這條測試存在是為了**釘住**這個決定不被以後的人改掉，不是
因為它現在會紅。

- [ ] **Step 3: 修改 `IN_PLACE_CATEGORIES`**

```python
IN_PLACE_CATEGORIES = frozenset(
    {
        "level_name",
        "book_title",
        "book_author",
        "draft_book_page",
        "block_entity_name",
        "command_say_text",
    }
)
```

同時在模組開頭的表格加一行：

```
| `command_say_text` | `say`／`me` 的參數沒有 component 語法可插 key，只能直接替換文字 |
```

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_strategy.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/mcmt/model/strategy.py tests/unit/test_strategy.py
git commit -m "策略：command_say_text 走 in_place（沒有 component 語法可插 key）"
```

---

### Task 5: 掃描 —— 指令字串的共用解析（`scan/command.py`）

這是掃描層最核心的任務，一次把白名單、`execute` 剝除、L1/L2/L3、行尾延續偵測都
寫完（這幾件事互相依賴，拆成更小的任務只會讓中間狀態測不了）。

**Files:**
- Create: `src/mcmt/scan/command.py`
- Test: `tests/unit/test_scan_command.py`

**Interfaces:**
- Consumes: `mcmt.tree.span_locator`（Task 2 的三個函式）、
  `mcmt.tree.codecs.codec_for`（既有，`json_component`/`snbt`）、
  `mcmt.scan.node.TextNode`（既有）、`mcmt.model.node`（`NodePath`、`key_step`、
  `index_step`、`decode_step`，既有）
- Produces:
  - `LINE_CONTINUES = "line_continuation"`（一個 sentinel 字串常數，供 Task 8 的
    `.mcfunction` 掃描判斷「這行要整批跳過」用）
  - `scan_command_string(text: str, *, base_path: "NodePath", anchor: dict, stats: "Counter") -> Iterator[TextNode]`
    ——給一整條**已經確定不是延續行**的指令文字，yield 裡面白名單動詞找到的
    `TextNode`。呼叫端（`region.py`／`entities.py`／`mcfunction.py`）負責先判斷
    這行是不是延續行，是的話直接跳過並自己計數
    `stats["skipped_command_line_continuation"]`，**不要**呼叫這個函式。

**白名單動詞規則（每個動詞怎麼找參數）：**

| 動詞 | 找法 | dialect | 是不是 L2 |
|---|---|---|---|
| `say` | 動詞後面（去掉一個空白）到行尾，整段是文字 | 無（純文字） | 否，`command_say_text` |
| `me` | 同上 | 無 | 否，`command_say_text` |
| `tellraw <target> <arg>` | 跳過動詞＋一個 token（`<target>`），剩下第一個 `{` 到配對 `}` 就是 `<arg>` | json | 否（L1） |
| `title <target> title\|subtitle\|actionbar <arg>` | 跳過動詞＋兩個 token，剩下的是 `<arg>` | json | 否（L1） |
| `bossbar set <id> name <arg>` | 必須是 `set ... name`（`value`/`max`/`color`/`style`/`players`/`visible` 都不算），`<arg>` 是最後一個 token 之後的 `{` 到配對 `}` | json | 否（L1） |
| `scoreboard objectives add <name> <criteria> [<arg>]` | 必須是 `objectives add`，`<arg>` 是可選的第 4 個參數，找不到就不是這個 unit（不是錯誤，是這條指令沒有顯示名稱） | json | 否（L1） |
| `data merge block\|entity\|storage ... <nbt>` | 跳過 `data merge <目標種類> <目標>`，剩下第一個 `{` 到配對 `}` 是整個 NBT；文字在 `front_text.messages[i]` 或 `back_text.messages[i]`（用 `locate_path_span` 對每個存在的面／索引各找一次） | snbt | 是（L2） |
| `data modify block\|entity\|storage ... merge value <nbt>` | 同上，但要先找到 `merge value` 這個子片語 | snbt | 是（L2） |
| `give <target> <item>[<components>]` / `item replace ... with <item>[<components>]` | 找 `[` 到配對 `]`（物品組件），文字在 `custom_name`／`item_name`／`lore` | snbt | 是（L2） |

**L3 偵測**：解出的值（不管 L1 還是 L2）如果含 `click_event`，其 `action` 是
`run_command` 或 `suggest_command`，且它的 `command` 字串（遞迴剝掉 `execute` 之後）
的動詞落在同一張白名單裡 → 這個 occurrence 整個不 yield，計
`stats["skipped_command_nested_reference"] += 1`。

- [ ] **Step 1: 寫 `say`/`me` 的失敗測試（最簡單，先建立骨架）**

```python
# tests/unit/test_scan_command.py
from collections import Counter

import amulet_nbt

from mcmt.model.node import NodePath, key_step
from mcmt.scan.command import scan_command_string


def _path():
    return NodePath([key_step("block_entities"), key_step("Command")])


def test_say_yields_a_bare_string_text_node():
    stats = Counter()
    nodes = list(
        scan_command_string(
            "say Welcome to the arena!",
            base_path=_path(),
            anchor={"kind": "block"},
            stats=stats,
        )
    )
    assert len(nodes) == 1
    node = nodes[0]
    assert node.category == "command_say_text"
    assert isinstance(node.tag, amulet_nbt.StringTag)
    assert str(node.tag) == "Welcome to the arena!"


def test_me_is_treated_the_same_as_say():
    stats = Counter()
    nodes = list(
        scan_command_string("me waves", base_path=_path(), anchor=None, stats=stats)
    )
    assert nodes[0].category == "command_say_text"
    assert str(nodes[0].tag) == "waves"


def test_an_unknown_verb_is_skipped_and_counted():
    stats = Counter()
    nodes = list(
        scan_command_string(
            "weather clear", base_path=_path(), anchor=None, stats=stats
        )
    )
    assert nodes == []
    assert stats["skipped_command_unsupported_shape"] == 1
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_command.py -v
```

Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 寫骨架實作（先只處理 say/me + 白名單檢查）**

```python
# src/mcmt/scan/command.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串裡的可翻文字——白名單動詞、execute 剝除、L1/L2/L3。

這是一個**共用的純函式模組**，不自己走訪 chunk。`scan/sources/region.py` 與
`scan/sources/entities.py` 在既有的「走訪一個 block entity／entity」函式裡呼叫
`scan_command_string()`；`scan/sources/mcfunction.py` 對每一行（已排除延續行）
也呼叫它。三處共用同一份白名單、同一份 L3 偵測邏輯，不是巧合的重複——理由跟
`scan/sources/item.py` 被三處共用一樣：漏掉一層是最短的出錯路徑。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §2、§3。
"""

from collections import Counter
from typing import Any, Iterator

import amulet_nbt

from mcmt.model.node import NodePath, decode_step, index_step, key_step
from mcmt.scan.node import TextNode
from mcmt.tree.codecs import codec_for
from mcmt.tree.span_locator import LocateError, find_balanced_span, find_unquoted_token

__all__ = ["scan_command_string"]

_SAY_VERBS = ("say", "me")


def scan_command_string(
    text: str, *, base_path: NodePath, anchor: dict[str, Any] | None, stats: Counter
) -> Iterator[TextNode]:
    """給一條**已確定不是延續行**的指令文字，yield 白名單動詞找到的文字節點。"""
    inner, offset = _strip_execute(text)
    stripped = inner.lstrip()
    lead = len(inner) - len(stripped)
    verb, rest = _split_first_token(stripped)
    if verb is None:
        stats["skipped_command_unsupported_shape"] += 1
        return

    if verb in _SAY_VERBS:
        payload = rest.lstrip()
        if not payload:
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield TextNode(
            path=base_path,
            tag=amulet_nbt.StringTag(payload),
            category="command_say_text",
            anchor=anchor,
        )
        return

    stats["skipped_command_unsupported_shape"] += 1


def _strip_execute(text: str) -> tuple[str, int]:
    """剝掉 `execute ... run ` 前綴，回傳 (剩下的指令文字, 它在原始 text 裡的
    起始位移)。沒有 `execute` 前綴就原樣回傳。"""
    stripped = text.lstrip()
    if not stripped.startswith("execute"):
        return text, 0
    idx = find_unquoted_token(text, 0, " run ")
    if idx == -1:
        return "", 0  # 只有條件、沒有 run——這條指令不執行任何東西，沒有文字。
    start = idx + len(" run ")
    return text[start:], start


def _split_first_token(text: str) -> tuple[str | None, str]:
    text = text.lstrip()
    if not text:
        return None, ""
    idx = text.find(" ")
    if idx == -1:
        return text, ""
    return text[:idx], text[idx + 1 :]
```

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_command.py -v
```

Expected: 3 個測試 PASS。

- [ ] **Step 5: 補 `execute` 前綴的測試**

```python
def test_execute_prefix_is_stripped_before_verb_matching():
    stats = Counter()
    nodes = list(
        scan_command_string(
            "execute as @a at @s run say hi there",
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes[0].category == "command_say_text"
    assert str(nodes[0].tag) == "hi there"


def test_the_word_run_inside_quotes_does_not_confuse_execute_stripping():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'execute if block ~ ~ ~ minecraft:stone run say run for it',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert str(nodes[0].tag) == "run for it"
```

跑測試確認通過（`.venv/Scripts/python -m pytest tests/unit/test_scan_command.py -v`）。

- [ ] **Step 6: 加 L1 動詞（`tellraw`）**

先寫測試：

```python
def test_tellraw_yields_a_decoded_json_component_node():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"text":"Hello"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    node = nodes[0]
    assert node.category == "command_component_text"
    assert isinstance(node.tag, amulet_nbt.CompoundTag)
    assert str(node.tag["text"]) == "Hello"
    # 最內層 decode 的 span 要對得上原始文字裡那個 JSON 區塊的絕對位移。
    last_span = node.path.last_span
    full = 'tellraw @a {"text":"Hello"}'
    assert full[last_span[0] : last_span[1]] == '{"text":"Hello"}'
```

實作：在 `scan_command_string` 裡 `say`/`me` 分支之後加：

```python
    if verb == "tellraw":
        target, arg_text = _split_first_token(rest)
        if target is None:
            stats["skipped_command_unsupported_shape"] += 1
            return
        arg_offset_in_stripped = len(stripped) - len(arg_text.lstrip())
        arg_start_in_stripped = arg_offset_in_stripped
        # 換算回原始 text 裡的絕對位移：execute 剝除的 offset + lstrip 掉的空白。
        absolute_start = offset + lead + arg_start_in_stripped
        try:
            arg_span = find_balanced_span(text, absolute_start)
        except LocateError:
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _yield_component(
            text, arg_span, path=(), base_path=base_path, anchor=anchor, stats=stats
        )
        return
```

以及共用的 `_yield_component` 輔助函式：

```python
def _yield_component(
    text: str,
    arg_span: tuple[int, int],
    *,
    path: tuple[str | int, ...],
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    """把 `arg_span`（一段 JSON 文字）解碼成 amulet_nbt 樹，套 L3 檢查後 yield。
    `path` 目前用不到（L1 呼叫端傳空 tuple），留給 Task 6 L2 呼叫端用同一個
    函式時傳入 decode 鏈需要的資訊。"""
    raw = text[arg_span[0] : arg_span[1]]
    try:
        value = codec_for("json_component").decode(raw)
    except Exception:
        stats["skipped_command_unsupported_shape"] += 1
        return
    tag = _to_amulet(value)
    if _has_nested_command_reference(tag):
        stats["skipped_command_nested_reference"] += 1
        return
    node_path = base_path.child(
        decode_step("command", span=(0, len(text)))
    ).child(decode_step("json_component", span=arg_span))
    yield TextNode(path=node_path, tag=tag, category="command_component_text", anchor=anchor)
```

（`_to_amulet` 與 `_has_nested_command_reference` 兩個輔助函式在 Step 8、Step 9
補；先讓這步的測試因為 `NameError` 失敗都沒關係，**不要**跳過寫測試這步。）

- [ ] **Step 7: 補 `_to_amulet`（值已經是 amulet_nbt 樹就直接用，否則按既有
  `scan/sources/datapack.py::_to_amulet` 的邏輯轉——直接照抄那份實作，理由
  一致：component 陣列語法允許異質，需要同質化才能塞進 `ListTag`）**

```python
from mcmt.scan.sources.datapack import _to_amulet as _to_amulet  # noqa: F401
```

**不要複製貼上 `datapack.py` 那段邏輯**——直接 import 它，兩處要的是同一個
轉換規則，複製一份是漏改一次的最短路徑（`datapack.py` 那份的 docstring已經
把「為什麼要同質化」講得很完整，這裡不重講一次）。

- [ ] **Step 8: 寫 `_has_nested_command_reference` 的測試與實作**

```python
def test_a_click_event_pointing_at_another_known_verb_is_skipped():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"text":"Click","click_event":'
            '{"action":"run_command","command":"say hi"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes == []
    assert stats["skipped_command_nested_reference"] == 1


def test_a_click_event_pointing_at_an_inert_command_is_not_skipped():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"text":"Click","click_event":'
            '{"action":"run_command","command":"/spawn"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert stats["skipped_command_nested_reference"] == 0
```

實作：

```python
_CLICK_ACTIONS = {"run_command", "suggest_command"}


def _has_nested_command_reference(tag: amulet_nbt.AbstractBaseTag) -> bool:
    """`tag`（或它的任何 extra 子節點）裡有沒有一個 click_event 指向另一條
    「白名單也認得出來、代表裡面還有文字」的指令。有 → 這整個 occurrence
    保守地整個跳過（方案 1 明確排除的 L3，見 spec §1）。"""
    if isinstance(tag, amulet_nbt.CompoundTag):
        click = tag.get("click_event")
        if isinstance(click, amulet_nbt.CompoundTag):
            action = str(click.get("action", ""))
            command = click.get("command")
            if action in _CLICK_ACTIONS and isinstance(command, amulet_nbt.StringTag):
                inner, _ = _strip_execute(str(command))
                verb, _ = _split_first_token(inner)
                if verb in _SAY_VERBS or verb in _COMPONENT_VERBS:
                    return True
        extra = tag.get("extra")
        if isinstance(extra, amulet_nbt.ListTag):
            for child in extra:
                if _has_nested_command_reference(child):
                    return True
    return False


_COMPONENT_VERBS = {"tellraw", "title", "bossbar", "scoreboard", "data", "give", "item"}
```

- [ ] **Step 9: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_command.py -v
```

Expected: 全部 PASS。

- [ ] **Step 10: 加剩下的 L1 動詞（`title`/`subtitle`/`actionbar`、`bossbar ... name`、
  `scoreboard objectives add`）——照抄 `tellraw` 那個分支的模式**

每個都是「跳過固定數量的 token，找 `{` 到配對 `}`，呼叫 `_yield_component`」，
差異只在跳過幾個 token、以及 `bossbar`/`scoreboard` 需要先確認子指令字面值對不對。
寫法：

```python
    if verb == "title":
        target, remainder = _split_first_token(rest)
        slot, arg_text = _split_first_token(remainder)
        if slot not in ("title", "subtitle", "actionbar"):
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _locate_and_yield(text, arg_text, offset, lead, stripped, base_path, anchor, stats)
        return

    if verb == "bossbar":
        sub, remainder = _split_first_token(rest)
        bar_id, remainder2 = _split_first_token(remainder)
        field, arg_text = _split_first_token(remainder2)
        if sub != "set" or field != "name":
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _locate_and_yield(text, arg_text, offset, lead, stripped, base_path, anchor, stats)
        return

    if verb == "scoreboard":
        sub, remainder = _split_first_token(rest)
        action, remainder2 = _split_first_token(remainder)
        if sub != "objectives" or action != "add":
            stats["skipped_command_unsupported_shape"] += 1
            return
        # <name> <criteria> [<displayname>] —— 顯示名稱是可選的第三個 token。
        _, remainder3 = _split_first_token(remainder2)
        _, arg_text = _split_first_token(remainder3)
        if not arg_text.strip():
            return  # 沒有顯示名稱，這條指令沒有文字，不是錯誤。
        yield from _locate_and_yield(text, arg_text, offset, lead, stripped, base_path, anchor, stats)
        return
```

把 Step 6 裡 `tellraw` 分支計算絕對位移那段抽成共用函式：

```python
def _locate_and_yield(
    text: str,
    arg_text: str,
    offset: int,
    lead: int,
    stripped: str,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    if not arg_text.strip():
        stats["skipped_command_unsupported_shape"] += 1
        return
    arg_start_in_stripped = len(stripped) - len(arg_text.lstrip())
    absolute_start = offset + lead + arg_start_in_stripped
    try:
        arg_span = find_balanced_span(text, absolute_start)
    except LocateError:
        stats["skipped_command_unsupported_shape"] += 1
        return
    yield from _yield_component(
        text, arg_span, path=(), base_path=base_path, anchor=anchor, stats=stats
    )
```

（`tellraw` 分支也改成呼叫 `_locate_and_yield`，不要留兩份重複邏輯。）

補測試：

```python
def test_title_subtitle_actionbar_all_work():
    for slot in ("title", "subtitle", "actionbar"):
        stats = Counter()
        nodes = list(
            scan_command_string(
                f'title @a {slot} {{"text":"Hi"}}',
                base_path=_path(),
                anchor=None,
                stats=stats,
            )
        )
        assert len(nodes) == 1, slot


def test_bossbar_name_is_recognised_but_bossbar_value_is_not():
    stats = Counter()
    named = list(
        scan_command_string(
            'bossbar set mymod:bar name {"text":"Boss"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(named) == 1
    stats2 = Counter()
    valued = list(
        scan_command_string(
            "bossbar set mymod:bar value 50", base_path=_path(), anchor=None, stats=stats2
        )
    )
    assert valued == []


def test_scoreboard_objectives_add_with_and_without_displayname():
    stats = Counter()
    with_name = list(
        scan_command_string(
            'scoreboard objectives add kills dummy {"text":"Kills"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(with_name) == 1
    stats2 = Counter()
    without_name = list(
        scan_command_string(
            "scoreboard objectives add kills dummy",
            base_path=_path(),
            anchor=None,
            stats=stats2,
        )
    )
    assert without_name == []
    assert stats2["skipped_command_unsupported_shape"] == 0
```

跑測試確認全部通過。

- [ ] **Step 11: 加 L2 動詞（`data merge`／`data modify ... set value`），巢狀 SNBT**

先寫測試（**這條直接照抄 spec §4 的例子，是最重要的回歸測試**）：

```python
def test_data_merge_finds_each_message_in_a_native_snbt_list():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {front_text:{messages:['
            '{text:"Line 1"},{text:"Line 2"},{text:""},{text:""}]}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 2  # 空字串沒有可翻文字，見 build.py 的 skipped_empty
    texts = {str(n.tag["text"]) for n in nodes}
    assert texts == {"Line 1", "Line 2"}


def test_data_merge_finds_a_json_string_wrapped_message():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert str(nodes[0].tag["text"]) == "Hello"


def test_data_modify_set_value_is_recognised():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data modify block ~ ~ ~ front_text.messages[0] merge value {text:"Hi"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
```

實作（放在 L1 動詞分支之後）：

```python
    if verb == "data":
        yield from _scan_data_command(text, rest, offset, lead, stripped, base_path, anchor, stats)
        return
```

```python
def _scan_data_command(
    text: str,
    rest: str,
    offset: int,
    lead: int,
    stripped: str,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    sub, remainder = _split_first_token(rest)
    if sub == "merge":
        # data merge block|entity|storage <target...> <nbt>
        _, after_kind = _split_first_token(remainder)
        arg_text = _skip_to_nbt_argument(after_kind)
    elif sub == "modify":
        idx = find_unquoted_token(text, 0, " merge value ")
        if idx == -1:
            stats["skipped_command_unsupported_shape"] += 1
            return
        arg_start = idx + len(" merge value ")
        yield from _scan_snbt_argument(text, arg_start, base_path, anchor, stats)
        return
    else:
        stats["skipped_command_unsupported_shape"] += 1
        return

    if arg_text is None:
        stats["skipped_command_unsupported_shape"] += 1
        return
    arg_start_in_stripped = len(stripped) - len(arg_text.lstrip())
    absolute_start = offset + lead + arg_start_in_stripped
    yield from _scan_snbt_argument(text, absolute_start, base_path, anchor, stats)


def _skip_to_nbt_argument(remainder: str) -> str | None:
    """`data merge block ~ ~ ~ {...}` 的 `<目標>` 部分長度不固定（座標、UUID、
    路徑都可能），但 NBT 引數永遠是**最後一段、以 `{` 開頭**的東西——直接找
    第一個 `{` 就是引數起點，不用去數前面有幾個 token。"""
    idx = remainder.find("{")
    return remainder[idx:] if idx != -1 else None


def _scan_snbt_argument(
    text: str,
    absolute_start: int,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    try:
        arg_span = find_balanced_span(text, absolute_start)
    except LocateError:
        stats["skipped_command_unsupported_shape"] += 1
        return
    raw = text[arg_span[0] : arg_span[1]]
    try:
        document = codec_for("snbt").decode(raw)
    except Exception:
        stats["skipped_command_unsupported_shape"] += 1
        return
    found_any = False
    for face in ("front_text", "back_text"):
        side = document.get(face) if isinstance(document, amulet_nbt.CompoundTag) else None
        messages = side.get("messages") if isinstance(side, amulet_nbt.CompoundTag) else None
        if not isinstance(messages, amulet_nbt.ListTag):
            continue
        for index, message in enumerate(messages):
            if isinstance(message, amulet_nbt.StringTag) and not str(message):
                continue  # 空字串沒有文字可翻，build.py 的 skipped_empty 職責
                          # 本來就該接手，這裡先不硬擋——但 continue 純粹是效能
                          # 考量，不是正確性要求，留給 build.py 判斷一樣正確。
            try:
                leaf_span = _locate_message_span(text, arg_span, face, index)
            except LocateError:
                continue
            yield from _yield_leaf(text, leaf_span, message, base_path, anchor, stats)
            found_any = True
    if not found_any and isinstance(document, amulet_nbt.CompoundTag):
        # 不是告示牌形狀（例如物品組件的 custom_name）——直接把整段當一個節點。
        yield from _yield_component(
            text, arg_span, path=(), base_path=base_path, anchor=anchor, stats=stats
        )
```

（`_locate_message_span` 是 `locate_path_span(text, arg_span, [face, "messages", index])`
的薄包裝；`_yield_leaf` 跟 `_yield_component` 邏輯一樣但 span 是 `leaf_span` 而不是
`arg_span`——把 `_yield_component` 重構成接受任意 span 即可，兩個呼叫點共用。）

跑測試確認通過。**這一步如果 `test_data_merge_finds_a_json_string_wrapped_message`
沒過，先去檢查 Task 2 的 `_find_key_value`／`_split_top_level` 對「字串常值本身是
一段跳脫過的 JSON」的處理，那是最容易漏的地方。**

- [ ] **Step 12: 加 `give`／`item` 的物品組件（L2 的第三種）**

測試：

```python
def test_give_finds_the_custom_name_component():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'give @s stone[custom_name={"text":"Special Stone"}]',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert str(nodes[0].tag["text"]) == "Special Stone"
```

實作：

```python
    if verb in ("give", "item"):
        idx = text.find("[", offset + lead)
        if idx == -1:
            stats["skipped_command_unsupported_shape"] += 1
            return
        try:
            bracket_span = find_balanced_span(text, idx)
            component_span = locate_path_span(text, bracket_span, ["custom_name"])
        except LocateError:
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _yield_component(
            text, component_span, path=(), base_path=base_path, anchor=anchor, stats=stats
        )
        return
```

（`locate_path_span` 目前只認 `{`/`[` 開頭的 span 走 compound/list 邏輯——`[custom_name={...},lore=[...]]`
這種「方括號包著用等號分隔的鍵值」語法跟 SNBT compound 的 `{key:value}` 語法不同，
`_find_key_value`／`_split_top_level` 目前是用 `:` 當 key/value 分隔——**這一步
需要在 `span_locator.py` 幫 `_find_top_level_colon` 也認 `=`**，或者在這裡自己寫
一個簡化版：物品組件永遠是 `key=value` 用逗號分隔、深度 0，直接複用
`_split_top_level` 切逗號、自己找 `=` 而不是呼叫 `locate_path_span`。選後者比較
不會動到 Task 2 已經測過的行為：

```python
from mcmt.tree.span_locator import _split_top_level  # 內部函式，同一個套件內共用

def _find_component(bracket_span: tuple[int, int], text: str, key: str) -> tuple[int, int] | None:
    start, end = bracket_span
    body = text[start + 1 : end - 1]
    for elem_start, elem_end in _split_top_level(body):
        piece = body[elem_start:elem_end]
        eq = piece.find("=")
        if eq == -1:
            continue
        if piece[:eq].strip() == key:
            value_start = start + 1 + elem_start + eq + 1
            value_end = start + 1 + elem_end
            return (value_start, value_end)
    return None
```

把上面 `give`／`item` 分支的 `locate_path_span(...)` 呼叫換成
`_find_component(bracket_span, text, "custom_name")`。

跑測試確認通過。

- [ ] **Step 13: 跑整個檔案的測試 + 全專案測試**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_command.py -v
.venv/Scripts/python -m pytest -q
```

Expected: 全部 PASS。

- [ ] **Step 14: Commit**

```bash
git add src/mcmt/scan/command.py tests/unit/test_scan_command.py
git commit -m "掃描：指令字串白名單（execute 剝除、say/me、L1/L2、L3 跳過並計數）"
```

---

### Task 6: 掛上 `region.py`／`entities.py` 的 `Command` 欄位

**Files:**
- Modify: `src/mcmt/scan/sources/region.py`
- Modify: `src/mcmt/scan/sources/entities.py`
- Test: `tests/unit/test_scan_region.py`（若有；否則加進既有測 `_scan_block_entity`
  的檔案）

**Interfaces:**
- Consumes: `mcmt.scan.command.scan_command_string`（Task 5）
- Produces: `scan_chunk`／`_scan_block_entity` 現在多接受一個可選的 `stats: Counter | None = None`
  參數（預設 `None` 時內部建一個丟棄用的 `Counter()`，不破壞既有呼叫端），並在
  `Command` 欄位存在時 yield 指令衍生的 `TextNode`。

- [ ] **Step 1: 寫失敗測試**

```python
# 加進 tests/unit/test_scan_region.py（或既有測 _scan_block_entity 的檔案）
from collections import Counter

import amulet_nbt

from mcmt.scan.sources.region import scan_chunk


def _chunk_with_command_block(command: str) -> amulet_nbt.CompoundTag:
    entity = amulet_nbt.CompoundTag(
        {
            "id": amulet_nbt.StringTag("minecraft:command_block"),
            "x": amulet_nbt.IntTag(0),
            "y": amulet_nbt.IntTag(0),
            "z": amulet_nbt.IntTag(0),
            "Command": amulet_nbt.StringTag(command),
        }
    )
    return amulet_nbt.CompoundTag(
        {"block_entities": amulet_nbt.ListTag([entity])}
    )


def test_a_command_block_yields_a_command_text_node():
    stats = Counter()
    nodes = list(scan_chunk(_chunk_with_command_block("say hello"), stats=stats))
    assert any(n.category == "command_say_text" for n in nodes)


def test_scan_chunk_still_works_without_stats_for_backward_compatibility():
    nodes = list(scan_chunk(_chunk_with_command_block("say hi")))
    assert any(n.category == "command_say_text" for n in nodes)
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_region.py -v
```

Expected: `TypeError: scan_chunk() got an unexpected keyword argument 'stats'`。

- [ ] **Step 3: 修改 `region.py`**

```python
from collections import Counter

from mcmt.scan.command import scan_command_string

# scan_chunk 簽名改成：
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

    # ...（既有的 sign / CustomName / Items / Book 邏輯不動）...

    command = entity.get("Command")
    if isinstance(command, amulet_nbt.StringTag):
        yield from scan_command_string(
            str(command),
            base_path=path.child(key_step("Command")),
            anchor=anchor,
            stats=stats,
        )
```

`scan()` 函式（既有，走訪所有 region 檔）在呼叫 `scan_chunk(root)` 的地方改成
`scan_chunk(root, stats)`（`scan()` 本來就有 `stats` 這個參數在作用域裡）。

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_region.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 對 `entities.py` 重複同樣的修改**

`scan_entities_chunk` 與它內部走訪每個 entity 的函式（Step 3 讀過的
`src/mcmt/scan/sources/entities.py:98` 附近）比照辦理：加 `stats` 參數（預設
`None`）、在既有的白名單檢查旁邊加一個 `Command` 欄位檢查（指令方塊礦車
`minecraft:command_block_minecart` 的 `Command` 欄位跟方塊指令方塊同一個
key 名稱）。寫對應的測試（照抄 Step 1 的模式，換成 entity 而不是 block_entity）。

- [ ] **Step 6: 跑全部測試**

```bash
.venv/Scripts/python -m pytest -q
```

Expected: 全部 PASS，既有的 region/entities 測試不受影響。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/scan/sources/region.py src/mcmt/scan/sources/entities.py tests/unit/test_scan_region.py tests/unit/test_scan_entities.py
git commit -m "掃描：region/entities 的 Command 欄位掛上共用的指令字串解析"
```

---

### Task 7: 寫入 —— splice 原語與「由內往外組字」（`write/command_span.py`）

**Files:**
- Create: `src/mcmt/write/command_span.py`
- Test: `tests/unit/test_command_span.py`

**Interfaces:**
- Consumes: `mcmt.model.node.NodePath`（既有的 `span_order`、`decode_step` 存取）、
  `mcmt.write.common.component_for`（既有）
- Produces:
  - `apply_command_edits(original: str, edits: list[dict[str, Any]], *, decode_offset: int, outcome: "ApplyOutcome") -> str | None`
    ——`edits` 是同一個物理字串（同一個 `Command` 欄位，或 `.mcfunction` 同一行）
    收到的所有 edit；`decode_offset` 是 `node_path` 裡「decode 鏈從第幾步開始」
    （前面是 key/index 步驟，走訪到字串節點為止）。回傳新字串；沒有任何一筆
    成功寫入時回傳 `None`（呼叫端不寫回、不算 `files_rewritten`）。

**這個任務直接把 spec §4 的例子當測試**——那是全案最容易寫錯的地方。

- [ ] **Step 1: 寫最簡單情境的失敗測試（單一 edit，L1 直接 JSON）**

```python
# tests/unit/test_command_span.py
from mcmt.model.node import NodePath, decode_step, key_step
from mcmt.write.command_span import apply_command_edits
from mcmt.write.common import ApplyOutcome


def _edit(span, value, unit_id="u:command_component_text:aaaaaaaaaaaaaaaa"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": unit_id,
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": None},
            {"t": "decode", "codec": "json_component", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "text_compound",
        "value": {"kind": "translate", "key": "mcmt.command_component_text.aaaaaaaaaaaaaaaa", "fallback": "Hello", "style": None},
    }


def test_a_single_l1_edit_replaces_just_its_span():
    original = 'tellraw @a {"text":"Hello"}'
    span = (original.index("{"), len(original))
    outcome = ApplyOutcome()

    result = apply_command_edits(
        original, [_edit(span, None)], decode_offset=1, outcome=outcome
    )

    assert result == 'tellraw @a {"translate":"mcmt.command_component_text.aaaaaaaaaaaaaaaa","fallback":"Hello"}'
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_command_span.py -v
```

Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 寫最小實作（先只處理「最內層 decode 是 json_component、直接
  splice」這個最簡單的情況）**

```python
# src/mcmt/write/command_span.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串內部的 splice 原語——字串進、字串出，完全不碰 amulet_nbt Tag。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §4、§5。

**核心規則**：splice 只在最外層發生一次。每筆 edit 的 decode 鏈記著它是從哪個
codec 解出來的；`compose_replacement()` 沿著這條鏈由內往外組字（每多一層
「值是一個字串常值、內容才是這段文字」，就多一次跳脫；每多一層「值本來就是
原生 compound/list」，不需要跳脫，直接換方言序列化），最後只在鏈上**最後一個
decode 步驟**記錄的絕對位移做一次替換。**這個函式完全不理解指令語法本身**
——它只知道「這一段字串換成那一段字串」，安全網（會不會切壞指令）全靠 extract
時 span 定位器抓對範圍。
"""

from typing import Any

from mcmt.model.node import NodePath, span_order
from mcmt.scan.sources.datapack import _to_amulet
from mcmt.tree.codecs import codec_for
from mcmt.write.common import ApplyOutcome, component_for, refuse, refuse_residue


def apply_command_edits(
    original: str,
    edits: list[dict[str, Any]],
    *,
    decode_offset: int,
    outcome: ApplyOutcome,
) -> str | None:
    """`edits` 全部指向同一個物理字串。依 `span_order()` 由後往前 splice，
    回傳新字串；一筆都沒成功時回傳 `None`。"""
    ordered = span_order(
        [NodePath.from_json(edit["node_path"]) for edit in edits]
    )
    by_path = {
        tuple(step.to_json().items() for step in path): edit
        for path, edit in zip(
            (NodePath.from_json(e["node_path"]) for e in edits), edits
        )
    }
    # 上面這行只是為了保留「原始 edit dict」跟排序後的 NodePath 的對應——
    # 更直接的寫法是把 (path, edit) 成對排序，見下方替代實作。
    text = original
    written = 0
    pairs = sorted(
        zip((NodePath.from_json(e["node_path"]) for e in edits), edits),
        key=lambda pair: (
            pair[0].last_span is None,
            -(pair[0].last_span or (0, 0))[0],
        ),
    )
    for path, edit in pairs:
        decode_chain = [step for step in path if step.t == "decode"][decode_offset - 1 :] \
            if decode_offset > 0 else [step for step in path if step.t == "decode"]
        span = path.last_span
        if span is None:
            refuse(outcome, edit, "unsupported_encoding", "指令 edit 缺少 span")
            continue
        replacement = _compose_replacement(edit, decode_chain)
        if replacement is None:
            refuse(outcome, edit, "unsupported_encoding", "無法組出替換文字")
            continue
        text = text[: span[0]] + replacement + text[span[1] :]
        written += 1
    return text if written else None


def _compose_replacement(edit: dict[str, Any], decode_chain: list) -> str | None:
    """由內往外組字。`component_for()` 回傳的是**純 Python dict**（不是
    amulet_nbt tag——見 `write/common.py:416`），`json_component.encode()` 直接
    吃 dict；`snbt.encode()` 要吃 amulet_nbt tag（它呼叫 `value.to_snbt()`），
    所以走 SNBT 方言時要先用 `_to_amulet()`（跟 Task 5 掃描 datapack advancement
    共用同一個轉換函式）轉一次。"""
    value = edit["value"]
    if not decode_chain:
        return None
    codecs = [step.codec.value for step in decode_chain]
    innermost = codecs[-1]

    if innermost == "command":
        # 沒有 JSON/SNBT 包裝——say/me 的參數本來就是純文字，不是 component，
        # 直接替換文字本身，不透過 component_for()。
        if value.get("kind") != "literal":
            return None
        text = value["text"]
        refuse_residue(text)
        return text

    plain = component_for(value)
    if plain is None:
        return None
    if innermost == "json_component":
        serialized = codec_for("json_component").encode(plain)
    elif innermost == "snbt":
        serialized = codec_for("snbt").encode(_to_amulet(plain))
    else:
        return None

    # 由內往外：最內層是 json_component、它的直接外層是 snbt，代表這段 JSON
    # 是被一個 SNBT 字串常值包住（不是原生 SNBT compound），序列化結果要重新
    # 包成一個跳脫過的 SNBT 字串常值才能塞回去。
    if len(codecs) >= 2 and codecs[-1] == "json_component" and codecs[-2] == "snbt":
        serialized = _snbt_string_literal(serialized)
    return serialized


def _snbt_string_literal(text: str) -> str:
    """把 `text` 包成一個 SNBT 雙引號字串常值，內部的 `\\` 與 `"` 都跳脫。
    `[待驗]`：這裡選雙引號＋跳脫，Mojang 自己的序列化器是不是傾向換成單引號
    避免跳脫，等 spec §9.3／Task 13 的進遊戲驗證確認。"""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
```

**這一步的實作先求「測試 1 過」，不用一次做完 §4 的兩層跳脫**——那是 Step 5。
測試 1（`test_a_single_l1_edit_replaces_just_its_span`）的 decode 鏈只有一層
`json_component`（`codecs == ["command", "json_component"]` 其實只有一個
真正的 decode 步驟，因為 Step 1 的 `_edit()` 範例故意省略了外層的 `command`
標記步驟——寫這一步時先讓 `decode_chain` 只含 `json_component` 那一步，
`codecs[-2]` 這個判斷在只有一個元素時天然不成立，不會誤觸發跳脫。

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_command_span.py -v
```

Expected: PASS。如果不過，先檢查 `component_for()` 的實際回傳型別（`write/common.py`
既有函式，回傳的是 `amulet_nbt` Tag 還是已經是字串——照它實際的簽名調整
`_json_text`／`_tag_to_plain`，**不要用讀不到原始碼、只憑名字猜的行為**）。

- [ ] **Step 5: 寫 spec §4 的「跳脫重構」回歸測試（這是全案最重要的一條測試）**

```python
def test_a_string_wrapped_json_leaf_is_re_escaped_correctly():
    """spec §4 的例子：messages 元素是一個 SNBT 字串常值，內容才是 JSON。
    直接在絕對位移上 splice 新的 JSON 文字會切壞指令（外層引號被提前閉合）；
    正確結果必須把新值重新包成一個跳脫過的 SNBT 字串常值。"""
    original = 'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}'
    # 這段文字對應到的 span 與 decode 鏈由 Task 5 的 scan 邏輯算出來，這裡
    # 直接手動構造成 edit 來單獨測 write 端的組字邏輯。
    inner_start = original.index('"{')
    inner_end = original.index('}"') + 2
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:bbbbbbbbbbbbbbbb",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": None},
            {"t": "decode", "codec": "snbt", "arg": None, "span": [24, len(original)]},
            {"t": "decode", "codec": "json_component", "arg": None,
             "span": [inner_start, inner_end]},
        ],
        "expected_encoding": "json_string_object",
        "value": {"kind": "translate", "key": "mcmt.command_component_text.bbbbbbbbbbbbbbbb", "fallback": "Hello", "style": None},
    }
    outcome = ApplyOutcome()

    result = apply_command_edits(original, [edit], decode_offset=1, outcome=outcome)

    # 錯誤做法會產出：...messages:["{"translate":...}"]}——外層引號被提前閉合。
    assert '"{' not in result.replace('\\"{', '')  # 沒有沒跳脫的內層開頭引號
    assert result == (
        'data merge block ~ ~ ~ {messages:['
        '"{\\"translate\\":\\"mcmt.command_component_text.bbbbbbbbbbbbbbbb\\",'
        '\\"fallback\\":\\"Hello\\"}"]}'
    )
```

- [ ] **Step 6: 跑測試，確認這條會紅，並確認紅的原因是「還沒處理跳脫」而不是
  別的錯誤**

```bash
.venv/Scripts/python -m pytest tests/unit/test_command_span.py -v
```

Step 3 寫的 `_compose_replacement` 已經包含跳脫邏輯（`codecs[-2] == "snbt"` 那個
判斷），理論上這條測試不用再改實作就會過。如果沒過，照這條測試的失敗訊息回頭
檢查：是 `codecs` 列表的內容跟 `decode_chain` 的實際 `PathStep` 對不上（例如
`decode_step()` 的 `codec` 參數傳的是字串還是 `Codec` enum，`step.codec.value`
拿不到預期字串），還是 `_snbt_string_literal` 的跳脫規則跟測試斷言的期待字串
沒對齊——**不要在這裡引入第二套跳脫邏輯**，Step 3 那份就是最終版本。

- [ ] **Step 7: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_command_span.py -v
```

Expected: 全部 PASS。

- [ ] **Step 8: 寫 spec §5 的「同字串多處編輯」回歸測試**

```python
def test_two_edits_in_the_same_snbt_argument_do_not_collide():
    original = (
        'data merge block ~ ~ ~ {front_text:{messages:'
        '[{text:"Line 1"},{text:"Line 2"}]}}'
    )
    line1_start = original.index('{text:"Line 1"}')
    line1_end = line1_start + len('{text:"Line 1"}')
    line2_start = original.index('{text:"Line 2"}')
    line2_end = line2_start + len('{text:"Line 2"}')

    def edit(span, key_suffix, fallback):
        return {
            "occurrence_id": f"o:{key_suffix}",
            "unit_id": f"u:command_component_text:{key_suffix}",
            "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
            "node_path": [
                {"t": "key", "name": "Command"},
                {"t": "decode", "codec": "command", "arg": None, "span": None},
                {"t": "decode", "codec": "snbt", "arg": None, "span": list(span)},
            ],
            "expected_encoding": "compound_tree",
            "value": {"kind": "translate", "key": f"mcmt.command_component_text.{key_suffix}", "fallback": fallback, "style": None},
        }

    edits = [
        edit((line1_start, line1_end), "1111111111111111", "Line 1"),
        edit((line2_start, line2_end), "2222222222222222", "Line 2"),
    ]
    outcome = ApplyOutcome()

    result = apply_command_edits(original, edits, decode_offset=1, outcome=outcome)

    assert '{translate:"mcmt.command_component_text.1111111111111111",fallback:"Line 1"}' in result
    assert '{translate:"mcmt.command_component_text.2222222222222222",fallback:"Line 2"}' in result
    # 兩段都在，而且中間的逗號、外層的 front_text/messages 結構完全沒被動過。
    assert result.startswith("data merge block ~ ~ ~ {front_text:{messages:[")
    assert result.endswith("]}}")
```

跑測試，若失敗多半是 `_compose_replacement` 對「原生 SNBT compound（不是字串
包 JSON）」那一支的序列化語法錯了（SNBT 的 key 不加引號）——檢查 `_snbt_text`
是不是真的呼叫了 `tag.to_snbt()` 而不是誤用 `_json_text`。

- [ ] **Step 9: Commit**

```bash
git add src/mcmt/write/command_span.py tests/unit/test_command_span.py
git commit -m "write/command_span：由內往外組字、由後往前 splice（獨立 commit，write/ 目錄規範要求）

理由：這是指令文字方案 1 的核心寫入原語，把早就寫好但從沒被呼叫過的
span_order() 第一次接上實際的字串拼裝。單獨成一個 commit 是因為
write/ 目錄的任何修改都必須獨立說明理由（CLAUDE.md 硬性禁令）。"
```

---

### Task 8: `write/common.py` 的分派點

**Files:**
- Modify: `src/mcmt/write/common.py`
- Test: `tests/unit/test_write_common.py`

**Interfaces:**
- Consumes: `mcmt.write.command_span.apply_command_edits`（Task 7）
- Produces: `apply_edit_to_compound`／`apply_edits` 現在認得「最後一步是
  `decode`」的 `node_path`，不再無條件 `refuse(..., "unsupported_encoding", ...)`。

- [ ] **Step 1: 寫失敗測試**

```python
# 加進 tests/unit/test_write_common.py
import amulet_nbt

from mcmt.write.common import ApplyOutcome, apply_edits


def test_a_decode_terminated_edit_is_applied_via_command_span():
    root = amulet_nbt.CompoundTag(
        {
            "block_entities": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {"Command": amulet_nbt.StringTag('tellraw @a {"text":"Hello"}')}
                    )
                ]
            )
        }
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:aaaaaaaaaaaaaaaa",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca"},
        "node_path": [
            {"t": "key", "name": "block_entities"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "Command"},
            {"t": "decode", "codec": "command", "arg": None, "span": None},
            {"t": "decode", "codec": "json_component", "arg": None, "span": [12, 27]},
        ],
        "expected_encoding": "text_compound",
        "value": {"kind": "translate", "key": "mcmt.command_component_text.aaaaaaaaaaaaaaaa", "fallback": "Hello", "style": None},
    }
    outcome = ApplyOutcome()

    written = apply_edits(root, [edit], outcome)

    assert written == 1
    new_command = str(
        root["block_entities"][0]["Command"]
    )
    assert new_command == 'tellraw @a {"translate":"mcmt.command_component_text.aaaaaaaaaaaaaaaa","fallback":"Hello"}'
```

（span `[12, 27]` 要對得上 `'tellraw @a {"text":"Hello"}'` 裡 `{"text":"Hello"}`
的實際位置——寫測試時先用 Python 互動模式或 `text.index("{")` 算一次，不要
憑感覺填數字。）

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_write_common.py -v
```

Expected: FAIL——目前 `apply_edits`／`apply_edit_to_compound` 對最後一步是
`decode` 的 `node_path` 一律 `refuse(..., "unsupported_encoding", "v1 的寫入路徑不支援 decode 步驟")`。

- [ ] **Step 3: 加分派邏輯**

在 `apply_edits()` 裡，把

```python
        if steps[-1].t != "index":
            refuse(outcome, edit, "unsupported_encoding", "v1 的寫入路徑不支援 decode 步驟")
            continue
        index_groups[NodePath(steps[:-1])].append(edit)
```

前面（`if steps[-1].t == "key":` 之後、`if steps[-1].t != "index":` 之前）插入：

```python
        if steps[-1].t == "decode":
            # 找到最後一個非 decode 步驟，那就是這個字串節點的位址；同一個
            # 字串節點收到的所有 decode 結尾 edits 分成一組，理由跟同一個
            # native list 收到多筆 edit 要批次處理一樣（見本函式上面的說明）。
            string_node_steps = [s for s in steps if s.t != "decode"]
            decode_groups[NodePath(string_node_steps)].append(edit)
            continue
```

在函式最上面加 `decode_groups: dict[NodePath, list[dict]] = defaultdict(list)`
（跟既有的 `index_groups` 並列），並在函式尾端、`return written` 之前加：

```python
    for parent, group in decode_groups.items():
        written += _apply_decode_group(root, parent, group, outcome)
```

新增 `_apply_decode_group`：

```python
def _apply_decode_group(
    root: amulet_nbt.CompoundTag,
    parent: NodePath,
    edits: list[dict[str, Any]],
    outcome: ApplyOutcome,
) -> int:
    from mcmt.write.command_span import apply_command_edits

    parent_steps = list(parent)
    if not parent_steps or parent_steps[-1].t != "key":
        for edit in edits:
            refuse(outcome, edit, "unsupported_encoding", "指令文字目前只支援 key 結尾的父節點")
        return 0
    try:
        container = _resolve(root, parent_steps[:-1])
    except (KeyError, IndexError) as exc:
        for edit in edits:
            refuse(outcome, edit, "node_missing", str(exc))
        return 0
    key = parent_steps[-1].name
    tag = container.get(key) if hasattr(container, "get") else None
    if not isinstance(tag, amulet_nbt.StringTag):
        for edit in edits:
            refuse(outcome, edit, "node_changed", f"{key} 不是字串節點，可能被改過了")
        return 0

    new_text = apply_command_edits(
        str(tag), edits, decode_offset=1, outcome=outcome
    )
    if new_text is None:
        return 0
    container[key] = amulet_nbt.StringTag(new_text)
    return sum(
        1 for edit in edits if edit not in outcome.unwritten
    )  # 粗略計數；精確寫法見 Step 4 的修正
```

**Step 4 會修正上面「粗略計數」那行**——先跑測試看看行不行。

- [ ] **Step 4: 跑測試，修正回傳值計數方式**

```bash
.venv/Scripts/python -m pytest tests/unit/test_write_common.py -v
```

`outcome.unwritten` 裡存的是 dict（`refuse()` 加進去的），`edit not in outcome.unwritten`
這種比較不可靠（dict 相等比較、且同一個 edit 可能沒被 refuse 但也没被算對）。改成
讓 `apply_command_edits` 回傳「實際寫入了幾筆」而不是只回傳字串：

修改 `write/command_span.py::apply_command_edits` 的回傳型別成
`tuple[str, int] | None`（字串, 寫入筆數）：

```python
def apply_command_edits(
    original: str, edits: list[dict[str, Any]], *, decode_offset: int, outcome: ApplyOutcome
) -> tuple[str, int] | None:
    ...
    return (text, written) if written else None
```

`_apply_decode_group` 對應改成：

```python
    result = apply_command_edits(str(tag), edits, decode_offset=1, outcome=outcome)
    if result is None:
        return 0
    new_text, written = result
    container[key] = amulet_nbt.StringTag(new_text)
    return written
```

同時修正 Task 7 test_command_span.py 裡所有斷言 `result == "..."` 的地方，改成
`result[0] == "..."`（或解構 `new_text, written = result`）——**這是型別簽名變更，
回去改 Task 7 的測試，不要留著兩份對不上的期待**。

- [ ] **Step 5: 跑全部測試**

```bash
.venv/Scripts/python -m pytest -q
```

Expected: 全部 PASS。

- [ ] **Step 6: Commit（獨立 commit，write/ 目錄規範）**

```bash
git add src/mcmt/write/common.py src/mcmt/write/command_span.py tests/unit/test_write_common.py tests/unit/test_command_span.py
git commit -m "write/common：接上 decode 結尾的 node_path，分派給 command_span

理由：write/ 目錄修改需要獨立 commit。apply_edit_to_compound 走到字串節點
一樣停下——這裡只多一個分派點，決定「整值替換」還是「委派給 command_span
做字串內部的 splice」，NBT 走訪邏輯本身沒有變胖。"
```

---

### Task 9: 掃描 —— `.mcfunction`（讀取、CRLF 保留、延續偵測）

**Files:**
- Create: `src/mcmt/scan/sources/mcfunction.py`
- Test: `tests/unit/test_scan_mcfunction.py`

**Interfaces:**
- Consumes: `mcmt.scan.command.scan_command_string`（Task 5）
- Produces: `scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]`
  （跟其他來源同一種簽名，`scan/registry.py` 會掛上它）。container.kind 為
  `"datapack_mcfunction_file"`，anchor 用既有的 `file` kind，`path` 帶
  `"datapacks/<pack>/data/<ns>/function/<name>.mcfunction:<line 1-based>"`
  這種「檔案路徑:行號」格式（不改 anchor schema，塞進既有的 `path` 字串裡，
  比新增一個 `line` 欄位省一次合約異動）。

- [ ] **Step 1: 寫「找檔案、切行、保留換行符」的失敗測試**

```python
# tests/unit/test_scan_mcfunction.py
from collections import Counter

from mcmt.scan.sources.mcfunction import scan


def test_a_folder_datapack_mcfunction_is_scanned(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_bytes(b"say hello\r\ntellraw @a {\"text\":\"Hi\"}\r\n")

    stats = Counter()
    nodes = list(scan(world, stats))

    categories = {n.node.category for n in nodes}
    assert categories == {"command_say_text", "command_component_text"}
    assert all(n.container["kind"] == "datapack_mcfunction_file" for n in nodes)


def test_crlf_is_preserved_byte_for_byte_when_untouched(project, tmp_path):
    # 這條先驗掃描不會意外改到磁碟上的東西（掃描本來就唯讀）；CRLF 保留的
    # 真正回歸測試在 Task 10 的寫入器那邊。
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    original = b"say hello\r\nsay world\r\n"
    func.write_bytes(original)

    list(scan(world, Counter()))

    assert func.read_bytes() == original
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_mcfunction.py -v
```

Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 寫實作**

```python
# src/mcmt/scan/sources/mcfunction.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack `.mcfunction` 裡的可翻文字。

物理字串單位是**一行**，不是整個檔案（見
docs/superpowers/specs/2026-09-05-command-text-design.md §6）。換行符全程當
不透明資料——只切 `\\n`，每行連同它自己的結尾（`"\\r\\n"`／`"\\n"`／空字串）一起
記下來，span 定位、白名單比對只作用在去掉結尾的那段文字上，重組時原封貼回去。

1.20.2+ 的行尾反斜線延續語法目前**明確不支援**——涉及延續的邏輯指令整批跳過，
計入 `stats.skipped_command_line_continuation`（spec §1／§6）。
"""

import zipfile
from collections import Counter
from typing import Any, Iterator

from mcmt.model.node import NodePath, key_step
from mcmt.safety.paths import ReadOnlyPath
from mcmt.scan.command import scan_command_string
from mcmt.scan.node import ScannedNode, TextNode

__all__ = ["scan", "split_lines"]

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
    for path in pack_dir.glob("data/*/function/**/*.mcfunction"):
        relative = path.relative_to(world).replace("\\", "/")
        try:
            data = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            stats["skipped_command_unsupported_shape"] += 1
            continue
        yield from _scan_lines(data, relative, stats)


def _scan_zip_pack(world, zip_path: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    zip_relative = zip_path.relative_to(world).replace("\\", "/")
    try:
        with zipfile.ZipFile(str(zip_path)) as archive:
            names = [
                n for n in archive.namelist()
                if n.endswith(".mcfunction") and _is_function_entry(n)
            ]
            for name in sorted(names):
                try:
                    data = archive.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    stats["skipped_command_unsupported_shape"] += 1
                    continue
                yield from _scan_lines(data, f"{zip_relative}/{name}", stats)
    except (zipfile.BadZipFile, OSError):
        stats["skipped_datapack_zip"] += 1


def _is_function_entry(name: str) -> bool:
    parts = name.split("/")
    return len(parts) >= 4 and parts[0] == "data" and parts[2] == "function"


def split_lines(text: str) -> list[tuple[str, str]]:
    """只切 `\\n`，回傳 `(command_text, terminator)` 對——`terminator` 是
    `"\\r\\n"`、`"\\n"`，或最後一行沒有結尾換行時的空字串。**不用
    `str.splitlines()`**：那個函式連 `\\v`／`\\f`／`\\u2028` 都當換行界線，
    而且會把換行符吃掉，重組時會把 CRLF 檔案整份改成 LF。"""
    lines: list[tuple[str, str]] = []
    start = 0
    n = len(text)
    while start <= n:
        idx = text.find("\n", start)
        if idx == -1:
            if start < n:
                lines.append((text[start:], ""))
            break
        if idx > start and text[idx - 1] == "\r":
            lines.append((text[start : idx - 1], "\r\n"))
        else:
            lines.append((text[start:idx], "\n"))
        start = idx + 1
    return lines


def _scan_lines(text: str, relative: str, stats: Counter) -> Iterator[ScannedNode]:
    lines = split_lines(text)
    continuation_indexes = {
        i for i, (command, _) in enumerate(lines) if command.endswith("\\")
    }
    # 一個延續行的「下一行」也算在同一條邏輯指令裡，整批跳過。
    skip_indexes: set[int] = set()
    for i in continuation_indexes:
        skip_indexes.add(i)
        skip_indexes.add(i + 1)

    for index, (command, _terminator) in enumerate(lines):
        stripped = command.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if index in skip_indexes:
            stats["skipped_command_line_continuation"] += 1
            continue
        container = _container(relative, index)
        base_path = NodePath([key_step(f"{relative}:{index}")])
        for node in scan_command_string(
            command, base_path=base_path, anchor=_ANCHOR, stats=stats
        ):
            yield ScannedNode(node=node, container=container)


def _container(relative: str, line_index: int) -> dict[str, Any]:
    return {
        "kind": "datapack_mcfunction_file",
        "path": f"{relative}:{line_index + 1}",
        "dimension": None,
        "chunk": None,
        "data_version": None,
        "compression": None,
        "external": False,
    }
```

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_scan_mcfunction.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 補行尾延續的測試**

```python
def test_a_line_ending_in_backslash_is_skipped_with_its_continuation(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_bytes(
        b"say normal line\n"
        b"tellraw @a \\\n"
        b'{"text":"continued"}\n'
    )

    stats = Counter()
    nodes = list(scan(world, stats))

    assert len(nodes) == 1  # 只有 "say normal line" 被抽到
    assert nodes[0].node.category == "command_say_text"
    assert stats["skipped_command_line_continuation"] == 2  # 延續行本身 + 它的下一行
```

跑測試確認通過。

- [ ] **Step 6: `container.path` 的相對路徑要用 `/` 不用 `\`（跟既有來源的
  正規化規則一致）**

補測試：

```python
def test_container_path_uses_forward_slashes_even_on_windows(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_text("say hi\n", encoding="utf-8")

    nodes = list(scan(world, Counter()))

    assert "/" in nodes[0].container["path"]
    assert "\\" not in nodes[0].container["path"]
```

如果 `relative_to(world)` 回傳的是 `Path`（含 `\\`），在 `_scan_folder_pack`
把 `.replace("\\", "/")` 加在 `str(path.relative_to(world))` 上——照抄
`scan/sources/datapack.py::_container` 既有的正規化寫法。

跑測試確認通過。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/scan/sources/mcfunction.py tests/unit/test_scan_mcfunction.py
git commit -m "掃描：.mcfunction 資料夾/zip，逐行處理、CRLF 全程原始保留、行尾延續跳過並計數"
```

---

### Task 10: 寫入 —— `.mcfunction`（`write/mcfunction_apply.py`）

**Files:**
- Create: `src/mcmt/write/mcfunction_apply.py`
- Test: `tests/unit/test_write_mcfunction_apply.py`

**Interfaces:**
- Consumes: `mcmt.write.command_span.apply_command_edits`（Task 7）、
  `mcmt.scan.sources.mcfunction.split_lines`（Task 9，重組時共用同一份切行邏輯）
- Produces: `apply_to_mcfunction_file(world: Path, relative: str, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet) -> None`
  ——簽名比照 `write/datapack_apply.py::apply_to_datapack_file`，`apply.py`
  的 `_WRITERS` 表會掛上它（Task 11）。

- [ ] **Step 1: 寫失敗測試（CRLF 保留是這個檔案最重要的一條）**

```python
# tests/unit/test_write_mcfunction_apply.py
from pathlib import Path

from mcmt.safety.backup import BackupSet
from mcmt.write.common import ApplyOutcome
from mcmt.write.mcfunction_apply import apply_to_mcfunction_file


def _edit(relative: str, line: int, span: tuple[int, int], fallback: str, key_suffix: str):
    return {
        "occurrence_id": f"o:{key_suffix}",
        "unit_id": f"u:command_say_text:{key_suffix}",
        "container": {
            "kind": "datapack_mcfunction_file",
            "path": f"{relative}:{line}",
            "dimension": None,
            "chunk": None,
            "data_version": None,
            "compression": None,
            "external": False,
        },
        "node_path": [
            {"t": "key", "name": f"__line_{line}__"},
            {"t": "decode", "codec": "command", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": fallback, "style": None},
    }


def test_crlf_line_endings_survive_untouched_apply(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"say hello\r\nsay world\r\n"
    path.write_bytes(original)

    edit = _edit(f"{relative}:1", 1, (4, 9), "你好", "1111111111111111")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, f"{relative}:1", [edit], outcome, backup)

    data = path.read_bytes()
    assert data.endswith(b"\r\n")
    assert b"\r\n\r\n" not in data  # 沒有多插入或少插入任何一個換行符
    assert data.count(b"\r\n") == 2
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
.venv/Scripts/python -m pytest tests/unit/test_write_mcfunction_apply.py -v
```

Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 寫實作**

```python
# src/mcmt/write/mcfunction_apply.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""`.mcfunction` 的寫入器。**高風險目錄。**

架構抄 `write/datapack_apply.py`：資料夾直接覆寫（暫存 → 回讀驗證 → 原子替換）、
zip 整份重建。差別是這裡的「文件」是純文字、逐行處理，不是 JSON 樹——見
docs/superpowers/specs/2026-09-05-command-text-design.md §6。

**全程當 bytes／不透明換行符**：讀寫都不經過 Python 的文字模式 `open()`，
換行符只被 `scan/sources/mcfunction.py::split_lines()` 認出、存起來、原封貼
回去，從未被任何字串運算正規化過。
"""

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from mcmt.errors import DatapackWriteVerificationError
from mcmt.model.node import NodePath
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.scan.sources.mcfunction import split_lines
from mcmt.write.command_span import apply_command_edits
from mcmt.write.common import ApplyOutcome, refuse

__all__ = ["apply_to_mcfunction_file"]


def apply_to_mcfunction_file(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    """`relative` 是 `apply_editplan` 的 `by_file` 分組鍵，形如
    `datapacks/p/data/n/function/hello.mcfunction:<行號 1-based>`——同一個檔案
    不同行落進不同分組，跟 `datapack_apply.py` 的 zip 條目分組是同一個道理。"""
    file_relative, _, line_part = relative.rpartition(":")
    if not file_relative:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"無法解析 container.path：{relative}")
        return
    zip_path, entry = _split_zip(world, file_relative)
    if zip_path is not None:
        _apply_to_zip_line(world, zip_path, entry, int(line_part), edits, outcome, backup)
        return
    _apply_to_folder_line(world, file_relative, int(line_part), edits, outcome, backup)


def _apply_to_folder_line(
    world: Path, relative: str, line_number: int, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet
) -> None:
    path = world / relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return
    try:
        text = ensure_readable(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    lines = split_lines(text)
    index = line_number - 1
    if index < 0 or index >= len(lines):
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"第 {line_number} 行不存在")
        return

    command, terminator = lines[index]
    result = apply_command_edits(command, edits, decode_offset=0, outcome=outcome)
    if result is None:
        return
    new_command, written = result
    lines[index] = (new_command, terminator)

    new_text = "".join(command + terminator for command, terminator in lines)
    outcome.counts["edits_written"] += written
    backup.protect(path)
    ensure_writable(path).write_bytes(new_text.encode("utf-8"))
    outcome.counts["files_rewritten"] += 1


def _apply_to_zip_line(
    world: Path, zip_relative: str, entry_name: str, line_number: int, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet
) -> None:
    path = world / zip_relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {zip_relative}")
        return
    try:
        with zipfile.ZipFile(str(ensure_readable(path))) as archive:
            entries = {i.filename: (i, archive.read(i.filename)) for i in archive.infolist()}
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
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    lines = split_lines(text)
    index = line_number - 1
    if index < 0 or index >= len(lines):
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"第 {line_number} 行不存在")
        return
    command, terminator = lines[index]
    result = apply_command_edits(command, edits, decode_offset=0, outcome=outcome)
    if result is None:
        return
    new_command, written = result
    lines[index] = (new_command, terminator)
    new_text = "".join(command + terminator for command, terminator in lines)

    entries[entry_name] = (info, new_text.encode("utf-8"))
    outcome.counts["edits_written"] += written
    backup.protect(path)
    _rewrite_zip(ensure_writable(path), entries, verify_entry=entry_name)
    outcome.counts["files_rewritten"] += 1


def _rewrite_zip(path: Path, entries: dict[str, tuple], *, verify_entry: str) -> None:
    """整份重建：暫存 → 回讀驗證（CRC + UTF-8 可解碼）→ 原子替換。"""
    temporary = ensure_writable(path.with_name(path.name + ".mcmt-tmp"))
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, (info, data) in sorted(entries.items()):
                archive.writestr(info, data)
        with zipfile.ZipFile(str(ensure_readable(temporary))) as archive:
            broken = archive.testzip()
            if broken is not None:
                raise DatapackWriteVerificationError(
                    f"重建出來的 zip 有條目 CRC 對不上（{broken}），已中止：{path}"
                )
            archive.read(verify_entry).decode("utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _split_zip(world: Path, relative: str) -> tuple[str | None, str | None]:
    parts = relative.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.endswith(".zip"):
            return "/".join(parts[: index + 1]), "/".join(parts[index + 1 :])
    return None, None
```

- [ ] **Step 4: 跑測試確認通過**

```bash
.venv/Scripts/python -m pytest tests/unit/test_write_mcfunction_apply.py -v
```

Expected: PASS。如果不過，先檢查 `apply_command_edits` 的 `decode_offset`
語意跟 `_compose_replacement` 對 `decode_chain` 起點的假設是不是對得上——
`.mcfunction` 的 `node_path` 沒有 key/index 前綴（整條就是 decode 開始），
`decode_offset=0` 要讓 `apply_command_edits` 從第 0 個 decode 步驟開始算，
跟 Task 7／8 裡指令方塊用 `decode_offset=1`（前面多一個 key 步驟落在 Command
欄位上）不一樣——**這個差異要在 `apply_command_edits` 的 docstring 跟型別
簽名裡講清楚，不要留一個「不知道為什麼是 1 還是 0」的魔術數字**。

- [ ] **Step 5: 補一個「同一行兩個 edit」與「找不到指定行」的測試**

```python
def test_two_edits_on_the_same_line_do_not_collide(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'tellraw @a [{"text":"A"},{"text":"B"}]\n', encoding="utf-8"
    )
    # 這裡只驗證兩筆 edit 落在同一行時不會互相踩到彼此的 span——
    # 實際的 tellraw 陣列參數解析交給 Task 5 的白名單決定要不要支援，
    # 這裡直接手動構造 span 驗證 write 層的分組行為。
    ...


def test_a_missing_line_is_refused_without_crashing(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("say only one line\n", encoding="utf-8")
    edit = _edit(f"{relative}:5", 5, (0, 3), "x", "3333333333333333")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, f"{relative}:5", [edit], outcome, backup)

    assert outcome.unwritten[0]["reason"] == "node_missing"
```

（第一條 `test_two_edits_on_the_same_line_do_not_collide` 的斷言部分請執行任務時
照 Task 7 Step 8 的模式具體寫出來——用兩個不重疊的絕對 span，斷言兩段都正確
出現且沒有互相污染；這裡不重複貼一次相同的斷言寫法。）

跑測試確認通過。

- [ ] **Step 6: Commit（獨立 commit，write/ 目錄規範）**

```bash
git add src/mcmt/write/mcfunction_apply.py tests/unit/test_write_mcfunction_apply.py
git commit -m "write/mcfunction_apply：.mcfunction 逐行寫回，CRLF 全程位元組保留

理由：write/ 目錄修改需要獨立 commit。"
```

---

### Task 11: 掛上 `_WRITERS`、`scan/registry.py`，端到端測試擴充

**Files:**
- Modify: `src/mcmt/write/apply.py`
- Modify: `src/mcmt/scan/registry.py`
- Modify: `tests/integration/test_end_to_end.py`

**Interfaces:**
- Consumes: 所有前面的任務
- Produces: 完整的 import → extract → 翻譯 → apply 對五種新 dispatch 組合都跑得通。

- [ ] **Step 1: 掛上 `_WRITERS`**

```python
# src/mcmt/write/apply.py
from mcmt.write.mcfunction_apply import apply_to_mcfunction_file

_WRITERS = {
    "region_chunk": _apply_to_region,
    "entities_chunk": _apply_to_region,
    "level_dat": apply_to_datfile,
    "scoreboard_dat": apply_to_datfile,
    "datapack_file": apply_to_datapack_file,
    "datapack_mcfunction_file": apply_to_mcfunction_file,
}
```

- [ ] **Step 2: 掛上 `scan/registry.py`**

```bash
cat src/mcmt/scan/registry.py
```

先看它目前怎麼登記 `datapack.py` 的 `scan()`，照同一個模式加
`from mcmt.scan.sources.mcfunction import scan as scan_mcfunction`，加進
`SOURCES` 那個集合／列表裡。

- [ ] **Step 3: 跑一次全部測試（含 contracts 驗證）**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python tools/validate_contracts.py
```

Expected: 全部 PASS。

- [ ] **Step 4: 擴充端到端測試——五種新 dispatch 組合**

打開 `tests/integration/test_end_to_end.py`，看它現有的 fixture 世界怎麼建的
（30-chunk 探測世界切片），照同一個模式：

1. 在 fixture 世界的一個 chunk 裡加一個帶 `say` 的指令方塊、一個帶 `tellraw`
   JSON 的指令方塊。
2. 在 fixture 的 sandbox 世界旁邊加一個 `datapacks/p/data/n/function/hello.mcfunction`，
   內容含一個 `say`、一個 `data merge` 兩行 messages。
3. 走完整 `mcmt sandbox import` → `mcmt extract` → 把 `target` 填上 → `mcmt apply`
   （或直接呼叫對應的 Python 函式，照現有測試的做法）。
4. 斷言：`apply_report.json` 的 `counts.edits_written` 涵蓋這些新節點、`unwritten`
   是空的、`stats` 裡的新欄位（`skipped_command_unsupported_shape` 等）數字合理。

補一條「五種組合都真的被涵蓋到」的斷言測試，照抄既有
`test_the_round_trip_actually_exercises_all_four_dispatch_combinations` 的寫法，
把新的五種組合（見 spec §9.1 的表）加進去比對。

- [ ] **Step 5: 跑端到端測試**

```bash
.venv/Scripts/python -m pytest tests/integration/test_end_to_end.py -v
```

Expected: 全部 PASS。**這一步最容易抓到前面任務裡型別/簽名對不上的地方**
（M13a 的教訓：端到端測試是唯一擋得住「舊不變式在新範圍下靜默失效」的防線）。

- [ ] **Step 6: 跑全專案測試**

```bash
.venv/Scripts/python -m pytest -q
```

Expected: 全部 PASS，數字跟改動前的 786 passed 相比只多不少。

- [ ] **Step 7: Commit**

```bash
git add src/mcmt/write/apply.py src/mcmt/scan/registry.py tests/integration/test_end_to_end.py
git commit -m "掛上 mcfunction 寫入器與掃描來源，端到端測試涵蓋五種新 dispatch 組合"
```

---

### Task 12: 真實地圖驗證與文件回寫

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `SPIKE_RESULT.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: 全部前面的任務（此任務不寫新程式碼，是驗證與記錄）

- [ ] **Step 1: 對 MP2（或語料裡指令方塊/`.mcfunction` 最多的地圖）跑 doctor**

```bash
.venv/Scripts/python -X utf8 -m mcmt.cli doctor "<MP2 sandbox 路徑>"
```

記錄輸出（doctor 現在應該能算出指令方塊與 `.mcfunction` 的數量，如果它目前
沒有算，這是本任務**不**要做的事——doctor 的健檢範圍擴充不在這次計畫內，
只要它不會因為新分類而報錯就好）。

- [ ] **Step 2: 跑 extract，記錄真實數字**

```bash
.venv/Scripts/python -X utf8 -m mcmt.cli extract "<MP2 sandbox 路徑>" --lang zh_tw
```

記錄：新分類 `command_say_text`／`command_component_text` 的翻譯單位數、
`stats.skipped_command_unsupported_shape`、
`stats.skipped_command_nested_reference`（L3 實際佔比——決定要不要做方案 2 的
關鍵數字）、`stats.skipped_command_line_continuation`。

- [ ] **Step 3: no-op 譯文驗證（`target = source`）+ `--dry-run` 確認 editplan 正確**

比照 `SPIKE_RESULT.md`「M13a/M13b 之後 MP2 全掃」那節的程序：把每筆 `target` 填成
`source`，跑 `mcmt apply --dry-run`，確認 `editplan.json` 產出合理、沒有大量
`unwritten`。

- [ ] **Step 4: 真的 apply（非 dry-run），從備份還原**

比照既有程序：apply → 確認 `unwritten` 是 0 或數字合理且都有清楚理由 → 從
`sandbox/.mcmt-backups/` 還原 → `doctor` 覆核數字與寫入前一致。

- [ ] **Step 5: 把結果寫回 `SPIKE_RESULT.md`**

新增一節「指令文字方案 1 MP2 全掃 `[實測 <日期>]`」，格式比照既有「M13a/M13b
之後 MP2 全掃」那節：doctor 數字、extract 數字（含三個新 stats 的真實計數）、
apply 數字、結論（L3 與行尾延續佔比是否值得做方案 2/未來支援）。

- [ ] **Step 6: 更新 `docs/STATUS.md`**

比照既有的里程碑記錄格式，加一段說明這次做了什麼、SCHEMA_VERSION 6→7、真實
數字、還留著什麼給未來（方案 2、`.mcfunction` 行尾延續、白名單以外動詞）。

- [ ] **Step 7: 更新 `CLAUDE.md`**

`tree/codecs/command.py` 的說明從「尚未實作，明確拒絕」改成指向這次的實作與
spec 文件；「還沒掃的（M13b 掃描廣度）」那個清單裡刪掉「指令方塊的 `Command`、
datapack 的 `.mcfunction`」兩項（已經做了）。

- [ ] **Step 8: Commit**

```bash
git add docs/STATUS.md SPIKE_RESULT.md CLAUDE.md
git commit -m "文件：指令文字方案 1 真實地圖驗證數字寫回 SPIKE_RESULT/STATUS/CLAUDE"
```

---

### Task 13: 進遊戲驗證清單（手動）

這個任務不是程式碼，是照專案既有的 checklist 慣例（`docs/m0-checklist.md`／
`docs/m4-checklist.md`）走一次進遊戲驗證，因為 spec §4 裡標了 `[待驗]` 的
SNBT 跳脫方式必須在這一步才能升級證據等級。

**Files:**
- Create: `docs/m-command-checklist.md`（可重跑程序，比照既有兩份 checklist 的格式）
- Modify: `SPIKE_RESULT.md`

- [ ] **Step 1: 寫可重跑程序到 `docs/m-command-checklist.md`**

至少包含：怎麼在探測世界（`TT_WORLD_NAME_PROBE`）放一個指令方塊、怎麼跑
extract/apply、要在遊戲裡確認的四件事（照抄 spec §9.3 那四點）。

- [ ] **Step 2: 實際進遊戲驗證這四件事**

1. 塞進 `tellraw` 的 `{"translate":key}` 正確顯示。
2. 塞進 `data merge` 寫的告示牌 `{"translate":key}` 正確顯示。
3. `say`/`me` 的 in_place 文字替換正確顯示。
4. SNBT 字串常值的跳脫方式（雙引號＋反斜線）被遊戲正確解析，沒有顯示成
   字面的跳脫符號或指令報錯。

- [ ] **Step 3: 把結果寫回 `SPIKE_RESULT.md`**

新增「指令文字 M-command 遊戲實測」一節，四項結果各自標
`[遊戲實測]`（成立）或記錄實際發生的偏差並說明對策——**如果第 4 點的雙引號
跳脫方式被遊戲拒絕，回頭修 `write/command_span.py::_snbt_string_literal`
改用單引號，這是本計畫唯一一個「進遊戲才能定案」的實作細節，不要在這之前
假裝它已經定案。**

- [ ] **Step 4: Commit**

```bash
git add docs/m-command-checklist.md SPIKE_RESULT.md
git commit -m "SPIKE：指令文字進遊戲驗證——tellraw/data merge/say 三條寫入路徑與 SNBT 跳脫方式"
```

---

## Self-Review 摘要（寫這份計畫時做的檢查）

- **spec 覆蓋**：spec 的 §2（掃描）→ Task 5/6/9；§3（span 定位器）→ Task 2；
  §4（跳脫組字）→ Task 7；§5（多處編輯排序）→ Task 7/8；§6（mcfunction 逐行）
  → Task 9/10；§7（合約異動）→ Task 1；§8（寫入拼裝）→ Task 7/8/10；§9（測試
  策略）→ 各任務內建 + Task 11 的端到端擴充 + Task 12/13 的真實地圖與進遊戲
  驗證；§10（明確排除項）→ 各任務裡對應的 `skipped_*` 計數而非實作。沒有遺漏
  的區塊。
- **型別一致性**：`apply_command_edits` 的回傳型別在 Task 7 定義後、Task 8
  發現需要「同時回傳字串與寫入筆數」時**回頭改了 Task 7 的簽名**（`tuple[str,int] | None`
  取代單純 `str | None`），並在 Task 8 Step 4 明講「回去改 Task 7 的測試」——
  避免簽名在任務之間漂移。`decode_offset` 這個參數在 Task 7/8/10 三處的用法
  （指令方塊是 1、mcfunction 是 0）已經在 Task 10 Step 4 明確點出差異的原因。
- **佔位符掃描**：沒有 "TBD"／"之後補"／"視情況處理" 這類字眼；`[待驗]` 是
  刻意保留給進遊戲驗證的開放項（Task 13），不是沒想清楚。
- **對 spec 的修正**：檔案結構那處（`scan/command.py` 是共用模組而非獨立
  registry 來源）已經在計畫開頭寫明是讀了真實程式碼後的修正，不是隱瞞分歧。
