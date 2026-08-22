# CLAUDE.md — mcmt 專案規範

Minecraft 地圖翻譯工具。Python 3.11+ · GPLv3 · 目標版本 Java Edition 1.21.11 · **單人開發**。

**這個工具會修改別人花幾千小時做的地圖存檔。** 本檔每一條規則都是為了讓「除了要改的地方以外什麼都沒動」成為結構性保證，而不是希望。事實依據見 `SPIKE_RESULT.md`，證據等級標註沿用該檔的四級制（`[實測]` / `[遊戲實測]` / `[文件]` / `[待驗]`）。

單人開發沒有第二個人會發現你的漂移。以下規則有一部分原本靠「協作者看不懂所以不會亂改」擋著，那個防火牆已經沒了，改由規範本身承擔。

---

## 零、開新對話先讀這裡

**本檔是「規範」，不是「進度」。** 做到哪、下一步是什麼、哪些結論已經驗過不必重推，全部在：

> ### 👉 `docs/STATUS.md`

新對話的第一件事就是讀它，**完成一個里程碑後回頭更新它**。它會指到其餘該讀的檔案（`SPIKE_RESULT.md` 是事實依據、`docs/superpowers/plans/2026-08-15-mcmt-architecture.md` 是架構計畫、`docs/contracts/` 是四份合約）。

漏更新 `docs/STATUS.md` 的代價，和漏把遊戲實測寫回 `SPIKE_RESULT.md` 一樣：下次會重跑一次已經驗過的東西，或更糟——重新推導出一個已經被實測推翻的結論。

---

## 零之二、核心工作流：純檔案解耦

**工具不做機器翻譯，不呼叫任何 API，沒有網路相依。** 兩個指令，中間是使用者自己的時間：

```
mcmt extract <sandbox 世界>          → extract.json（機器用）
                                     → translations.<lang>.json（**人直接編輯**）
        ↓  使用者用任何編輯器把 target 填上
mcmt apply <sandbox 世界> --translations translations.<lang>.json
                                     → resources.zip + 外科式寫回 + apply_report.json
```

`translations.<lang>.json` 是**這個專案唯一給人手動編輯的檔案**，所以它的形狀有硬要求：

- **每筆自帶原文**（`source`）、位置（`where`）與提示（`note`）。人不該為了知道自己在翻什麼而回頭開 `extract.json`。
- **`apply` 只讀 `target`。** `source` 不拿去比對——翻譯途中把它改短或加註是常見的事，那不該讓整份檔案失效。與某一份 extract 的綁定靠 `extract_fingerprint`。
- **空的 `target` = 尚未翻譯**，`apply` 保留原文並列進報告。`status: skip` 是「刻意不翻」，報告要分得開這兩件事。
- **只有一個段落時不插 `[[n]]` 標記**——純文字就是純文字。每行都掛一個無意義的前綴，譯者很容易順手刪掉，而刪掉之後佔位符驗證會硬失敗，錯卻是我們造成的。

`[[n]]` 佔位符驗證的規則不因為「翻譯的是人不是 LLM」而放寬：多一個、少一個、重複都是 hard fail（理由見三節）。人會犯的錯和機器一樣多，而 § 格式碼染到行尾的後果一樣。

---

## 一、安全規則（不可協商）

沒有例外、沒有 flag 可以關掉、不接受「暫時先這樣」。

### 1. 路徑：寫入必須在 sandbox，讀取必須明示

```python
from mcmt.safety.paths import ensure_writable, ensure_readable
target = ensure_writable(p)   # 唯一合法的取得寫入路徑的方式
source = ensure_readable(p)   # 唯一合法的取得讀取路徑的方式
```

**寫入** — `ensure_writable`：
- 任何 `open(...,"w")`、`write_bytes`、`shutil.copy`、`Path.unlink` 之前必須先過。
- 路徑含 `.minecraft/saves` → `MinecraftSavesPathError`。**此檢查優先於 sandbox 檢查**（有人把 `.minecraft` 複製進 sandbox 也一樣擋）。
- 先 `resolve()` 再判斷，`..` 與符號連結逃逸都要擋。
- 必須在 `sandbox/` 底下，否則 `PathOutsideSandboxError`。

**讀取** — `ensure_readable`：
- **允許**唯讀 `.minecraft/saves`（`doctor` 與 `extract` 需要）。
- 但必須是明示呼叫，**不接受「沒呼叫 ensure_writable 所以安全」這種隱性論證**。所有讀取入口一律過 `ensure_readable`，它負責記錄「本次執行讀了哪些路徑」供報告使用。
- 回傳唯讀 handle 的包裝，讓誤用寫入模式在型別層就爆掉。

