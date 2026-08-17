# 專案進度 — mcmt

**這份檔案是跨對話的交接點。** 新開一個 Claude Code 對話時先讀這裡，就知道做到哪、下一步是什麼、哪些結論不能重新推導。
**每完成一個里程碑就更新這裡**，和「進遊戲驗證要寫回 `SPIKE_RESULT.md`」是同一個紀律：單人開發沒有第二個人會提醒你。

最後更新：**2026-08-17**（M2 完成）

---

## 一句話現況

**M0 驗證通過，M1（`doctor` 唯讀讀取鏈）與 M2（安全層）完成。`mcmt doctor` 與 `mcmt sandbox import` 都在真實地圖上跑過。下一步是 M3 nbtio 完整（region 寫入）。**

M1 只差「節點形狀分佈」那一項驗收條件——等 M5 的嗅探器，見下方 M1.4。

## 該讀哪幾份（依序）

| 檔案 | 是什麼 | 什麼時候讀 |
|---|---|---|
| `CLAUDE.md` | **規範**。安全規則、格式規則、key 生成、禁令 | 每次動手前 |
| `docs/STATUS.md` | 本檔。進度與交接 | 每次開新對話 |
| `SPIKE_RESULT.md` | **事實依據**。所有實測結論與證據等級（四級制） | 要引用「為什麼這樣設計」時 |
| `docs/superpowers/plans/2026-08-15-mcmt-architecture.md` | 架構計畫 rev.2。目錄結構、四份合約、A/B/C 題、M0–M14 | 排下一步工作時 |
| `docs/contracts/*.json` | 四份 JSON Schema（`SCHEMA_VERSION = 3`） | 寫任何跨層資料時 |
| `docs/ownership.md` | 模組邊界與三個整合檢查點 | 決定某段程式該放哪裡時 |
| `docs/adr/0007-prior-art-and-licensing.md` | 為何不得對照 maptranslator 原始碼 | 想參考既有實作時 |
| `docs/m0-checklist.md` | M0 可重跑程序（換版本時用） | 要重驗遊戲行為時 |

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
- **路徑還沒過 `ensure_readable`**（M2 才有）。接安全層時唯一要改的是 `region.py` 的 `open`，已在檔頭註明。
- 真實資料健檢（唯讀）：MP2 的 3 個 region、2,952 chunk，全 type 2、外部 0、解壓後都是 TAG_Compound、DataVersion 4556 — 與 `SPIKE_RESULT.md` 一致。

### M1.3 — 世界結構偵測（2026-08-17）✅

`src/mcmt/nbtio/structure.py`（`load_chunk_root` + `ensure_supported_structure`）+ 9 個測試。

- `UnsupportedWorldStructureError` 帶**機器可讀的 `reason`**（`level_wrapper` / `legacy_sign_text` / `missing_data_version`），所以 `doctor` 能 catch 起來統計症狀分佈，不必為了「能報數字」就把閘門做成不拋錯的版本。
- `ensure_supported_structure` 回傳 chunk 自己的 DataVersion，但那只是順路讀到——**形狀一律逐節點嗅探**。
- 放在 `nbtio/` 而不是計畫的 `scan/`：這裡只判斷位元組是什麼形狀、不碰語意，錯誤也都是 `FormatError` 家族；`scan/` 要到 M5 才存在。

**真實資料推翻了一個說法，已寫回 `SPIKE_RESULT.md`：** 「同一世界兩套結構」**不是 1.12 專屬**，而 `Text1..Text4` 是「1.20 之前的告示牌格式」**不是「1.12 結構」**。證據：`Find The Button No Cakewalk`（1.18.2）有 852 個帶 `Level` 包裝的 chunk（抽驗 DataVersion 1963）與 15 個 DataVersion 2975、容器是現代 `block_entities` 但告示牌用 `Text1..Text4` 的 chunk。

### M1.4 — `mcmt doctor`（2026-08-17）⚠️ 一項驗收條件未做

`src/mcmt/doctor.py`（統計）+ `src/mcmt/cli/`（組裝與格式化）+ 12 個測試。指令：`mcmt doctor <世界資料夾>`，離開碼 0 可處理 / 1 拒絕 / 2 路徑有問題。

