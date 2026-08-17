# M4 — legacy 寫入驗證（可重跑程序）

**目的**：確認在 **DataVersion 遠低於 4325** 的 chunk 裡寫入 legacy JSON 形式的
translate key，1.21.11 會不會正確顯示；以及該 chunk 的 DataVersion 會不會被順手升級。

這一項不寫程式，是**進遊戲看結果**。準備工作已經自動化在 `tools/m4_prepare.py`。

---

## 為什麼是 `Arena of Darkness`

原本計畫寫「在 DataVersion 3955 的 chunk 寫入」，指的是 Minecraft Party 2。**但 MP2
的 3955 chunk 一面告示牌都沒有**——全掃 207,515 個 chunk，DV 3955 的告示牌數為 **0**，
與 `SPIKE_RESULT.md` 記的「3955 區域沒有 `front_text` 形狀的告示牌」一致。

改掃全部 20 個世界後找到替代品：

| 世界 | 版本 | DV < 4325 且有 `front_text` 告示牌 |
|---|---|---|
| **Arena of Darkness** | 1.20.4 | **DV 3700：737 面** · DV 3465：11 面 |
| 【酷米家族】狼人殺 AI 4.0 | 1.21.4 | DV 4189：2,298 面 |
| Minecraft Party 2 | 1.21.10 | 0 面 |

選 `Arena of Darkness`：3700 遠低於分水嶺 4325，而且它的告示牌**本來就在用**
`json_string_scalar`（`'"Queue Refight"'`）與 `'""'`，正是我們要驗的形狀。

---

## 準備（已完成，可重跑）

```
mcmt sandbox import "<...>\1.20.4\saves\Arena of Darkness"
python tools/m4_prepare.py "sandbox/Arena of Darkness" --region region/r.-1.-1.mca --chunk 1022
```

腳本改寫 chunk 1022 裡**本來就空白**的 4 面告示牌（挑空白的，看到的任何東西才確定
是我們造成的），四行分別測四件事，**四行都是 `TAG_String`**（legacy 形狀）：

| 行 | 寫進去的字面內容 | 驗什麼 |
|---|---|---|
| 1 | `{"translate":"mcmt.test.legacy"}` | 資源包的 key 在舊世代 chunk 解不解得開 |
| 2 | `{"text":"對照組A 物件"}` | 舊式 JSON **物件**到底有沒有被解析 |
| 3 | `"對照組B 純量"` | `json_string_scalar`（這張地圖自己就在用的形狀） |
| 4 | `""` | 空字串在舊世代顯示空白，還是像 M0-4 那樣顯示兩個引號 |

第 2、3 行同時是「你找對告示牌了」的訊號：就算資源包整個沒生效，它們也該出現。

`resources.zip`：`mcmt.test.legacy` → `哈囉舊世代`（`zh_tw` 與 `en_us` 都放，語言不是
繁中也能看到）。

> **地圖自己帶了一個 131 MB 的 `resources.zip`。** 第一版腳本直接覆蓋掉它，`BackupSet`
> 接住了。現在是**合併**：既有 329 個條目一個都不動（含地圖自己的 `pack.mcmeta`），
> 只加上我們命名空間底下的 2 個 lang 檔。這正是 M10「既有 pack 合併」的預演。

### 準備後的自動檢查（已通過）

- 同 region 953 個 chunk，**只有 index 1022 的 payload 與 timestamp 有變**
- 改動後 chunk 的 DataVersion 仍是 **3700**（工具沒有升級它）
- 4 面告示牌的四行都是 `TAG_String`，內容如上表
- `resources.zip` 331 個條目、`pack.mcmeta` 在根目錄、zip 完整性 OK

---

## 進遊戲（需要人）

1. 把 `sandbox\Arena of Darkness` **整個資料夾複製**到 `%APPDATA%\.minecraft\saves\`
   （工具永不自動複製回去——那是使用者的決定，CLAUDE.md §1.1）
2. 用 **1.21.11** 開啟。會跳「上次遊玩版本較舊」的警告，那是預期的
3. `/gamemode spectator`（或 creative）
4. `/tp @s -21 -17 -12`，看向附近的告示牌。另外三面在
   `-23 -17 -12`、`-21 -17 -16`、`-23 -17 -16`
5. **截圖**，並記下四行各顯示什麼

### 要回報的四件事

| # | 問題 | 可能的結果 |
|---|---|---|
| 1 | 第 1 行顯示什麼 | `哈囉舊世代` = **legacy 路線成立** · 字面的 `{"translate":...}` = DataFixer 沒跑 |
| 2 | 第 2 行顯示什麼 | `對照組A 物件` = 舊式 JSON 物件有被解析 |
| 3 | 第 3 行顯示什麼 | `對照組B 純量` = 純量形式有被解析 |
| 4 | 第 4 行顯示什麼 | 空白 = 與 native chunk 的 M0-4 行為**不同**（那裡顯示兩個引號） |

### 離開遊戲後（我來跑）

```
python -X utf8 -c "..."   # 重讀 chunk 1022 的 DataVersion
```

**關鍵觀察**：DataVersion 若從 3700 變成 4671，代表遊戲順手升級了那個 chunk——
「工具永不升級格式、讀什麼世代寫回什麼世代」的承諾就有一個前提條件：**只要使用者
在新版本開過那個 chunk，世代就已經被改變了**，與我們無關但會影響 `expected_encoding`
守門的假設。

---

## 結果

**尚未執行。** 進遊戲後把四行結果與 DataVersion 觀察寫回 `SPIKE_RESULT.md`「尚待驗證」
表並標 `[遊戲實測]`，推翻既有推論時**保留原推論並說明為何被推翻**。

**若第 1 行失敗**：`write/` 的設計要在寫任何實作前先改——那代表舊世代 chunk 不能走
resourcepack 路線，只剩「直接把譯文寫進節點」這條，而那是 v1 移出範圍的後端 A。
