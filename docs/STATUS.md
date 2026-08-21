# 專案進度 — mcmt

**這份檔案是跨對話的交接點。** 新開一個 Claude Code 對話時先讀這裡，就知道做到哪、下一步是什麼、哪些結論不能重新推導。
**每完成一個里程碑就更新這裡**，和「進遊戲驗證要寫回 `SPIKE_RESULT.md`」是同一個紀律：單人開發沒有第二個人會提醒你。

最後更新：**2026-08-21**（M8 校準完成、legacy `CustomName` 驗完。**沒有任何一項卡在進遊戲了**，下一步是 M13 掃描廣度）

---

## 一句話現況

**M0–M8、M10–M12 完成，而且沒有任何一項卡在「要進遊戲」了。** 整條鏈
（`import → extract → 人工翻譯 → apply`）有自動化測試釘住，兩條寫入路徑
（translate key 與 in_place）都走得通，字寬預算是量出來的、`enforcement` 已經是
`error` 而且真的會擋。下一步是 **M13 掃描廣度**——目前只掃告示牌與 `CustomName`。

~~M1 只差「節點形狀分佈」~~ → **M5.6 已補上**，`doctor` 現在會報形狀分佈與「有多少節點會被跳過不翻」。

## 現在這個工具能做什麼

四個指令，全部在真實地圖上跑過：

```
mcmt doctor <世界>                     健檢（唯讀）：DataVersion 分佈、節點形狀分佈、
                                       有多少節點會被跳過不翻、可不可以處理
mcmt sandbox import <來源世界>          唯一合法的把世界帶進 sandbox 的入口
mcmt extract <sandbox 世界>            → translations.<lang>.json（**人編輯這個**）
mcmt apply <sandbox 世界> --translations …   → resources.zip + 外科式寫回
                                       （--dry-run 完全不碰存檔，只產 editplan.json）
```

實跑數字：`Arena of Darkness`（88,969 chunk）extract 出 **607 個翻譯單位**（涵蓋
10,421 次出現，94% 是重複的）。apply 在探測世界上改動 1 個 chunk、**原封複製 929 個**。

`sandbox/` 現有三份副本可用：`100 Ways To Die`(95M)、`Arena of Darkness`(378M)、
`roundtrip`(18M，**已翻好且驗證過的探測世界**)。不需要就整個資料夾刪掉。

---

## 架構調整（2026-08-21）：取消內建 LLM 翻譯

**核心工作流是純檔案解耦**，工具不做機器翻譯、不呼叫任何 API、執行期沒有網路相依：

```
mcmt extract → translations.<lang>.json（人直接編輯）→ mcmt apply
```

三處落地，都已完成：

1. **合約 `SCHEMA_VERSION` 3 → 4**。`translations` 的 entry 從 `{text, status}` 變成 `{source, target, note, where}`——舊形狀只有 unit_id 當鍵，人打開檔案看不到自己在翻什麼。`apply` **只讀 `target`**；`source` 不拿去比對（翻譯途中改短它是常見的事），綁定靠 `extract_fingerprint`。空 `target` = 未翻譯，`status: skip` = 刻意不翻，報告分得開。
2. **單一段落不再插 `[[0]]`**。純文字就是純文字；每行都掛無意義前綴，譯者容易順手刪掉，而刪掉之後佔位符驗證會硬失敗、錯卻是我們造成的。
3. **M9 移出 v1**，`pyproject` 拿掉 `[llm]` extra。原本屬於 M9 的兩件事沒有消失：佔位符驗證 → M11 守門 + `mcmt check`；寬度量測 → M8 的表。

**M8 的定位因此變重要**：寬度預算要**寫進待翻檔的 `note` 給人看**，譯者得先知道「這行只放得下十個字」才有辦法斟酌用詞。事後才報超寬對人沒有幫助。

**沒有放寬的一條**：`[[n]]` 驗證仍是 hard fail。人會犯的錯和機器一樣多，§ 碼染到行尾的後果一樣。

### 一併決定：**不做術語表、不做「不翻」標記、連警告都不做**（2026-08-21）

問題是「一句話裡有要翻和不要翻的部分」，例如 `how are you josh` 該翻成「你好嗎 josh」
而不是「你好嗎 喬許」。

**決定：工具不介入。** 待翻檔把 `source` 放在 `target` 隔壁，譯者看得到原文，人名要
不要留是他的判斷。不做 `glossary.json`、不做 `{{ }}` 之類的保護標記、`mcmt check`
也不為此發警告。

考慮過但沒採用的理由不是「做不到」，是**這是單人翻一張地圖的工具**：譯者就是使用者
本人，他看得懂自己在翻什麼；為了一致性引入一份要維護的清單，成本比它省下的多。

> **未來要重新考慮的唯一觸發點**：M13 補上 lang 檔／datapack 掃描時。
> [實測] MP2 自己的 50,959 個 lang 值裡有 **18,796 個（37%）含 `%1$s`**、847 個含 `§` 碼。
> 那類是**格式參數**不是人名——漏掉一個 `%1$s`，遊戲少填一個玩家名進去。它與人名
> 不同類：機器驗得出來，而且錯了不只是難看。
> v1 目前掃的來源（告示牌、CustomName）裡格式參數實測是 **0**，所以現在不處理是正確的；
> **M13 開工時要重新問一次**，別直接沿用這個決定。

---

## 該讀哪幾份（依序）