- 逐 region 檔、逐 chunk 串流，峰值記憶體是單一 chunk。region header 壞掉時記錄並中止那一張，**掃描繼續**。
- **「唯讀」有測試擋著**：比對掃描前後世界資料夾內每個檔案的 mtime 與大小。
- 掃描範圍是所有名為 `region` 的目錄（含 `DIM-1`/`DIM1`/datapack 自訂維度）。`entities/` 與 `poi/` 不算方塊 chunk，v1 不看。

**未做：節點形狀分佈。** 那需要 7 種形狀的嗅探器，而 `occurrence.encoding` 的唯一權威只能有一份——現在另寫一份等於製造兩個會漂移的判斷邏輯。**等 M5 的 `model/component.py` 出來後接進 doctor**，這是 M5 的收尾項，別忘了。

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

---

## 下一步：M3 — nbtio 完整

region **寫入**（外科式 + timestamp 表規則）、`datfile.py`、損壞防禦四種畸形檔。

| 任務 | 驗收條件 |
|---|---|
| M3.1 region 寫入 | 未修改的 chunk **原封複製原始壓縮位元組**；未改的 timestamp 原樣搬運、改過的更新為當下時間；磁區重整記進 `warnings` 的 `sector_realignment` |
| M3.2 `datfile.py` | `level.dat` 的 gzip NBT 讀寫 |
| M3.3 損壞防禦 | 四種畸形檔（截斷、offset 指向檔外、長度為 0 的空槽、磁區數溢位）——M1.2 已擋下前三種，補齊並確認寫入端同樣防禦 |

**寫入層的兩個前提已經就位**：`BackupSet`（M2.4）與 `ensure_writable`（M2.1）。順序不能反——「先寫入再備份」是 CLAUDE.md 明列的反模式。

之後：`M4 legacy 寫入驗證 ─► M5 掃描 ─► M6 規則引擎 ─► M7 extract ─► M8 字寬校準 ─► M9 翻譯層 ─► M10 resourcepack 後端 ─► M11 寫入層 ─► M12 自動化端到端 ─► M13 掃描廣度 ─► M14 CLI/報告/文件`

---

## 開工前該補掉的兩件事

兩項都不阻塞 M1，但**在對應里程碑開工前要補**，否則會把推論當事實用：

1. **混合 list 存到磁碟後是什麼形狀**（`[待驗]`，**M11 前必補**）。M0 那次實際下的是 `/data merge` 且正面用了混合 list（第一元素 compound、其餘裸字串），指令被接受且顯示正確，但**沒做回讀取證**。`write/` 的 list 提升邏輯目前建立在推論上。補法：`/data get block ... front_text.messages` + `spike/probe_raw_nbt.py` 看實際 tag 型別。
2. **DV < 4325 的 chunk 經 DataFixer 升級後，舊式 JSON 是否被正確解析**（目前只有 `[文件]` 級推論，**M5 前該補**）。它決定 M0 結論 ③ 的跳過規則是否真的該以 4325 為界。

其餘 `[待驗]` 項見 `SPIKE_RESULT.md`「尚待驗證」表。

---

## 環境備忘

- **語料地圖在版本隔離的資料夾**：`%APPDATA%\.minecraft\versions\1.21.10\saves`，不是 `%APPDATA%\.minecraft\saves`。找不到 Minecraft Party 2 就是找錯地方了。
- `spike/.venv` 與 `spike/.venv_alt` 共 134 MB，已 gitignore。
- `claude-code-stats/` 是**放在同一個資料夾裡的第三方工具**，與 mcmt 無關，已 gitignore。
- 驗證合約：`.venv\Scripts\python tools/validate_contracts.py`（目前 44 passed, 0 failed）。`jsonschema` + `referencing` 是 dev 相依，不是執行期相依。
- 開發環境是根目錄的 `.venv`（`pip install -e ".[dev,lz4]"`），跑測試：`.venv\Scripts\python -m pytest`（目前 127 passed）。**全域 python 沒有 pytest**，直接打 `python -m pytest` 會失敗。
- 跑 CLI：`.venv\Scripts\python -X utf8 -m mcmt.cli doctor "<世界資料夾>"`、`... -m mcmt.cli sandbox import "<來源世界>"`。**`-X utf8` 是必要的**，Windows 終端機的預設編碼會把中文報告印成亂碼。
- `sandbox/` 已有一份 95 MB 的「100 Ways To Die」副本供 M3/M4 用（gitignore）。
