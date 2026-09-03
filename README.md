# mcmt

Minecraft 地圖翻譯工具。Python 3.11+ · GPLv3 · Java Edition 1.21.11＋。

把冒險地圖裡的文字——告示牌、物品名、成書、記分板、boss 條、自訂進度——翻成
你要的語言。主要走資源包（自訂命名空間的 lang key），少數不能走資源包的欄位
才直接改寫存檔。

**工具本身不做翻譯，也不連任何翻譯服務**（沒有 API、沒有網路相依）。它把「掃描」
和「寫回」拆成兩個指令，中間夾的是你把 `target` 填好的時間——自己翻、丟給 LLM
翻、找譯者翻都行：

```
mcmt extract <世界>   →  translations.zh_tw.json   ← 你在這裡填譯文
                                  │
                          （把每筆的 target 填上）
                                  │
mcmt apply <世界> --translations translations.zh_tw.json
                      →  resources.zip + 寫回存檔 + apply_report.json
```

## 安全

這個工具會修改別人花幾千小時做的地圖存檔，所以每一步都以「不弄壞」為前提：

- **動任何存檔前一定先備份**，備份失敗就中止——沒有 flag 可以關掉。
- **只改該改的地方**：沒被翻譯到的資料原樣不動，連地圖的格式版本都不升級。
- **所有寫入都關在 `sandbox/` 裡的世界副本**，工具**永不**自動覆蓋你
  `.minecraft/saves/` 裡的存檔——要不要換上翻譯版，永遠是你手動決定。
- 已在 Java 1.21.11 與 26.2 上實際進遊戲驗證過。

**目前不翻**：指令方塊與 `.mcfunction`（datapack 函式）裡的文字。

---

## 安裝

需要 Python 3.11 以上。

```
git clone <這個 repo 的網址>
cd minecraft-map-translate
python -m venv .venv

# Windows
.venv\Scripts\pip install -e .
# macOS / Linux
.venv/bin/pip install -e .
```

少數用 LZ4 壓縮的地圖需要額外裝：`pip install -e ".[lz4]"`。

裝好之後 `mcmt` 就在虛擬環境的 PATH 上（`source .venv/bin/activate` 之後直接打
`mcmt`）。**Windows 終端機請一律加 `-X utf8`**，否則中文報告會變亂碼：

```
.venv\Scripts\python -X utf8 -m mcmt.cli <指令> …
```

以下範例用 `mcmt` 代表這一整串。

---

## 最短可行路徑

```
# 1. 把要翻的世界複製進 sandbox（extract / apply 只認 sandbox 底下的副本）
mcmt sandbox import "C:\Users\you\AppData\Roaming\.minecraft\saves\範例地圖"

# 2. 掃描，產出待翻檔 sandbox/.mcmt-out/範例地圖/translations.zh_tw.json
mcmt extract "sandbox/範例地圖" --lang zh_tw

# 3. 把 translations.zh_tw.json 每筆的 target 填上（自己翻、丟給 LLM、找譯者都行）

# 4. 寫回
mcmt apply "sandbox/範例地圖" --translations "sandbox/.mcmt-out/範例地圖/translations.zh_tw.json"
```

翻好的世界在 `sandbox/範例地圖`，自己複製回 `.minecraft/saves` 就完成了——這一步
工具不會替你做。

### 翻成別的語言

`--lang zh_tw` 換成任何 Minecraft 語言代碼即可，待翻檔名跟著變
`translations.<代碼>.json`。例如翻成英文：

```
mcmt extract "sandbox/範例地圖" --lang en_us
mcmt apply   "sandbox/範例地圖" --translations "sandbox/.mcmt-out/範例地圖/translations.en_us.json"
```

`en_us` 的譯文會顯示給遊戲語言設成英文的玩家，`ja_jp` 給日文，以此類推。一個世界
也可以放多份不同語言的資源包 lang 檔（多跑幾次不同 `--lang` 即可）。

---

## 四個指令

