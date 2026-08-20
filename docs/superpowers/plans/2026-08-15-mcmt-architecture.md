# Minecraft 地圖翻譯工具（mcmt）實作計畫 — rev.2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Subagent 的任務範圍不得跨越模組邊界**（見 `docs/ownership.md`），尤其不得在非 write 任務中修改 `src/mcmt/write/` 或 `src/mcmt/safety/`。

**Goal:** 把 Minecraft Java 1.21.11 冒險地圖裡的可見文字抽成一份人類好編輯的待翻檔，翻完之後以資源包路線寫回成中文化地圖，過程中除了必須修改的節點外不動存檔任何一個位元組。**翻譯由使用者自己完成，工具不碰任何 API。**

**Architecture:** 四層流水線（掃描 → 建樹 → 規則標記 → 輸出後端），四份 JSON 合約作為層間介面；翻譯是**使用者在兩個指令之間做的事**，不是流水線的一層。寫入層獨立於輸出後端，負責 per-chunk DataVersion 分派、NBT list 同型、外科式重寫與備份。

**Tech Stack:** Python 3.11+ · `amulet-nbt` 2.1.8 · 自寫 anvil 層 · stdlib · `pytest` + `jsonschema`（dev）· GPLv3。**無網路相依。**

**Spec:** `SPIKE_RESULT.md`（含 2026-08-16 第二輪 probe 結果）

**開發模式：單人。** 本計畫不含要落地的實作程式碼；任務步驟裡的程式碼區塊是規格。

## rev.2 相對 rev.1 的變更

| 變更 | 原因 |
|---|---|
| `generation` 不再由 DataVersion 推導 | [實測] DV 4556 內有 2,340 個舊式 JSON 空字串 |
| B 題結論推翻重寫 | [實測] 2,261 個可翻譯 `extra` 樹，深度至 3，84% 帶自身格式 |
| hash 10 hex → 16 hex；輸入改為 `source.text` | 40 bits 在 5 萬條目下碰撞率 11%；帶 extra 的樹沒有單一 `raw` |
| 新增第四份合約 `apply_report.schema.json` | 寫入層的拒絕原因原本沒有出口 |
| 任務順序：端到端最小驗證提前到最前 | 成本以小時計，卻能證偽整個架構 |
| legacy 寫入驗證從 M7.4 提前 | legacy 佔 43%，讀取形狀比 native 更雜 |
| 字寬校準提前到翻譯層之前 | 寬度預算反向決定 prompt 怎麼寫 |
| 後端 A（直接替換）移出 v1 | 單人後工作量翻倍，風險對沖價值已由端到端驗證取代 |
| v1 拒絕舊結構世界與 `.mcc` | 未測過的寫入路徑比拒絕處理危險 |

---

## Global Constraints

每個任務的驗收條件都隱含包含這一節。完整規範見 `CLAUDE.md`。

- **目標版本** Java Edition 1.21.11 · DataVersion 4671 · `pack_format` 75
- **DataVersion 決定寫回哪個世代，不決定節點形狀。** `occurrence.encoding` 由逐節點嗅探決定，是唯一權威
- **外科式寫入**：未修改的 chunk 原封複製原始壓縮位元組。timestamp 表：未改的原樣搬運、改過的更新為當下時間
- **NBT list 同型**：全 String 的 list 插入 Compound 時四行全部改寫；已是 Compound 則只動目標
- **讀取容忍 7 種形狀**：`bare_string` / `empty_key_compound` / `text_compound` / `json_string_scalar` / `json_string_object` / `json_string_array` / `json_empty_quoted`；解析失敗 → 跳過並計數，絕不當裸文字
- **寫入用 `{"text":...}`，但只限被修改的節點**
- **4 個 `in_place` 欄位**：`LevelName`、`title.raw`、`author`、草稿書 `pages[].raw`
- **絕不翻譯**：`LastOutput`、`profile.properties[].value`、`palette[].Name`、`custom_data`、`Objectives[].Name`/`CriteriaName`、`Teams[].Name`、`PlayerScores[].Name`、`DisplaySlots.*`
- **v1 拒絕**：外部 `.mcc`、`Level.TileEntities` / `Text1..Text4` 結構、`data_version` 為 null 的 chunk
- **安全**：寫入限 `sandbox/`；讀取走 `ensure_readable`；強制備份，失敗即中止；未知壓縮類型必須報錯
- **`SCHEMA_VERSION` = 2**，四份合約共用，不符即失敗，無向下相容
- **授權** GPLv3，每檔 SPDX 標頭；不得逐段對照 maptranslator 原始碼（`docs/adr/0007`）