**匯入** — `mcmt sandbox import <來源世界>` 是唯一合法的把世界帶進 sandbox 的入口：
- 完整目錄複製（不是 symlink、不是硬連結）。
- 在 `sandbox/<name>/.mcmt-origin.json` 記錄來源絕對路徑、匯入時間、來源的 `world_fingerprint`。
- 目標已存在時拒絕，除非 `--replace`。

**`BackupSet` 收到 `.minecraft/saves` 底下的路徑時**：拋 `MinecraftSavesPathError`。備份層不是繞過路徑圍籬的後門。

**工具永不自動把結果複製回 `.minecraft/saves/`。** 那是使用者的手動決定。

### 2. 修改任何存檔前強制備份，無法備份就中止

```python
with BackupSet(world_dir) as bk:
    bk.protect(region_path)     # 第一次修改前呼叫，重複呼叫不重複備份
    ...                          # 例外發生時自動還原所有已備份的檔案
```

- 備份失敗（磁碟滿、權限不足、目標唯讀）→ `BackupFailedError` 並中止。**絕不允許「備份失敗但繼續寫」**。
- 還原失敗時，錯誤訊息必須印出備份目錄的**絕對路徑**——使用者永遠要有一條救回來的路。
- 備份目錄與檔案數必須寫進 `apply_report.json` 的 `backup` 欄位。該欄位為 null 而 `outcome` 不是 `dry_run`/`aborted`，即為 bug。

### 3. 未知的 chunk 壓縮類型必須明確報錯

四種：`1` gzip / `2` zlib / `3` 未壓縮 / `4` LZ4。

```python
type_id, is_external = parse_compression_byte(b)   # 遮罩 0x80 必須在判斷型別之前
```

- 最高位 `0x80` 代表 chunk 存在外部 `.mcc`，**判斷型別前先遮罩**。
- `1/2/3/4` 以外 → `UnknownCompressionError`，訊息含實際數值與 chunk index。
- **不可靜默略過、不可猜測、不可 fallback 到 zlib。** 猜錯就是寫壞別人的存檔。
- schema 刻意不用 enum 限制此欄位，就是為了讓錯誤走這條訊息清楚的路徑而不是通用的 schema 驗證失敗。
- LZ4 缺相依時訊息要寫清楚裝什麼（`pip install mcmt[lz4]`）。

### 4. 外科式寫入

> **未被修改的 chunk，必須原封不動複製其原始壓縮位元組，絕不重新編碼。
> 只有被修改的 chunk 才走「解碼 → 改 → 編碼」路徑。**

`read_region()` 讀出的 `RawChunk.payload` 是**原始壓縮位元組**（未解壓）；`write_region()` 收到的 dict 裡，只有被改過的項目其 `payload` 是新壓縮出來的，其餘是同一個原始 bytes 物件。

**為什麼不能放寬** [實測]：「重新壓縮後位元組一致」（L2）是巧合——Python `zlib.compress()` 的預設等級恰好與 Mojang 的 Java `Deflater` 相同。只要 region 曾被其他工具以不同等級寫過、或未來版本改設定，巧合就消失。外科式寫入讓「什麼都沒動」從實測觀察變成結構性保證。

> 初版報告曾以「未觸碰 chunk 1023/1023 不變」佐證此規則，那是**套套邏輯**——當時的 `write_region` 本來就沿用原始 payload，驗的是「寫入路徑會原樣保留餵給它的東西」。真正支撐結論的是 L1/L2。這個自承要保留，不要在後續文件裡把它改寫成正面證據。

**timestamp 表的處理**（第二個 4096 bytes）：
- 未修改的 chunk：**原樣搬運**它原本的 timestamp。
- 修改過的 chunk：更新為當下時間（與 Minecraft 自身行為一致）。
- 不可整表歸零，也不可整表沿用——前者讓遊戲誤判所有 chunk 都是新的，後者讓被改的 chunk 帶著舊時間。

**外部 `.mcc` chunk：v1 明確不支援。**
- `doctor` 掃到 `0x80` 旗標即報錯並拒絕處理該世界。
- 理由：帶旗標時 region 內只有 header，「原封複製壓縮位元組」複製到的是空的；反向若修改後 chunk 超過 255 sectors 必須外置。這條寫入路徑**完全沒有實測過**（語料 5 張地圖 16.2 萬 chunk 外部 chunk 數為 0）。未測過的寫入路徑比拒絕處理危險得多。