| 檔案 | 是什麼 | 什麼時候讀 |
|---|---|---|
| `CLAUDE.md` | **規範**。安全規則、格式規則、key 生成、禁令 | 每次動手前 |
| `docs/STATUS.md` | 本檔。進度與交接 | 每次開新對話 |
| `SPIKE_RESULT.md` | **事實依據**。所有實測結論與證據等級（四級制） | 要引用「為什麼這樣設計」時 |
| `docs/superpowers/plans/2026-08-15-mcmt-architecture.md` | 架構計畫 rev.2。目錄結構、四份合約、A/B/C 題、M0–M14 | 排下一步工作時 |
| `docs/contracts/*.json` | 四份 JSON Schema（`SCHEMA_VERSION = 4`） | 寫任何跨層資料時 |
| `docs/ownership.md` | 模組邊界與三個整合檢查點 | 決定某段程式該放哪裡時 |
| `docs/adr/0007-prior-art-and-licensing.md` | 為何不得對照 maptranslator 原始碼 | 想參考既有實作時 |
| `docs/m0-checklist.md` | M0 可重跑程序（換版本時用） | 要重驗遊戲行為時 |
| `docs/m8-checklist.md` | 字寬校準的可重跑程序（M13 掃到書本後要再跑一次） | 要重驗字寬時 |

---

## 已完成

### 規劃階段（2026-08-15 ～ 08-16）

- 三輪 spike 實測，語料 5 張地圖 / 162,226 chunk，結論全部寫進 `SPIKE_RESULT.md` 並標證據等級
- 四份合約定稿 + `tests/fixtures/contracts/*.sample.json` + `tools/validate_contracts.py`
- `CLAUDE.md`、`docs/ownership.md`、ADR-0007、架構計畫 rev.2

### M0 — 端到端最小驗證（2026-08-17，`[遊戲實測]`）✅

**資源包路線成立**：自訂命名空間 key 由世界根目錄的 `resources.zip` 解出並顯示中文。這是「整個架構的最終證明」，M1 之後的工作不再有被整體推翻的風險。

另得四項結論，其中 M0-3 推翻了一項隱含假設 —— 詳見 `SPIKE_RESULT.md`「M0 遊戲實測」。**最重要的一條**：

> DataVersion **不**決定節點是什麼形狀，但 DataVersion **決定遊戲會不會替該節點跑 DataFixer**。
> 因此 DV ≥ 4325 的 chunk 裡的舊式 JSON 字串是**字面亂碼，不是內容** → v1 跳過不翻譯，也不「順手修好」。

合約隨之 bump 到 `SCHEMA_VERSION = 3`：新增 `occurrence.excluded`、`stats.skipped_legacy_json_in_native_chunk`、unit flag `legacy_json_in_native_chunk`，並在 editplan schema 結構性禁止「DV ≥ 4325 + `json_*` encoding」的組合。驗證器 44 passed。

### M1.1 — 壓縮分派（2026-08-17）✅

`src/mcmt/nbtio/compression.py` + `src/mcmt/errors.py` + 22 個單元測試。同時建立 `pyproject.toml` 與 `.venv`（editable 安裝）。

三個實作決定與規範的關係，之後不必重推：

- **`chunk_index` 是必填關鍵字參數**。CLAUDE.md 只要求訊息含 chunk index，但可選參數等於允許呼叫端丟掉它。
- **`decompress_chunk` 收到未遮罩的位元組（如 `0x82`）會拋錯，不順手遮罩**。遮罩是 `parse_compression_byte` 的職責，兩處都做等於允許跳過 parse。
- **type 4 走 lz4-java 的 `LZ4BlockOutputStream` 框架**（`"LZ4Block"` magic + 每區塊 21 bytes 標頭），不是標準 LZ4 frame。無真實樣本，標 `[待驗]`，已寫回 `SPIKE_RESULT.md`。xxhash32 檢查碼不驗（為它引入相依不划算，壞資料會被 NBT 解析擋下）。

已用突變測試確認「先判型別再遮罩」會讓 4 個測試變紅——這條不變式是真的被測到的，不是寫在註解裡而已。

### M1.2 — region 讀取（2026-08-17）✅

`src/mcmt/nbtio/region.py`（`read_region` 產生器 + `RawChunk`）+ 16 個單元測試。

- **payload 是磁碟上的原始壓縮位元組，這層不解壓。** 讀取層若順手解壓，外科式寫入的保證就只剩呼叫端的自律。
- 畸形檔分兩類，因為對 `doctor` 意義不同：`TruncatedRegionError`（檔案比宣告的短）vs `MalformedRegionError`（header 自相矛盾：偏移指進前兩磁區、磁區數 0、長度溢出磁區、非外部 chunk 卻空 payload）。
- `0x80` 只報 `is_external`，**不夾帶政策**——拒絕處理外部 chunk 是 M1.3 的事。
- ~~路徑還沒過 `ensure_readable`~~ → **M2.5 已接上**：`read_region` 現在只收 `ReadOnlyPath`。
- 真實資料健檢（唯讀）：MP2 的 3 個 region、2,952 chunk，全 type 2、外部 0、解壓後都是 TAG_Compound、DataVersion 4556 — 與 `SPIKE_RESULT.md` 一致。

### M1.3 — 世界結構偵測（2026-08-17）✅

`src/mcmt/nbtio/structure.py`（`load_chunk_root` + `ensure_supported_structure`）+ 9 個測試。

- `UnsupportedWorldStructureError` 帶**機器可讀的 `reason`**（`level_wrapper` / `legacy_sign_text` / `missing_data_version`），所以 `doctor` 能 catch 起來統計症狀分佈，不必為了「能報數字」就把閘門做成不拋錯的版本。
- `ensure_supported_structure` 回傳 chunk 自己的 DataVersion，但那只是順路讀到——**形狀一律逐節點嗅探**。
- 放在 `nbtio/` 而不是計畫的 `scan/`：這裡只判斷位元組是什麼形狀、不碰語意，錯誤也都是 `FormatError` 家族；`scan/` 要到 M5 才存在。

**真實資料推翻了一個說法，已寫回 `SPIKE_RESULT.md`：** 「同一世界兩套結構」**不是 1.12 專屬**，而 `Text1..Text4` 是「1.20 之前的告示牌格式」**不是「1.12 結構」**。證據：`Find The Button No Cakewalk`（1.18.2）有 852 個帶 `Level` 包裝的 chunk（抽驗 DataVersion 1963）與 15 個 DataVersion 2975、容器是現代 `block_entities` 但告示牌用 `Text1..Text4` 的 chunk。