---

## 1. 目錄結構

```
minecraft-map-translate/
├── CLAUDE.md                    # 專案規範（規則的真相來源）
├── LICENSE                      # GPLv3
├── pyproject.toml
├── SPIKE_RESULT.md              # 證據的真相來源
├── docs/
│   ├── contracts/               # ★ 四份 schema，SCHEMA_VERSION 2
│   │   ├── extract.schema.json
│   │   ├── translations.schema.json
│   │   ├── editplan.schema.json
│   │   └── apply_report.schema.json
│   ├── adr/0001..0007
│   ├── ownership.md             # 模組邊界
│   ├── journal/                 # 卡住超過 30 分鐘就寫這裡
│   └── superpowers/plans/
├── src/mcmt/
│   ├── errors.py
│   ├── safety/  paths.py · backup.py
│   ├── nbtio/   compression.py · region.py · datfile.py
│   ├── model/   generation.py · node.py · component.py · segments.py · unit.py
│   ├── scan/    world.py · sources/{region,entities,leveldat,scoreboard,datapack}.py
│   ├── tree/    build.py · codecs/{json_component,snbt,command}.py
│   ├── rules/   engine.py · matcher.py · registry.py · sets/*.py
│   ├── extract/ keys.py · placeholders.py · flatten.py · width.py · constraints.py · emit.py
│   ├── translate/ batching.py · prompt.py · validate.py · glossary.py · provider/*.py
│   ├── backends/ base.py · resourcepack/{lang,pack,backend}.py
│   ├── write/   planner.py · legacy.py · native.py · rebuild.py · apply.py
│   ├── report.py
│   └── cli/     __main__.py · doctor.py · sandbox.py · extract.py · translate.py · apply.py
├── tests/{unit,integration,fixtures/{regions,contracts,golden}}
├── tools/  make_fixture_region.py · calibrate_font_widths.py
└── sandbox/                     # .gitignore；唯一允許寫入的地方
```

相較 rev.1 的新增：`model/segments.py`（攤平與段落）、`extract/placeholders.py`（遮罩／還原／驗證）、`extract/flatten.py`（component 樹攤平與骨架）、`write/rebuild.py`（非塌縮樹的重建）、`docs/journal/`。移除：`backends/inplace/`（移出 v1，介面保留在 `base.py`）。

**例外階層** — 相較 rev.1 新增三個：

```
McmtError
├── SafetyError            PathOutsideSandbox / MinecraftSavesPath / BackupFailed
├── FormatError            UnknownCompression / ExternalChunk / TruncatedRegion
│                          UnsupportedWorldStructure ★ / UnparseableComponent ★
├── ContractError          SchemaVersionMismatch ★ / FingerprintMismatch / PlaceholderMismatch
├── RuleError              RuleEngineDidNotConverge ★
└── WriteError             NodeChanged / ListHomogeneity / PlaceholderResidue ★
```

---

## 2. 四份合約

完整定義在 `docs/contracts/*.json`。這裡只講設計要點。

| 合約 | 生產者 → 消費者 | 為什麼獨立存在 |
|---|---|---|
| `extract.json` | 第 3 層 → 第 4/5 層 | 掃描結果與翻譯解耦；可重跑翻譯而不重掃 |
| `translations.<lang>.json` | **使用者** → 第 5 層 | 與 extract **欄位重疊 0%**；是人工複審介面；每語言一份；增量翻譯需要 diff 兩份 |
| `editplan.json` | 第 5 層 → 寫入層 | 輸出後端可插拔（決策 7）；`--dry-run` 的可檢查中間產物 |
| `apply_report.json` | 寫入層 → 使用者 | 寫入層的拒絕原因需要機器可讀的出口 |

### 為什麼三份保留（5.4 重評）

`translations` entry 的七個欄位（`text`/`status`/`origin`/`measured_width_px`/`warnings`/`notes`/`alternatives`）**沒有一個是 extract 的複製**；`unit_id` 是外鍵不是複製。重疊率 0%，合併論證不成立。合併的實際損失：多語言要塞成巢狀 dict、每次翻譯重寫整份 extract（MP2 規模數十 MB）、增量翻譯無法 diff。

