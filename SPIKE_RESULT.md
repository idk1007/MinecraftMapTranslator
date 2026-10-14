# SPIKE_RESULT — Minecraft 地圖翻譯工具技術驗證

- 日期：2026-08-15
- 目標版本：Java Edition **1.21.11** — DataVersion **4671**、資源包 format **75**、datapack format **94.1**
- 環境：Windows 11 · Python 3.11.7 · 本機 `.minecraft`
- 驗證腳本：`spike/`（可整個刪除，含兩個 venv）

**證據等級標示**
**[實測]** 本機跑出來的結果 ·
**[遊戲實測]** 在 1.21.11 遊戲內肉眼確認 ·
**[文件]** 官方 wiki 且與實測不衝突 ·
**[待驗]** 尚未驗證，附驗證方法

**測試素材**
1. `Minecraft Party 2` — 1.21.10 商業冒險地圖，989 MB / 120,036 chunks，**本身就走資源包路線**
2. `TT_WORLD_NAME_PROBE` — 為本次驗證新建的 1.21.11 世界，用測試 datapack 生成涵蓋所有目標欄位的 fixture

---

## 摘要

| 問題 | 結論 |
|---|---|
| **Q1** 函式庫 | `amulet-nbt` + **自寫 anvil 層**（骨架 90 行，完整實作 200–300 行）。`amulet-core` 可用但過重。 |
| **Q2** NBT 路徑 | 完整路徑表已實測取得，見下。**但 schema 是 per-chunk 不是 per-world**。 |
| **Q3** translate key | 11 個欄位可用、4 個必須直接替換。**全部經 1.21.11 遊戲畫面確認**。 |
| **Q4** resources.zip | **仍有效**。有 1.21.10 商業地圖實例可對照，`pack_format` 過期不會拒載。 |

### 三個會影響架構的發現

**① 同一個世界的 chunk 停在不同格式世代 [實測]**

Minecraft 只在**實際載入某個 chunk 時**才對它跑 DataFixerUpper。玩家沒去過的區域永遠保持建圖當下的格式。`Minecraft Party 2`（level.dat 宣稱 4556）實際分佈：

| chunk DataVersion | 版本 | chunk 數 |
|---|---|---|
| 3955 | 1.21.1 | 51,369 |
| 4438 | 1.21.7 | 47,148 |
| 4440 | 1.21.8 | 71 |
| 4556 | 1.21.10 | 21,448 |

這條分佈跨過 **1.21.5（4325）**——文字組件從「JSON 字串」改成「原生 NBT」的分水嶺。所以同張圖裡兩種格式**同時存在**：

- `CustomName`：2,022 個舊式 JSON 字串 · 186 個純字面 · **僅 15 個**原生 Compound
- 告示牌 `messages[]`：2,450 個舊式 JSON 字串 · 5,411 個原生 Compound · 40,253 個空字串

**必須讀每個 chunk 自己的 `DataVersion` 再決定解讀方式**，寫回時也要寫回該 chunk 原本的世代格式。

**② 純文字 component 會被折疊成裸字串 [實測]**

1.21.11 中，只有文字沒有格式的 text component **存成裸 `TAG_String`**：

| 寫入的內容 | 存進 NBT 的實際路徑與型別 |
|---|---|
| `{text:"A"}` | `custom_name` = `TAG_String 'A'` ← 折疊 |
| `{text:"A",italic:false}` | `custom_name.text` = `TAG_String 'A'` ← 保持 Compound |

所以工具遇到某個 text component 位置上的 `TAG_String`，必須理解成「一個剛好只有字面文字的 component」，而不是「純字串欄位」。把它換成 translate key 是**型別變更**（String → Compound），不是值變更。

**③ 插入 translate key 會強迫整個 list 升級 [實測，位元組層級驗證]**

NBT 的 list 必須同型。告示牌四行只要有一行是結構化 component，其餘三行就**不能**是裸字串，會被編碼成**空名稱**的 compound：

```
back_text.messages  = TAG_List of TAG_String        ← 四行都是純文字
      TAG_String ''  ×4

front_text.messages = TAG_List of TAG_Compound      ← 有一行是 translate
      TAG_Compound { 'translate' : TAG_String 'block.minecraft.diamond_block' }
      TAG_Compound { ''          : TAG_String 'TT_SIGN_TRANSLATE_PROBE' }
      TAG_Compound { ''          : TAG_String '' }
      TAG_Compound { ''          : TAG_String '' }
```

**意義**：在告示牌任一行插入 translate key，其餘三行必須一併改寫。只換單一元素會產生非法的異質 list。

#### 為什麼這條需要三重證據

空字串當 key 極度反直覺——在 JSON text component 規範裡它不對應任何欄位，合理的猜測應該是 `{"text": "原文"}`。而且「真實地圖也出現 14 次」**不構成獨立證據**：若是解析器的 bug（例如 name length 欄位 off-by-one），同一個 bug 出現 14 次跟出現 1 次是一樣的。所以用三條獨立證據交叉驗證：

| 證據 | 來源 | 結果 |
|---|---|---|
| 讀取器 A | `amulet-nbt` 2.1.8，第三方 C extension | `key=''`，`len 0` |
| 讀取器 B | `probe_raw_nbt.py`，自寫位元組解析 | `NAME LENGTH = 0` |
| 原始位元組 | `probe_verify_emptykey.py` 標註位移 | `@0x000483 = 00 00` |

```
--- element 1 ---
@0x000482  08                 tag id 8 = TAG_String
@0x000483  00 00              NAME LENGTH = 0   <-- 零長度 key
@0x000485  00 17              string length = 23
@0x000487  54 54 5f ...                        = 'TT_SIGN_TRANSLATE_PROBE'
@0x00049e  00                 TAG_End
```

off-by-one 的可能性也被排除：若 name length 讀錯，後續元素會全部錯位、解不到乾淨的 `TAG_End` 邊界，而實測四個元素全部對齊。加上 amulet-nbt 是完全獨立的實作卻給出相同結果。

**推測的成因**（未經原始碼確認）：這可能不是 text component 專屬行為，而是 Mojang `NbtOps` 的通則——NBT 的 list 必須同型，當 list 需要容納異質元素時，非 compound 的元素會被包成 `{"": value}`。若成立，則所有「可為字串或結構」的 component 欄位放進 list 時都適用同一規則。

#### 反向驗證結果：兩種編碼都有效 [遊戲實測]

fixture 是遊戲自己寫出來的，所以那個格式遊戲一定讀得懂——這不能證明**我們**寫出來的檔案會正確顯示。於是用 `spike/write_sign_variants.py` 以 amulet-nbt 直接寫入 region 檔，同一塊告示牌兩面各用一種編碼，第一行都是 `{"translate":"block.minecraft.diamond_block"}`：

| 面 | 寫入編碼 | 遊戲內顯示 |
|---|---|---|
| 正面 | `{"": "文字"}` | ✅ 正常顯示 A2 / A3 / A4 |
| 背面 | `{"text": "文字"}` | ✅ 正常顯示 B2 / B3 / B4 |

**兩種都正常。** 這修正了本節初版的推論：

> **`{"": "文字"}` 是「讀取端」的必要條件，不是「寫入端」的約束。**
>
> - **讀取**：必須同時容忍三種形狀——裸 `StringTag`、`{"": "文字"}`、`{"text": "文字"}`，三者都代表字面文字。漏掉 `{"": ...}` 會讀不到遊戲自己產生的內容。
> - **寫入**：兩種 Compound 形式皆可。建議採用 `{"text": ...}`，因為它是官方文件記載的形狀，維護者一看就懂；`{"": ...}` 只是 `NbtOps` 的內部產物。

**仍然成立的硬性約束**：NBT list 必須同型。只要有一行變成 Compound，其餘三行就**必須**一併改寫成 Compound，不能留下裸字串。發現 ③ 的核心結論不變，變的只是「改寫成哪一種 Compound」有選擇餘地。

---

## Q1：Python 函式庫能否讀寫 1.21.11 的 region 與 NBT

### 實測結果

全部在 Python 3.11 全新 venv 實裝後對真實世界檔測試，非讀文件宣稱。

| 函式庫 | 版本 | 最後更新 | level.dat | .mca | 判讀 chunk | 結論 |
|---|---|---|---|---|---|---|
| **amulet-nbt** | 2.1.8 | 2026-04 | ✅ | ❌ 無此層 | — | **採用**，作 NBT 編解碼 |
| **amulet-core** | 1.9.44 | 2026-08 | ✅ | ✅ | ✅ | 可用但過重 |
| **anvil-parser2** | 0.10.6 | 2024-07 | — | ✅ | ✅ 認得 4556 | 意外可用，備案 |
| nbtlib | 2.0.4 | 2021-11 | ✅ | ❌ 無此層 | — | 僅 NBT，仍可運作 |
| mcworldlib | 2023.7.13 | 2023-07 | ✅ | ⚠️ API 異常 | ❌ | 不採用 |
| anvil-parser | 0.9.0 | 2021-01 | — | — | — | 已被 anvil-parser2 取代 |
| pyanvil | — | — | — | — | — | **見下方陷阱** |

**`pyanvil` 陷阱 [實測]**：PyPI 上的 `pyanvil` **不是 Minecraft 函式庫**，是生物資訊套件（"AnVIL client library. Data harmonization, gen3, terra single sign-on"）。Minecraft 的 pyanvil 只在 GitHub，且已停止維護。`pip install pyanvil` 會裝到完全無關的東西。

### 決定：amulet-nbt + 自寫 anvil 層

`amulet-core` 確實能用（成功載入 1.21.10 世界、列出含 datapack 自訂維度在內的 5 個維度、列舉 25,904 個 chunk、讀出 block entity）。不採用是取捨不是缺陷：

1. 它是**世界轉換器**，會把方塊轉成自有的 universal 格式再轉回來。翻譯工具只改 NBT 字串、完全不需碰方塊，多一層轉換就是多一層損壞風險。
2. 相依很重：`numpy`、`amulet-rocksdb`、`amulet-leveldb`、`pymctranslate`，約 50 MB。
3. 它不暴露 per-chunk DataVersion 分派這個我們必須要有的控制權（發現 ①）。

**自寫 anvil 層的實際成本 [實測]**：`spike/probe_roundtrip.py` 裡可運作的讀+寫**骨架**是 **約 90 行**（僅 zlib、僅乾淨資料，不含 LZ4／`.mcc`／損壞防禦，完整實作見下方估計）。格式本身很單純：4096 bytes 偏移表 + 4096 bytes 時間戳表，接著每個 chunk 是 4 bytes 長度 + 1 byte 壓縮類型 + zlib 資料，對齊到 4096 bytes 磁區。

### 關鍵驗證：外科式讀改寫 [實測]

「位元組一致」有三個不同的層次，初版報告把它們混為一談，以下分開陳述。

| 層次 | 意義 | 實測結果 |
|---|---|---|
| **L1** 解壓後的 NBT 位元組 | amulet-nbt 解析→序列化是否還原 | 1024/1024 · 870/870 **一致** |
| **L2** 重新壓縮後的 payload | 再經 deflate 是否還原 | 1024/1024 · 870/870 **一致** |
| **L3** 原始壓縮位元組直接複製 | 根本不解碼 | 恆為一致（定義如此） |

L2 一致是個**巧合**，不是保證：Python `zlib.compress()` 的預設等級恰好與 Mojang 的 Java `Deflater` 預設輸出相同。只要 region 曾被其他工具以不同壓縮等級寫過、或未來版本改變設定，這個巧合就會消失。

> 初版報告的「未觸碰 chunk 1023/1023 不變」其實是**套套邏輯**：當時的 `write_region` 對未修改的 chunk 直接沿用原始壓縮 payload，所以那項驗證的是「寫入路徑會原樣保留餵給它的東西」，而非「重新編碼是穩定的」。真正支撐結論的是 L1/L2。

### 因此這是規格層級的設計規則，不是實作細節

> **未被修改的 chunk，必須原封不動複製其原始壓縮位元組，絕不重新編碼。
> 只有被修改的 chunk 才走「解碼 → 改 → 編碼」路徑。**

這條讓「除了要改的地方什麼都沒動」從一個**實測觀察**變成**結構性保證**——不依賴 deflate 實作的巧合、不依賴 NBT 序列化順序穩定、也不依賴函式庫版本。對一個要動別人 989 MB 存檔的工具，這個差別很大。

`spike/write_sign_variants.py` 已按此規則實作：修改一個 chunk 時，同 region 內其餘 929 個 chunk 全程未解碼、未重新壓縮。

> 重寫後檔案 5,398,528 → 5,304,320 bytes，是磁區重整（原檔有空隙），非資料遺失。

### 壓縮類型分佈 [實測] 與 LZ4 [待驗]