### M1.4 — `mcmt doctor`（2026-08-17）✅（形狀分佈由 M5.6 補齊）

`src/mcmt/doctor.py`（統計）+ `src/mcmt/cli/`（組裝與格式化）+ 12 個測試。指令：`mcmt doctor <世界資料夾>`，離開碼 0 可處理 / 1 拒絕 / 2 路徑有問題。

- 逐 region 檔、逐 chunk 串流，峰值記憶體是單一 chunk。region header 壞掉時記錄並中止那一張，**掃描繼續**。
- **「唯讀」有測試擋著**：比對掃描前後世界資料夾內每個檔案的 mtime 與大小。
- 掃描範圍是所有名為 `region` 的目錄（含 `DIM-1`/`DIM1`/datapack 自訂維度）。`entities/` 與 `poi/` 不算方塊 chunk，v1 不看。

~~未做：節點形狀分佈~~ → **M5.6 已補上**。doctor 自己不判斷形狀，只把嗅探器與掃描層的答案數起來。

真實世界實跑：

| 世界 | 規模 | 時間 | 結果 |
|---|---|---|---|
| 100 Ways To Die | 13 region / 6,465 chunk | 2 秒 | 通過（DV 4325 佔 96.9%） |
| Minecraft Party 2 | 5 維度 / 406 region / **207,515 chunk** | **93 秒** | 通過（DV 3955 43.5% · 4438 43.1% · 4556 13.3%） |
| Find The Button No Cakewalk | 142 region / 36,459 chunk | 未計時 | **拒絕**（852 `level_wrapper` + 15 `legacy_sign_text`） |

MP2 的 DataVersion 分佈證實 **per-chunk 世代分派不是理論問題**：兩個世代各佔 43%。
93 秒的瓶頸是「每個 chunk 都完整解析 NBT」——目前只為了讀 `DataVersion` 與結構檢查。真要加速就是寫一個只挖需要欄位的淺解析器，但那是最佳化，不是現在該做的事。

### M2 — 安全層（2026-08-17）✅

五個任務五個 commit，其中兩個是 `safety/` 的獨立 commit。共 127 個測試通過。

**M2.1 路徑圍籬** `safety/paths.py`
- sandbox 根 = `<專案根>/sandbox`（往上找 `.git`/`pyproject.toml`），找不到才退回 `<CWD>/sandbox`。從 `src/` 或 `tests/` 底下跑都指向同一個沙箱。
- `.minecraft` 檢查**優先於** sandbox 檢查。比對的不是字面 `.minecraft/saves`，而是「有 `.minecraft` 成分且其後有 `saves` 成分」——語料就在 `.minecraft\versions\1.21.10\saves`。
- `ReadOnlyPath` **刻意不實作 `__fspath__`**：`open(p,"w")` 會 TypeError，`shutil.copy` 也拿不到它。
- **連結逃逸是真的走得通的**：這台機器不給建 symlink（WinError 1314），但 `mklink /J` 的目錄連接點不需要管理員權限，`resolve()` 一樣穿過去。測試 symlink 失敗就退回 junction，不整條跳過。

**M2.2 世界指紋** `fingerprint.py` — blake2b 掃「region 相對路徑 + chunk index + 原始壓縮 payload」。不餵磁區排列、chunk 時間戳、mtime/大小（合約明文禁止 mtime）。壞掉的 region 折成穩定標記而不拋錯——指紋負責身分，健檢是 doctor 的事。

**M2.3 `mcmt sandbox import`** `sandbox.py` — 逐檔 `ensure_readable` 讀 → 逐檔 `ensure_writable` 寫，不是 `shutil.copytree`：**每一個寫入都經過圍籬**。`.mcmt-origin.json` 記來源絕對路徑、匯入時間、**來源的**指紋。目標已存在要 `--replace`；目標落在來源底下直接拒絕。

**M2.4 `BackupSet`** `safety/backup.py` — 備份放 `sandbox/.mcmt-backups/<世界>/<時間戳>/`，與世界資料夾**平行**，世界資料夾不會多出任何檔案。重複 `protect` 不重複備份（重複備份會用已改壞的內容蓋掉原始備份，那比沒有備份更糟）。protect 一個還不存在的檔案是合法的，回滾時刪掉它。還原逐檔進行、失敗的收集起來繼續，訊息含備份目錄絕對路徑並 `from` 原始例外。

**M2.5 讀取入口接上圍籬** — **高階函式收使用者路徑**（`survey_world`/`world_fingerprint`，入口呼叫一次 `ensure_readable`）；**低階只收 `ReadOnlyPath`**（`read_region`，裸 `Path` 直接 TypeError）。`nbtio/` 因此 import `safety/paths.py`——沒有環，例外與理由記在 `docs/ownership.md`。

真實資料驗證（工具第一次真的寫東西）：`sandbox import` 「100 Ways To Die」95 MB / 1,775 檔 / 12 秒，逐位元組比對 **1,775/1,775 相同**，副本只多出 `.mcmt-origin.json`，副本指紋與 origin 記的來源指紋一致。

> `sandbox/100 Ways To Die/` 現在有一份 95 MB 的真實世界副本（已 gitignore），M3/M4 要驗證 region 寫入時可以直接用。不需要了就整個資料夾刪掉。

### M3 — nbtio 完整（2026-08-17）✅

三個任務三個 commit（外加一個 fixture 更換）。178 個測試通過，其中 9 個是碰真實檔案的整合測試。