### 5. 磁區重整不是資料遺失，但要報告

重寫後 region 檔變小是磁區重整（原檔有空隙），不是資料遺失。但必須在 `apply_report.warnings` 以 `sector_realignment` 記錄前後大小，否則使用者看到檔案縮小會合理地恐慌。

---

## 二、格式規則

### DataVersion 決定「寫回哪個世代」，**不決定**「節點是什麼形狀」

這是本專案最容易踩錯的一條。

- **必須讀每個 chunk 自己的 `DataVersion`**，不是 `level.dat` 的 [實測：同一世界跨 3955/4325/4438/4440/4556 五個世代]。
- **讀什麼世代就寫回什麼世代。工具永不升級格式。**
- 但 **DataVersion 不能拿來推導節點的儲存形狀** [實測]：MP2 的 DataVersion **4556** chunk（遠在分水嶺 4325 之後）內，告示牌 `messages[]` 仍有 **2,340 個舊式 JSON 空字串 `'""'`** 與 **110 個舊式 JSON 物件字串**。推測成因是地圖自己的 datapack 用 `data merge block` 寫入。

**因此**：`occurrence.encoding` 由**逐節點嗅探實際值的形狀**決定，是唯一權威。`container` 刻意**沒有** `generation` 欄位——那個推導已知為錯，留著只會讓人再用一次。

### 讀取形狀：必須容忍的完整清單

現代（原生 NBT）三種字面文字形狀：

```
StringTag("文字")                      # 純文字 component 被折疊成裸字串
CompoundTag({"": "文字"})              # Mojang NbtOps 產生的形狀
CompoundTag({"text": "文字"})          # 官方文件形狀
```

舊式（JSON 字串）四種，**同樣可能出現在 native DataVersion 的 chunk 裡**：

```
'"文字"'                    json_string_scalar   — JSON 引號純量
'{"text":"文字",...}'       json_string_object   — JSON 物件
'["", {...}, {...}]'        json_string_array    — 陣列形式，第一元素為父級其餘為 extra
'""'                        json_empty_quoted    — 2 字元的 JSON 空字串
```

`json_string_array` [實測]：`100 Ways To Die` 66 筆、`Questioning` 40 筆。
`json_empty_quoted` [實測]：MP2 2,340 筆，且整面四行皆是（585 面全空告示牌）。

### native chunk 裡的舊式 JSON 一律跳過

[遊戲實測 M0-3/M0-4] 在 DataVersion 4671 的 chunk 裡，`TAG_String` 就是**字面文字 component**——遊戲不會嘗試 JSON 解析。`'{"translate":"mcmt.test.hello"}'` 顯示為字面的 `{"translate":"mcmt.`，`'""'` 顯示為字面的兩個引號。DataFixerUpper 只在 chunk 的 DataVersion **低於**目標版本時才跑，DV ≥ 4325 的 chunk 不觸發修復。

所以要分清楚兩件事（很容易混）：

- **DataVersion 不決定節點是什麼形狀** [實測]。形狀一律逐節點嗅探。
- **DataVersion 決定遊戲會不會替這個節點跑 DataFixer**，因而決定同一個舊式 JSON 字串是「真內容」還是「使用者眼裡的字面亂碼」。

**v1 規則**：`container.data_version >= 4325` 且 `occurrence.encoding` 為四種 `json_*` 之一 → **跳過不翻譯**，計入 `stats.skipped_legacy_json_in_native_chunk`，加 `legacy_json_in_native_chunk` 旗標，並列進報告。

翻了會寫回一個顯示結果同樣是亂碼的字串——沒有任何好處，卻在別人的地圖上留下我們造成的改動。**也不要「順手修好」**（把它改成正常 component）：那是地圖自身的瑕疵，修它超出翻譯工具的職責，而且會重新編碼一個沒被要求改的節點，違反安全規則 4。

`data_version < 4325` 的 chunk 維持原路徑（解析 JSON 後翻譯）。**[待驗]**：DataFixer 升級後舊式 JSON 確實被正確解析——目前只有 `[文件]` 級推論。

**JSON 解析失敗的行為**：不是裸文字。按安全規則 3 的精神——
- 標記為 `unparseable_json`，**跳過該節點不翻譯**，計入 `stats.skipped_unparseable`，並列進報告。
- **絕不靜默當作裸文字翻掉**。翻了會寫回非法 JSON，而遊戲對非法 JSON 的行為未定義。