| 世界 | chunk 數 | 類型分佈 | 外部 `.mcc` |
|---|---|---|---|
| `TT_WORLD_NAME_PROBE` (1.21.11) | 3,610 | 全部 type 2 (zlib) | 0 |
| `Minecraft Party 2` (1.21.10) | 121,403 | 全部 type 2 (zlib) | 0 |

兩個樣本都沒出現 type 4 (LZ4)，與「單機預設 zlib」一致。但**這不能證明 1.21.11 不支援 LZ4**——只證明我手上的地圖沒用到。從伺服器匯出的冒險地圖有可能是 LZ4，讀取器若只處理 type 2 會直接爆。

**驗證方法**：在寫任何解析程式碼前，先對目標地圖跑一次 `spike/probe_compression.py` 掃描類型分佈。實作上四種類型（1 gzip / 2 zlib / 3 未壓縮 / 4 LZ4）都要處理，並對未知類型明確報錯而非靜默略過。另外 compression 位元組的**最高位 (0x80) 代表 chunk 存在外部 `.mcc` 檔**，判斷時要先遮罩。

### 0 bytes 的 region 檔是慣例，不是損壞 [實測，2026-08-17]

M4 找語料時掃過 20 個世界的 **1,608 個 `region/` 底下的 `.mca`**：

| 大小 | 檔案數 | 佔比 |
|---|---|---|
| 正常（≥ 8192 bytes） | 1,405 | 87.4% |
| **正好 0 bytes** | **203** | **12.6%** |
| 介於 1..8191 bytes | **0** | 0% |

203 個 0 bytes 檔分佈在 **6 個世界**，其中「新的世界」（Villager Life 3）的 **28 個
region 檔全部**是 0 bytes。

**推翻的推論**：M1.2 實作時把「0 bytes 的 `.mca`」判為 `TruncatedRegionError`，理由寫的是
「0 bytes 的 .mca 是壞檔，不是『這個 region 沒有 chunk』」。那個推論是錯的——照它走，
上述 6 個世界會被 `doctor` **整個拒絕處理**，而拒絕的理由是一個根本不是損壞的現象。
（`Celestial Challenges` 修正後重跑：56,658 chunk，疑似損壞 0，結論「可以處理」。）

**現在的規則**：`0 bytes` → 空 region（沒有 chunk）；`1..8191 bytes` → 仍然是
`TruncatedRegionError`。分界線放在 0 而不是 8192 有實測支撐：**真實世界不存在
1..8191 bytes 的 region 檔**，所以「寫到一半的 header」這個情境沒有被放行。

### 若全部函式庫都不能用的工作量估計

不成立——`amulet-nbt` 可用。但即使連它都不能用：

| 項目 | 估計 |
|---|---|
| NBT 讀寫（13 種 tag、gzip/zlib、Modified UTF-8） | 300–400 行 |
| anvil region 讀寫**骨架** | 90 行（**已實測完成**） |
| 四種壓縮類型 + 未知類型報錯 | 30 行 |
| 外部 `.mcc` 檔 | 40 行 |
| 錯誤處理（截斷的 region、offset 指向檔外、長度為 0 的空槽、磁區數溢位） | 60–100 行 |
| 合計 | 約 550–650 行，3–4 人日 |

> **排程時不要按 90 行估。** 那 90 行是「在乾淨資料上能跑通」的骨架，不含 LZ4、`.mcc`、以及對損壞檔案的防禦。實務上 anvil 層本身會落在 200–300 行。

`spike/probe_raw_nbt.py` 已經是一個能用的唯讀 NBT 解析器（約 120 行），可當起點。真正的難點從來不是格式解析，是 Q2/Q3 的語意判斷。

---

## Q2：1.21.11 各類文字的實際 NBT 路徑

全部由 1.21.11 fixture 世界（DataVersion 4671）實測取得。`[]` 表示陣列元素。

### 告示牌 [實測]

```
chunk → block_entities[].front_text.messages[]     4 元素
chunk → block_entities[].back_text.messages[]      4 元素
```

- 方塊 id：`minecraft:sign`、`minecraft:hanging_sign`（同樣結構）
- `front_text.color`、`front_text.has_glowing_text`、`is_waxed` — **非文字，勿翻譯**
- 元素型別依同列其他元素而定，見發現 ②③
- 手打輸入與指令產生**存法完全相同**：`手動測試` 存成 `messages[]` 的裸 `TAG_String`

### 書本 [實測]

```
物品 → components."minecraft:written_book_content".title.raw     ← 純字串
物品 → components."minecraft:written_book_content".author        ← 純字串
物品 → components."minecraft:written_book_content".pages[].raw   ← text component
物品 → components."minecraft:writable_book_content".pages[].raw  ← 純字串（未簽名草稿）
講台 → block_entities[].Book.components."minecraft:written_book_content"....
```

**注意 `title` 是 `{raw: ...}` 包裝**（filterable 結構），路徑是 `title.raw` 不是 `title`。`pages[]` 同樣是 `{raw: ...}` 包裝，但 `raw` 底下可以是完整 component；`title.raw` 底下只能是字串。這個不對稱是 Q3 的關鍵。

### 物品自訂名稱與 lore [實測]

```
物品 → components."minecraft:custom_name"      ← 玩家/指令命名，斜體顯示
物品 → components."minecraft:item_name"        ← 物品本身的名字，不可被鐵砧改
物品 → components."minecraft:lore"[]           ← 陣列，每個元素是 component
```

三者都是 text component。`custom_name` 與 `item_name` 是**不同組件**，各自獨立存在。

### 容器與巢狀 [實測]

```
方塊實體 → block_entities[].CustomName                    ← 箱子/命令方塊等的自訂名
方塊實體 → block_entities[].Items[].components....         ← 容器內物品
物品     → components."minecraft:container"[].item.components....  ← 潛影盒內物品
玩家     → level.dat → Data.Player.Inventory[].components....
```

**必須遞迴**：實測 fixture 中「箱子 → 潛影盒 → 綠寶石」三層巢狀的 `TT_NESTED_ITEM_NAME` 確實存在於
`block_entities[].Items[].components."minecraft:container"[].item.components."minecraft:custom_name"`。

### 實體 [實測]

```
entities/*.mca → Entities[].CustomName                    ← 具名生物、盔甲座
entities/*.mca → Entities[].text                          ← text_display（1.19.4+）
entities/*.mca → Entities[].Item.components....           ← 展示框內的物品
```

**實體不在 `region/` 而在 `entities/` 資料夾**（1.17 起分離）。只掃 `region/` 會漏掉所有具名生物、盔甲座、展示框。

`text_display` 是 1.19.4 加入的顯示實體，現代冒險地圖大量用它取代盔甲座做浮空文字，優先支援。

### level.dat [實測]

```
Data.LevelName                          ← 純字串，非 component
Data.CustomBossEvents.<id>.Name         ← text component
Data.Player.Inventory[].components....  ← 玩家背包內物品
```

### 記分板 [實測]

```
data/scoreboard.dat → data.Objectives[].DisplayName        ← text component
data/scoreboard.dat → data.Teams[].DisplayName             ← text component
data/scoreboard.dat → data.Teams[].MemberNamePrefix        ← text component
data/scoreboard.dat → data.Teams[].MemberNameSuffix        ← text component
```

`Objectives[].Name`、`Teams[].Name`、`Objectives[].CriteriaName` 是**識別碼不是文字**，指令會引用，翻了會壞。

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

`100 Ways To Die` 沒有任何 datapack（`extract` 掃出 0 個 `advancement_title`/
`advancement_description`），所以這兩則發現只有 AoD 一張地圖的樣本。

### M13a/M13b 之後 MP2 全掃 [實測 2026-09-01]

`docs/STATUS.md` 已知缺口第 15 項留到現在才跑：「MP2 還沒用 M13a／M13b 之後的完整掃描
跑過」。用 `mcmt sandbox import` 匯入、`mcmt doctor` 健檢、`mcmt extract` 全掃、
把 `translations.zh_tw.json` 每筆 `target = source`（no-op 驗證譯文）、`mcmt apply`
真的寫入（非 dry-run），再從備份還原、`mcmt doctor` 覆核數字與寫入前一致。

**doctor（寫入前後數字一致）**：

```
維度：5 個 region 目錄（DIM-1、DIM1、dimensions/new_dimensions/{sky,void}_dimension、主世界）
region 檔：406 個 · chunk：207,515 個
實體 region 檔：185 個 · 實體 chunk：760 個
level.dat：1 個 · scoreboard.dat：1 個 · datapack 進度檔：43 個
DataVersion：3955 43.4% / 4438 43.1% / 4556 13.3% / 4325 0.2% / 4440 0.0%
壓縮類型：全部 zlib
節點形狀（文字節點 58,723）：bare_string 77.0%／compound_tree 10.7%／
  empty_key_compound 4.7%／json_empty_quoted 4.0%／json_string_scalar 3.4%／
  json_string_object 0.3%
外部 .mcc：0，不支援的結構：0，疑似損壞：0
```

**extract**：

```
翻譯單位：1,062 個（出現 3,072 次，去重省下 2,010 次）
  sign 578 / objective 310 / hanging_sign 44 / team 39 / block_entity_name 36 /
  book_page 34 / team_affix 10 / entity_name 4 / item_name 2 / book_title 2 /
  custom_name 1 / book_author 1 / level_name 1
跳過：4,507 個新世代 chunk 裡的舊式 JSON、3,515 個已在地化（M13b `_contains_translate`）、
  47,629 個空白節點
```

**apply（no-op 譯文，真實寫入）**：

```
計畫要改的節點：3,072 → 實際寫入：3,072（unwritten 0，refuse 0）
改動的 chunk：463（原封複製 28,200 個）· 重寫的 region 檔：32
NBT list 提升：829（M13a 之後的批次守門——同一面告示牌多筆 edit 不再自撞）
warnings：31（全部是磁區重整，附前後大小；無其他警告種類）
```

MP2 自己的 `resources.zip` 宣告 `pack_format 55`，1.21.11 會拒絕整包（連我們寫入的
譯文一起）；`apply` 自動加上 `supported_formats 55–75`，未更動它原本宣告的
`pack_format`——這是安全規則之外、資源包合併邏輯第一次在真實地圖的舊 `resources.zip`
上被觸發並驗證過。

**結論**：語料裡形狀最雜的一張地圖（`json_empty_quoted` 2,340、`compound_tree` 6,282、
`hover_event` 331、自帶 `mcp.*` 中文化系統）在 M13a（掃描範圍擴大）與 M13b（已在地化
跳過）之後，**沒有任何一筆 edit 被拒寫**，`已知缺口第 5 項`（native list 批次自撞）與
`第 3 項`（`raw_snapshot` 守門）在最複雜的真實資料上都沒有暴露新問題。之前
`stats.skipped_already_localised` 只在單元測試與小語料上驗證過，這是它第一次在
3,515 筆真實地圖資料上生效——若它沒接上，這 3,515 筆會混進待翻檔，靜默蓋掉地圖
自己的 5 語言中文化系統（見上方「M13b」一節與 STATUS.md 對此規則的說明）。

### 指令文字方案 1 MP2 全掃 [實測 2026-09-05]

「command text」功能（指令方塊 `Command` ＋ datapack `.mcfunction` 的白名單動詞
解析／外科式寫回，13 個任務、SCHEMA_VERSION 6 → 7）落地後，第一次把整條鏈對
語料裡 datapack 最大的一張地圖跑完：`mcmt doctor` → `mcmt extract --lang zh_tw`
→ 把 `translations.zh_tw.json` 每筆 `target = source`（no-op 驗證譯文）→
`mcmt apply --dry-run` 檢查 editplan → `mcmt apply` 真的寫入（非 dry-run）→
從備份還原 → `mcmt doctor` 覆核。設計文件見
`docs/superpowers/specs/2026-09-05-command-text-design.md`。

**doctor（寫入前後 byte 級一致）**：

```
維度：5 個 region 目錄 · region 檔 406 · chunk 207,515
實體 region 檔 185 · 實體 chunk 760 · level.dat 1 · scoreboard.dat 1 · datapack 進度檔 43
DataVersion：3955 43.4% / 4438 43.1% / 4556 13.3% / 4325 0.2% / 4440 0.0%
壓縮類型：全部 zlib
節點形狀（文字節點 58,754）：bare_string 76.9%／compound_tree 10.7%／
  empty_key_compound 4.7%／json_empty_quoted 4.0%／json_string_scalar 3.4%／
  json_string_object 0.3%
節點種類新增一列：command_component_text 31（doctor 的 survey 會數指令方塊
  Command 內的 component 文字；`command_say_text` 不在 doctor 的分類清單裡）
外部 .mcc：0，不支援的結構：0，疑似損壞：0
```

**extract**：