**M3.1 region 寫入** `write_region` + `ChunkWrite` + `RegionWriteReport`
- 介面讓「這個 chunk 有沒有被改過」在呼叫端**看得見**：`ChunkWrite.unchanged()` / `.replaced()` 兩個建構子，不是一個讓人隨手填的旗標。`unchanged` 只能從 `RawChunk` 建，帶著磁碟上的原始壓縮位元組與原始 timestamp。
- **這一層永遠不壓縮任何東西。** payload 一律是已壓縮好的位元組。L2「重新壓縮後位元組一致」是巧合，寫入層不依賴它。
- 先寫 `.mcmt-tmp` 再 `os.replace`：寫到一半掛掉時原檔完好無損。
- 真實資料：讀進來寫回去，**檔案位元組與 fixture 完全一致**；改一個 chunk，其餘 29 個 payload 與 timestamp 全部原樣；整個世界（13 region / 6,465 chunk）round-trip **6,465/6,465 位元組一致**。
- 那次全世界跑抓到一個真 bug：目標檔不存在時 `size_before` 是 0，`realigned` 因此恆為 true，13 張全被報成磁區重整。**警告出現在不需要它的地方，使用者就會學會忽略它。**已修。

**M3.2 `datfile.py`** — `level.dat` 讀寫。**這裡沒有外科式寫入這回事**：region 是 1024 份獨立文件，`level.dat` 是一份，改一個欄位就得整份重編。保證只到 L1（解析→序列化位元組一致），已在真實 `level.dat`（7,271 bytes NBT）上實測成立。壓縮形式讀什麼寫什麼（不順手升級成 gzip）；gzip `mtime` 固定 0（否則同內容每次位元組都不同）。

**M3.3 損壞防禦** — 補兩個 M1.2 沒處理的類別：**磁區重疊**（讀；兩邊都讀得出東西，不檢查就安靜地讀到垃圾）與**寫入端輸入驗證**（重複 index、index 超範圍、非法壓縮類型、空 payload）。重複 index 特別陰險——其中一筆會變成指不到的孤兒磁區，而檔案看起來還是合法的。驗證在動磁碟之前做完。

**測試 fixture 的授權考量**：`tests/fixtures/` 底下的真實資料一律取自 `TT_WORLD_NAME_PROBE`（本專案自建的探測世界），**不用語料地圖**——那些是別人做的冒險地圖，放進要公開發布的 GPLv3 repo 等於重新散布別人的作品。`level.dat` fixture 另外移除了 `Player`（玩家 UUID 與座標）與 `WorldGenSettings`（種子）。

---

### M4 — legacy 寫入驗證（2026-08-17，`[遊戲實測]`）✅

**legacy 寫入路線成立**：DV **3700** 的 chunk 裡以舊式 JSON 字串寫入自訂命名空間 translate key，1.21.11 由世界 `resources.zip` 解出並顯示中文。`write/legacy.py` 的設計前提不必改。

程序與兩輪測試的細節見 `docs/m4-checklist.md`，完整記錄見 `SPIKE_RESULT.md`「M4 遊戲實測」。**四項不能重推的結論**：

1. **DataFixer 確實解析 DV < 4325 chunk 裡的舊式 JSON**，而且**存回磁碟時就地轉成原生 compound**——`{"text":…}` 與純量都變成 **`{"": …}` 空鍵形式**。`empty_key_compound` 不是某個工具的怪癖，是 Mojang `NbtOps` 的標準輸出。
2. **4325 分水嶺由對照實驗確立**：同一個 `'""'`，native chunk 顯示字面引號（M0-4）、3700 chunk 顯示空白。同一份輸入只差 DataVersion，結果相反。
3. **遊戲會升級玩家走過的 chunk**：開一次世界後，同一張 region 的 953 個 chunk 有 144 個 3700→4671、809 個不動。**「同一世界兩套世代並存」是使用者玩過就會發生的事**，不是 1.12 舊地圖專屬，也不是我們造成的。→ **extract 當下嗅探的 `encoding` 會因為使用者中間玩過一次而失效**；`world_fingerprint` 抓得到，M11 的 `expected_encoding` 守門是這個情境的唯一防線。
4. **世界資源包的 `pack_format` 有下限，修正了 M0-5**：地圖自帶的 `pack_format: 22` 被 1.21.11 拒絕（「無法套用伺服器資源包」），換成 75 + `supported_formats` 就正常。→ **M10 的硬需求**：合併進地圖既有的舊 pack 時**不能只加 lang 檔**，必須同時處理 `pack.mcmeta`，否則整個 pack 被拒、譯文一起陪葬；而那是在改地圖自己的檔案，要在報告中明確告知使用者。

---

### M5 — model + 掃描 + 建樹（2026-08-21）✅

| 任務 | 狀態 |
|---|---|
| M5.1 `model/component.py` 形狀嗅探 | ✅ |
| M5.2 `model/generation.py` | ✅ |
| M5.3 `model/segments.py` 攤平與段落 | ✅ |
| M5.4 `model/node.py` 節點路徑 | ✅ |
| M5.5 `scan/sources/region.py` | ✅（告示牌 + CustomName；廣度留給 M13） |
| M5.6 doctor 接上形狀分佈 | ✅ |
| M5.7 四個 codec（`tree/codecs/`） | ✅ |

**與合約綁死的做法**：`model/` 的三個模組都有一條測試**直接讀 `docs/contracts/*.json`**
比對 enum（`Encoding`、`Codec`）與 `SCHEMA_VERSION`。所以這幾個 commit **沒有 bump
`SCHEMA_VERSION`**——沒有任何合約欄位被新增、移除或重新定義，而版本號 +1 只會讓現有
產物作廢卻不告訴任何人哪裡不一樣。要漂移得同時改兩邊，那正是合約改動流程想擋的事。

**真實資料驗證**（每一項都在跑完之後才算完成）：

- 嗅探器**重現了第二輪 probe 的數字**：MP2 的 `json_empty_quoted` 2,340、
  `json_string_object` 110，且都在 DV 4556。
- 攤平器跑 MP2 的 5,344 棵樹，**失敗 0**，最大巢狀深度 3（與 probe 一致）。
- `doctor` 現在會報：MP2 57,192 個文字節點，其中 **4,473 個是「新世代 chunk 裡的
  舊式 JSON」會被跳過不翻**，並在報告裡說明理由。