`extract` 與 `editplan` 的分離理由改寫為：**輸出後端可插拔（決策 7 的架構要求）** 與 **`--dry-run` 需要一個可檢查的中間產物**。原本「不讓協作者的後端層理解 chunk 格式」的論證已失效。

`tests/fixtures/contracts/` 的定位從「兩人獨立開發的依據」改為 **分層回歸測試 fixture**。

### 三個關鍵設計

**`unit_id` 與 `key` 的 discriminator 是同一個字串**，同一個函式產生一次。`u:sign:7f3a91c204d5e618` ↔ `mcmt.sign.7f3a91c204d5e618`。消歧走 discriminator 內的 `_1`（兩者都變），段落序號走 key 尾綴的 `.0`/`.1`（只有 key 有）。

**`unit` 是一段文字，`occurrence` 是它出現的地方。** 樣式**值**在 occurrence（同一句話的金色版與紅色版是同一個翻譯單位），段落**切點**在 unit（切點不同必然是不同單位，因為 `[[n]]` 數量不同）。

**`decode` 步驟標記「這裡以下是另一份文件」。** 寫入層由內往外逐層重新編碼。同一父字串多處編輯必須**依 span 降序**處理。

---

## 3. A / B / C 三題（B 題已推翻重寫）

### A. translate key 生成 — 混合 + `keymap.json`

方案比較維持 rev.1 的結論（純 hash / 座標路徑 / 混合），選**混合**。但規格修正三處：

```python
hash_input    = f"{SCHEMA_VERSION}\x1f{category}\x1f{source.text}"
discriminator = blake2b(hash_input.encode("utf-8"), digest_size=8).hexdigest()   # 16 hex
```

1. **16 hex（64 bits），不是 10 hex。** 40 bits 在 1 萬條目下碰撞率約 0.5%、5 萬條目約 11%。掃描範圍含 2,613 個 mcfunction 與 692 個指令方塊，碰撞會實際發生。
2. **輸入是 `source.text` 不是 `raw`**（rev.1 的 A 節與 B 節此處矛盾）。理由：帶 `extra` 的樹沒有單一 `raw`；`text` 同時編碼字詞與段落切點，正是決定「是不是同一個翻譯單位」的東西。樣式值不進 hash。
3. **`normalize` 不碰空白**：NFC + 換行統一，**不 strip、不折疊**。告示牌用前導空白置中，折疊會讓 `"  歡迎  "` 與 `"歡迎"` 塌成同一個 key。
4. **碰撞硬失敗**：寫入 `keymap.json`、產生 `_1`、加 `collision_resolved` 旗標、列入報告。絕不靜默覆蓋。

`keymap.json` 進版控——它是專案的一部分，不是產物。

### B. § 顏色碼 — **rev.1 的結論是錯的**

> rev.1 寫：「結構化格式走 `structural_format` 由寫入層原封搬運，一行內多段不同顏色根本不會出現。」
>
> [實測] 這是錯的。`extra` 陣列就是一行內多段格式的標準表達：MP2 可翻譯路徑上 **2,261 個** 帶 `extra` 的 component 樹，最大深度 **3**，元素數長尾至 **34**，**84%** 的子元素自帶格式。原結論保留於此以說明為何被推翻。

**新結論：§ 舊碼與結構化格式是同一套佔位符機制的兩種輸入，不是兩條路。**

```
component 樹 ──攤平──► source.text = "[[0]]Cost:[[1]] 5 Coins"
                       source.segments[n] = {kind, sigma_expressible}
                       occurrence.segment_styles[n] = 實際樣式值
                       occurrence.skeleton = 樹骨架（文字換成段落序號）
```

- `[[n]]` 統一代表「一段格式的開始」，不分來源。翻譯的人看到的是不透明記號。**只有一段時完全不插標記**（SCHEMA_VERSION 4）。
- `unit.collapsible` 決定寫回方式：
  - `true` → 整棵樹塌成一個 `{translate: key}`，樣式轉 § 碼進 lang 值
  - `false` → **重建整棵樹**，每段一個 key（`<key>.0`、`<key>.1`…）
- `collapsible` 為 false 的條件：任一段樣式無法用 § 表達，或樹含 `click_event`/`hover_event`/`font`/`insertion`/巢狀 `translate`

