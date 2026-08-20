# 模組邊界

單人開發。本檔的對象是**寫這個專案的 AI 助理**（以及三個月後忘記細節的自己），不是協作者。

原本靠「另一個人看不懂所以不會亂改」擋著的邊界，現在只剩下規範本身。以下是哪些模組可以自由改、哪些需要刻意的動作才能碰。

## 分層與相依方向

```
  cli/            ── 只組裝，不含邏輯
   │
   ├── scan/ ──► tree/ ──► rules/ ──► extract/     第 1–3 層：讀
   │                                      │
   │                                 extract.json
   │                                      ▼
   │        translations.<lang>.json  ← **使用者自己填**（工具不做機器翻譯）
   │                                      ▼
   ├── backends/                                    第 4 層：決定寫什麼
   │                                  editplan.json
   │                                      ▼
   └── write/  ◄── safety/                          寫入層：決定怎麼安全地寫
        │
        └── nbtio/                                  第 0 層：位元組
```

**相依只能往下。** `nbtio/` 不得 import `rules/`；`backends/` 不得 import `write/`（它只產 editplan，由 `cli/apply` 交給 writer）。

**例外（2026-08-17，M2.5）**：`nbtio/` **可以** import `safety/paths.py`。`read_region` 只收 `ReadOnlyPath`，讓「忘了過 `ensure_readable`」在型別層就被擋下，而不是靠呼叫端自律。方向上沒有環——`safety/` 只 import `errors`，永遠不會 import `nbtio/`。上圖把 `safety/` 畫在 `write/` 旁邊是因為它最初只服務寫入路徑；實際上它是所有層都能倚賴的底層設施。

`model/` 被所有層 import，因此它**不得 import 任何其他 mcmt 模組**。

## 高風險目錄

| 目錄 | 規則 |
|---|---|
| `src/mcmt/write/` | **修改必須是獨立 commit 並說明理由。** 不得在其他任務中附帶修改 |
| `src/mcmt/safety/` | 同上 |
| `docs/contracts/` | 改動必須是獨立 commit，同 commit 內更新 sample fixture，並 bump `SCHEMA_VERSION` |
| `src/mcmt/model/` | 同 `docs/contracts/`——它是 schema 的程式碼投影 |

理由：這四個目錄弄壞了，後果是「別人的地圖沒了」或「兩層之間安靜地對不上」。需要一個刻意的動作才能碰，才不會在做別的事情時順手改掉。

`spike/` 唯讀，不 import。

## 為什麼寫入層與輸出後端是分開的

後端決定**值是什麼**（這個節點放 `{translate: key}`），寫入層決定**怎麼安全地放進去**（per-chunk DataVersion 分派、NBT list 同型、外科式重寫、備份與回滾）。

原本的論證是「不讓協作者的後端層去理解 chunk 格式」，那個論證已失效。**現在的論證是**：

1. 決策 7 要求輸出後端可插拔。若寫入邏輯散在後端裡，每加一個後端就要重寫一次同樣的危險程式碼。
2. 分層讓 `editplan.json` 成為一個可檢查的中間產物——`--dry-run` 能在不碰存檔的前提下印出「打算改哪些節點、改成什麼」。這是這個工具最重要的安全網之一。

## 三個整合檢查點

其餘時間各模組可獨立推進。

1. **合約改動** — schema 一改，上下游同時要動，且 sample fixture 必須同 commit 更新。
2. **M4 → M7** — 寫入層的 `expected_encoding` 守門依賴 extract 的 `encoding` 判定穩定。`encoding` 現在是逐節點嗅探的結果，嗅探規則一改，所有既有 editplan 立即失效。
3. **首次端到端** — extract →（人翻）→ apply 第一次接在真實資料上跑。前面每一層的單元測試都通過，不代表接起來會動。

## 工作紀律

- **一個任務一個 commit。** commit 訊息說明「為什麼」，不是「改了什麼」（diff 已經說了改什麼）。
- **卡住超過 30 分鐘，寫下「我試了什麼、看到什麼」** 到 `docs/journal/`。單人時這是唯一的思路外化機制，寫的過程本身常常就解掉了。
- **進遊戲驗證的結果一律寫回 `SPIKE_RESULT.md`**，標註證據等級。單人時沒人提醒你更新，只能靠規範。推翻先前推論時保留原推論並說明為何被推翻——證據分級與自承錯誤是那份文件的價值所在。