**兩個真實資料抓到的修正**（都寫回 `SPIKE_RESULT.md`）：

1. **前導引號不算 JSON 證據**。`100 Ways To Die` 有一行告示牌是 `"looks like you`
   ——跨行的英文引述。原本會被判成解析失敗而跳過。改成「前導引號必須解析成功才算
   `json_string_scalar`」；`{` 與 `[` 維持保守。
2. **`with` 不攤平、只原樣帶走**。MP2 的節點有 translate 參數，內容是玩家名與分數
   這類執行期產物——翻它沒意義，弄丟它會讓重建時整個參數消失。

**M5.2 與 M5.7 的重點**：

- `generation.py` **刻意不提供任何形狀相關的函式**，而且有測試守著（掃過公開名稱，出現含 encoding/shape 的名字就失敗）。`write_back_version()` 回傳它收到的版本號——「永不升級」寫成函式而不是註解。
- **每個 codec 都要回答 `faithful_round_trip`**。`json_component` 忠實（真實資料 78/78，compact 形式）；**`snbt` 不忠實**——`to_snbt()` 會把鍵排序，所以 SNBT 不能整份重編，只能用 `span` 位移替換。那正是合約裡 `decode.span` 與「由後往前」存在的理由。
- `command` codec **明確拒絕**（`NotImplementedError`）：指令語法解析是最難估的一項，而掃描層根本還不去找 `Command` 欄位，留一個猜著做的實作等於等著某天寫壞別人的指令方塊。
- `lang_json` 的「寬容」被真實資料打了一次臉：初版用正則，MP2 的 5 個語言檔 **0/5** 通過（註解裡有雙引號、BOM、註解裡有冒號逗號）。改成會追蹤字串狀態的掃描器後 **5/5，讀出 50,959 個 key**。

**兩件留給後面里程碑的判斷**：

- **可塌縮只有 20%**（MP2 5,344 棵樹裡 1,066 棵）。不可塌縮的主因是 `click_event`
  （1,694 個互動告示牌，§ 碼表達不了，非塌縮不可）與 `translate`（2,045 個）。
  後者是**合約的規範文字與它自己的 sample 互相矛盾**的地方：規範說 false 只給
  「nested translate」，sample 卻把根節點標 false、巢狀標 true。目前採**保守解讀**
  （任何 translate 都不可塌縮），代價是「重建整棵樹」變成常態路徑。M10/M11 開工前
  要定案。
- **MP2 有自己的中文化系統**（5 個語言檔 + `mcp.*` key）。翻它的 `{translate:"mcp.X"}`
  節點等於覆蓋地圖作者自己的在地化；更合理的可能是翻它的 lang 檔。M6 denylist 或
  M13 要處理。

---

### M6 — 規則引擎（2026-08-21）✅

不動點迭代，上限 32、超限拋錯並列出最後一輪新增的標籤。**兩條硬性要求都不是靠自律**：
順序無關是因為每輪跑完所有規則再取聯集（規則只加標籤、不刪標籤）；不靜默停止是因為
「有時候少抽幾個節點」是最難查的 bug。

denylist 用 `deny:<原因>` → `do_not_translate` 兩段式，結論的定義只有一處。

**回歸測試刻意不走正式掃描層**——掃描層現在只找告示牌與 CustomName，拿它驗 denylist
會通過但什麼都沒驗到。改成走過 chunk 裡每一個字串節點問規則引擎。M13 掃描廣度補齊後
第一道防線會消失，那時這條測試已經在守著。

**它立刻抓到兩個逐條列舉想不到的漏洞**：`biomes.palette` 是**字串 list 不是 compound**，
所以 `("palette","Name")` 完全認不到（MP2 有 456 萬個）；`Status` 與 `id` 也是識別碼。
因此改成「`sections` 底下整段擋掉」——**列舉已知陷阱漏掉的東西你不會知道，圈出已知
安全區漏掉的東西會馬上炸在臉上。**

MP2 全掃 12,262,582 個字串節點、96% 被擋、**0 漏**。

### M7 — `mcmt extract`（2026-08-21）✅

`extract/keys.py` · `placeholders.py` · `build.py` · `emit.py` + `cli/extract.py`。

- **key**：`discriminator` 在 `unit_id` 與 `translateKey` 裡是同一個字串，由同一個函式產生一次。三種格式都與合約的 regex 綁死。`normalize` 只做 NFC 與換行統一，**不碰空白**（告示牌用前導空白置中）。碰撞走 `_1` 並把兩邊 hash 輸入記進 `keymap.json`。
- **佔位符**：多重集合完全一致才過，**hard fail**。順序可不同；「全數前移」單獨警告（判準是標記彼此相鄰，不是在字串開頭）。空 target 回報 `empty_translation` 而不是佔位符錯誤。
- **`build.py` 不自己判斷任何一件事**——形狀問嗅探器、世代問 `generation`、該不該翻問規則引擎、攤平問 `segments`。
- **最重要的測試是「產出的文件真的通過 schema 驗證」**，而且真實產出也驗過：`Arena of Darkness` 的 13 MB `extract.json` 0 錯誤。

真實地圖：

| 世界 | chunk | 文字節點 | 翻譯單位 | 出現次數 | 時間 |
|---|---:|---:|---:|---:|---:|
| 100 Ways To Die | 6,465 | 8,315 | **937** | 1,691 | 2 秒 |
| Arena of Darkness | 88,969 | 15,563 | **607** | 10,421 | 31 秒 |

**去重省下的量才是這個工作流的重點**：Arena of Darkness 的譯者要打 607 條，不是 10,421 條。

> 一個真實觀察：Arena of Darkness 有一個 `block_entity_name` 是 `'@'`，**出現 9,491 次**。
> 那多半是地圖的紅石／指令系統用來找容器的名字，翻了會壞。待翻檔的 `note` 會寫「出現
> 9491 次」，人看到這個數字自然會停下來想一下——這正是「工具不介入、但把該看到的資訊
> 攤在眼前」的實例（見上方「不做術語表」那節）。