真實案例（MP2 自己的中文化系統，我們必須讀得懂並重建）：

```jsonc
{"translate":"mcp.Cost_","fallback":"Cost:",
 "extra":[{"translate":"mcp.CenterParkSlotMachineCost","fallback":" 5 Coins","color":"gold"}]}
```

特別小心 `{"text":"","extra":[{"text":"X","italic":false}]}`——空父節點加帶格式子節點是用來壓掉物品名預設斜體的，重建時漏掉 `italic:false` 物品名會變回斜體。

**佔位符驗證是 hard fail 不是 warn**：`§l`/`§n` 持續生效到 `§r` 或行尾，少一個就染到整行。另加兩條規則：原文含字面 `[[n]]` 要轉義並記入 `escaped_literals`；佔位符全數前移（集合通過但語意全毀）以 `placeholder_front_loaded` 警告。

### C. 譯文長度 — 可量測預算 + 驗證重試（結論維持）

第 3 層算預算 → 第 4 層量測並重試 → apply 依 `enforcement` 擋或警告。

初始預算（**全部 [待驗]**）：`sign` 90px×1 行不換行；`book_page` 114px×14 行可換行；其餘無硬限制。

**校準提前**（rev.1 排在 M4.4 收尾）。理由：這是中翻專案，Minecraft 預設字型下 CJK 遠寬於拉丁字元，90 px 換算中文大約只有十個字。**寬度預算是給翻譯的人看的**——他要知道「這行只放得下十個字」才有辦法斟酌用詞。所以它必須在人開始翻之前就寫進待翻檔的 `note`，不是事後才報超寬。

**校準完成前 `enforcement` 一律 `warn`**——這條維持不變。

---

## 4. 里程碑

### 排序原則

先做**便宜的證偽測試**。端到端驗證成本以小時計、`doctor` 以天計，而端到端是「整個架構的最終證明」。先跑那個。

```
M0  端到端最小驗證（手動，數小時）  ← 能證偽整個資源包路線
 ▼
M1  doctor（唯讀）                  ← 產出的資料是後面每個決策的輸入
 ▼
M2  安全層 ─► M3 nbtio ─► M4 legacy 寫入驗證（提前）
 ▼
M5  model + 掃描 + 建樹 ─► M6 規則引擎 ─► M7 extract 產出
 ▼
M8  字寬校準（給人翻譯時的寬度預算）
 ▼
M10 resourcepack 後端 ─► M11 寫入層
 ▼
M12 自動化端到端 ─► M13 掃描廣度 ─► M14 CLI/報告/文件
```

### M0 — 端到端最小驗證（手動）✅ 已於 2026-08-17 完成

**結果**：正面顯示「哈囉世界」——**資源包路線成立**。另得三項 `[遊戲實測]`：`'""'` 在 native chunk 顯示為字面引號、native chunk 內的舊式 JSON **不被解析**（顯示為字面大括號）、`pack_format` 過期不警告也不拒載。完整記錄與兩點但書見 `SPIKE_RESULT.md`「M0 遊戲實測」。程序（可重跑）見 `docs/m0-checklist.md`。

**不寫任何程式碼。** 目標是在投入任何實作前，證明或推翻「自訂命名空間 key + 自製 resources.zip」這條鏈。SPIKE_RESULT.md 把這項標為**高·整個架構的最終證明**，且它是最後一個未驗項（Q3 用的是原版 key，那段鏈沒證過）。

**逐項執行清單見 `docs/m0-checklist.md`**（含回讀取證、失敗分診、控制組）。摘要：

同一塊告示牌**正反兩面寫入不同形狀**，沿用 spike `write_sign_variants.py` 已驗證有效的對照手法。正反面在同一個 chunk、同一個 block entity、同一次載入，任何差異只可能來自 `messages[]` 的形狀差異。

| 面 | 寫入形狀 | 驗什麼 |
|---|---|---|
| 正面 | native compound `{translate:"..."}` | **主目標**：資源包路線是否成立 |
| 背面 | legacy JSON 字串 `'{"translate":"..."}'` | native chunk 內的 legacy 形狀是否有效 + `'""'` 如何算繪 |