```
掃過 chunk 207,515 · 文字節點 62,105
翻譯單位：1,280 個（出現 3,331 次，去重省下 2,051 次）
  既有：sign 578 / objective 310 / hanging_sign 44 / team 39 / block_entity_name 36 /
    book_page 34 / team_affix 10 / entity_name 4 / item_name 2 / book_title 2 /
    custom_name 1 / book_author 1 / level_name 1
  新增：command_say_text 150 / command_component_text 68
    （共 218 單位，正好等於相對 2026-09-01 M13a/M13b 全掃的增量；
     occurrence 增量 259 = command_say_text 151 + command_component_text 108）
跳過：4,507 新世代 chunk 舊式 JSON、4,288 已在地化、50,772 空白節點
```

三個新的指令文字 stats（活在 `result.stats` 內，**但 `extract/emit.py` 組
`stats` dict 時沒有把它們轉出來**，所以 `extract.json` 與 CLI 摘要都看不到——
見下方「本輪新發現的第 4 個缺口」）：

```
skipped_command_unsupported_shape = 113,692
skipped_command_nested_reference（L3）= 0
skipped_command_line_continuation  = 2,094
```

`skipped_command_unsupported_shape` 的 113,692 幾乎全是「白名單以外的動詞」，
**不是漏抽**：`data.zip` 有 2,613 個 `.mcfunction`、118,502 條非註解指令行，逐行
都呼叫 `scan_command_string()`，非白名單動詞就記一次後返回。逐動詞拆解
（`execute` 67,598、`scoreboard`〔players … 非 objectives add〕17,259、
`summon` 9,261、`give` 3,277、`data` 2,069、`kill` 1,791、`tag` 1,582、
`item` 1,288、`setblock` 1,138、`fill` 1,137、其餘尾巴）。這是設計行為
（只認白名單動詞），不是缺口。

**apply（no-op 譯文，真實寫入）**：

```
計畫要改的節點：3,331 → 實際寫入：3,331（unwritten 0，refuse 0）
改動的 chunk：463（原封複製 28,200 個）· 重寫的檔案：259
container.kind：region_chunk 2,714 / scoreboard_dat 361 /
  datapack_mcfunction_file 251 / entities_chunk 4 / level_dat 1
指令文字 edit：datapack_mcfunction_file 251、region_chunk 8
  ——MP2 的指令文字絕大多數在 .mcfunction 裡，不在指令方塊
value.kind：translate 2,704 / literal 366 / component 261
NBT list 提升：829
warnings：30（全部磁區重整，附前後大小）
備份：33 個檔案 → sandbox/.mcmt-backups/MP2/20260905-213155/
```

**還原**：把備份的 33 個檔案覆蓋回去、刪掉 apply 新建的 `resources.zip`（這份 MP2
匯入副本原本沒有 `resources.zip`）。三重覆核全部通過：(1) 33 個備份檔的 md5 與
還原後的世界 byte 一致；(2) `mcmt doctor` 輸出與寫入前 byte 完全相同；
(3) `world_fingerprint` == 匯入時記的 `blake2b:f688c4d4a49484a94f7083e742d4ae24`。

**Task 11 釘住的三個已知缺口，在 MP2 上的真實影響**：

| 缺口 | MP2 實際遇到 |
|---|---|
| **#1** `scan/command.py::_find_component` 不認命名空間組件鍵（`minecraft:custom_name=…`） | **遇到，佔比不小。** `give`/`item` 指令共 4,565 次出現，其中 **3,935 次**帶 `minecraft:custom_name=…`（命名空間形式），被 `_find_component` 拿裸字串 `"custom_name"` 比對比不到，整條記進 `skipped_command_unsupported_shape`，一個字沒抽。去重後只是 **8 個相異物品名**（`Jump Left`／`Jump Middle`／`Jump Right`／`Star Protector (Empty)`／`Star Protector (With Star)`／`Emerald Block`／`Diamond Block`／`Gold Block`；後三個看來是地圖自己 item-lock 系統的內部名，`emu_lock_name` 存同一字串），但 3,935／4,565 這個佔比說明真實 1.20.5+ 語料就是用命名空間寫的，非命名空間才是 fixture 的特例。 |
| **#2** `write/common.py::_decode_command_leaf` 不能還原「SNBT 字串包裝 JSON」的 `data merge` 訊息（三步 `command→snbt→json_component`） | **未遇到（0 次）。** MP2 的 21 個相異 `data merge block` 指令，訊息全是原生 compound（`{text:"Star Stealer",color:"yellow",…}`），沒有單／雙引號字串包一段轉義 JSON 的形式；`.mcfunction` 裡完全沒有 `data merge`。那 8 個 region 指令方塊的 `data merge` L2 路徑因此全部寫成功。〔2026-10-14 後記：這個形狀依 [遊戲實測 M0-3] 在 1.21.11 是字面亂碼，修法改為掃描端跳過並計入 `skipped_legacy_json_in_native_chunk`，不修寫入層——原「修寫入層」的推論保留在這一列，推翻理由見 `docs/STATUS.md` 缺口 B。〕 |
| **#3** `write/mcfunction_apply.py` 沒有重放守門 | **本輪不觸發，但潛在。** 251 筆 `.mcfunction` 指令文字 edit 走的是無守門路徑，首次 apply 正常寫入；只有「拿同一份 plan 對 `.mcfunction` 重放」才會靜默重蓋（region/entities 會拒），本輪只 apply 一次故未暴露。 |

> **[2026-09-06] #3 那一格的「靜默重蓋（no-op）」是錯的，保留原文並說明為何被推翻。**
>
> 「重蓋同樣的譯文、無害」這個結論來自 pinned 測試用的例子
> （`say Hello world` → `say 你好世界`）**剛好冪等**：走味的 span `[4,15]` 落在
> 9 字元的新字串上，仍然解析成「`say ` 之後的全部」。換一個在 extract 之後**長度
> 變了**的指令行重放，同一條路徑會從一個 token 的正中央切開，寫出語法壞掉的指令，
> 而 `outcome.unwritten` 是空的：
>
> ```
> plan 抽自：tellraw @a {"text":"Hello"}
> 重放到　：tellraw @s {"text":"Hello there, friend","color":"red"}
> 結果　　：tellraw @s {"translate":"mcmt.…","fallback":"Hello"}here, friend","color":"red"}
> ```
>
> 也就是說它跟 #2 不同：#2 失敗的方向是**拒寫**（安全），#3 失敗的方向是**寫壞**。
> 「MP2 本輪不觸發」仍然成立（只 apply 一次，且 `cli/apply.py` 的
> `world_fingerprint` 閘門涵蓋 `datapacks/**`），但「無害」不成立。
>
> **已補**（2026-09-06）：`_guard_by_length()`，資料夾式與 zip 式兩條路都接，判準
> 與拒寫理由重用 `write/common.py::_command_length_matches` 本尊。**殘餘**：
> `raw_snapshot` 逐位元組那一層還沒接（改成一樣長的另一句仍會被蓋掉），沒有一起接
> 的理由是 `_decode_command_leaf` 自己還帶著 #2 的缺陷——用一個已知壞掉的解碼器去
> 守門，是拿一個真缺陷換一個假保護。
>
> **這一格真正的教訓是關於證據，不是關於那個 bug**：pinned 測試挑了一個最方便的
> 例子，於是「測試是綠的」被讀成「行為是無害的」。釘住現狀的測試要挑**會痛的**例子。

> **[2026-09-06] 整支分支 review 另外抓到兩個不在這四項裡的缺陷，都已修。**
>
> * **`.mcfunction` 在複數 `functions/` 目錄下完全隱形，且沒有任何計數器。**
>   1.21 才改成單數 `function/`。[實測] `Arena of Darkness`（1.20.4）四個資料包共
>   **120 個 `.mcfunction` 全部**在複數目錄底下，全部被跳過——連 glob 都掃不到，
>   所以一個計數器都沒動，摘要跟「這張地圖沒有任何 function」逐位元組相同。
>   （`sources/datapack.py` 對 advancement 目錄早就解過同一題，邏輯沒被抄過來。）
>   MP2 沒暴露它是因為 MP2 的資料包用的是單數目錄。
>
>   **[實測 2026-09-06] 修正前後在 `Arena of Darkness` 上的實際數字**（唯讀掃描，
>   `scan/sources/mcfunction.py::scan`）：
>
>   | | 抽到的文字節點 | `skipped_command_*` 計數 | 有節點的檔案 |
>   |---|---|---|---|
>   | 修正前（只認單數） | **0** | **0**（一個都沒動） | 0 |
>   | 修正後（兩個都認） | **149** | 1,094 | 40 |
>
>   （第三欄的 40 是**至少產出一個文字節點**的檔案數，不是「120 個裡只掃到 40 個」
>   ——120 個 `.mcfunction` 全部掃到了，另外 80 個只含非白名單動詞，已全數計入
>   那 1,094 筆跳過。）
>
>   「0 個節點 ＋ 0 個計數」正是這個 bug 最惡劣的地方：使用者看到的輸出，與
>   「這張地圖真的沒有可翻的 function」**完全無法區分**。修正後那 1,094 筆
>   `skipped_command_unsupported_shape`（白名單外的動詞）現在是**看得見的**跳過。
> * **`data merge` 的裸字串訊息被寫成異質 SNBT list。**
>   `messages:["Hello","","",""]` 這個形狀原本走 translate key，splice 進一個 SNBT
>   compound，產出的 `TAG_List` 元素型別不一致，遊戲的指令解析器吃不下——指令方塊
>   寫得進磁碟、指令再也跑不動，而報告說 `unwritten: []`。**span 完全正確，錯的是
>   型別。** MP2 沒暴露它是因為 MP2 的 21 個 `data merge` 訊息**全是原生 compound**
>   （見上面 #2 那一格的同一個觀察）——同一個語料事實同時解釋了為什麼 #2 影響為 0、
>   以及為什麼這個更嚴重的缺陷一次都沒被照到。**一張語料掃乾淨了，不等於形狀都走過
>   一遍。**

**第 4 個缺口（plumbing，非安全）— 已於 2026-09-05 修正**：`extract/emit.py` 與
`cli/extract.py` 都補上了三個指令計數器（`skipped_command_unsupported_shape`／
`…_nested_reference`／`…_line_continuation`）的轉接，使其出現在 `extract.json`
與 CLI 摘要裡。使用者現在可以看到「指令文字漏抽了多少」。測試已涵蓋。

**結論**：

* **L3（巢狀指令參照）在 MP2 是 0**。方案 2（處理 `skipped_command_nested_reference`
  那類）在這張語料上零收益，不值得現在做。
* **行尾延續 2,094 條**（佔非註解指令行 1.8%）：無法在不重組多行指令的前提下便宜地
  判斷其中有多少帶可翻文字。同樣不急。
* 方案 1（白名單 `say`／`me`／`tellraw`／`title`／`bossbar`／`scoreboard objectives
  add`／`data merge`／`give`／`item`）在語料規模最大的 datapack（2,613 個
  `.mcfunction`）上一次寫入 251 筆 `.mcfunction` edit ＋ 8 筆指令方塊 edit，
  **0 筆拒寫，還原後世界指紋一致**。
* 缺口 #1 是唯一有實質漏抽的：帶命名空間 `custom_name` 的 `give`/`item` 物品名
  （MP2：3,935 次出現／8 個相異名）在修好前不會進待翻檔。

### tab 玩家列表 [實測]

tab 列表沒有專屬的文字欄位，它顯示的東西全部來自上面已列的路徑：

| tab 上看到的元素 | 實際來源 | 處理方式 |
|---|---|---|
| 玩家名字前後的裝飾 | `Teams[].MemberNamePrefix` / `MemberNameSuffix` | 翻譯（text component） |
| 隊伍名稱 | `Teams[].DisplayName` | 翻譯（text component） |
| 名字旁的分數 | `data.DisplaySlots.list` | **勿翻譯**，值是 objective 識別碼 |
| 表頭 / 表尾 | 不在存檔內 | 原版 Java 無指令可寫入存檔，是純封包功能 |

實測 fixture 的 `DisplaySlots` 內容為 `{'sidebar': 'tt_trans'}`——值是 objective 的 ID。翻掉會讓記分板顯示直接失效。`Minecraft Party 2` 則完全沒有 `DisplaySlots`（執行期才綁定）。

> `list` 槽是否會連帶顯示 objective 的 `DisplayName`，未進遊戲確認。但無論會不會，該路徑本來就在翻譯清單內，不影響實作。

### 自訂進度 [實測]

進度**定義**在 datapack 檔案裡不在世界 NBT 裡：

```
datapacks/<pack>/data/<ns>/advancement/*.json → display.title
datapacks/<pack>/data/<ns>/advancement/*.json → display.description
```

世界的 `advancements/<uuid>.json` 只存玩家**已達成狀態**，沒有顯示文字，不需處理。

> 1.21 起 datapack 目錄名改為單數：`function/`、`advancement/`（舊版是 `functions/`、`advancements/`）。