---

### M10 — resourcepack 後端（2026-08-21）✅

| 任務 | 重點 |
|---|---|
| M10.1 `lang.py` | **樣式跟著文字走，不跟著位置走**——譯者調換語序時，第一版照段落序號輸出，把譯者寫的順序改回去了 |
| M10.2 `pack.py` | 合併既有 pack，**只加 `supported_formats`、不改它宣告的 `pack_format`**（M4-5 的教訓） |
| M10.3 `backend.py` | editplan：後端決定**值是什麼**，寫入層決定**怎麼安全地放進去** |

另外兩個順序細節：§ 的顏色碼會重設格式，所以顏色必須寫在格式之前；轉義還原要在殘留
檢查**之後**做。

寫 M10.1 時發現並修掉 `segments.py` 的一個錯誤：**§ 碼只能開啟樣式，沒有關閉的方向**。
`{"italic": false}`（壓掉物品名預設斜體的慣用法）因此不可塌縮。

### M11 — 寫入層（2026-08-21）✅

三個 `write/` 獨立 commit。**不對稱終於可以講得很具體**：

| | legacy chunk（DV < 4325） | native chunk（DV ≥ 4325） |
|---|---|---|
| 寫什麼 | JSON 字串（[遊戲實測 M4-1]） | NBT compound（[遊戲實測 M0-3]） |
| list | 型別不變，**不必提升** | String list 塞不進 compound，**非提升不可** |

所以「不要用一套邏輯硬套」不是風格偏好——一邊完全不必提升，另一邊非提升不可，
用 if/else 藏起來就是等著某天套錯邊。

**真實世界的完整來回**（自建探測世界，3,599 chunk）：

```
計畫 10 個節點 → 寫入 9 個
改動 1 個 chunk，原封複製 929 個
NBT list 提升 2 次
磁區重整 3,821,568 → 3,817,472 bytes（有報告）
```

逐項驗證：930 個 chunk 只有 chunk 0 的 payload 變了、**929/929 未改動的 chunk 連
timestamp 都一樣**、探測世界原本就有的 `block.minecraft.diamond_block` 節點沒被碰、
`resources.zip` 有 lang 檔。`--dry-run` 完全不碰存檔並產出 `editplan.json`。

### M11 遊戲實測（2026-08-21）：**整條鏈成立** ✅

把翻好的 `sandbox/roundtrip` 拿進 1.21.11，三項 `[遊戲實測]`：

**① 端到端成立。** 告示牌全部顯示中文。這是「尚待驗證」表首列、標為**高**的那一項
——M0 證明的是「手動注入 + 資源包」那半段，這次**中間沒有人下過任何一個 `/data` 指令**。
同 chunk 裡本來就有的 `block.minecraft.diamond_block` 照常顯示，**沒有誤傷**。

**② 吊掛告示牌比一般告示牌窄很多。** 7 個 CJK 字（`吊牌正面第一行`）被截掉，同樣長度
在一般告示牌上完全正常。目前給它的 60px 預算**仍偏寬**。→ 這是 M8 的第一個真實資料點。

**③ `CustomName` 在 native chunk 不解析任何形狀。** 寫 SNBT（`{translate:"…"}`）進去，
GUI 標題顯示**字面文字**。行為與 M0-3 的告示牌 `messages` 完全一致。
→ **native 的 `block_entity_name` 只能走 `in_place`**（直接把譯文寫進節點），和
`LevelName`、書名、作者、草稿書頁同組。

> 原本的推測（探測世界的裸字串既是合法 SNBT 也是合法折疊 component，所以 CustomName
> 應該是 component 的 SNBT）**被推翻**，理由記在 `SPIKE_RESULT.md`。

> **一個誠實的缺口：`CustomName` 目前拒寫。** [實測] 它在兩個世代都是 String 節點
> ——native（DV 4671）是裸字串、legacy（DV 3700）是 JSON 純量 `'"@"'`。要放
> translate key 進去，native 那邊該寫什麼形狀**沒有實測依據**：寫 compound 會改掉
> 欄位的 NBT 型別，寫 JSON 字串又踩到 M0-3。已列入 `SPIKE_RESULT.md` 尚待驗證，
> 標為高——**`Arena of Darkness` 有 9,579 個這種節點**。

---

### `CustomName` 改走 `in_place`（2026-08-21）✅

[遊戲實測 M11-3] 已經給出答案，所以這一項不必再進遊戲。四個 commit（合約／model／
extract／`write/` 各一，後兩者是規範要求的獨立 commit）：

| 層 | 做了什麼 |
|---|---|
| 合約 | `SCHEMA_VERSION` 4 → 5。`block_entity_name` 加進「category ⇒ in_place」那條 if/then；`excluded.reason` 新增 `untested_write_shape`；`literal` 的語意收緊為**保留節點既有的 NBT 形狀** |
| `model/strategy.py` | category ⇒ strategy 的唯一權威。與合約的 if/then 由測試綁死 |
| `extract/` | legacy chunk 的 in_place 節點 per-occurrence 排除；不可塌縮的整個跳過並計數 |
| `write/in_place.py` | 新的第三條寫入路徑 |

**`write/in_place.py` 不是第三份 legacy/native 實作。** 那兩份的不對稱是**世代**的
（遊戲會不會跑 DataFixerUpper），而 in_place 完全不做那個判斷——它**什麼形狀都不選**，
保留節點原本的形狀只換裡面的字。分派依據因此是 `encoding` 不是 `data_version`。

有依據的形狀只有四個（`bare_string` / `plain_string` / `text_compound` /
`empty_key_compound`），其餘一律拒寫並進報告。**不把 `TAG_String` 提升成 compound**
（告示牌那邊整個 list 提升過，`CustomName` 沒有那條退路），**兩種 compound 形式互不
正規化**（路過的 `{"": …}` 順手改成 `{"text": …}` 就是重新編碼一個沒被要求改的欄位）。