- [ ] 另存世界備份（`TT_WORLD_NAME_PROBE_BACKUP` 是舊的，15 MB vs 18 MB，不可靠）
- [ ] 放一塊站立式告示牌（`minecraft:sign`，不上蠟），四行留空
- [ ] 正面：`/data modify block <x> <y> <z> front_text.messages set value [{translate:"mcmt.test.hello"},{text:""},{text:""},{text:""}]`
- [ ] 背面：`/data modify block <x> <y> <z> back_text.messages set value ['{"translate":"mcmt.test.hello"}','""','""','""']`
- [ ] **回讀取證**：`/data get block <x> <y> <z> front_text`（與 `back_text`），輸出從 `%APPDATA%\.minecraft\logs\latest.log` 抓，不要對著聊天視窗抄
- [ ] 手寫 `resources.zip`：`pack.mcmeta`（`pack_format: 75` + `supported_formats`）+ `assets/mcmt/lang/zh_tw.json`（`{"mcmt.test.hello":"哈囉世界"}`，UTF-8 無 BOM）
- [ ] 用 `zipfile` 驗結構（無外層包裹資料夾）——同時預演 M10 的驗收條件
- [ ] 放進世界資料夾，語言切繁中，重進世界
- [ ] **正面顯示「哈囉世界」= 資源包路線成立**
- [ ] 觀察背面第 1 行（legacy 形狀是否有效）與第 2–4 行（`'""'` 顯示空白還是兩個引號）
- [ ] 最後重打包一次：`pack_format` 改 `55` 並**刪掉 `supported_formats`**，觀察是警告還是拒載
- [ ] **五個結果**寫回 `SPIKE_RESULT.md`「尚待驗證」表並標 `[遊戲實測]`，附回讀原文與截圖檔名

**為什麼用 `/data modify ... set value` 而不是 `/data merge`**：merge 對 list 的語意是整體替換，但既有 `messages` 是 `TAG_List of TAG_String`、新值是 `TAG_List of TAG_Compound` 時，型別衝突行為無明確文件。`set value` 語意明確。若真的跳型別錯誤，那本身就是發現 ③ 的額外證據，記下來。

正面四個元素**全部是 compound**（不是 `[{translate:...},"","",""]`）——這是同型約束的正確寫法，也是 mcmt 實際會產生的形狀。

**若失敗**：整個後端 B 路線要重新設計，後續里程碑全部作廢。這就是它排第一的原因。

### M1 — `mcmt doctor`（唯讀）

| 任務 | 驗收條件 |
|---|---|
| M1.1 壓縮分派 | 四種類型 + `0x80` 遮罩先行；未知類型 `UnknownCompressionError` 含數值與 chunk index；缺 `lz4` 時訊息含安裝指令 |
| M1.2 region 讀取 | 原始壓縮位元組不解壓；offset/length/sector 邊界檢查；截斷檔 `TruncatedRegionError` |
| M1.3 世界結構偵測 | 偵測 `Level.TileEntities` / `Text1..Text4` / `data_version` 為 null → `UnsupportedWorldStructureError`；偵測 `0x80` → `ExternalChunkError` |
| M1.4 `doctor` CLI | 輸出 DataVersion 直方圖、壓縮分佈、`.mcc` 數、legacy/native 節點形狀分佈、疑似損壞 chunk。**per-region 串流，峰值記憶體為單一 chunk**（[實測] 12 萬 chunk 22 秒可達成）。唯讀，永不寫入 |

`doctor` 的輸出同時是 M11 的規格說明書——它直接告訴你兩套寫入邏輯的實際比例。

### M2 — 安全層

`ensure_writable` / `ensure_readable` / `mcmt sandbox import` / `BackupSet`。驗收條件見 `CLAUDE.md` §1，每一條都要有對應測試，包含 `BackupSet` 收到 `.minecraft/saves` 路徑時拋 `MinecraftSavesPathError`。

### M3 — nbtio 完整

region 寫入（外科式 + timestamp 表規則）、`datfile.py`、損壞防禦四種畸形檔。

### M4 — legacy 寫入驗證（提前，人工）

rev.1 排在 M7.4 最後。提前的理由：legacy 佔 **43%**（51,369 chunks）、風險標記為高、讀取形狀比 native 更雜。

- [ ] 在 DataVersion 3955 的 chunk 寫入 legacy JSON 形式的 translate key
- [ ] 用 1.21.11 開啟，確認顯示正確
- [ ] **觀察該 chunk 的 DataVersion 是否被順手升級**（若會，「寫回原世代」的承諾就有前提條件）
- [ ] 結果寫回 SPIKE_RESULT.md