### datapack .mcfunction [實測]

```
datapacks/<pack>/data/<ns>/function/*.mcfunction
```

指令內含的 text component 需要解析指令語法才能取出。實測 `Minecraft Party 2` 的 `data.zip` 內有 **2,613 個 .mcfunction**，這是真實冒險地圖的規模。datapack 可以是資料夾也可以是 **zip 檔**，兩種都要支援。

### 指令方塊 [實測]

```
chunk → block_entities[].Command       ← 字串，內含巢狀 NBT/JSON
```

實測 fixture 的四個指令方塊分別藏著：
`say TT_CMDBLOCK_SAY_TEXT`、`tellraw @a {"text":"..."}`、
`give @s minecraft:stone[minecraft:custom_name={text:"..."}]`、`title @a title {"text":"..."}`

`Minecraft Party 2` 更狠，692 個指令方塊裡有這種：
`data merge block ~ ~-1 ~-1 {front_text:{messages:[{text:"Star Stealer",color:"yellow",click_event:{...}}]}}`
——**指令內含 NBT、NBT 內含 component、component 內又含指令**。這正是 maptranslator 的迭代式規則架構要解決的問題。

### 必須排除的路徑（實測發現的陷阱）

| 路徑 | 內容 | 為何危險 |
|---|---|---|
| `block_entities[].LastOutput` | 指令方塊上次執行輸出 | 執行期產物，含原版 key（`commands.fill.success`）。實測該地圖有 284 個 |
| `block_entities[].profile.properties[].value` | base64 皮膚材質 | 翻了破壞頭顱貼圖。實測 412 個 |
| `sections[].block_states.palette[].Name` | 方塊 ID | 翻了毀掉地形。實測 113,228 個 |
| `components."minecraft:custom_data"` | 地圖自訂資料 | 任意結構，常放 quest id 等識別碼 |
| `Objectives[].Name` / `CriteriaName` / `Teams[].Name` | 內部識別碼 | 指令會引用 |
| `...click_event.command` | 點擊執行的指令 | 是指令不是文字，但**內部可能又含文字**，需遞迴 |
| `PlayerScores[].Name` | 玩家名或變數名 | 識別碼 |

---

## Q3：translate key 在哪些欄位真的有效

下表**每一項都經過 1.21.11 遊戲畫面肉眼確認**，沒有任何一項是純結構推論。

初版報告曾把其中五項標成實測，但它們當時只有「該欄位存為 text component」這個結構依據。之所以不接受這種推論，是因為 `written_book_content.title.raw` 就是活生生的反例——它在結構上位於 component 位置，實際卻只吃字串。有這個反例在，結構推論在這個系統裡就不能當證據用。那五項後來以 `tt:verify` 補測，結果全部成立。

### 可用 translate key [全部遊戲實測]

| 欄位 | 遊戲內顯示 |
|---|---|
| 告示牌 `front_text/back_text.messages[]` | 鑽石方塊 |
| 物品 `components."minecraft:custom_name"` | 黃金方塊 |
| 物品 `components."minecraft:item_name"` | 鑽石方塊 |
| 物品 `components."minecraft:lore"[]` | 綠寶石方塊、黃金方塊（兩行都翻） |
| 書本 `written_book_content.pages[].raw` | 鑽石方塊 |
| 實體 `CustomName`（盔甲座、生物） | 鑽石方塊 |
| 實體 `text`（text_display） | 鑽石方塊 |
| 記分板 `Objectives[].DisplayName` | 鑽石方塊 |
| 記分板 `Teams[].DisplayName` | 鑽石方塊（`/team list` 輸出） |
| `CustomBossEvents.<id>.Name` | 鑽石方塊 |
| 進度 `display.title` / `display.description` | 鑽石方塊 |

### 必須直接替換原文 [遊戲實測]

| 欄位 | 證據 |
|---|---|
| `level.dat` → `Data.LevelName` | `TAG_String` 純字面。真實地圖存的是 `§l§kM §9§lM...` 舊式顏色碼而非 component |
| 書本 `written_book_content.title.raw` | **遊戲內直接顯示原始字串 `block.minecraft.diamond_block`** |
| 書本 `written_book_content.author` | `TAG_String`，無 component 包裝 |
| 草稿書 `writable_book_content.pages[].raw` | `TAG_String`，無 component 包裝 |

書名這一項是最乾淨的對照：同一本書的 `pages[].raw` 底下存的是 `{translate: ...}` compound 並正常翻譯，`title.raw` 底下只能存字串因而顯示原始 key。**你原本的懷疑正確。**

### 後果

`LevelName` 與書名/作者無法走資源包路線，只能直接改存檔文字。這代表工具**不可能做到「存檔完全不動、只靠資源包」**——至少這幾個欄位必須寫回存檔，所以備份機制是必要而非可選。

---

## Q4：resources.zip 機制

### 仍然有效 [實測]

證據不是文件，是一張正在運作的商業地圖：`Minecraft Party 2`（1.21.10）世界資料夾裡就有 `resources.zip`，87,035,223 bytes，內含 5 個語言檔（en_us、zh_cn、ja_jp、ru_ru、en_pt）。

### 格式要求

| 要求 | 實測結果 |
|---|---|
| 必須是 zip 而非資料夾 | ✅ `zipfile.is_zipfile` = True |
| 檔名與位置 | 世界資料夾根目錄，固定 `resources.zip` |
| level.dat 是否需登記 | **不需要**，隱含機制（該地圖 level.dat 只有 `DataPacks`） |
| 壓縮檔內部結構 | 根目錄直接是 `assets/`、`pack.mcmeta`、`pack.png`，**不可有外層包裹資料夾** |
| pack_format | 1.21.11 為 **75**。該地圖宣告 **55**（1.21.5 時代）仍正常出貨運作 |

**pack_format 過期的容忍度 [實測+推論]**：該地圖以 `pack_format: 55` 在 1.21.10 環境實際運作，是很強的間接證據，但「是否顯示警告」需進遊戲確認。保險做法：宣告 `75` 並加 `supported_formats` 區間。

### 額外發現：Minecraft 的 lang JSON 解析器是寬容的 [實測]

該地圖 5 個語言檔**全部無法通過 Python `json.loads`**，因為含 `//` 註解：

```
"menu.options": "§bOptions...", //Be sure to keep '§b' before the following text
```

Minecraft 用 GSON lenient 模式所以照樣運作。**工具產出時要寫嚴格 JSON**；若要讀取既有語言包，解析器必須容忍註解與尾逗號。

### 額外發現：key 命名慣例 [實測]

該地圖 `zh_cn.json` 共 **9,997 個 key**：

- 9,986 個在自訂命名空間 `mcp.` 底下，僅 7 個覆寫原版命名空間
- 語意化命名：`mcp.SignGamemode`、`mcp.SignTurn`、`mcp.Dice`
- 值本身仍可含 `§` 舊式顏色碼

建議直接沿用：**單一自訂命名空間 + 語意化 key**，不覆寫原版 key。

---

## 第二輪 probe（2026-08-16）：extra 巢狀 / filterable / 空值分佈

- 腳本：`spike/probe_components.py`（P1–P3 首輪）、`spike/probe_components2.py`（R1–R3 細分）
- 語料：5 張真實地圖，**單次 per-region 串流掃描**（一個 chunk 解壓→解析→走訪→丟棄，峰值記憶體為單一 chunk）
- 掃描範圍：`region/*.mca` 與 `entities/*.mca` 的 `block_entities` / `TileEntities` / `Entities` / `Level` 子樹，加 `level.dat`。方塊調色盤、高度圖、生態域按鍵名跳過。

| 地圖 | chunks | DataVersion 分佈 | 用途 |
|---|---|---|---|
| `Minecraft Party 2` | 120,218 | 3955 / **4325** / 4438 / 4440 / 4556 | 主語料，跨分水嶺 |
| `100 Ways To Die` | 9,892 | 3953 / 4082 / 4189 / **4325** | 邊界值大量存在 |
| `Questioning` | 7,529 | 3465 | 1.20 世代 |
| `LOST - Horror Map 1.12.10` | 7,523 | 4556 | 1.12 地圖已被完全升級 |
| `From Ashes Reborn 1.12 v03` | 17,064 | 1139 / 1241 / **None** | 完全未升級的 1.12 |

> **效能 [實測]**：MP2 的 120,218 chunk（203 region + 90 entities）單次掃描 **22.3 秒**。串流可行，計畫中「doctor 必須 per-region 串流」的驗收條件成立。

### 首要發現：DataVersion 不能決定節點的儲存形狀 [實測]

DataVersion **4556**（1.21.10，遠在分水嶺 4325 之後、應為 native）的 chunk 內，告示牌 `messages[]` 仍存在舊式形狀：

| 形狀 | 數量 | 說明 |
|---|---|---|
| `TAG_String ''`（零長度） | 39,106 | native 空值 |
| `TAG_String '""'`（2 字元） | **2,340** | 舊式 JSON 空字串，未被轉換 |
| `TAG_String '{...}'`（JSON 物件） | **110** | 舊式 JSON 內容 |

`'""'` 的 2,340 筆全部集中在 MP2（front 1,000 / back 1,340），且抽樣顯示**整面四行皆為 `'""'`**（585 面全空告示牌），其餘四張地圖為 0。

初版報告的「40,253 個空字串」因此拆解為：39,106 native 零長度 + 2,340 舊式 JSON 空字串（合計 41,446，與初版的 40,253 有差異，原因見下）。

**推測成因**（未經證實）：MP2 自身的 datapack 以 `data merge block` 寫入字面 `""`。spike 已記錄該地圖 692 個指令方塊含此類指令。

**架構後果**：`generation` **不可**由 `container.data_version` 推導。必須逐節點嗅探實際形狀。這推翻了主計畫「`generation` 由 `data_version` 導出、兩者同時攜帶以確保雙方一致」的設計。

**[待驗]**：遊戲如何算繪 native 世代下的 `'""'`——顯示為兩個引號字元，還是仍被當 JSON 解析為空？驗證方法：在 1.21.11 以 `data merge block` 寫入 `'""'` 並肉眼確認。這決定我們該把它當「空值」還是「字面文字」。

### 側發現：世界只要被開啟過，DataVersion 分佈就會改變 [實測]

同一張 MP2，初版與本輪的分佈不同：

| DataVersion | 初版 | 本輪 | 差 |
|---|---|---|---|
| 3955 | 51,369 | 51,369 | 0 |
| **4325** | 未列出 | **22** | +22 |
| 4438 | 47,148 | 47,159 | +11 |
| 4440 | 71 | 71 | 0 |
| 4556 | 21,448 | 21,597 | +149 |
| 合計 | 120,036 | 120,218 | +182 |

兩次之間該世界被遊戲開啟過，182 個 chunk 因載入而被 DataFixerUpper 升級。**這證明 extract 文件會因為「使用者只是進去看了一眼」而失效**，與世界檔案的 mtime/大小無關。主計畫 2.3 提出的 `extract_fingerprint` 需求由此獲得實證支持，且 fingerprint 不能只採 level.dat 的 mtime。

---

### P1 / R1：extra 巢狀 component [實測]

**結論：extra 大量存在於可翻譯路徑上，計畫的 1.1 條不作廢。**

| 地圖 | 帶 extra 的 component | 位於 denylist 路徑 | **位於可翻譯路徑** |
|---|---|---|---|
| Minecraft Party 2 | 3,073 | 812 | **2,261**（73.6%） |
| 100 Ways To Die | 2,828 | 2,604 | **224** |
| Questioning | 748 | 733 | **15** |
| LOST 1.12.10 | 101 | 101 | 0 |
| From Ashes Reborn | 289 | 288 | **1** |

首輪 probe 的 13.49% 曾誤導——抽樣例全是 `LastOutput`（denylist）。細分後 MP2 仍有 **2,261 個可翻譯的 extra 節點**。

MP2 可翻譯 extra 的巢狀深度：`1 → 2,083`、`2 → 166`、`3 → 12`（**最大深度 3**）。
extra 元素數分佈：`1 → 749`、`5 → 998`、`19 → 113`、`20 → 53`，長尾至 **34**。
**2,261 個之中有 1,904 個（84%）的 extra 子元素自帶格式屬性。**

MP2 可翻譯 extra 的前幾大路徑：

```
/block_entities[]/front_text/messages[]                                              377
/block_entities[]/Book/.../written_book_content/pages[]/raw/extra[]                  365
/block_entities[]/Items[]/.../written_book_content/pages[]/raw                       332
/block_entities[]/Book/.../pages[]/raw/extra[]/hover_event/name                      331
/block_entities[]/back_text/messages[]                                                91
/block_entities[]/front_text/messages[]/with[]                                        49
/block_entities[]/Book/.../pages[]/raw/extra[]/extra[]                                46
/block_entities[]/CustomName                                                          37
```