順手抓到 backend 的兩個 bug——in_place 之前沒有任何 category 走得到，所以一直沒被觸發：
`_value_for` 回傳的是**原文**不是譯文（會是一次沒有效果卻看起來完全成功的存檔修改），
而 in_place 的 unit 也被塞進 lang 檔、`key` 是 null 於是寫成字面的 `"None"` 鍵。

真實資料：探測世界的兩個 CustomName 正確寫成 `StringTag` 譯文、沒進 lang 檔、929 個
chunk 原封複製。**但 `Arena of Darkness` 一個都寫不出去**——見下方 B。

### M8 字寬的表與工具（2026-08-21）✅（量測見下面那節）

`mcmt/width.py` + `mcmt/fontdata/vanilla_v1.json` + `tools/calibrate_font_widths.py`
+ `docs/m8-checklist.md`。

**數字放在資料裡不放在程式裡**：校準是「改資料」，`--record` 只重寫那一個 JSON，
「哪些量過、哪些還是猜的」永遠只有一個地方要看。`emit.py` 原本自己有一份
`_WIDTH_BUDGET`，已刪掉——兩份數字就會有一天只校準了其中一份。

**note 從「寬度上限 90px」改成「約 10 個中文字」。** px 對譯者沒有意義，字數有。

`enforcement` 判準是資料裡的 `calibrated` 旗標（當時全部是 `warn`，量測完成後自動
升成 `error`）。一條測試把 [遊戲實測 M11-2] 變成會紅的東西：數字必須預測得出
「6 個 CJK 進得去、7 個進不去」——後來的量測證實它一直是對的。

校準工具**產生方式是改寫你放好的空白告示牌，不是生成 `/setblock`**——這個工具從來
不碰方塊，要它生成 setblock 就得猜 1.21.11 的方塊實體 NBT 語法，猜錯的症狀是「進遊戲
什麼都沒出現」，白跑一趟。做法沿用 `tools/m4_prepare.py`。

### M12 自動化端到端（2026-08-21）✅

`tests/integration/test_end_to_end.py`，19 條。走使用者真的會走的四步，fixture 是
自建探測世界的 30-chunk 切片（剛好同時有告示牌與 CustomName，**兩條寫入路徑一趟都
走到**）。

**它立刻抓到一個真 bug**：`apply_report.assets_installed` 一直是 `["resources.zip"]`，
而合約要的是物件陣列。單元測試驗的是手寫的 sample fixture，驗不到「程式真的會吐出來
的東西」。

**一個值得記住的發現**：「未觸碰的 chunk 位元組一致」這條**單獨不夠**。用突變確認過
——把 apply 改成每個 chunk 都解碼再編碼，那條測試**仍然是綠的**，正是 `SPIKE_RESULT`
的 L2 那個巧合。抓得到的是 **timestamp**：`ChunkWrite.unchanged` 帶原始時間戳、
`replaced` 蓋當下時間，所以「有沒有走原封複製那條路」在磁碟上留得下痕跡，位元組留不下。

---

### M8 校準完成 + legacy `CustomName`（2026-08-21，`[遊戲實測]`）✅

一次進遊戲做完兩件事，兩件都成立。完整記錄見 `SPIKE_RESULT.md`「M8 + legacy
CustomName 遊戲實測」，這裡只留不能重推的結論。

**① 字寬：四個數字全部命中校準前的猜測。**

| | ASCII（`M`） | CJK（`中`） | 預算 |
|---|---|---|---|
| 一般告示牌 | 15 | 10 | **90px（約 10 個中文字）** |
| 吊掛告示牌 | 10 | 6 | **60px（約 6 個中文字）** |

CJK 9px、粗體 +1（吊掛上 10 個粗體 `M` 只顯示 8 個——若粗體不加寬就會全部顯示）。
所以 [遊戲實測 M11-2]「7 個 CJK 字被截掉」不是碰巧對上，`hanging_sign` 從 `[待驗]`
升成 `[遊戲實測]`。

> **階梯定的是比例，不是絕對 px。** 窮舉過所有相容的參數組，全部是等比族
> （ASCII : CJK 恆為 2 : 3），整張表乘以 2 也一樣相容。絕對尺度靠「ASCII = 6px」
> 這個 `[文件]` 級的錨。不影響工具——真正用到的 `cjk_capacity` 只依賴比值。

**`enforcement` 因此升成 `error`，而且現在真的會擋**（`overflow_rejected`，合約本來
就有這個原因）。合約寫的是「拒絕該筆譯文」，校準前一律 warn 是因為「拿沒驗過的預算
去擋會退掉正確的譯文」；驗過了就得執行，否則那個欄位在說謊。

**一個豁免**：原文本身就放不下時，只要譯文不比原文寬就放行。那是地圖自己的排版，
在那種節點上退掉一個「不比原文糟」的譯文，等於要求譯者解一個原作者沒解的問題，
而且無論他怎麼寫都過不了。

**② legacy `CustomName`：JSON 兩種都成立，裸字串會弄丟名字。**

| 變體 | 結果 |
|---|---|
| `'"譯文"'`（JSON 純量） | 正確顯示 |
| `'{"translate":…}'`（JSON 物件） | 正確解出資源包的譯文 |
| `'譯文'`（非 JSON 裸字串） | **顯示原版預設名——欄位整個被丟掉** |

**第三個是反面證據，而且比前兩個重要**：在舊世代換掉節點的形狀會**悄無聲息地弄丟
別人地圖上的名字**。「保留節點既有的形狀」在這裡不是保守，是唯一不會壞事的選擇。

落地：`write/in_place.py` 支援六種形狀（多了 `json_string_scalar` /
`json_string_object`），`extract` 的排除判準從**世代**改成**形狀有沒有實測依據**
（清單在 `model/strategy.py`，寫入層的實作與它由一個 assert 綁死）。