**若失敗**：`write/` 的設計要在寫任何實作前先改。

### M5 — model + 掃描 + 建樹

`generation.py`（DataVersion → 寫回世代，**不**用於形狀判斷）、`component.py`（7 種形狀嗅探）、`segments.py`（攤平／段落）、`node.py`（節點樹與 `node_path`）、掃描各來源、三個 codec。

關鍵驗收：`json_string_array`（`["",{...}]`）與 `json_empty_quoted`（`'""'`）能正確識別；JSON 解析失敗 → 跳過並計入 `stats.skipped_unparseable`，**絕不當裸文字**。

### M6 — 規則引擎

不動點迭代，**上限 32、超限 `RuleEngineDidNotConvergeError` 並列出最後一輪新增的標籤**。相同輸入標記結果穩定。denylist 回歸測試對 MP2 全掃，斷言 `LastOutput`(719)、`profile.properties[].value`、`palette[].Name` 一個都沒進 units。

### M7 — `mcmt extract` 產出

`keys.py`（16 hex + normalize + 碰撞硬失敗 + keymap）、`placeholders.py`（遮罩／還原／轉義／驗證）、`flatten.py`（樹攤平 + skeleton + collapsible 判定）、`constraints.py`、`emit.py`（schema 驗證）。

**同時產出兩份檔案**：`extract.json`（機器用）與 `translations.<lang>.json`（**人直接編輯**，每筆自帶 `source`/`note`/`where`，`target` 留空）。後者的形狀是 SCHEMA_VERSION 4 的重點改動，驗收條件包含「不開 extract.json 就能翻完整份檔案」。

`already_target_language` 以 CJK 字元比例粗略偵測，讓翻譯層跳過已是目標語言的 unit。

### M8 — 字寬校準（在翻譯層之前）

`tools/calibrate_font_widths.py` 產生測試告示牌 → 進遊戲截圖 → 回填量測表。ASCII 與 CJK 分開量。完成後才把 `sign` 的 `enforcement` 從 `warn` 升成 `error`。

### ~~M9 — 翻譯層~~ **已移出 v1（2026-08-21 決定）**

> 原本規劃：provider 介面（`echo` + `anthropic`）、批次與 Batch API、prompt 與重試、
> 增量翻譯、詞彙表、prompt caching。

**取消內建 LLM 翻譯。** 核心工作流改成純檔案解耦：

```
mcmt extract → translations.<lang>.json（人直接編輯）→ mcmt apply
```

工具不做機器翻譯、不呼叫任何 API、沒有網路相依。使用者要用什麼翻（自己翻、找譯者、
丟給任何工具）都是他家的事，而那也表示**沒有金鑰管理、沒有速率限制、沒有供應商相依**
這些與「安全地改別人的地圖」無關的複雜度。

原本屬於 M9 的兩件事仍然需要，但搬到別處：

* **佔位符驗證**（hard fail）→ M11 寫入層的守門，外加一個獨立的 `mcmt check`。
  規則不因為「翻譯的是人」而放寬——人會犯的錯和機器一樣多。
* **寬度量測** → M8 產出的量測表，`mcmt check` 用它報告超寬。

### M10 — resourcepack 後端

lang 嚴格寫／寬容讀、`resources.zip` 打包、既有 pack 合併（[實測] MP2 的 5 個語言檔都過不了 `json.loads`）、`collapsible` 為 false 時的樹重建、editplan 產出。

### M11 — 寫入層

`legacy.py` 與 `native.py` **兩份分開的實作**、`rebuild.py`、分派器、`expected_encoding` 守門、list 同型提升計數、`apply_report.json` 產出、in_place 四欄位寫入。

### M12–M14

自動化端到端測試、掃描廣度補齊（entities/容器巢狀/書本/scoreboard/hover_event/datapack）、CLI 與報告與文件。

### 移出 v1

- **後端 A（譯文直接寫回原位置）**：`backends/base.py` 保留可插拔介面與 `editplan.backend` 的 `inplace` 列舉值，但不實作。單人後工作量翻倍，而 M0 做完後它的風險對沖價值已大半消失。
- **舊結構世界支援**（`Level.TileEntities` / `Text1..Text4`）：拒絕處理。
- **外部 `.mcc`**：拒絕處理。
- **datapack `.mcfunction`**：延後，需要指令語法解析，工作量最難估。