三個超出現行 schema 表達能力的實例：

```jsonc
// 1. 告示牌一行 = translate + extra(translate)，各自帶 color 與 fallback
//    這是 MP2 自己的中文化系統，我們必須能讀懂並重建
{ "translate": "mcp.Cost_", "fallback": "Cost:",
  "extra": [ { "translate": "mcp.CenterParkSlotMachineCost",
               "fallback": " 5 Coins", "color": "gold" } ] }

// 2. 空父節點 + 帶格式子節點（用來壓掉物品名的預設斜體）
//    若攤平重建時漏掉 italic:false，物品名會變回斜體
{ "text": "", "extra": [ { "text": "Letter E", "italic": false } ] }

// 3. 書頁 → extra → hover_event.name → 又是一個 component（331 筆）
//    文字藏在 hover_event 裡，現行 node_path 沒有這條路徑
```

**證據等級**：`[實測]`。跨 5 張地圖、13.7 萬 chunk。

**對主計畫的影響**：B 題結論「結構化格式走 `structural_format` 由寫入層原封搬運，一行內多段不同顏色根本不會出現」**證實為錯**。`extra` 就是一行內多段格式的標準表達，且 84% 帶自身格式。`format_codes` 的 `^(§…)+$` pattern 與單一 object 的 `structural_format` 都無法表達。1.1 的修正方向成立。

### P2 / R2：filterable 的 `filtered` 欄位 [實測]

**結論：包裝結構普遍存在，但 `filtered` 欄位在全語料中出現 0 次。**

| 地圖 | `written_book_content` | title 為 filterable 包裝 | pages 為 filterable 包裝 | 告示牌面 | **`filtered` 命中** |
|---|---|---|---|---|---|
| Minecraft Party 2 | 65 | 65 | 698 | 13,486 | **0** |
| 100 Ways To Die | 147 | 147 | 161 | 2,024 | **0** |
| LOST 1.12.10 | 26 | 26 | 208 | 2 | **0** |
| Questioning | 0 | 0 | 0 | 328 | **0** |
| From Ashes Reborn | 0 | 0 | 0 | 0（Text1-4） | **0** |

四條目標路徑（`title.filtered`、`written pages[].filtered`、`writable pages[].filtered`、`filtered_messages[]`）**全部為 0**。

這個零有意義而非取樣不足：語料中存在 **1,067 個 filterable 包裝**（238 title + 829 pages）與 **15,840 個告示牌面**，每一個都是 `filtered` 可能出現的位置，實際出現 0 次。`filtered` 僅在簽署書本／編輯告示牌當下聊天過濾為啟用狀態時才會被寫入。

**證據等級**：`[實測]`。

**對主計畫的影響**：3.2 不是 v1 阻塞項。但 `{raw, filtered}` 包裝本身 100% 存在（所有 238 個 title 都是包裝形式），所以 `title.raw` 的路徑處理仍然必要。建議做法：讀 `raw`；若同層存在 `filtered` 則寫入相同的 translate key（約 5 行防禦性程式碼）。`filtered_messages` 同理。

### P3 / R3：告示牌 messages[] 依 DataVersion 分組 [實測]

MP2：

| DataVersion | 元素分類 | 數量 |
|---|---|---|
| 4438 | `native_empty_zero_length` | 1,147 |
| | `bare_literal_nonempty` | 161 |
| | `native_compound_translate` | 109 |
| | `native_compound_text_nonempty` | 97 |
| | `native_compound_emptykey_empty` | 85 |
| | `native_compound_emptykey_text` | 81 |
| 4556 | `native_empty_zero_length` | 39,106 |
| | **`legacy_json_empty_quoted`** | **2,340** |
| | `bare_literal_nonempty` | 3,136 |
| | `native_compound_text_nonempty` | 2,572 |
| | `native_compound_translate` | 2,412 |
| | `native_compound_emptykey_empty` | 2,051 |
| | `native_compound_emptykey_text` | 497 |
| | **`legacy_json_content`** | **110** |
| | `native_compound_text_empty` | 40 |

DataVersion 3955（51,369 chunks）**完全沒有 `front_text/back_text` 形狀的告示牌**——該世代的告示牌若存在，會是 `Text1..Text4`。本輪在 MP2 未偵測到 `legacy_Text1_4`，代表 3955 區域內沒有告示牌，或告示牌都在已升級的區域。

**同一世代內六種形狀並存**（native compound 三種變體 × 空/非空、bare string、legacy JSON 空、legacy JSON 內容）。寫入層的分派不能只有 legacy/native 二分。

**證據等級**：`[實測]`。

### 額外發現：舊版地圖的結構差異遠大於「JSON 字串 vs 原生 NBT」[實測]

`From Ashes Reborn 1.12 v03`（DataVersion 1139/1241，882 個 chunk **完全沒有 DataVersion 欄位**）：

- chunk 根節點有 `Level` 包裝層，方塊實體在 `Level.TileEntities` 而非 `block_entities`
- 告示牌是 `Text1` / `Text2` / `Text3` / `Text4`（924 個），**沒有** `front_text` / `back_text`
- 書本在 `Items[].tag.pages` 而非 `components."minecraft:written_book_content"`
- 物品名在 `Items[].tag.display.Name`（`Questioning` 亦有 9 筆）

`legacy_json_array_form`（`["", {...}, {...}]` 形式，第一元素為父級其餘為 extra）：`100 Ways To Die` **66 筆**、`Questioning` **40 筆**。計畫 3.1 對此形式的預判正確。

**風險**：1.12 地圖在 1.21.11 開啟後，走過的區域升級、沒走過的維持原狀，**同一世界會同時存在 `Level.TileEntities`+`Text1-4` 與 `block_entities`+`front_text` 兩套完全不同的結構**。`LOST 1.12.10` 已被完整升級（全 4556）證明升級會發生；`From Ashes Reborn` 未被開啟證明不升級也會發生。

**建議**（待決策）：v1 明確只支援 `block_entities` + `front_text` 結構；`doctor` 偵測到 `Level.TileEntities` 或 `Text1-4` 時報錯並拒絕處理，而非半套支援。理由與 `.mcc` 相同——未測過的寫入路徑比拒絕處理危險。

#### 補充（2026-08-17，M1.3 實作時的全掃）[實測]：**混合結構不是 1.12 專屬，`Text1-4` 也不是 1.12 的標記**

`Find The Button No Cakewalk`（1.18.2，`mcmt doctor` 全世界 3 個維度、142 個 region 檔、**36,459 chunk**）：

| 結果 | chunk 數 | DataVersion |
|---|---|---|
| 通過 | 35,592 | 2865（25,622）· 2975（9,970） |
| `Level` 包裝層 | **852** | 主世界那 94 個抽驗為 **1963**（1.13.x） |
| `Text1..Text4` | **15** | **2975**（1.18.2） |

（先前只掃主世界時是 32,409 chunk / 94 個 `Level`；跨維度後才看到真正的量。）

兩件事因此要修正上面的說法：

1. **「同一世界兩套結構」不是 1.12 地圖的特例。** 一張 1.18.2 的地圖裡就有 94 個 1.13 世代、帶 `Level` 包裝的未升級 chunk。原文用 `From Ashes Reborn`（1.12）舉例容易讓人以為只要擋 1.12 就好。
2. **`Text1..Text4` 是「1.20 之前的告示牌格式」，不是「1.12 結構」。** 那 15 個 chunk 的容器是現代的 `block_entities`（root keys 有 `Heightmaps`/`block_ticks`/`Status`），只有告示牌欄位是舊的——`front_text`/`back_text` 要到 1.20（23w12a）才出現。所以偵測 `Text1-4` 攔下的是**告示牌格式**，與 chunk 容器的世代無關，兩者要分開理解。

拒絕的政策不變（未測過的寫入路徑比拒絕處理危險），但理由的精確描述應為：**v1 只支援 `block_entities` + `front_text`；任何一個 chunk 不符就拒絕整個世界。**

---

## 參考專案評估

### to2mbn/maptranslator（Java, GPLv2, 停在 1.12）[已讀原始碼]

架構是 `MARKERS`（`TagMarker` 陣列）+ `REPLACERS`（`NodeReplacer`/`TextReplacer` 陣列）。路徑表示法用括號引用既有標籤並支援萬用字元，例如 `"(entity)/Items/*"`；標籤可層層擴展成 `entity → entity.minecraft:villager` 的階層。宣告長這樣：

```java
tag("(store.level)/Data/LevelName", "level.name", translatable)

CommandReplacer.of("give <player> <item> <amount> <data> <dataTag>",
    "dataTag", args -> constructNBT(args.get("dataTag"))
        .withTag("itemtag")
        .withTag("itemtag." + toUniqueName(args.get("item"))))
```

**值得借用**：「規則反覆標記直到收斂」的不動點設計，能自然處理指令含 NBT、NBT 又含指令的遞迴。實測證明 1.21.11 資料確實有這種三層巢狀，這個設計對症。

**不能沿用**：規則的路徑內容因 1.20.5 組件化幾乎全部作廢；且它假設單一版本，無法處理發現 ① 的 per-chunk 多世代問題。另外它走的是**直接替換原文**路線，不是資源包路線，`translatable` 標記的語意與本專案不同。

### CrafterKolyan/minecraft-map-translator（Python）[已查證]

README 自述範圍是「translate signs and command blocks in Overworld, The Nether and The End」。`main.py` 只是 PySide2 GUI 啟動器，實際邏輯在 `ui/`。

僅就 README 宣告的範圍即可確認本次實測揭露的缺口：只處理告示牌與指令方塊，代表會漏掉容器內物品、書本、`entities/` 裡的具名生物與盔甲座、記分板、進度、datapack。當反面教材用即可。

---

## M0 遊戲實測（2026-08-17）：資源包路線與 native chunk 內的舊式 JSON

環境：Java Edition 1.21.11 全新世界（chunk DataVersion **4671**），世界根目錄 `resources.zip`，自訂命名空間 `mcmt`。一面告示牌兩面分別寫入兩種編碼，控制變因只有編碼形狀：

```
front_text: {has_glowing_text:0b, color:"black", messages:[{translate:"mcmt.test.hello"}, "", "", ""]}
back_text:  {has_glowing_text:0b, color:"black", messages:['{"translate":"mcmt.test.hello"}', '""', '""', '""']}
```

`zh_tw.json` 內 `"mcmt.test.hello": "哈囉世界"`。

### 結果

| # | 觀察點 | 結果 | 等級 |
|---|---|---|---|
| M0-1 | 正面第 1 行（native `CompoundTag{translate}`） | 顯示 **哈囉世界** | `[遊戲實測]` |
| M0-2 | 正面第 2–4 行（native 零長度 `""`） | 空白 | `[遊戲實測]` |
| M0-3 | 背面第 1 行（舊式 `'{"translate":...}'`） | 顯示**字面文字** `{"translate":"mcmt.`（被告示牌寬度截斷），**未被解析成 JSON、未解出 translate key** | `[遊戲實測]` |
| M0-4 | 背面第 2–4 行（舊式 `'""'`） | 顯示**字面的兩個引號** `""`，**不是空白** | `[遊戲實測]` |
| M0-5 | 以過期 `pack_format` 打包後載入 | 資源包清單**無紅字、無警告**；告示牌顯示完全不變（正面仍為哈囉世界） | `[遊戲實測]` |

兩點但書，記下來以免日後把這次的結論用超過它的射程：

- M0-5 未記錄所用的確切 `pack_format` 數值，也未記錄 `supported_formats` 是否同時移除。結論「過期不拒載」對世界資源包成立，但「多舊才會拒載」的邊界仍未知。
- 實際下的是 `/data merge block`（計畫寫的是 `/data modify ... set value`），且正面的 `messages` 是**混合 list**（第一元素 compound、其餘裸字串）。指令**被接受且正確顯示**，但**沒有做回讀取證**，所以「遊戲把這個混合 list 存成什麼形狀」仍然未知——很可能在編解碼時被正規化過。這不動搖 M0-1～M0-5 的顯示層結論（顯示是肉眼直接觀察的），但它**不能**被拿來當「NBT list 可以不同型」的證據。

### 三項結論

**① 資源包路線成立——整個架構的最終證明。**
自訂命名空間的 translate key 由世界根目錄的 `resources.zip` 解出並正確顯示中文。這是「尚待驗證」表首列的端到端證明的前半段（注入 + 資源包），剩下的只是把手打的 `/data modify` 換成工具寫入。

**② `[待驗]` 已解：native 世代下 `'""'` 算繪為字面引號。**
先前的處理決定（一律視為 `json_empty_quoted` 保留原樣，不當空值也不當字面文字）**維持不變**，但理由改變了：先前是「不知道所以不動」，現在是「已知它是壞掉的字面文字，動了會改變顯示結果，而修正顯示不是翻譯工具的職責」。