真實地圖：`Arena of Darkness` 的 CustomName occurrence 從 **9,579 全數排除** 變成
**9,581 個 0 排除**，並真的寫了一筆驗證（DV 3700 的旗幟，`'"Letter F"'` →
`'"測試譯文"'`，形狀與 DataVersion 都沒變，同 region 其餘 952 個 chunk 原封複製）。

> **B 成立代表舊世代可以走 translate key**（一份存檔支援多語言）。v1 不走：
> `strategy` 是 per-unit 的，而同一段原文可能同時有 native 與 legacy 的 occurrence，
> native 那邊 translate key 不成立（M11-3）。留給 v2。

---

## 下一步

### 1. M13 掃描廣度 ← **現在就是這一項**

目前只掃告示牌與 `CustomName`。還沒掃的：容器裡的物品（`Items[]` 的
`custom_name`/`lore`/書本）、實體（在 `entities/` 而非 `region/`）、`level.dat`、
記分板、進度、指令方塊、datapack、`hover_event` 內的文字。

**開工時要重新問一次「不翻術語」那個決定**——那時待翻項會含 `%1$s` 格式參數
（[實測] MP2 的 lang 值 37% 有），那是機器驗得出來的另一類（見上方「決定」那節）。

順帶會用到的東西已經備好：`level_name` / `book_title` / `book_author` /
`draft_book_page` 四個 category 早就在 `IN_PLACE_CATEGORIES` 裡，`in_place` 的
`plain_string` 形狀也實作好了（有單元測試，但**還沒有任何 region 路徑走得到它**
——那四個欄位都在 `level.dat` 或物品裡）。

### 2. M14 CLI／報告／文件

### 已知缺口（不急，但別忘了）

* **`occurrence.raw_snapshot` 一直是 null。** `expected_encoding` 守門看得到「形狀
  變了」，看不到「形狀沒變但字變了」——`in_place` 保留形狀，所以使用者若在 extract
  之後自己把箱子改名，apply 會蓋掉他的改名。合約裡的 `raw_snapshot` 正是為這件事
  準備的欄位。M12 有一條測試把這個缺口釘住，接上去的那天它會變紅。
* **`run_apply` 不比對世界指紋。** extract 記了 `world_fingerprint`，apply 只記錄不
  比對，全靠 per-node 守門。M14 報告那一輪順手補掉。
* **`book_page` 的寬度還沒校準**（114px 是 `[文件]`）。v1 還沒掃到書本，所以連一個
  真實資料點都沒有；M13 掃到之後要照 `docs/m8-checklist.md` 再跑一次校準。
* **`json_string_array` 形狀的 `in_place` 仍拒寫**，沒測過。實務上罕見。

## 開工前該補掉的兩件事

**兩項都已解決**（第 1 項 2026-08-21、第 2 項由 M4）。留著是因為它們的結論仍然重要。

1. ~~**混合 list 存到磁碟後是什麼形狀**~~ → **2026-08-21 解決，而且不用進遊戲**：那種 list **不可能存在**。`TAG_List` 在 NBT 格式層就帶單一元素型別 id，把 `CompoundTag` 塞進 String list 會直接 `TypeError`。所以「四行全部改寫」是**格式強制**的，寫入層連「不小心只改一行」都做不到。詳見 `SPIKE_RESULT.md`。
2. ~~**DV < 4325 的 chunk 經 DataFixer 升級後，舊式 JSON 是否被正確解析**~~ → **M4-2 已答**：三種舊式形式全部被解析，且存回磁碟時轉成 `{"": …}`。4325 這條界線由對照實驗確立。

其餘 `[待驗]` 項見 `SPIKE_RESULT.md`「尚待驗證」表。

---

## 環境備忘

- **語料地圖在版本隔離的資料夾**：`%APPDATA%\.minecraft\versions\1.21.10\saves`，不是 `%APPDATA%\.minecraft\saves`。找不到 Minecraft Party 2 就是找錯地方了。
- `spike/.venv` 與 `spike/.venv_alt` 共 134 MB，已 gitignore。
- `claude-code-stats/` 是**放在同一個資料夾裡的第三方工具**，與 mcmt 無關，已 gitignore。
- 驗證合約：`.venv\Scripts\python tools/validate_contracts.py`（目前 46 passed, 0 failed）。`jsonschema` + `referencing` 是 dev 相依，不是執行期相依。
- 開發環境是根目錄的 `.venv`（`pip install -e ".[dev,lz4]"`），跑測試：`.venv\Scripts\python -m pytest`（目前 502 passed）。**全域 python 沒有 pytest**，直接打 `python -m pytest` 會失敗。
- 跑 CLI：`.venv\Scripts\python -X utf8 -m mcmt.cli {doctor|sandbox import|extract|apply} …`。
- **heredoc 會吃掉反斜線**：用 `bash << 'PY'` 寫含 `
`、``、` ` 的 Python 原始碼會被破壞（曾寫出 NUL byte 讓檔案無法解析）。含跳脫序列的檔案改用 Write 工具，或用 `chr(92)` 組出反斜線。
- 真實地圖的路徑：MP2 在 `versions.21.10\saves`、`Arena of Darkness` 在 `versions.20.4\saves`、`100 Ways To Die` 在桌面、自建探測世界 `TT_WORLD_NAME_PROBE` 在 `.minecraft\saves`。**`-X utf8` 是必要的**，Windows 終端機的預設編碼會把中文報告印成亂碼。
- `sandbox/` 已有一份 95 MB 的「100 Ways To Die」副本（gitignore）。M4 要的是 DataVersion 3955 的 chunk，那在 Minecraft Party 2；這份是 4325，可以留著當寫入測試的對象。
- 測試 fixture 一律取自自建的 `TT_WORLD_NAME_PROBE`，不放語料地圖的內容（授權考量，見 M3 那節）。
