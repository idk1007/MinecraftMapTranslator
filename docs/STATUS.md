# 專案進度 — mcmt

**這份檔案是跨對話的交接點。** 新開一個 Claude Code 對話時先讀這裡，就知道做到哪、下一步是什麼、哪些結論不能重新推導。
**每完成一個里程碑就更新這裡**，和「進遊戲驗證要寫回 `SPIKE_RESULT.md`」是同一個紀律：單人開發沒有第二個人會提醒你。

最後更新：**2026-08-17**

---

## 一句話現況

**規劃與合約已定稿，M0 端到端驗證已通過，尚未寫任何 `src/` 程式碼。下一步是 M1.1 壓縮分派。**

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

---

## 下一步：M1 — `mcmt doctor`（唯讀）

從 **M1.1 壓縮分派**開始 —— 整條讀取鏈最底層、最容易測、也最容易寫錯（`0x80` 遮罩順序）的一環。

| 任務 | 驗收條件 |
|---|---|
| M1.1 壓縮分派 | 四種類型 + `0x80` **遮罩先行**；未知類型 `UnknownCompressionError` 含數值與 chunk index；缺 `lz4` 時訊息含安裝指令 |
| M1.2 region 讀取 | 原始壓縮位元組**不解壓**；offset/length/sector 邊界檢查；截斷檔 `TruncatedRegionError` |
| M1.3 世界結構偵測 | `Level.TileEntities` / `Text1..Text4` / `data_version` 為 null → `UnsupportedWorldStructureError`；`0x80` → `ExternalChunkError` |
| M1.4 `doctor` CLI | DataVersion 直方圖、壓縮分佈、`.mcc` 數、節點形狀分佈、疑似損壞 chunk。**per-region 串流**，峰值記憶體為單一 chunk。唯讀 |

走 TDD：先寫失敗的測試 → 確認失敗 → 最小實作 → 確認通過 → 一個任務一個 commit。

之後：`M2 安全層 ─► M3 nbtio ─► M4 legacy 寫入驗證 ─► M5 掃描 ─► M6 規則引擎 ─► M7 extract ─► M8 字寬校準 ─► M9 翻譯層 ─► M10 resourcepack 後端 ─► M11 寫入層 ─► M12 自動化端到端 ─► M13 掃描廣度 ─► M14 CLI/報告/文件`

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
- 驗證合約：`python tools/validate_contracts.py`（目前 44 passed, 0 failed）。`jsonschema` + `referencing` 是 dev 相依，不是執行期相依。