### 寫入形狀

**寫入一律用 `{"text": "文字"}`——但這條只適用於「被本次修改的節點」。**

未被修改的節點讀到 `{"": "..."}` **不得**正規化成 `{"text": "..."}`。那會重新編碼一個我們沒被要求改的節點，直接違反安全規則 4。「一律用 text 形狀」講的是我們**新產生**的值，不是我們**路過**的值。

[遊戲實測] 兩種 Compound 形式遊戲都能正確顯示；選 `text` 是因為它是官方文件記載的形狀。

### NBT list 同型

告示牌四行只要有一行是結構化 component，其餘三行就不能是裸字串。

| 節點形狀 | 插入 translate key 的做法 |
|---|---|
| list 元素全為 `TAG_String`（舊式） | **單點替換**，不動其他行 |
| list 元素已為 `TAG_Compound`（原生） | 改目標元素即可，其餘原樣不動 |
| list 為全 String 且要插入 Compound | **四行全部改寫**：目標為 `{translate:...}`，其餘為 `{text: 原字串}` |

`write/legacy.py` 與 `write/native.py` 是兩份分開的實作。**不要用一套邏輯硬套**——這是規格層級的不對稱，不是可以抽象掉的重複。每次 list 提升都要計入 `apply_report.counts.list_promotions`。

> **[實測 2026-08-21] 「四行全部改寫」是格式強制的，不是設計選擇。** `TAG_List` 在 NBT 格式層就帶單一元素型別 id；把 `CompoundTag` 塞進 `list_data_type=8` 的 list，amulet-nbt 直接 `TypeError`。混合 list 在磁碟上不可能存在，所以寫入層連「不小心只改一行」都做不到。

### component 樹（extra）不是「原封搬運」

[實測] MP2 可翻譯路徑上有 **2,261 個帶 `extra` 的 component 樹**，最大巢狀深度 **3**，extra 元素數長尾至 **34**，其中 **84% 的子元素自帶格式屬性**。

所以一個節點常常是「一行內多段文字、多組格式」的樹，例如：

```jsonc
{"translate":"mcp.Cost_","fallback":"Cost:",
 "extra":[{"translate":"mcp.CenterParkSlotMachineCost","fallback":" 5 Coins","color":"gold"}]}
```

處理方式：

1. **攤平**成單一字串，每段格式的起點插一個 `[[n]]` 標記 → `source.text`（**只有一段時不插**，見下）。§ 舊碼與結構化格式**是同一套佔位符機制的兩種輸入**，不是兩條路。
2. 段落的**樣式值**存在 `occurrence.segment_styles`（per-occurrence），**樹的骨架**存在 `occurrence.skeleton`。
3. `unit.collapsible` 決定寫回方式：
   - `true` → 整棵樹塌成一個 `{translate: key}`，樣式轉成 § 碼進 lang 檔值。
   - `false` → 必須**重建整棵樹**，每段一個 key（`<key>.0`、`<key>.1`…）。當樹含 `click_event` / `hover_event` / `font` / `insertion` / 巢狀 `translate`，或樣式無法用 § 表達時為 false。

**`{"text":"","extra":[{"text":"X","italic":false}]}` 這個慣用法要特別小心**——空父節點加帶格式子節點是用來壓掉物品名預設斜體的。重建時漏掉 `italic:false`，物品名會變回斜體。

> **[M13b] 上面那棵示範樹，現在會被整棵跳過不翻。原文保留，因為攤平機制本身沒有變，被推翻的只有這個例子的結論。**
>
> M13b 加了一條「**已在地化就整個跳過**」規則（`extract/build.py` 的 `_contains_translate`，計入 `stats.skipped_already_localised`）：攤平後的骨架裡**任何一處**有 `translate` 節點，這個單位就不抽出來。上面那棵樹的根節點和它的 extra 子節點都是 `translate`，所以它正是這條規則要擋的東西——不是「攤平成 `[[0]]Cost:[[1]] 5 Coins` 然後翻譯」，是**根本不進待翻檔**。
>
> 理由：那兩個 `mcp.*` key 是**地圖自己的多語言系統**。我們重建這棵樹時會把它們換成我們的 key，於是一張本來支援 5 種語言的地圖，退化成只支援我們寫進去的那一種——而且是靜默地退化。`fallback` 看起來像「可以翻的字」，它其實是別人在地化系統的預設值。用「任何一處」而不是「根節點是」，是為了連半文字半 key 的樹一起擋（`{"text":"Hello ","extra":[{"translate":"mcp.X"}]}` 重建時一樣會蓋掉那個巢狀 key）。
>
> 所以這一節的攤平／`[[n]]`／`collapsible` 規則**全部仍然有效**，只是適用對象縮小成「不含任何 `translate` 節點的樹」。真實數字（`mcmt extract`，2026-08-23）：`Arena of Darkness` 跳過 **5** 個、`100 Ways To Die` 跳過 **0** 個；MP2 那種自帶中文化的地圖才是這條規則真正要保護的對象。

