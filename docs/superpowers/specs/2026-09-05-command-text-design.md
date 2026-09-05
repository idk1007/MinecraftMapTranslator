# 指令文字（方案 1）—— 指令方塊與 `.mcfunction` 的文字掃描與寫回

**狀態**：brainstorming 完成，待寫 implementation plan。
**範圍**：架構計畫裡「V2：指令方塊 + datapack 函式」的第一刀。CLAUDE.md 稱指令語法解析為
「工作量最難估的一項」；本文件的每一個決定都以「圈出已知安全區、未知就跳過並計數」
為最高原則（M6 denylist 的教訓），不追求一次做完整。

---

## 1. 目的與範圍

**目的**：這個工具目前只能翻譯告示牌、書本、物品名等「靜態存在於 NBT 裡」的文字。
真實冒險地圖有大量文字是**指令產生的**——指令方塊 `Command` 欄位、datapack
`.mcfunction` 檔——這些完全不在掃描範圍內。本方案把這兩個來源接上，讓完整翻譯一張
地圖成為可能。

**驅動這次設計的原則**：這不是為了翻某一張特定地圖，是為了**大部分冒險地圖都會遇到
的情況**。任何「只對某張地圖成立」的捷徑一律不採用。

**方案 1 的範圍（本文件僅涵蓋這些）**：

| 有做 | 沒做（明確排除，跳過並計數，供未來評估用） |
|---|---|
| 指令方塊 `Command`（region + entities 兩種 chunk，含連鎖／自動／礦車） | L3：`click_event.command` 指向的另一條指令裡還有文字（`stats.skipped_command_nested_reference`） |
| `.mcfunction`（datapack 資料夾與 zip 兩種形式） | `.mcfunction` 行尾反斜線延續（1.20.2+，`stats.skipped_command_line_continuation`） |
| L1：指令直接帶一個 JSON/SNBT 文字參數（`tellraw`／`title`／`say`…） | Function 巨集 `$(...)` 佔位符（`stats.skipped_command_unsupported_shape`） |
| L2：指令帶一個 SNBT 參數，裡面才有 component（`data merge`／`give` 物品組件） | 白名單以外的任何指令動詞（同上） |
| `say`／`me`（純文字尾巴，走 in_place） | |

排除項不是「做不到」，是「這次不猜、留給有真實數字之後再決定」（見 §8）。

---

## 2. 掃描層

### 2.1 新的掃描來源

- `scan/sources/command_block.py`：掃 region／entities chunk 裡 `block_entities[].Command`。
  **不是新容器種類**——`Command` 只是既有 `region_chunk`／`entities_chunk` 容器裡的一個
  欄位，跟掃告示牌、CustomName 用的是同一個容器。
- `scan/sources/mcfunction.py`：掃 datapack 裡的 `*.mcfunction`，資料夾與 zip 兩種形式都
  要（比照 `scan/sources/datapack.py` 的既有做法）。**是新容器種類**：`datapack_mcfunction_file`
  （純文字檔，不是 NBT 也不是 JSON 樹）。

### 2.2 指令怎麼被認出來

1. **剝 `execute ... run`**：`execute` 後面一串條件子指令，最後一個 `run` 才是真正要
   執行的指令。找 `run` 必須用 §3 的括號／引號深度掃描，不能用字串搜尋——指令文字裡
   可能真的出現 "run" 這個字（`tellraw @a {"text":"run for it"}`）。
2. **比對白名單動詞**：`tellraw`／`title`／`subtitle`／`actionbar`／`say`／`me`／
   `bossbar ... name`／`scoreboard objectives add`／`data merge`／`data modify ... set value`／
   `give`・`item` 的物品組件。不在名單上 → 跳過，計入 `stats.skipped_command_unsupported_shape`。
3. **`say`／`me`**：動詞後面到行尾整段就是可翻文字本身，沒有 component 語法——**沒有
   插 lang key 的地方**，走 `in_place`（直接替換文字）。
4. **其餘動詞**：都是「動詞 + 固定位置的 JSON 或 SNBT 參數」，交給 §3 定位；走
   `translate_key`。
5. **L3 偵測**：解出的 component 樹如果含 `click_event`，其 `action` 是
   `run_command`／`suggest_command` 系列**且**其 `command` 值的動詞落在白名單內（代表
   裡面真的還有文字，不是像 `/spawn` 這種無文字的指令）→ 這個 occurrence **整個**跳過
   不翻（不是只跳過巢狀那部分），計入 `stats.skipped_command_nested_reference`，加
   `nested_in_command` 旗標。