**③ 推翻一項先前的隱含假設：native chunk 裡的舊式 JSON 字串不是可翻譯內容。**

> **原假設（保留）**：第二輪 probe 發現 DV 4556 的 chunk 內有 2,340 筆 `json_empty_quoted` 與 110 筆 `json_string_object` 後，合約與 CLAUDE.md 把四種舊式 JSON 形狀一律列為「必須容忍的讀取形狀」，隱含假設遊戲仍會把它們當 JSON component 解析——只是儲存世代比較舊。
>
> **為何被推翻**：M0-3 證明在 DataVersion 4671 的 chunk 裡，`TAG_String` 就是**字面文字 component**，遊戲不會嘗試 JSON 解析。DataFixerUpper 只在 chunk 的 DataVersion **低於**目標版本時才會跑；DV ≥ 4325 的 chunk 不觸發修復，所以那些由 datapack 事後 `data merge block` 寫進去的 JSON 字串，在遊戲裡就是一堆可見的引號與大括號。

由此得到一個容易搞混但必須講清楚的不對稱：

- **DataVersion 不決定節點是什麼形狀**（第二輪 probe 已證，仍然成立）。
- **DataVersion 決定遊戲會不會替這個節點跑 DataFixer**，因而決定同一個舊式 JSON 字串是「真內容」還是「字面亂碼」。

v1 對策（見 CLAUDE.md 二節）：chunk DataVersion ≥ 4325 且節點為舊式 JSON 形狀 → **跳過不翻譯**，計入 `stats.skipped_legacy_json_in_native_chunk`，並在報告列出。理由與 `.mcc`、1.12 世界相同：翻了會寫回一個顯示結果同樣是亂碼的字串，等於在別人的地圖上留下我們造成的改動卻沒有任何好處。

「DV < 4325 的 chunk 由 DataFixer 升級後舊式 JSON 會被正確解析」目前是 `[文件]` 級推論，未實測——已列入尚待驗證。**→ 2026-08-17 由 M4 實測證實，見下節。**

---

## M4 遊戲實測（2026-08-17）：舊世代 chunk 的 legacy 寫入

### 程序

語料**不是**計畫寫的 Minecraft Party 2——全掃 207,515 個 chunk 後確認 **MP2 的 DV 3955 chunk 一面 `front_text` 告示牌都沒有**（與下方 P3/R3 一節的記載一致）。改掃 20 個世界後選用 `Arena of Darkness`（1.20.4）：**DV 3700 有 737 面告示牌**，且它們原本就在用 `json_string_scalar` 與 `'""'`。

用 `tools/m4_prepare.py` 在 `sandbox` 副本裡改寫 chunk 1022（DV **3700**）中 4 面**原本空白**的告示牌，四行都寫成 `TAG_String`（舊式形狀），一面告示牌問四個問題。完整程序見 `docs/m4-checklist.md`。

### 結果 [遊戲實測]

| 行 | 寫進去的字面內容 | 遊戲顯示 | 存回磁碟後的形狀 |
|---|---|---|---|
| 1 | `{"translate":"mcmt.test.legacy"}` | **哈囉舊世代** | `CompoundTag {translate: "mcmt.test.legacy"}` |
| 2 | `{"text":"對照組A 物件"}` | 對照組A 物件 | `CompoundTag {"": "對照組A 物件"}` |
| 3 | `"對照組B 純量"` | 對照組B 純量 | `CompoundTag {"": "對照組B 純量"}` |
| 4 | `""` | **完全空白** | `CompoundTag {"": ""}` |

### 五項結論

**① M4-1 舊世代 chunk 的 legacy 寫入路線成立。**
在 DV 3700 的 chunk 裡以舊式 JSON 字串寫入自訂命名空間的 translate key，1.21.11 由世界 `resources.zip` 解出並顯示中文。**`write/legacy.py` 的設計前提成立**，M11 不需要為舊世代另闢蹊徑。

**② M4-2 DataFixer 確實解析 DV < 4325 chunk 裡的舊式 JSON，且會就地轉成原生 compound。**
先前只有 `[文件]` 級推論，現在是直接對照實驗。三種形式（物件 / 純量 / 空字串）全部被解析。**存回磁碟時形狀被改寫**：`{"text": …}` 與純量都變成 **`{"": …}` 空鍵形式**，只有 `translate` 保持 `{translate: …}`。這也是 `empty_key_compound` 這個「必須容忍的讀取形狀」的來源——它不是某個工具的怪癖，是 Mojang `NbtOps` 的標準輸出。

**③ M4-3 分水嶺 4325 由對照實驗確立。**
同一個字面 `'""'`：在 native chunk（M0-4）顯示為**字面的兩個引號**；在 DV 3700 chunk 顯示為**空白**（磁碟上變成 `{"": ""}`）。同一份輸入、只差 chunk 的 DataVersion，結果相反。CLAUDE.md「DataVersion 決定遊戲會不會替這個節點跑 DataFixer」由此從推論升為 `[遊戲實測]`。

**④ M4-4 遊戲會升級玩家走過的 chunk，未走過的不動。**
開一次世界後，同一張 region 的 953 個 chunk 裡 **144 個從 3700 變成 4671、809 個仍是 3700**（改動的 chunk 1022 在被升級之列）。

> **對 v1 的影響**：「同一世界兩套世代並存」**不是**只有 1.12 舊地圖會發生，也不是我們造成的——**使用者開過一次世界就會發生**。工具「永不升級格式」的承諾仍然成立，但有一個前提要講清楚：**extract 當下嗅探到的 `encoding`，會因為使用者在中間玩過一次而失效**（舊式 JSON 被 DataFixer 轉成 `{"": …}`）。`world_fingerprint` 會抓到這件事（payload 變了），M11 的 `expected_encoding` 守門因此不是多餘的防呆，而是這個情境的唯一防線。

**⑤ M4-5 世界資源包的 `pack_format` 有下限——修正 M0-5。**

> **M0-5 原結論（保留）**：「世界資源包的 `pack_format` 過期時**不警告也不拒載**，照常生效。」那次是把 `pack_format` 從 75 下調到 **55** 並移除 `supported_formats` 測的。
>
> **為何要修正**：`Arena of Darkness` 自帶的 `resources.zip` 宣告 `pack_format: 22`（1.20.4），1.21.11 進世界前跳出「**無法套用伺服器資源包**」並拒絕套用，第 1 行因此顯示 key 本身而不是譯文。把同一個世界的 pack 換成 `pack_format: 75` + `supported_formats` 的最小 pack 後，同一個 chunk、同一面告示牌就正常顯示譯文。
>
> **修正後的說法**：`pack_format` 過期**在某個範圍內**不警告也不拒載（55 可以），但**有下限**，落在 22 與 55 之間。確切邊界 `[待驗]`。

> **對 M10 的硬需求**：地圖自己帶舊 pack 時，**不能只是把 lang 檔併進去**——整個 pack 會被拒絕，我們的譯文跟著陪葬。合併時必須同時處理 `pack.mcmeta`（加 `supported_formats` 或改 `pack_format`），而那是在改地圖自己的檔案，要在報告中明確告知使用者。

**排除的干擾項**：合併後的 zip 與原始在結構上等價（條目 329→331、`flag_bits` 全 0、CRC 逐項相同、`unzip -t` 通過），所以拒載不是合併造成的。

---

## 嗅探器對照實測（2026-08-17，M5.1）

`model/component.py` 寫完後拿它去跑三張真實地圖的告示牌 `messages[]`（`front_text`
與 `back_text` 都算），一方面驗嗅探器，一方面得到第一份**節點形狀分佈**。

| encoding | Minecraft Party 2 | 100 Ways To Die | Arena of Darkness |
|---|---:|---:|---:|
| `bare_string` | 44,550 | 5,700 | **0** |
| （其中 0 字元） | 41,119 | 4,839 | 0 |
| `compound_tree` | 5,234 | 2,396 | 0 |
| `empty_key_compound` | 2,734 | 0 | 0 |
| `json_empty_quoted` | **2,340** | 0 | 5,062 |
| `json_string_object` | **110** | 0 | 100 |
| `json_string_scalar` | 0 | 0 | 822 |
| **解析失敗** | 0 | 0 | 0 |

**與第二輪 probe 的數字逐項吻合**：MP2 的 `json_empty_quoted` 2,340 與
`json_string_object` 110，且都落在 DV 4556——嗅探器重現了獨立實作量到的結果。

三個新觀察：

1. **`empty_key_compound` 在 MP2 有 2,734 筆。** M4-2 證明它是 Mojang `NbtOps` 的
   標準輸出，這裡看到它在真實資料裡的規模——它不是邊緣案例。
2. **`Arena of Darkness`（DV 3700/3465）的 5,984 個節點全部是舊式 JSON 形狀**，
   一個 `bare_string` 都沒有。舊世代地圖與新世代地圖的形狀分佈是兩個世界。
3. **5.9 萬個節點、解析失敗 0。** 「JSON 解析失敗就跳過」這條保守規則在真實資料上
   幾乎不觸發，不會安靜地吃掉大量內容。

### 啟發式修正：前導引號不算 JSON 證據 [實測]

`100 Ways To Die` 有一行告示牌是 `"looks like you`——一句跨行的英文引述，收尾引號
在下一行。初版嗅探器把「前導 `"`」當成 JSON 純量的證據，於是判成解析失敗，那一行
就會被跳過不翻。

**修正後的規則**：前導引號**必須解析成功**才算 `json_string_scalar`；失敗就是
`bare_string`。理由是不對稱的——真的是 JSON 純量的話它會解析成功（`'"Queue Refight"'`
就成功了），而散文以引號開頭太常見。`{` 與 `[` 開頭**維持保守**（解析失敗仍標
`unparseable_json` 並跳過），因為散文極少那樣開頭。

---

## codec 對照實測（2026-08-21，M5.7）

`decode` 步驟以下是另一份文件；每個 codec 都要回答一件事：**重新編碼之後還是同一串
位元組嗎？** 不是的話，寫入層就只能用 `span` 做位移替換，不能整份重編。

| codec | 往返忠實 | 依據 |
|---|---|---|
| `json_component` | ✅ | 真實地圖 78 個舊式 JSON 節點，**compact 形式 78/78 位元組一致**；`json.dumps` 預設（帶空格）**0/78** |
| `lang_json` | ❌（註解會消失） | 讀寬容寫嚴格，見下 |
| `snbt` | **❌** | `amulet_nbt.to_snbt()` 會**把鍵排序** |
| `command` | — | 尚未實作，明確拒絕 |

### `snbt` 的往返不忠實 [實測]

    輸入  {text:"hi",count:3b,items:[1,2]}
    輸出  {count: 3b, items: [1, 2], text: "hi"}

鍵被排序了。所以 SNBT 文件**不能整份重編**——那會改到一堆沒被要求改的地方。這正是
合約裡 `decode.span` 與「同一父字串的編輯由後往前」存在的理由，不是理論上的謹慎。

### lang 檔的「寬容」要寬容到什麼程度 [實測]

先前只記了「MP2 的 5 個語言檔全部無法通過 `json.loads`」，沒記**為什麼**。實作時
用正則去註解與尾逗號，結果仍然 **0/5**。三個破口正則做不到：

1. `"mcp.Ztar": "Ztar", //An "anti star"` —— **註解裡有雙引號**
2. `// 1: "ClashAssassin", 2: "Loominardy"` —— 註解裡有冒號、逗號與引號
3. `zh_cn.json` 以 **UTF-8 BOM**（`EF BB BF`）開頭

而「去掉尾逗號」用正則還會誤傷字串內容裡的逗號（`"你好, 世界"`）。要正確就必須知道
「現在在不在字串裡」——也就是掃描器。

改成掃描器後：**MP2 5/5 通過，讀出 50,959 個 key**；`Arena of Darkness` 那個 131 MB
的 pack 也 1/1。

---

## denylist 全掃實測（2026-08-21，M6）

走過 MP2 的**每一個字串節點**（不是只走掃描層看得到的那些），問規則引擎「這條路徑
該不該翻」：

| 陷阱路徑 | 找到 | 漏掉 |
|---|---:|---:|
| `LastOutput` | 769 | 0 |
| `profile.properties[].value` | 1,498 | 0 |
| `palette[].Name` | **5,997,411** | 0 |
| `biomes.palette` | **4,561,951** | 0 |
| `custom_data` | 17 | 0 |

全世界 **12,262,582 個字串節點**，其中 **11,765,714 個（96%）被 denylist 擋下**，
只有 **406 種不同的路徑形狀**。

> 先前記的數字（`LastOutput` 284、`palette[].Name` 113,228）是單一維度或抽樣的結果；
> 這次是五個維度全掃，所以量級不同，不是矛盾。

### 逐條列舉會漏，整段擋才可靠 [實測]