### hover_event 內的文字在掃描範圍內

[實測] MP2 有 331 筆 `pages[]/raw/extra[]/hover_event/name`。category 為 `hover_text`，`node_path` 照常走 key 步驟即可。含 hover_event 的樹一律 `collapsible: false`。

### v1 拒絕處理的世界結構

[實測] `From Ashes Reborn 1.12`（DataVersion 1139/1241，**882 個 chunk 完全沒有 DataVersion 欄位**）的結構與 1.21 完全不同：

- chunk 根有 `Level` 包裝層，方塊實體在 `Level.TileEntities` 而非 `block_entities`
- 告示牌是 `Text1`/`Text2`/`Text3`/`Text4`（924 個），沒有 `front_text`/`back_text`
- 書本在 `Items[].tag.pages`，物品名在 `Items[].tag.display.Name`

且 1.12 地圖在 1.21.11 開啟後，走過的區域升級、沒走過的維持原狀，**同一世界會同時存在兩套結構**。

**v1 行為**：`doctor` 偵測到 `Level.TileEntities`、`Text1..Text4`、或 `data_version` 為 null 的 chunk，即拋 `UnsupportedWorldStructureError` 並拒絕處理整個世界。理由與 `.mcc` 相同——未測過的寫入路徑比拒絕處理危險。

### 資源包

- 必須是 zip 而非資料夾，檔名固定 `resources.zip`，放世界資料夾根目錄
- zip 內根目錄直接是 `assets/` 與 `pack.mcmeta`，**不可有外層包裹資料夾**
- `pack_format` 宣告 `75`（1.21.11），另加 `supported_formats` 區間
- [遊戲實測 M0-5] 世界資源包的 `pack_format` 過期時**不警告也不拒載**，照常生效。所以宣告正確的號碼是為了未來版本的行為，不是為了現在能載入——不要因為「反正過期也能用」就不維護這個值
- level.dat 不需要登記，是隱含機制

### lang 檔

- **輸出寫嚴格 JSON**：無註解、無尾逗號、UTF-8 無 BOM、`ensure_ascii=False`、key 排序（diff 穩定）
- **讀取既有 lang 檔必須寬容**：容忍 `//` 註解與尾逗號。[實測] MP2 的 5 個語言檔**全部無法通過 `json.loads`**
- 值本身可含 `§` 顏色碼 [實測]
- 單一自訂命名空間（預設 `mcmt.`），**永不覆寫 `minecraft.*`**

---

## 三、key 生成與佔位符

### key 的組成

```
translateKey = <namespace>.<category>.<discriminator>[.<segment_index>]
unitId       = u:<category>:<discriminator>
```

`discriminator` 在兩者中是**同一個字串**，由同一個函式產生一次，永不分岔。

- `discriminator` = 16 hex（**64 bits**），碰撞或人工消歧時追加 `_<n>`
- 為什麼是 16 hex 不是 10：40 bits 在 5 萬條目下碰撞機率約 11%，而掃描範圍含 2,613 個 mcfunction 與 692 個指令方塊，碰撞會實際發生
- 尾綴 `.<segment_index>` **只有** `collapsible: false` 時才出現，代表段落序號。消歧一律走 `_<n>`，兩者不共用同一個位置

### hash 輸入（此前 A 節與 B 節說法矛盾，以此為準）

```
hash_input = f"{SCHEMA_VERSION}\x1f{category}\x1f{source.text}"
discriminator = blake2b(hash_input.encode("utf-8"), digest_size=8).hexdigest()
```

**輸入是 `source.text`（攤平後、含 `[[n]]` 標記的字串），不是 `raw`。** 理由：帶 `extra` 的樹沒有單一 `raw`；而 `text` 同時編碼了字詞與段落切點，正是決定「這是不是同一個翻譯單位」的東西。

樣式**值**不進 hash——同一句話的金色版與紅色版是同一個翻譯單位，樣式差異存在 occurrence 層。但段落**切點**進 hash（因為它在 `text` 裡），切點不同必然是不同單位。