---

## 5. 第一個任務

**M0，手動，不寫程式碼。** 進遊戲放一塊告示牌、手寫一個 zip、看它顯示什麼。

這件事幾小時內能做完，而它能證偽整個架構。在它通過之前寫的任何 `nbtio/` 程式碼都可能是白工。

M0 通過後才開 M1，並且從 `M1.1 壓縮分派` 開始——那是整條讀取鏈最底層、最容易測、也最容易寫錯（`0x80` 遮罩順序）的一環。

---

## 6. Self-Review

**Spec 覆蓋** — 對照 SPIKE_RESULT.md（含第二輪）逐項：

| 來源 | 對應 |
|---|---|
| Q1 函式庫 / 外科式 / 壓縮 / `.mcc` / 損壞防禦 | M1.1–M1.3、M3、ADR 0001–0002 |
| Q2 各類文字路徑（告示牌/書本/物品/容器/實體/level.dat/記分板/進度/指令方塊） | M5、M13 |
| Q2 必須排除的路徑 | M6 denylist 回歸測試 |
| Q3 可用 translate key 的 11 欄位 / 必須直改的 4 欄位 | M5、M11 |
| Q4 resources.zip / lang 寬容性 / key 命名慣例 | M0、M10、A 題 |
| 發現 ① per-chunk 世代 | M1.4、M4、M11 |
| 發現 ② 裸字串折疊 | M5 |
| 發現 ③ list 同型 | M11 |
| 第二輪 R1 extra 巢狀 | B 題重寫、M7 flatten、M10 樹重建 |
| 第二輪 R2 filterable | M13（防禦性 5 行，非阻塞） |
| 第二輪 R3 `'""'` 與 DV 不決定形狀 | M0（已驗：字面引號）、M5 嗅探、`container` 移除 `generation` |
| 第二輪 舊結構差異 | M1.3 拒絕處理 |
| **M0 結論 ③ native chunk 內舊式 JSON 是亂碼** | M5 嗅探時標 `excluded`、M10 不得產生該筆 edit（schema 已結構性禁止） |
| ~~未驗：端到端 / pack_format~~ | ~~M0~~ → **已完成 2026-08-17** |
| 未驗：legacy 寫入 | M4 |
| 未驗：LZ4 / `.mcc` | M1.1 / M1.3（拒絕處理） |

**已知風險，明講：**

1. ~~**M0 若失敗，M1 之後全部作廢。**~~ **M0 已於 2026-08-17 通過**：正面顯示「哈囉世界」，資源包路線成立。這條風險解除。
2. **字寬數值未實測。** 已設計成可抽換資料 + 校準任務 + 校準前一律 `warn`。
3. **`extra` 樹的攤平／重建是本專案最複雜的一段**，且 rev.1 完全沒有預留。深度至 3、元素數至 34、84% 帶自身格式，重建錯誤的後果是視覺損壞而非崩潰——這類錯誤最難自動偵測。M10 的驗收必須包含「取 MP2 真實實例做 round-trip 比對」。
4. **`unit` 層級去重讓同字不同義無法分開翻**，逃生口是 `keymap.json` 手動消歧，需人工介入。
5. ~~**`'""'` 的語意未定** [待驗]~~ → **M0-4 已驗**：在 native chunk 裡顯示為**字面的兩個引號**。處理決定（保留原樣）不變，但理由從「不知道所以不動」改成「已知是壞掉的字面文字，修它不是翻譯工具的職責」。
6. **新增風險：native chunk 內的舊式 JSON 節點會被排除，而排除是 per-occurrence 的。** 同一段原文可能一半可寫一半不可寫（`extract.sample.json` 的 `u:sign:b31f00ac5d7e2916` 就是這個案例）。實作 M5 與 M10 時最容易犯的錯是把排除做成 per-unit，結果整個單位被靜默丟掉。合約已加 `occurrence.excluded` 與兩條交叉檢查擋這件事。
7. **M0 那次沒做回讀取證**，所以「混合 list 存到磁碟後是什麼形狀」仍未知，`write/` 的 list 提升邏輯目前建立在推論上。已列入尚待驗證，**在 M11 開工前補掉**。
