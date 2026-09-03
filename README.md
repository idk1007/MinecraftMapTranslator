# mcmt

Minecraft 地圖翻譯工具。Python 3.11+ · GPLv3 · 目標版本 Java Edition 1.21.11。

以資源包（自訂命名空間的 lang key）為主要路線翻譯冒險地圖裡的文字——告示牌、物品名、
成書、記分板、boss 條、自訂進度——並對無法走資源包的少數欄位做外科式就地寫入。

存檔的 NBT 寫回**不綁版本**（逐 chunk 讀它自己的 DataVersion、原樣寫回，永不升級格式），
已在 Java 1.21.11 與 26.2 上進遊戲驗證。資源包宣告一個很寬的 `supported_formats` 區間，
新版遊戲不必更新工具就能載入。指令方塊與 `.mcfunction` 裡的文字目前**不抽**（見
`docs/STATUS.md`）。

**這個工具不做機器翻譯。** 沒有 API、沒有網路相依。它把「掃描」和「寫回」拆成兩個
指令，中間夾的是你自己拿任何編輯器翻譯的時間：

```
mcmt extract <世界>   →  translations.zh_tw.json   ← 你編輯這個檔案
                                  │
                          （用任何編輯器把 target 填上）
                                  │
mcmt apply <世界> --translations translations.zh_tw.json
                      →  resources.zip + 外科式寫回 + apply_report.json
```

**這個工具會修改別人花幾千小時做的地圖存檔。** 設計上的每一條規則都是為了讓「除了
要改的地方以外什麼都沒動」成為結構性保證，不是希望：

- **改任何存檔前強制備份，備份失敗就中止。** 沒有 flag 可以關掉。
- **未被修改的 chunk 原封複製其原始壓縮位元組，絕不重新編碼。** 只有真的被改到的
  節點才走「解碼 → 改 → 編碼」。
- **所有寫入都被圍在 `sandbox/` 底下**，工具**永不**自動把結果複製回 `.minecraft/saves/`。
  那一步是你的手動決定。

規範細節見 `CLAUDE.md`，實測依據見 `SPIKE_RESULT.md`，開發進度見 `docs/STATUS.md`。

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

想讀 LZ4 壓縮（type 4）的 chunk 再加上 `lz4` extra：`pip install -e ".[lz4]"`。
一般地圖用不到。

裝好之後 `mcmt` 就在虛擬環境的 PATH 上（`source .venv/bin/activate` 之後直接打
`mcmt`）。**Windows 終端機請一律加 `-X utf8`**，否則中文報告會變亂碼：

```
.venv\Scripts\python -X utf8 -m mcmt.cli <指令> …
```

以下範例用 `mcmt` 代表這一整串。開發相依（跑測試）：`pip install -e ".[dev]"`，
測試指令 `python -m pytest`。

---

## 四個指令

| 指令 | 做什麼 |
|---|---|
| `mcmt doctor <世界>` | 健檢（**唯讀**）：DataVersion 分佈、節點形狀分佈、有多少節點會被跳過不翻、這個世界能不能處理 |
| `mcmt sandbox import <來源世界>` | 唯一合法的把世界帶進 `sandbox/` 的入口。完整目錄複製，記錄來源與指紋 |
| `mcmt extract <sandbox 世界>` | 掃描世界，產出待翻檔。唯讀掃描，只寫 `sandbox/.mcmt-out/` |
| `mcmt apply <sandbox 世界> --translations …` | 讀翻好的檔案，產出 `resources.zip` 並外科式寫回。`--dry-run` 完全不碰存檔，只印出打算改什麼並產 `editplan.json` |

`doctor` 可以直接對 `.minecraft/saves` 裡的世界跑（唯讀）。`extract` 和 `apply` 只
處理 `sandbox/` 底下的副本——所以第一步一定是 `sandbox import`。

---

## 最短可行路徑

假設要翻一張放在 `.minecraft/saves/My Adventure` 的地圖：

```
# 1. 先健檢原始世界（唯讀，不會動到任何東西）
mcmt doctor "C:\Users\you\AppData\Roaming\.minecraft\saves\My Adventure"

# 2. 複製進 sandbox
mcmt sandbox import "C:\Users\you\AppData\Roaming\.minecraft\saves\My Adventure"
#    → sandbox/My Adventure/

# 3. 掃描，產出待翻檔
mcmt extract "sandbox/My Adventure" --lang zh_tw
#    → sandbox/.mcmt-out/My Adventure/
#        translations.zh_tw.json   ← 編輯這個
#        extract.json / keymap.json  機器用，不要手動改

# 4. 用任何編輯器打開 translations.zh_tw.json，把每筆的 target 填上

# 5. 寫回（先 dry-run 看一遍，確認沒問題再拿掉 --dry-run）
mcmt apply "sandbox/My Adventure" \
    --translations "sandbox/.mcmt-out/My Adventure/translations.zh_tw.json" --dry-run

mcmt apply "sandbox/My Adventure" \
    --translations "sandbox/.mcmt-out/My Adventure/translations.zh_tw.json"
#    → sandbox/My Adventure/resources.zip  + 外科式寫回
#    → sandbox/.mcmt-out/My Adventure/apply_report.json

# 6. 確認遊戲裡顯示正確後，自己手動把 sandbox/My Adventure 複製回 .minecraft/saves
#    （工具不會替你做這一步）
```

備份放在 `sandbox/.mcmt-backups/<世界>/<時間戳>/`，與世界資料夾平行——世界資料夾本身
不會多出備份檔。

---

## 待翻檔長什麼樣

`translations.zh_tw.json` 是**這個專案唯一給人手動編輯的檔案**。`entries` 以翻譯單位
的 id 為鍵，每筆自帶原文、位置與提示：

```jsonc
{
  "entries": {
    "u:sign:1a2b3c4d5e6f7a8b": {
      "source": "Welcome to the\nDark Arena",
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
- `note` 會告訴你這一行放得下幾個中文字（字寬是量出來的）。超寬的譯文 `apply` 會
  **拒絕寫入**並列進報告，不是默默截斷。
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

> **為什麼這段話要在這裡，而不是只放一份 `LICENSE`**：`LICENSE` 只是授權「條文」，上面這段才是**授權的授予**（尤其是 "or (at your option) any later version" 這句）。兩者不能互相取代——`LICENSE` 附錄裡的 "How to Apply These Terms" 是**教你怎麼授予**的說明，不是授予本身。這個區別在 `docs/adr/0007-prior-art-and-licensing.md` 判定 to2mbn/maptranslator 為 GPLv2-only 時是決定性的，別在自己的專案上犯同一個錯。

## 第三方

- `spike/` 是唯讀的自製探針，不是相依。
- 執行期相依：`amulet-nbt` + 標準函式庫。`lz4`（`mcmt[lz4]`）為可選，用來讀 type 4 壓縮的 chunk。
- `jsonschema` / `referencing` 是 dev/test 相依，不是執行期相依。
- 本專案**不含**任何來自 to2mbn/maptranslator 的程式碼；僅採用其公開描述的架構模式。理由見 ADR-0007。