### normalize 的逐條規則

```
1. Unicode NFC 正規化
2. 換行統一為 \n（CRLF / CR → LF）
3. 不做任何空白處理 —— 不 strip、不折疊、不移除
4. 不做大小寫轉換
5. § 碼是內容的一部分，不移除
```

**第 3 條是硬性的。** 告示牌用前導空白做置中排版，`"  歡迎  "` 與 `"歡迎"` 是不同的視覺結果；折疊空白會讓它們塌成同一個 key，排版全毀。

### 碰撞必須硬失敗

同 digest 但 `hash_input` 不同 → 在 key 生成當下：

1. 寫入 `keymap.json`，記錄兩個 `hash_input` 與解法
2. 產生 `_1` 後綴的新 key
3. 在 `unit.flags` 加 `collision_resolved`
4. 在報告中列出

**絕不靜默覆蓋。** 靜默覆蓋的後果是兩段不同的文字共用一個譯文，而且沒有任何跡象。

### 佔位符驗證是硬失敗

譯文的 `[[n]]` 多重集合必須與原文**完全一致**——不多、不少、不重複。

**這是 hard fail 不是 warn。** `§l`、`§n` 這類格式碼持續生效到 `§r` 或行尾，少一個就是顏色／粗體染到整行結尾。違反者 `status: rejected`，不寫入，進 `apply_report.unwritten`。

順序**可以**不同（中文語序重排是正常的）。

兩個附帶規則：
- **原文含字面 `[[n]]`**：轉義為 `[[\n]]` 寫進 `source.text`，原字串記入 `source.escaped_literals`，並加 `contains_placeholder_like_text` 旗標。
- **佔位符全數前移**（如 `[[0]][[1]]文字`）：集合檢查會通過但語意全毀。單獨檢查並以 `placeholder_front_loaded` 警告，交人工複審。

### 寫入端的最後一道關

任何 `value.kind == "literal"` 的 `text` 若殘留 `[[n]]`，writer 必須**拒絕整份 plan**（`placeholder_residue`），不是跳過該筆。

---

## 四、其他實作規則

### 不動點規則引擎必須終止

- 迭代上限 **32**，超限拋 `RuleEngineDidNotConvergeError` 並列出最後一輪新增的標籤。
- **不可靜默停止**。兩條規則互相餵標籤就是無限迴圈，靜默停止會產生「有時候少抽幾個節點」這種最難查的 bug。
- 相同輸入的標記結果必須穩定（規則套用順序不得影響最終標籤集合）。

### 同一父字串內多處編輯必須由後往前

`pathStep.decode.span` 是父字串內的位元組位移。一個指令方塊的 `Command` 字串裡有多處要翻譯時，**改完第一處，其餘 span 全部失效**。

規則：同一父字串的編輯**依 span 降序處理**，或改用結構化重建而非位移替換。[實測] 三層巢狀（指令含 NBT、NBT 含 component）確實存在，這個坑會踩到。

### SCHEMA_VERSION 單一版本號，不相容即失敗

- 四份合約共用同一個 `SCHEMA_VERSION` 整數。
- 讀到不符 → **立即失敗**，訊息說明「請重新產生」。
- **不實作任何向下相容、不寫 migration**。單人專案沒有跨版本相容的承諾要維持，留這個包袱只會讓錯誤晚一點才爆。

### 相依

執行期只允許 `amulet-nbt` + stdlib；`lz4` 可選。**沒有任何網路相依**——工具不做機器翻譯，也不呼叫任何 API（見「零之二、核心工作流」）。

**`jsonschema` 是 dev/test 相依，不是執行期相依。**
- CI 對 `tests/fixtures/contracts/*.sample.json` 跑 schema 驗證。
- 執行期不驗 schema（避免拖累 12 萬 chunk 的處理）。
- 但**每個合約的產生與讀取都必須有一個對應的 sample fixture 測試**。否則 schema 只是文件，沒有東西強制它與程式碼一致——單人開發時這個漂移不會有第二個人發現。

**不要引入 `amulet-core`**：它是世界轉換器，會把方塊轉成 universal 格式再轉回來；翻譯工具不碰方塊，多一層轉換就是多一層損壞風險。且它不暴露 per-chunk DataVersion 分派這個必需的控制權。

**PyPI 上的 `pyanvil` 不是 Minecraft 函式庫**，是生物資訊套件。不要裝。

### 授權

每個原始碼檔頂端：`# SPDX-License-Identifier: GPL-3.0-or-later`

### TDD

