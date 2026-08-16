# ADR 0007 — 參考專案與授權

- 狀態：已決定
- 日期：2026-08-16
- 相關：`CLAUDE.md` §5 禁令 2、`LICENSE`

## 背景

本專案為 GPLv3、公開發布。SPIKE_RESULT.md 記載「已讀原始碼」的參考專案 `to2mbn/maptranslator`，並宣稱借用其「不動點規則標記」架構。「已讀原始碼」之後照著寫，若實作結構高度相似，會有授權污染爭議。發布前必須把授權關係釐清並留下書面紀錄。

## 查證結果

### to2mbn/maptranslator — **GPLv2-only（保守認定）**

| 查證項目 | 結果 |
|---|---|
| 儲存庫（現於 `yushijinhun/maptranslator`）授權標示 | GitHub 顯示 `GPL-2.0 license` |
| `LICENSE` 檔內容 | GNU GPL **Version 2, June 1991** 全文 |
| 原始碼檔頭（`process/NodeReplacer.java`） | **無任何授權標頭**，檔案直接以 `package` 宣告開始 |
| 明示的 "or (at your option) any later version" 授權 | **未發現** |

> **陷阱**：GPLv2 授權書本身的附錄（"How to Apply These Terms to Your New Programs"）一定含有 "or (at your option) any later version" 字樣。那是**教你怎麼授權的樣板**，不是專案已經做出的授權宣告。自動化工具與 LLM 摘要很容易把它誤讀成 or-later。判準是**檔頭或 README 的明示宣告**，不是 LICENSE 檔的內文。

「or later」的權限必須由著作權人**主動授予**。本專案未見任何主動授予，因此保守認定為 **GPLv2-only**。

**後果**：GPLv2-only 與 GPLv3 **不相容**。其程式碼**不得**併入本專案。

### WorldTranslationExtractor（Suso, 2024）— **MIT**

同領域、同語言（Python）、功能高度重疊（抽取世界文字產生語言檔）的既有專案。本機 `~/Downloads/WorldTranslationExtractor-main`，且已對 `100 Ways To Die` 實際執行過（產出 `wte_lang.json` 與 `100 Ways To Die_wte` 世界）。

MIT **與 GPLv3 相容**：其程式碼可以併入本專案，條件是保留 MIT 版權聲明與授權文字，並在 `NOTICE` 或檔頭標明來源。

## 決定

1. **本專案未複製 `to2mbn/maptranslator` 的任何程式碼。** 僅採用其公開描述的架構模式——「反覆對節點樹套用規則標記直到收斂」的不動點設計。架構構想不受著作權保護；程式碼的表達方式受保護。

2. **禁止逐段對照撰寫。** 不得開著 maptranslator 的原始碼一邊寫本專案的 `rules/engine.py`。這條寫進 `CLAUDE.md` §5 作為硬性禁令。實作必須從行為規格（「給定規則集，反覆套用直到標籤集合不再增長，上限 32 輪」）出發，而非從其原始碼的結構出發。

3. **maptranslator 的路徑規則不得移植。** 除授權理由外，還有技術理由：其路徑規則因 1.20.5 組件化已全部作廢，且它假設單一版本，無法處理 per-chunk 多世代。移植過去也是錯的。

4. **若日後要引用 WorldTranslationExtractor 的程式碼**，必須：
   - 在該檔檔頭標明 `Portions derived from WorldTranslationExtractor (MIT), Copyright (c) 2024 Suso`
   - 在專案根目錄新增 `NOTICE` 收錄其 MIT 全文
   - 在 commit 訊息明確說明引用範圍

   目前**尚未引用任何一行**。

5. **`SPIKE_RESULT.md` 的「已讀原始碼」標註保留。** 讀過並理解一個 GPLv2 專案的架構、再以自己的方式實作，是合法的。隱瞞讀過才是問題。但該標註同時也是本 ADR 存在的理由。

## 未決

- **是否改為 GPLv2-or-later 或雙授權**：若未來真的需要併入 maptranslator 的程式碼，本專案得改為 GPLv2-or-later。目前不需要，且 GPLv3 的專利條款與 tivoization 條款對本專案有價值，維持 GPLv3。
- **`Minecraft Party 2` 等測試素材不進版控。** 它們是第三方商業地圖，本專案只在本機讀取，不重新散布。`tests/fixtures/regions/` 只放**自建 fixture 世界**的切片，不放商業地圖的切片。這一條同樣是發布前的必要條件。