規則第一版照著「必須排除的路徑」那張表逐條寫，拿自建 fixture 的 30 個真實 chunk 一跑
就漏了兩種：

1. **`biomes.palette` 是字串 list，不是 compound。** 方塊調色盤是
   `palette[].Name`（compound 裡的 Name），生態域調色盤是 `biomes.palette` 直接放字串
   ——`("palette", "Name")` 那條規則**完全認不到它**。fixture 30 個 chunk 就有 720 個，
   MP2 全掃 **456 萬個**。
2. `Status`（chunk 產生狀態）與 `id`（方塊實體型別）也是識別碼。

改成 **`sections` 底下整段擋掉**：那裡是方塊與生態域資料，沒有任何給人看的字，而方塊
實體是 chunk 根的兄弟節點不受影響。**這是「列舉已知陷阱」與「圈出已知安全區」的差別**
——前者漏掉的東西你不會知道，後者漏掉的東西會馬上炸在臉上。

---

## 混合 list 的問題由格式本身回答（2026-08-21）[實測]

**尚待驗證表裡「混合 list（compound + 裸字串）存到磁碟後是什麼形狀」是個假問題——
那種 list 不可能存在。**

NBT 的 `TAG_List` 在格式層就帶著**單一元素型別 id**，整個 list 共用：

```
>>> lst = ListTag([StringTag("a"), StringTag("b")])
>>> lst.list_data_type
8                                    # 8 = TAG_String
>>> lst[0] = CompoundTag({"text": StringTag("x")})
TypeError: Invalid type CompoundTag for ListTag(list_data_type=8)
>>> lst.append(CompoundTag())
TypeError: Invalid type CompoundTag for ListTag(list_data_type=8)
```

唯一的做法是**整個 list 換成新的**（`list_data_type=10`）。

因此 CLAUDE.md 的「list 為全 String 且要插入 Compound → **四行全部改寫**」不是設計
選擇，是**格式強制**的——寫入層根本沒有別的選項，連「不小心只改一行」都做不到，
amulet-nbt 會先擋下來。

> **M0 那次的疑問也一併解釋了。** 當時 `/data merge` 餵進去的是「第一元素 compound、
> 其餘裸字串」，指令被接受且顯示正確，所以留下「混合 list 到底存成什麼樣」的疑問。
> 答案是遊戲把整個 list 正規化了——[遊戲實測 M4-2] 直接看到這件事：寫進去 4 個
> `TAG_String`，遊戲存回磁碟時變成 4 個 `CompoundTag`。
>
> 原本標「M11 前必補、要進遊戲驗」的項目，實際上用一個 3 行的實驗就解掉了，而且
> 得到的是比遊戲實測更強的保證：這是格式的性質，不是某個版本的行為。

---

## M11 遊戲實測（2026-08-21）：完整來回 + CustomName 的形狀

工具第一次自己走完 `sandbox import → extract → 人工翻譯 → apply`，把翻好的探測世界
拿進 1.21.11。

### ① 工具產出的譯文正確顯示 —— **整條鏈成立** [遊戲實測]

告示牌全部顯示中文。這是「端到端：由**工具**產生的編輯計畫寫回存檔後遊戲正確顯示」
那一項——尚待驗證表的首列、標為**高**的那個——**現在成立**。

M0 證明的是「手動注入 + 資源包」這半段；這次是工具自己算出 key、自己產 lang 檔、
自己外科式寫回。中間沒有人手動下過任何一個 `/data` 指令。

同一個 chunk 裡本來就有的 `block.minecraft.diamond_block`（原版 key）照常顯示，
**沒有被誤傷**。

### ② 吊掛告示牌的寬度比一般告示牌窄很多 [遊戲實測]

`吊牌正面第一行`（7 個 CJK 字）在吊掛告示牌上**超出範圍被截掉**，正反面都是。
一般告示牌上同樣長度的中文完全正常。

目前 `constraints` 給吊掛告示牌的預算是 **60px**（`[待驗]` 的猜測值），一般告示牌是
90px。這次證實**兩者確實不同、而且 60px 的猜測仍然偏寬**——7 個 CJK 字放不下。

> **這是 M8 字寬校準的第一個真實資料點**，也證明那個里程碑不是可有可無：待翻檔的
> `note` 現在寫「寬度上限 60px（未校準，僅供參考）」，譯者照著翻就會超出。
> 校準前**不要**把 `enforcement` 從 `warn` 升成 `error`，但 `note` 的措辭應該更強硬。

### ③ CustomName 在 native chunk **不解析任何形狀**，只吃字面文字 [遊戲實測]

箱子的 GUI 標題顯示**字面的** `{translate:"mcmt.test.customname"}`。

寫進去的是 SNBT 形式（`{translate:"…"}`）。它是合法的 SNBT，若 `CustomName` 真的是
「component 的 SNBT」就會顯示譯文——**沒有**。

> **原本的假設（保留）**：探測世界的箱子存的是裸字串 `TT_CHEST_CUSTOM_NAME`，那既是
> 合法 SNBT 也是合法的折疊文字 component，所以推測 `CustomName` 是 component 的 SNBT。
>
> **為何被推翻**：SNBT 形式顯示為字面文字。`CustomName` 在 native chunk 的行為與
> [遊戲實測 M0-3] 的告示牌 `messages` **完全一致**——`TAG_String` 就是字面文字，
> 遊戲不做任何解析。

**因此 native chunk 的 `block_entity_name` 不能走 translate key 路線。** 它屬於
「必須直接替換原文」那一類，和 `LevelName` / 書名 / 作者 / 草稿書頁同組——合約的
`strategy: in_place` 正是為這種欄位存在的。

> **這句話的邊界要講清楚**（2026-08-21 補，實作 in_place 時發現原本的措辭比證據強）：
> 實測證明的是「`CustomName` 位置上的 `TAG_String` 是字面文字」，因此**寫字面譯文
> 這條路有實測依據**。它**沒有**證明「把該欄位換成 `TAG_Compound` 的
> `{translate:…}` 一定不行」——第二輪掃描本來就數到 **15 個原生 Compound 的
> `CustomName`**，那個形狀在真實地圖裡是存在的。
>
> 兩者的差別是：in_place 有依據、compound 提升沒有。v1 走有依據的那條，並且
> `write/in_place.py` 明確**不做** String → Compound 的提升。要改走 translate key
> 得先有一次遊戲實測，不是靠這一節推得出來。

**legacy chunk（DV < 4325）的 CustomName 仍未測**：那裡 DataFixer 會解析 JSON，
[遊戲實測 M4-1] 已證明告示牌的 `messages` 在 DV 3700 吃 JSON 字串的 translate key。
`Arena of Darkness` 的 9,579 個 CustomName 全部是 DV 3700 的 `'"@"'`，所以那條路
**可能**通——但那是推論，仍列尚待驗證。

---

## M8 + legacy CustomName 遊戲實測（2026-08-21）

同一次進遊戲做完兩件事：字寬校準，以及 DV < 4325 的 `CustomName` 該寫什麼形狀。

### ④ 字寬校準：四個數字全部命中校準前的猜測 [遊戲實測]

階梯（第 N 行放 N 個同樣的字），回報「最後一行完整顯示的是第幾行」：

| | ASCII（`M`） | CJK（`中`） |
|---|---|---|
| 一般告示牌 | **15** | **10** |
| 吊掛告示牌 | **10** | **6** |

換算後：**一般告示牌 90px（約 10 個中文字）· 吊掛 60px（約 6 個中文字）· CJK 9px**。

**這四個數字正是校準前的猜測值**，所以 [遊戲實測 M11-2]「7 個 CJK 字在吊掛上被截掉」
不是碰巧對上——`hanging_sign` 的 60px 從 `[待驗]` 升成 `[遊戲實測]`。

校準板另外給了粗體：**吊掛告示牌上 10 個粗體 `M` 只顯示 8 個**（一般告示牌全顯示）。
若粗體不加寬，10 個粗體 `M` 就和 10 個一般 `M` 一樣寬、在吊掛上會全部顯示；它沒有，
所以 `bold_extra = 1` 也升成 `[遊戲實測]`。

> **一個誠實的限制：階梯定的是比例，不是絕對 px。** 窮舉過所有與這四個觀察相容的
> 參數組，它們**全部是等比族**（ASCII : CJK 恆為 2 : 3）——把整張表乘以 2 也一樣相容。
> 絕對尺度來自「原版 ASCII 大部分字元 advance = 6px」這個 `[文件]` 級的錨。
>
> 這不影響工具：真正用到的是 `cjk_capacity`（一行放得下幾個中文字），那個數字只依賴
> 比值，就算尺度整體錯了它仍然是對的。已記在 `fontdata/vanilla_v1.json` 的 `scale_note`。

截圖交叉驗證了窄字表（同一張圖內的相對量測，不受相機距離影響）：

| 參考字串 | 預期墨水寬 | 螢幕量到 | 每遊戲 px |
|---|---|---|---|
| `l` × 10 | 29 | 170 | 5.86 |
| `t` × 10 | 39 | 228 | 5.85 |
| `MiMiMiMiMi` | 39 | 228 | 5.85 |

`t×10` 與 `MiMiMiMiMi` 量到**完全相同的寬度**，而它們的預期值也相同（都是 39）——
這同時釘住了 `t = 4` 與 `M + i = 8`。粗體那張圖：8 個粗體 `M` 對 `0123456789` 量到
516 : 546，預期 55 : 59，比值 0.945 對 0.932。

### ⑤ legacy chunk 的 `CustomName`：JSON 兩種都成立，裸字串會**弄丟名字** [遊戲實測]

在 `Arena of Darkness` 的 DV 3700 chunk（region `r.-3.1.mca` chunk 235）放三個箱子：

| 變體 | 寫進去的 | 開箱子看到 | 結論 |
|---|---|---|---|
| **A** JSON 純量 | `'"A 純量成功"'` | 「A 純量成功」 | **成立** |
| **B** JSON 物件的 translate key | `'{"translate":"mcmt.test.customname"}'` | 「自訂名稱翻譯成功」 | **成立**，資源包解得開 |
| **C** 非 JSON 的裸字串 | `'C 裸字串成功'` | **「大型儲物箱」** | **失敗，欄位整個被丟掉** |

**C 是這一輪最重要的結果，而且它是反面的。** 顯示出來的是原版的預設容器名，也就是
DataFixerUpper 沒能解析那個字串、整個 `CustomName` 欄位被丟棄了。所以：

> **在舊世代換掉節點的形狀會悄無聲息地弄丟別人地圖上的名字。**
> 「保留節點既有的形狀」在這裡不是保守的選擇，是唯一不會壞事的選擇。

**對 v1 的影響**：`write/in_place.py` 加上 `json_string_scalar` 與 `json_string_object`
兩種形狀（都是保留原形狀、只換文字），`extract` 的排除判準從「世代」改成「形狀有沒有
實測依據」。`Arena of Darkness` 的 CustomName occurrence 因此從 **9,579 全數排除** 變成
**9,581 個 0 排除**，並在同一張地圖上真的寫了一筆驗證（DV 3700 的旗幟，
`'"Letter F"'` → `'"測試譯文"'`，形狀與 DataVersion 都沒變）。

> **B 成立代表舊世代的 `CustomName` 可以走 translate key 路線**（一份存檔支援多語言）。
> v1 不走：`strategy` 是 per-unit 的，而同一段原文可能同時有 native 與 legacy 的
> occurrence，native 那邊 translate key 不成立（M11-3）。留給 v2。

> **一個沒有排除的可能**：C 那個箱子若剛好與旁邊的箱子併成大型儲物箱，顯示預設名也
> 可能是雙箱的命名邏輯造成的，而不是欄位被丟掉。沒有再驗一次，因為它不影響任何決定
> ——`in_place` 保留形狀，永遠不會產生 C 那種寫法。記在這裡是為了不把推論說得比證據強。

---

## Minecraft 26.2 遊戲實測（2026-09-03）：新版本上的材質包過期

第一次有真實使用者在**比 1.21.11 新**的版本上跑完整條鏈。地圖 `all-the-same`，
遊戲版本 **26.2**（`version.json`：`resource_major` 88 / `world_version` 4903）。

### ⑥ `supported_formats` 上限卡在 75 → 26.2 判整包過期 [實測 → 已修]

`mcmt apply` 產的 `resources.zip` 宣告 `supported_formats {min:75, max:75}`
（`pack.py` 的 `PACK_FORMAT = 75` 寫死成 1.21.11）。26.2 的材質包格式是 88，
落在 `[75,75]` 之外 → 遊戲判定過期、**拒絕整個世界資源包**，連 `assets/mcmt/
lang/zh_tw.json` 一起沒生效。告示牌顯示 key 本身而不是譯文。