先寫失敗的測試 → 執行確認失敗 → 最小實作 → 執行確認通過 → commit。一個任務一個 commit。

- `tests/unit/` — 純函式，只碰 `tmp_path`
- `tests/integration/` — 碰真實 region fixture，寫入只在 `sandbox/` 或 `tmp_path`
- `tests/fixtures/regions/` — 小型真實 region 切片，每個 < 1 MB
- `tests/fixtures/contracts/` — **分層回歸測試 fixture**。每份合約一個樣本，schema 改動必須同步更新

### 合約改動流程

`docs/contracts/*.json` 與 `src/mcmt/model/` 的改動：

1. **獨立 commit**，不得夾帶在其他任務裡
2. 同一個 commit 內同步更新 `tests/fixtures/contracts/*.sample.json`
3. bump `SCHEMA_VERSION`
4. 驗證測試通過才算完成

---

## 五、給 AI 助手的特別提醒

### 兩條硬性禁令

1. **`src/mcmt/write/` 與 `src/mcmt/safety/` 底下任何檔案的修改，必須是獨立 commit 並在訊息中說明理由。** 不得在其他任務中附帶修改。這兩個目錄是「弄壞了就是別人的地圖沒了」的地方，需要一個刻意的動作才能碰。

2. **不得開著 `to2mbn/maptranslator` 的原始碼逐段對照撰寫。** 只採用其公開描述的架構模式（規則反覆標記直到收斂）。逐段對照會產生高度相似的實作結構，對一個要公開發布的 GPLv3 專案是實質的授權污染風險。詳見 `docs/adr/0007-prior-art-and-licensing.md`。

### 看似合理、實際會破壞不變式的想法

| 想法 | 為什麼不行 |
|---|---|
| 「統一走解碼→編碼路徑比較乾淨」 | 破壞外科式寫入。L2 位元組一致是巧合不是保證 |
| 「用 DataVersion 判斷節點是 JSON 還是原生就好」 | [實測] DV 4556 裡有 2,340 個舊式 JSON 空字串。必須逐節點嗅探 |
| 「native chunk 裡的舊式 JSON 就照舊式路徑翻一翻」 | [遊戲實測 M0-3] 遊戲根本不解析它。翻了寫回去，顯示還是同一坨亂碼 |
| 「那順手把那坨亂碼修成正常 component 吧」 | 修地圖自身的顯示瑕疵不是翻譯工具的職責，而且重新編碼了沒被要求改的節點 |
| 「legacy 和 native 寫入邏輯很像，抽象成一個」 | 不對稱是規格層級的。合併只會用 if/else 把它藏起來，然後某天套錯 |
| 「讀 component 只認 `{"text":...}` 就好」 | 會漏掉 `{"":...}`、裸字串、四種 JSON 形狀 |
| 「路過的 `{"":...}` 順手正規化成 `{"text":...}`」 | 重新編碼了沒被要求改的節點，違反安全規則 4 |
| 「extra 就是格式，原封搬運就好」 | [實測] 84% 的 extra 子元素自帶格式，深度到 3。要攤平＋重建，不是搬運 |
| 「未知壓縮類型就當 zlib 試試看」 | 猜錯就是寫壞存檔。必須報錯 |
| 「JSON 解析失敗就當純文字翻一翻」 | 會寫回非法 JSON。必須跳過並計數 |
| 「先寫入再備份，比較快」 | 順序反了就沒有備份 |
| 「佔位符少一個就 warn 一下」 | § 格式碼會染到行尾。hard fail |
| 「翻譯 `LastOutput` 也沒差」 | [實測] MP2 有 719 筆，是執行期產物且含原版 key |
| 「1.12 地圖也支援一下吧，改幾行而已」 | 兩套 chunk 結構會在同一世界並存。v1 拒絕處理 |
| 「`.mcc` 順手支援一下」 | 該寫入路徑 0 樣本、完全未測 |
| 「把 `resources.zip` 自動複製回 `.minecraft/saves`」 | 違反安全規則 1 |
| 「`sandbox/` 檢查在測試裡很麻煩，加個 `--force`」 | 不加。測試用 `sandbox/` 底下的臨時目錄 |
| 「掃描範圍擴大而已，寫入層不必改」 | [M13a] 寫入層的分派可能建立在**舊範圍碰巧成立的等價關係**上。擴範圍時要列出新的 `(strategy, node_path 形狀)` 組合，不是只列新的 category |
| 「這段程式碼在別處是對的，複製過來就好」 | [M13a] 它依賴的不變式可能只在原本的脈絡下成立。複製前先問：這段程式碼假設了什麼？新的地方還成立嗎？ |
| 「規則引擎跑不完就先停下來回傳現有結果」 | 靜默少抽節點是最難查的 bug。必須報錯 |

