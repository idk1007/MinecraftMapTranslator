# M0 逐項執行清單 — 端到端最小驗證（手動）

**狀態：已於 2026-08-17 執行完畢。** 結果見 `SPIKE_RESULT.md`「M0 遊戲實測」一節。
本檔保留為**可重跑的程序**——換 Minecraft 版本、換資源包格式、或要重驗 `[待驗]` 項時照著再跑一次。

M0 不寫任何程式碼。它的唯一目的是在投入實作前證明或推翻「自訂命名空間 key + 自製 `resources.zip`」這條鏈。
若這條鏈不成立，M1 之後的所有里程碑全部作廢——這就是先付這筆最便宜的證偽成本的理由。

---

## 前置

- [ ] **另存世界備份。** `TT_WORLD_NAME_PROBE_BACKUP` 是舊的（15 MB vs 18 MB），不可靠，重做一份。
- [ ] 啟動器版本確認為 **1.21.11**（不是 1.21.10；版本隔離的存檔在 `versions/<ver>/saves/`）。
- [ ] 世界開作弊。
- [ ] 記下世界資料夾絕對路徑。

## 對照設計：一塊告示牌，正反兩面

沿用 spike `write_sign_variants.py` 已驗證有效的手法。正反面在**同一個 chunk、同一個 block entity、同一次載入**，任何顯示差異只可能來自 `messages[]` 的形狀差異——沒有其他變因。

| 面 | 寫入形狀 | 驗什麼 |
|---|---|---|
| 正面 | native compound `{translate:"..."}` | **主目標**：資源包路線是否成立 |
| 背面 | legacy JSON 字串 `'{"translate":"..."}'` | native chunk 內的 legacy 形狀是否有效 + `'""'` 如何算繪 |

## 執行

- [ ] 放一塊站立式告示牌（`minecraft:sign`，**不上蠟**），四行留空。F3 記下座標。
- [ ] 正面：
      `/data modify block <x> <y> <z> front_text.messages set value [{translate:"mcmt.test.hello"},{text:""},{text:""},{text:""}]`
- [ ] 背面：
      `/data modify block <x> <y> <z> back_text.messages set value ['{"translate":"mcmt.test.hello"}','""','""','""']`
- [ ] **回讀取證**：`/data get block <x> <y> <z> front_text`（與 `back_text`）。輸出從
      `%APPDATA%\.minecraft\logs\latest.log` 抓，**不要對著聊天視窗抄**——抄的過程會把引號、逃逸與空白抹平，而這次要驗的正是引號與空白。
- [ ] 手寫 `resources.zip`：
      - `pack.mcmeta`：`pack_format: 75` + `supported_formats` 區間
      - `assets/mcmt/lang/zh_tw.json`：`{"mcmt.test.hello":"哈囉世界"}`，**UTF-8 無 BOM**
- [ ] 用 `zipfile` 驗結構：zip 內根目錄直接是 `assets/` 與 `pack.mcmeta`，**沒有外層包裹資料夾**。
      這一步同時預演 M10 的驗收條件。
- [ ] 放進世界資料夾根目錄，語言切繁體中文，重進世界。

## 三個觀察點

- [ ] **正面第 1 行顯示「哈囉世界」→ 資源包路線成立。** 這是整個架構的最終證明。
- [ ] 正面第 2–4 行：native 零長度 `""` 是否顯示為空白。
- [ ] 背面第 1 行（legacy 形狀是否被解析）與第 2–4 行（`'""'` 顯示空白還是兩個引號）。

## `pack_format` 過期測試

- [ ] 重打包一次：`pack_format` 改為過期號（例如 `55`）並**刪掉 `supported_formats`**。
- [ ] 觀察資源包清單是警告（紅字）還是直接拒載，以及告示牌顯示有無改變。
- [ ] **記下所用的確切數值。** 上一次沒記，導致「多舊才會拒載」的邊界至今未知。

## 失敗分診

正面沒顯示中文時，**不要一次改兩個變因**。按這個順序排除：

1. 語言真的切到 `zh_tw` 了嗎（不是 `zh_cn`）？
2. `zh_tw.json` 是 UTF-8 **無 BOM** 嗎？BOM 會讓第一個 key 變成 `﻿mcmt.test.hello`。
3. zip 內有沒有多一層包裹資料夾？
4. 資源包在世界資源包清單裡有出現嗎（出現但沒生效 vs 根本沒出現，是兩種不同的病）。
5. `pack.mcmeta` 是合法 JSON 嗎（尾逗號會讓整個包靜默失效）。
6. **控制組**：把 lang key 換成原版的 `block.minecraft.diamond_block`。它在告示牌上已是 `[遊戲實測]` 有效。
   - 控制組**有效**而自訂 key 無效 → 問題在資源包（1–5 其中之一）。
   - 控制組**也無效** → 問題在告示牌的寫入形狀，不在資源包。

## 收尾

- [ ] **所有結果寫回 `SPIKE_RESULT.md`「尚待驗證」表，標 `[遊戲實測]`**，附回讀原文與截圖檔名。
      單人開發沒有第二個人會提醒你更新——這一步漏掉，下次就會重跑一次已經驗過的東西。
- [ ] 若推翻了先前的推論，**保留原推論並說明為何被推翻**，不要直接改掉。

---

## 為什麼用 `/data modify ... set value` 而不是 `/data merge`

`merge` 對 list 的語意是整體替換，但既有 `messages` 是 `TAG_List of TAG_String`、新值是 `TAG_List of TAG_Compound` 時，型別衝突行為無明確文件。`set value` 語意明確。若真的跳型別錯誤，那本身就是發現 ③ 的額外證據，記下來。

正面四個元素**全部寫成 compound**（不是 `[{translate:...},"","",""]`）——這是 NBT list 同型約束的正確寫法，也是 mcmt 實際會產生的形狀。

> **2026-08-17 那次實際下的是 `/data merge block`，且正面用了混合 list**（第一元素 compound、其餘裸字串）。指令被接受且顯示正確，但**沒有做回讀取證**，所以遊戲把它存成什麼形狀仍然未知（很可能在編解碼時被正規化了）。顯示層的五項結論不受影響，但那次執行**不能**被引用為「NBT list 可以不同型」的證據。這一項已列入 `SPIKE_RESULT.md` 的尚待驗證表。