**這推翻了 M0-5 的前半。** M0-5（在更早版本上）記「世界資源包 `pack_format` 過期
不警告也不拒載」；M4-5 已經把它修正成「有下限」；這次證實**上限那側 1.21.11 之後
也會拒載**——只要遊戲的格式高過 pack 宣告的 `supported_formats.max_inclusive`。

**修法（commit `2be79c7`）**：`supported_formats` 上下限都開很寬——
`MIN_PACK_FORMAT = 4`（JSON lang 檔第一次存在的版本 / 1.13）到
`FORWARD_PACK_FORMAT = 9999`（實質無上限）。`pack_format` 主宣告維持 75。
合併地圖自帶的舊 pack 時只把上限推到 9999、下限維持地圖宣告值。
**取捨**：未來 Mojang 真的改了 lang 檔或資源包載入邏輯時，這個包會**默默失效**
（遊戲仍載入、譯文不顯示），不是乾淨的錯誤——這個工具不保證跟上每個遊戲版本，刻意接受。

### ⑦ NBT 寫回不受版本影響 [實測]

同一份 `sandbox/all-the-same`（DataVersion 4903 的 chunk）extract → apply：
28 筆 edit 全寫入、0 拒寫、原封複製 1,561 個 chunk、list 提升 12。逐 chunk 讀每個
自己的 DataVersion、寫回同一個世代——4903 不在任何寫死的表裡也照走。
「per-chunk 世代分派」對未知的新 DataVersion 直接成立。

### ⑧ 修正後的完整結果 [遊戲實測]

換上 `supported_formats {75, 9999}` 的 `resources.zip` 後，26.2 進 `all-the-same`：
**告示牌與書本的譯文全部正確顯示**，材質包清單無過期提示。使用者原話「翻譯得非常
完美」。這是資源包路線第一次在 1.21.11 以外的版本上 `[遊戲實測]`。

---

## 尚待驗證

> 已完成：寫入端編碼對照（兩種皆有效）、Q3 五個結構推論項（全部成立）、第二輪 P1/P2/P3（extra 巢狀、filterable、空值分佈）、M0 遊戲實測（資源包路線、`'""'` 算繪、`pack_format` 過期）、**M4 遊戲實測（舊世代 legacy 寫入、DataFixer 解析、世代升級、`pack_format` 下限）**。

| 項目 | 驗證方法 | 重要性 |
|---|---|---|
| ~~**端到端**：由**工具**產生的編輯計畫寫回存檔後遊戲正確顯示~~ | ~~跑完整流程~~ | **已完成（2026-08-21，M11）**：`extract → 人工翻譯 → apply` 全程由工具完成，告示牌全部正確顯示中文，同 chunk 的原版 key 節點沒被誤傷 |
| ~~**DV < 4325 的 chunk 經 DataFixer 升級後，舊式 JSON 是否被正確解析**~~ | ~~肉眼確認~~ | **已完成（M4-2 / M4-3）**：三種舊式形式全部被解析，且存回磁碟時轉成 `{"": …}`。4325 分水嶺由對照實驗確立 |
| ~~舊世代 chunk 寫入 translate key 後是否正確顯示~~ | ~~在舊世代 chunk 寫入後用 1.21.11 開啟~~ | **已完成（M4-1）**：DV 3700 chunk 寫入 legacy JSON translate key，資源包解出中文。舊世代寫入**原生** component 的變體仍未測，但 M4-2 顯示遊戲自己就會把舊式轉成原生，風險已大幅降低 |
| `pack_format` 拒載的確切下限 | 在 22 與 55 之間逐級測試 | 中 — M4-5 已證明有下限（22 被拒、55 可用），邊界值影響 M10 合併既有 pack 時該宣告什麼 |
| **`extra` 攤平後重建是否保真** | 取 MP2 的 `{translate+extra(translate)+fallback+color}` 實例，攤平→翻譯→重建→寫回→進遊戲比對 | **高**，決定 1.1 的 schema 修正是否足夠（第二輪 R1） |
| **`hover_event.name` 內的文字是否需翻譯** | MP2 有 331 筆；進遊戲確認滑鼠停留時是否可見 | 中，影響掃描範圍（第二輪 R1） |
| ~~**混合 list 存到磁碟後是什麼形狀**~~ | ~~回讀取證~~ | **已完成（2026-08-21）**：那種 list **不可能存在**——`TAG_List` 在格式層就帶單一元素型別。四行全部改寫是格式強制的，不是設計選擇。見上一節 |
| MP2 那 585 面全 `'""'` 告示牌是否真的顯示引號 | 在 sandbox 副本裡走到現場肉眼確認 | 中 — M0-4 的直接推論，成立則證實那是地圖自身的顯示瑕疵，工具不應「順手修好」 |
| ~~`pack_format` 多舊才會拒載~~ | ~~逐級下調~~ | **部分完成（M4-5）**：22 會被拒（「無法套用伺服器資源包」），55 不會。M0-5 的「過期不拒載」需限縮為「在某個範圍內」。確切邊界見上一列 |
| ~~**方塊實體 `CustomName` 在 native chunk 該寫成什麼形狀**~~ | ~~進遊戲測~~ | **已完成（2026-08-21）**：**不解析任何形狀**，SNBT 顯示為字面文字。native 的 `block_entity_name` 只能走 `in_place`（直接替換原文） |
| ~~**legacy chunk 的 `CustomName` 吃不吃 JSON 的 translate key**~~ | ~~在 DV 3700 的 chunk 寫進去開箱子看標題~~ | **已完成（2026-08-21，⑤）**：JSON 純量與 JSON 物件的 translate key **兩種都成立**；非 JSON 的裸字串**失敗且欄位整個被丟掉**。9,581 個 occurrence 已全部解開 |
| ~~**吊掛告示牌的實際寬度上限**~~ | ~~M8 字寬校準~~ | **已完成（2026-08-21，④）**：**60px（約 6 個中文字）**，一般告示牌 90px、CJK 9px、粗體 +1。四個數字全部命中校準前的猜測，所以「60px 偏寬」那個推測是錯的——它剛好就是對的 |
| region 是否會出現 LZ4 (type 4) | 對更多來源的地圖跑 `probe_compression.py`，特別是伺服器匯出的 | 中 — 第二輪 5 張地圖 16.2 萬 chunk 全為 type 2，仍未見 type 4 |
| **type 4 的實際位元組框架** | 拿到真實 type 4 chunk 後，用 `nbtio/compression.py` 的 `_decompress_lz4` 對它跑一次 | 中 — `[文件]` 級：Mojang 走 lz4-java 的 `LZ4BlockOutputStream`（`"LZ4Block"` magic + 每區塊 21 bytes 標頭），**不是**標準 LZ4 frame。M1.1 已照此格式實作並以手寫編碼器測過，但沒有任何真實樣本走過這條路徑 |
| 外部 `.mcc` 檔 | 需要找到含 `.mcc` 的地圖 | 低 — 第二輪 5 張地圖 16.2 萬 chunk 外部 chunk 數為 **0** |
| `{"": v}` 是否為 `NbtOps` 通則而非告示牌專屬 | 讀 Mojang 原始碼，或對其他 component list 做同樣測試 | 低，不影響實作 |
| ~~`extra` 巢狀是否存在~~ | ~~掃描 MP2~~ | **已完成**：可翻譯路徑上 2,261 筆，最大深度 3，84% 帶自身格式 |
| ~~四條 filterable 路徑出現次數~~ | ~~掃描 MP2~~ | **已完成**：1,067 個包裝機會、15,840 個告示牌面，`filtered` 命中 **0** |
| ~~告示牌空值依世代分佈~~ | ~~重跑 messages[] 統計~~ | **已完成**：39,106 native 零長度 vs 2,340 舊式 `'""'`，且同存於 DV 4556 |
| ~~native 世代下的 `'""'` 如何算繪~~ | ~~1.21.11 寫入字面 `'""'` 肉眼確認~~ | **已完成（M0-4）**：顯示字面的兩個引號，不是空白 |
| ~~自訂命名空間 translate key 是否由世界資源包解出~~ | ~~M0 手動注入~~ | **已完成（M0-1）**：正確顯示 |
| ~~`pack_format` 過期是否只警告不拒載~~ | ~~刻意用過期號打包載入觀察~~ | **已完成（M0-5）**：無警告、無紅字、照常載入 |
| `Teams[].MemberNamePrefix`/`MemberNameSuffix` 的 translate key 是否真的顯示 | 在一支隊伍上設定非空的前後綴、寫入 translate key、`/team list` 或 tab 列表肉眼確認 | 低 — 兩張語料地圖的實際內容全空，沒有實測動機驅動；`Objectives`/`Teams[].DisplayName` 本身已經是 [全部遊戲實測] |
| `scoreboard.dat`（DV < 4325）的 legacy JSON 字串寫入是否被 DataFixer 正確解析 | 在一個 DV 3700 的 `scoreboard.dat` 寫入 JSON 字串型 translate key，1.21.11 開啟後看 `/scoreboard objectives list` 或側邊欄 | 中 — 與 chunk 層級的 M4-2 是同一個機制（DataFixerUpper 對任何版本化 NBT 文件一視同仁），但 `.dat` 檔本身沒有被單獨驗證過；寫入器完全沿用 M4 已驗證的 legacy.py，風險主要在「機制是否真的對 `.dat` 檔案一視同仁」這個推論本身 |
| **指令文字（command text）進遊戲算繪** — ① `tellraw` 的 `{"translate":key}`、② `data merge` 寫的告示牌、③ `say`／`me` 的 in_place、④ `_snbt_string_literal` 的雙引號＋反斜線跳脫被 1.21.11 指令解析器接不接受 | 可重跑程序見 **`docs/m-command-checklist.md`**（在 `TT_WORLD_NAME_PROBE` 手動佈置四個指令方塊＋一塊告示牌，跑 extract／apply，進遊戲肉眼核對） | **中** — 程式碼／單元／端到端／MP2 全掃已驗（見「指令文字方案 1 MP2 全掃」），只差遊戲算繪。④ 目前 `[待驗]`，且與已知缺口 #2（`_decode_command_leaf` 讀不回字串包裝 JSON）解耦——checklist 第四節用手打指令直接問解析器；若雙引號形式被拒，補救是把 `write/command_span.py::_snbt_string_literal` 改成單引號分隔。〔2026-10-14：缺口 #2 改為掃描端跳過；④ 的預期改成「形式 A／B 都顯示字面文字」，另新增 4e 控制字元跳脫（`[文件]` 1.21.5 起 SNBT 支援 `\n` 等跳脫，1.21.11 `[待驗]`）。〕 |

---

## 附錄：spike/ 內容

| 檔案 | 用途 |
|---|---|
| `probe_pypi.py` | 候選函式庫的 PyPI 維護狀況 |
| `probe_api.py` | amulet-nbt / amulet-core 實際 API 內省 |
| `probe_world_meta.py` | level.dat、scoreboard.dat、resources.zip |
| `probe_libs.py` | Q1 主測（含手刻 region 讀取器） |
| `probe_libs_alt.py` | Q1 其餘函式庫實測 |
| `probe_roundtrip.py` | 外科式讀改寫驗證，含約 90 行 anvil 讀寫骨架 |
| `probe_text_paths.py` | Q2 路徑簽章掃描 |
| `probe_chunk_versions.py` | 發現 ① 的 per-chunk DataVersion 統計 |
| `probe_resourcepack.py` | Q4 資源包機制 |
| `probe_misc_sources.py` | bossbar、datapack、進度、lang 慣例 |
| `probe_tablist.py` | tab 玩家列表的文字來源與 DisplaySlots |
| `probe_compression.py` | L1/L2 分層一致性、壓縮類型與 `.mcc` 分佈 |
| `probe_verify_emptykey.py` | 發現 ③ 的雙讀取器 + 標註位元組交叉驗證 |
| `write_sign_variants.py` | **反向驗證：兩種編碼各寫一面告示牌**，並示範原樣複製規則 |
| `probe_dump_fixtures.py` | fixture 原始 NBT 傾印 |
| `probe_manual.py` | 手打文字的存法、translate 探針交叉比對 |
| `probe_raw_nbt.py` | **位元組層級 NBT 解析，不依賴任何函式庫** |
| `probe_crosscheck.py` | nbtlib 交叉驗證（API 不符，已由 `probe_raw_nbt.py` 取代） |
| `probe_components.py` | **第二輪 P1/P2/P3**：extra 巢狀、filterable、messages 依 DataVersion 分組。單次 per-region 串流 |
| `probe_components2.py` | **第二輪 R1/R2/R3**：extra 按 denylist 細分、filterable 母體普查、`'""'` 上下文定位 |
| `testpack/` | 測試 datapack，一行指令生成所有 fixture |
| `install_testpack.ps1` | 把測試 datapack 裝進最新的世界 |

測試世界 `TT_WORLD_NAME_PROBE` 在 `%APPDATA%\.minecraft\saves\`，可保留供後續端到端驗證，或直接刪除。