### 最危險的一類 bug：舊範圍下碰巧成立的不變式

**[M13a 的教訓]** 那一輪的 code review 抓到**七個計畫層級的 bug**，其中五個是同一種：
**複製了一段在舊脈絡下正確的程式碼，而它依賴的不變式在範圍擴大之後靜默失效。**

三個實例，都不是「寫錯」而是「原本對，後來不對了」：

| 東西 | 在舊範圍下為什麼是對的 | 擴大後為什麼錯了 |
|---|---|---|
| `chunks = list(read_region(path))` | 只有一個消費端時沒人會踩到 | `read_region` 是產生器，中途拋例外時 `list()` 把**已經讀成功**的 chunk 一起丟棄，損壞世界的部分搶救能力消失 |
| `apply.py`：「路徑 key 結尾 ⇒ `in_place`、index 結尾 ⇒ `translate_key`」 | v1 只掃告示牌（index+translate）與 `CustomName`（key+in_place），剛好是四種組合的兩種 | M13a 加進另外兩種：草稿書頁被寫成 JSON 字串**弄壞存檔**，物品名 4,152 個 occurrence 一個字都寫不出去 |
| `doctor` 只走 `region_files()` | v1 只讀 `region/`，閘門是完整的 | extract 開始讀 `entities/` 之後，那裡的外部 `.mcc` 會通過 doctor，apply 到**備份之後**才炸 |

**這一類靠逐任務 review 幾乎抓不到**，因為每個任務單獨看都自洽。它只在
「舊不變式的證人」（既有測試、既有閘門、既有 fixture）與**新範圍**對照時才現形。

**唯一有效的防線是端到端測試跟著範圍長。** M13a 的 spec 明文要求擴充 `test_end_to_end.py`，
那一項被跳過了，於是那一輪的盲點一個都沒被自動抓到——最後是靠整支分支的 review 才發現。
補上之後，把修正前的 `apply.py` 換回去會讓 **13 條**端到端測試變紅。

所以擴大任何範圍（掃描來源、寫入路徑、支援的格式）時：

1. **列出新的組合**，不是只列新的項目。四種 `(strategy, 路徑形狀)` 組合，v1 只有兩種。
2. **端到端測試要涵蓋每一種新組合**，而且要有一條測試斷言「所有組合都被涵蓋了」
   （`test_the_round_trip_actually_exercises_all_four_dispatch_combinations`）。
3. **問一次：這個範圍裡還有哪些地方假設了舊範圍？** 閘門（`doctor`）、身分
   （`world_fingerprint`）、統計（`result.chunks`）都是常見的落點。

### 卡住的處理

**卡住超過 30 分鐘，就在 issue 或 `docs/journal/` 寫下「我試了什麼、看到什麼」。** 單人開發時這是唯一的思路外化機制，寫下來的過程本身常常就解掉了。不要獨自撞牆。

### 進遊戲驗證的結果一律寫回 SPIKE_RESULT.md

**單人時沒有第二個人會提醒你更新。** 每次進遊戲驗證後：

1. 把結果寫回「尚待驗證」表
2. 標註證據等級（`[實測]` / `[遊戲實測]` / `[文件]` / `[待驗]`）
3. 若推翻了先前的推論，**保留原推論並說明為何被推翻**，不要直接改掉

證據分級與自承錯誤是這份文件的價值所在。初版報告把「未觸碰 chunk 不變」自承為套套邏輯、把 L1/L2/L3 分層陳述，這兩處的標準要一路維持到專案結束。

### spike/ 目錄

`spike/` 是唯讀的參考實作，不要修改也不要 import。有用的起點：

- `probe_roundtrip.py:29-90` — anvil 讀寫骨架（約 90 行，僅乾淨資料）
- `write_sign_variants.py:51-67` — `write_region` 與原樣複製規則的示範
- `probe_raw_nbt.py` — 不依賴函式庫的位元組層 NBT 解析（約 120 行）
- `probe_components.py` / `probe_components2.py` — 第二輪 P1/P2/P3 掃描，含 per-region 串流的可行性驗證

**排程時不要按 90 行估 anvil 層。** 那是「乾淨資料上能跑通」的骨架，不含 LZ4、`.mcc`、損壞防禦。完整實作落在 200–300 行。