| 指令 | 做什麼 |
|---|---|
| `mcmt doctor <世界>` | 健檢（**唯讀**）：DataVersion 分佈、節點形狀分佈、有多少節點會被跳過不翻、這個世界能不能處理 |
| `mcmt sandbox import <來源世界>` | 唯一合法的把世界帶進 `sandbox/` 的入口。完整目錄複製，記錄來源與指紋 |
| `mcmt extract <sandbox 世界>` | 掃描世界，產出待翻檔。唯讀掃描，只寫 `sandbox/.mcmt-out/` |
| `mcmt apply <sandbox 世界> --translations …` | 讀翻好的檔案，產出 `resources.zip` 並寫回存檔。`--dry-run` 完全不碰存檔，只印出打算改什麼並產 `editplan.json` |

`doctor` 可以直接對 `.minecraft/saves` 裡的世界跑（唯讀）。`extract` 和 `apply` 只
處理 `sandbox/` 底下的副本——所以第一步一定是 `sandbox import`。

---

## 出問題再看這裡

上面順順跑完就不用管這一段。

- **想先確認地圖能不能處理**：`mcmt doctor "<世界路徑>"`（唯讀）。印出 DataVersion
  分佈、有多少節點會被跳過不翻、這個世界能不能處理。1.12 舊地圖、帶外部 `.mcc`
  chunk 的世界會在這裡被拒絕。
- **想先看 `apply` 會改什麼、但先不碰存檔**：`mcmt apply … --dry-run`。印出完整計畫
  並產 `editplan.json`，一個位元都不寫。
- **`apply` 說有些譯文沒寫進去**（佔位符對不上、太長、節點在 extract 之後被改過…）：
  原因逐筆列在 `sandbox/.mcmt-out/範例地圖/apply_report.json`。
- **備份**：每次 `apply` 前自動備份到 `sandbox/.mcmt-backups/<世界>/<時間戳>/`（與世界
  資料夾平行，資料夾本身不會多出東西）；備份失敗 `apply` 直接中止。

---

## 待翻檔長什麼樣

`translations.zh_tw.json`（語言代碼跟著 `--lang` 變）是**這個專案唯一由你提供內容的
檔案**。`entries` 以翻譯單位的 id 為鍵，每筆自帶原文、位置與提示：

```jsonc
{
  "entries": {
    "u:sign:1a2b3c4d5e6f7a8b": {
      "source": "Welcome to the\nExample Hall",
      "target": "",
      "note": "sign · 寬度上限 90px（約 10 個中文字） · 出現 3 次",
      "where": "overworld 128,71,-64"
    }
  }
}
```

規則：

- **`apply` 只讀 `target`。** `source` 不拿去比對——翻譯途中把它改短或加註是常見的
  事，那不該讓整份檔案失效。與某一份 extract 的綁定靠檔案裡的指紋。
- **空的 `target` = 尚未翻譯。** `apply` 保留原文並列進報告。
- **`"status": "skip"`** 是「刻意不翻」，報告會跟「還沒翻」分開來算。
- `note` 會給出這一行的寬度上限——px 數字，以及大約幾個 CJK 字寬（非 CJK 語言
  看 px 就好）。字寬是實際量出來的；超寬的譯文 `apply` 會**拒絕寫入**並列進報告，
  不是默默截斷。
- 原文裡的 `[[0]]`、`[[1]]` 是**段落格式標記**。譯文裡這些標記的數量必須跟原文
  完全一致——多一個、少一個、重複都會讓那一筆被拒絕（少一個 `§` 格式碼就會染到
  整行結尾）。順序可以不同。只有一個段落時不會有標記，純文字就是純文字。

---

## 授權

Copyright (C) 2026 mcmt contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either **version 3 of the License, or
(at your option) any later version**.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

授權全文見 `LICENSE`。每個原始碼檔頂端標註 `# SPDX-License-Identifier: GPL-3.0-or-later`。

---

## 參與開發

內部設計文件（架構決策、資料合約、開發進度）在 `docs/`。相依套件與先行專案的
說明見 [`docs/CREDITS.md`](docs/CREDITS.md)。