6. **`.mcfunction` 行尾延續偵測**：一行（去掉換行符後）以裸 `\` 結尾 → 這條邏輯指令
   （延續開頭、中間、結尾涉及的所有行）整批跳過，計入 `stats.skipped_command_line_continuation`，
   不嘗試組裝。

---

## 3. 核心新元件：span 定位器

**問題**：指令的寫回必須是「在原始位元組上動最小範圍」（CLAUDE.md：SNBT 不忠實、
不能整份重編，只能位移替換），所以需要一個東西回答「這段可翻文字在原始指令字串裡的
哪個位元組區間」。

**採用做法**：一個只做**括號／引號深度計數**的小函式，不做語意解析：

```
locate_span(text: str, path: Sequence[str | int]) -> tuple[int, int]
```

- `path` 為空 → 從目前位置找下一個 `{`（或字串起點）到配對的 `}`（或行尾），回傳整個
  區間。這是 L1（`tellraw` 整包 JSON）跟找 `execute ... run` 之後那段的共同用法。
- `path` 非空 → 先定位到最外層區間，再在**這段子字串內**數 `,` 分隔的清單元素、數
  `key:` 找 compound 欄位，沿著 path 逐層縮小範圍，全程只認括號、引號、逗號的深度，
  不理解值本身的意義。
- 只有**找到候選區間之後**，才把這一段字串交給既有的 `json_component`／`snbt` codec
  真的解碼一次（拿來生 Unit、判斷形狀），解碼失敗 → 這個 occurrence 算
  `skipped_command_unsupported_shape`。

**為什麼不做別的**：
- 不寫完整帶位置追蹤的 SNBT/JSON 解析器——那就是「最難估的一項」本身，風險最高。
- 不對每種指令形狀各寫死一條正則——每加一種形狀就要再開一個特例，脆、難測、漏了
  不會發現。
- 深度計數是唯一「不需要理解語意、複雜度鎖死在數括號這一件事」的做法，L1、L2 共用
  同一個函式，只是路徑深淺不同。

---

## 4. 巢狀寫回：由內往外組字，只 splice 一次

**這是全案最容易寫錯的地方**，用一個具體例子講清楚規則。

```
/data merge block ~ ~ ~ {messages:["{\"text\":\"Hello\"}"]}
```

`messages` 的元素不是原生 SNBT compound（`{text:"Hello"}`，結構字元無跳脫），而是**一個
SNBT 字串常值，內容剛好是一段 JSON 文字**——跟 legacy chunk 的 `'{"text":"文字"}'`
（NBT 字串內容是 JSON）是同一個形狀，只是這次外層跳脫規則是 SNBT 的，不是 NBT 的
（NBT 字串本身無跳脫）。

**錯誤做法**（本文件初稿曾經這樣想，記錄下來避免重犯）：直接在絕對位移上 splice 一段
新文字 `{"translate":"key.1"}`，會產出：

```
/data merge block ~ ~ ~ {messages:["{"translate":"key.1"}"]}
```

外層雙引號在第一個 `{"` 的 `"` 就被提前閉合——**指令壞掉，存檔進不去**。

**正確做法**：splice **只在最外層發生一次**；中間每多一層「字串包字串」，是多一次
「組出來的文字要不要重新跳脫」的判斷，不是多一次 splice：

1. 從 decode 鏈**最內層**開始（鏈上每一步本來就記著自己的 `codec`，這不是新資訊）：
   用該層 codec 把新值序列化（`json_component.encode()` → `{"translate":"key.1"}`）。
2. **往外走一層**：如果外層是「這個值是一個字串常值，內容才是剛剛那段文字」（本例
   如此）→ 把剛剛那段文字當成字串內容，依外層的字串跳脫規則重新加引號、加反斜線
   （`"{\"translate\":\"key.1\"}"`）。如果外層是「這個值本來就是原生 SNBT compound」
   （`data merge` 直接寫 `{text:"Hello"}` 那種，沒有字串包一層）→ 不需要跳脫，直接用
   **SNBT 語法**序列化（`{translate:"key.1"}`，注意 SNBT 的 key 不加引號，跟 JSON
   語法不同，不能直接拿 JSON 文字去塞）。
3. 重複到鏈的最外層，這時候得到的文字，才是真正要 splice 進最外層物理字串（`Command`
   整條，或該行文字）的**那一段**，用它在最外層座標系裡的絕對位移換掉舊的那一段。

`[待驗]`：SNBT 字串常值要用雙引號＋跳脫還是換成單引號比較貼近 Mojang 自己的序列化
習慣，等 §9 的進遊戲驗證再確認；先按雙引號＋跳脫做。

---

## 5. 同一物理字串內多處編輯：由後往前

**問題**：一條指令／一行裡可能同時有兩處要翻的文字（例如同一個 `data merge` 裡
`messages[0]` 跟 `messages[1]`）。換掉前面那處之後，後面那些位移全部失效。

**已經有解，只是還沒被呼叫**：`model/node.py::span_order()`（依最內層 decode 的 span
起點降冪排序）在 2026-08-17 就寫好、有單元測試，但**目前沒有任何寫入器真的呼叫它**
——跟 `command` codec 一樣是「合約先蓋好，等這次來蓋房子」。

本方案要做的：

1. **分組**：把 `apply_edits()` 現有的「同一個 NBT list 的 edits 要批次處理，不能逐筆
   呼叫」那套邏輯（2026-08-31 修 native list 自撞用的同一招），分組鍵擴大成「同一個
   物理字串」——指令方塊是同一個 block_entity 的 `Command`，`.mcfunction` 是同一個檔
   同一行（見 §6）。
2. **組內用 `span_order()` 排序**，逐一 splice。降冪排序保證：處理某一筆時，字串裡
   右邊（更晚的位移）已經沒有其他還沒處理的 edit 在等，所以前面幾筆的座標永遠有效。
3. **組內先用既有 `raw_snapshot` 機制**比對整條物理字串有沒有在 extract 之後被改過
   （跟現有守門同一套邏輯，只是比對對象是字串而不是整個 NBT 節點）。

---

## 6. `.mcfunction`：以「邏輯指令」為物理字串單位，而非整檔或裸行

**不是整個檔案當一個字串**：一個檔案裡通常有多條互不相干的指令，把整檔當一個字串會
讓每次 splice 的座標系毫無必要地放大，也讓錯誤訊息（「第 185,420 個字元」）難以排查。

**也不是天真的「裸一行」**：1.20.2+ 的行尾延續語法（§2.6）代表「一行」不保證等於
「一條指令」——但本方案選擇**跳過任何涉及延續的邏輯指令**（見 §1），所以在 v1 的
實際範圍內，**每一條會被處理的指令，保證剛好對應一個物理行**（因為牽涉延續的都被
排除了）。

**換行符必須全程當不透明資料，不經過任何字串正規化**：

1. 讀檔用 `read_bytes().decode("utf-8")`（跟 `write/datapack_apply.py` 現有寫法一致），
   **不用 Python 文字模式的 `open()`**——那會把 `\r\n` 正規化成 `\n`。
2. **只切 `\n`**，不用 `str.splitlines()`（那個函式連 `\v`、`\f`、` ` 都當換行界線，
   而且會把換行符吃掉）。每一行拆成 `(command_text, terminator)`，`terminator` 是
   `"\r\n"`、`"\n"`，或空字串（檔案最後一行沒有結尾換行時）。
3. span 定位、白名單比對、splice 全部只作用在 `command_text` 上，`terminator` 全程
   原封不動存著，重組時直接拼回去——**換行符從頭到尾沒有被任何字串運算碰過**，不是
   「維持一致」，是「根本沒被動過」。
4. 內部座標仍用絕對位移（`(line_index, start, end)` 其實化簡為「每行各自的區域絕對
   位移」，因為行與行之間本來就不共用同一個 splice 操作），但**錯誤訊息額外算出
   `line_index` 顯示給人看**（對照事先算好的換行位置表，一次 `bisect`，成本可忽略）。

寫入器 `write/mcfunction_apply.py`：架構抄 `write/datapack_apply.py`（暫存 → 回讀
驗證 → 原子替換；zip 形式整份重建），驗證方式改成「UTF-8 可解碼、位元組除了改動的
範圍外逐行比對不變」（不像 JSON 有 `json.loads` 可以嚴格驗證語法，指令語法驗證超出
這次範圍）。

---

## 7. 分類、策略、容器種類（合約異動）

**兩個新分類**（取代目前只是佔位的 `command_text`）：

| 分類 | 策略 | 對應 |
|---|---|---|
| `command_say_text` | `in_place`（比照 `block_entity_name`，加進既有的 category → in_place 那條 if/then） | `say`／`me` |
| `command_component_text` | `translate_key`（預設路徑，不需要新 if/then） | 其餘白名單動詞 |

`command_say_text` 的 `occurrence.encoding` 填既有的 `bare_string`（沒有任何包裝的裸
文字，語意完全對得上，不用新增 encoding 值）。`command_component_text` 的 encoding
是「decode 到最內層之後那個節點長什麼樣」，用既有 8 種形狀就夠，不用新增。

**容器種類**：`docs/contracts/*.json` 的 `container.kind` enum 新增
`datapack_mcfunction_file`（指令方塊沿用既有的 `region_chunk`／`entities_chunk`，
不需要新種類）。

**新的 stats 欄位**（extract 合約）：
- `stats.skipped_command_unsupported_shape`
- `stats.skipped_command_nested_reference`
- `stats.skipped_command_line_continuation`

既有的 `nested_in_command` 旗標沿用（語意是「這個 unit 的文字住在指令字串裡」），每個
指令來源的 unit 都會帶上，跟上面新的 stats 是分開的兩件事（旗標標記 provenance，stats
記跳過的量）。

**anchor**：指令方塊沿用既有的位置 anchor（block 座標）。`.mcfunction` 沿用既有的
`file` anchor kind，額外加一個可選的 `line` 欄位（方便 `where` 顯示「第幾行」，不是
必要功能，若嫌合約異動範圍變大可以先不加，`where` 退回只顯示檔案路徑）。

**這些異動together是一次獨立的合約改動**：SCHEMA_VERSION 6 → 7，`tests/fixtures/contracts/*.sample.json` 同步更新，跑
`tools/validate_contracts.py` 驗證，照 CLAUDE.md「合約改動流程」獨立 commit。

---

## 8. 寫入層完整拼裝順序

**指令方塊**（在既有 `_apply_to_region` 裡擴充）：

1. `apply_edits()` 分組（見 §5）。
2. 讀取 `Command` 目前的字串值，比對 `raw_snapshot`。
3. `span_order()` 排序。
4. 逐一：用 §4 的「由內往外組字」得到最終替換文字，splice 進 `Command` 字串。
5. 包回 `TAG_String`，其餘（chunk touched、備份、報告）不變。

**`write/common.py` 的擴充是一個分派點，不是重寫**：`apply_edit_to_compound` 走到
`Command` 這個 `TAG_String` 一樣停下——decode 步驟怎麼處理是 codec 的事（`NodePath`
文件本來就這樣寫）。新增一個獨立、只做字串進字串出的函式（`write/command_span.py`），
`write/common.py` 只多一個 if：這步的 `node_path` 後面還有 `decode` 步驟嗎？有 →
呼叫這個新函式；沒有 → 走原本的整值替換。

**`.mcfunction`**：同一套邏輯，物理字串是「該行文字」而非 NBT 欄位，見 §6。

---

## 9. 測試策略

### 9.1 需要涵蓋的新 dispatch 組合（M13a 教訓：擴範圍先列組合）

| 容器 | 策略 | 是否新組合 |
|---|---|---|
| region/entities chunk（指令方塊） | in_place（say/me） | 新 |
| region/entities chunk（指令方塊） | translate_key，L1 | 新 |
| region/entities chunk（指令方塊） | translate_key，L2 巢狀 SNBT | 新 |
| `datapack_mcfunction_file` | in_place | 新 |
| `datapack_mcfunction_file` | translate_key | 新 |

端到端測試要五種都各跑一次，外加一條「五種都真的被涵蓋到」的斷言測試（照抄
`test_the_round_trip_actually_exercises_all_four_dispatch_combinations` 的做法）。

### 9.2 單元測試分層

1. **span 定位器**（`tests/unit/test_span_locator.py`）：純函式，餵 `SPIKE_RESULT.md`
   裡四個指令方塊範例＋MP2 的 `data merge` 範例；驗證 `run` 誤判防護（JSON 內文含
   "run"）、括號／引號深度計數的邊界情況。
2. **白名單／execute 剝除**（`tests/unit/test_scan_command.py`）：巢狀
   `execute ... if ... run`、未知動詞、`$(...)` 巨集、L3 偵測、行尾延續偵測。
3. **由內往外組字**（`tests/unit/test_command_span_write.py`）：**直接把 §4 的
   `messages:["{\"text\":...}"]` 範例當回歸測試**，斷言錯誤做法產出的壞指令不會再
   出現。
4. **同字串多處編輯**（同上檔案）：**直接把 §5 提到的「同一個 `data merge` 兩個
   messages」當回歸測試**。
5. **CRLF 保留**（`tests/unit/test_mcfunction_apply.py`）：CRLF 檔案 apply 後，未改到
   的每一個 `\r\n` 位元組不變；混合 CRLF/LF 的檔案也要測。
6. **行尾延續**：一個含 `\` 延續行的檔案，斷言那條邏輯指令整批跳過、其餘正常指令不
   受影響、`stats.skipped_command_line_continuation` 數字正確。
7. **端到端**：擴充 `test_end_to_end.py`，塞一個 say 指令方塊、一個 tellraw 指令方塊、
   一個兩行的 `.mcfunction`。

### 9.3 真實地圖驗證與進遊戲驗證

- 實作完在 MP2（692 指令方塊、2,613 個 `.mcfunction`）跑一次，量出：
  - L3 實際佔比 → 決定要不要做方案 2
  - 行尾延續實際出現次數 → 決定值不值得補
  - 各白名單動詞的真實分布
  - 寫回一律不猜；跑完數字寫回 `SPIKE_RESULT.md`。
- **進遊戲驗證**（跟 M0/M4/M11 同一標準，寫回結果前只能標 `[待驗]`）：
  1. 塞進 `tellraw` 的 `{"translate":key}` 正確顯示。
  2. 塞進 `data merge` 寫的告示牌 `{"translate":key}` 正確顯示（跟一般告示牌走
     translate key 路徑理論上該一樣，但沒有驗過不能假設）。
  3. `say`/`me` 的 in_place 文字替換正確顯示。
  4. SNBT 字串常值的跳脫方式（§4 的 `[待驗]`）是否被遊戲正確解析。

---

## 10. 明確排除、留給未來的項目

- L3（`click_event.command` 遞迴）——見 §1，數字出來後再評估「方案 2」。
- `.mcfunction` 行尾延續（1.20.2+）——見 §1／§6，數字出來後再評估。
- Function 巨集 `$(...)`——原樣跳過，不翻，跟現有 `with` 參數處理原則一致。
- 白名單以外的任何指令動詞——不猜，只計數。
- 這次不處理 `.mcc`、1.12 舊結構——與本方案無關，維持既有政策。

---

## 11. 檔案異動清單（供寫 implementation plan 時參考）

**新檔案**：
- `src/mcmt/scan/sources/command_block.py`
- `src/mcmt/scan/sources/mcfunction.py`
- `src/mcmt/tree/span_locator.py`（§3 的定位器 + §4 的「由內往外組字」）
- `src/mcmt/write/command_span.py`（§5 的 splice 原語，字串進字串出，不碰 Tag）
- `src/mcmt/write/mcfunction_apply.py`
- `tests/unit/test_span_locator.py`
- `tests/unit/test_scan_command.py`
- `tests/unit/test_command_span_write.py`
- `tests/unit/test_mcfunction_apply.py`

**修改既有檔案**：
- `src/mcmt/tree/codecs/command.py`（把 `NotImplementedError` 換成真的實作）
- `src/mcmt/write/common.py`（§8 的一個分派點）
- `src/mcmt/write/apply.py`（`_WRITERS` 表加 `datapack_mcfunction_file`）
- `src/mcmt/model/strategy.py`（兩個新分類的 category → strategy 對照）
- `src/mcmt/scan/registry.py`（掛上兩個新來源）
- `docs/contracts/extract.schema.json`、`editplan.schema.json`（§7）
- `tests/fixtures/contracts/*.sample.json`（合約改動流程要求同步）
- `tests/integration/test_end_to_end.py`（§9.1 的五種新組合）
- `CLAUDE.md`（`command` codec 從「明確拒絕」改成「已實作，範圍見本 spec」；`docs/STATUS.md`
  更新進度）
- `SPIKE_RESULT.md`（§9.3 的真實地圖數字與進遊戲驗證結果）

**合約改動**（獨立 commit，SCHEMA_VERSION 6 → 7）與 **`write/`／`safety/` 改動**
（獨立 commit，各自附理由）分開處理，照 CLAUDE.md 現有規範。
