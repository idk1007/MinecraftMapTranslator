# mcmt (Minecraft Map Translator)

Minecraft 冒險地圖文字提取與寫回工具。

> ⚠️ **支援版本：Java Edition 1.21.11 及以上版本**（舊版本如 1.12 或含外部 `.mcc` 檔案的存檔暫不支援）。

`mcmt` 能把冒險地圖中的告示牌、自訂物品名稱、成書、記分板、Boss 血條、自訂進度等文字完整提取出來。主要以**自訂資源包（語系檔）**為途徑套用翻譯，少數特殊欄位則進行精準的安全寫回。

**本工具不做翻譯，僅負責文字的「提取」與「寫回」。**  
沒有外部 API 依賴、不需連網。執行 `extract` 產出 JSON 待翻檔，填妥 `target` 欄位後再執行 `apply` 即可完成：

```text
mcmt extract <世界>   →   translations.zh_tw.json   ← 在這裡填入譯文
                                    │
                          （填寫 target 欄位）
                                    │
mcmt apply <世界> --translations translations.zh_tw.json
                          → resources.zip + 安全寫回存檔 + apply_report.json
```

* **存檔安全第一**：所有修改都在獨立的 `sandbox/` 目錄中進行，寫回前**強制自動備份**。未修改的區塊與格式版本完全原樣保留，絕不損壞地圖。
* **目前尚不支援**：指令方塊與 Datapack 中的 `.mcfunction` 程式碼文字。

---

## 安裝

需要 Python 3.11 以上環境：

```bash
git clone https://github.com/idk1007/MinecraftMapTranslator.git
cd MinecraftMapTranslator
python -m venv .venv

# Windows
.venv\Scripts\pip install -e .
# macOS / Linux
.venv/bin/pip install -e .
```

> 💡 極少數使用 LZ4 壓縮（type 4）的地圖，請額外安裝：`pip install -e ".[lz4]"`。

安裝後 `mcmt` 就在虛擬環境的 PATH 上。下面的範例都用 `mcmt` 代表它——
**Windows 請改用 `.venv\Scripts\python -X utf8 -m mcmt.cli`**，否則指令印出的
中文報告會變亂碼（Python 3.11 在 Windows 的預設編碼不是 UTF-8）。

---

## 快速啟動

只需四個步驟即可完成地圖翻譯：

```bash
# 1. 將存檔複製進 sandbox 沙盒（避免直接改動原存檔）
mcmt sandbox import "C:\Users\you\AppData\Roaming\.minecraft\saves\範例地圖"

# 2. 掃描地圖並產出待翻檔
mcmt extract "sandbox/範例地圖" --lang zh_tw

# 3. 打開 translations.zh_tw.json 填寫翻譯（見下方說明）

# 4. 寫回存檔並生成資源包
mcmt apply "sandbox/範例地圖" --translations "sandbox/.mcmt-out/範例地圖/translations.zh_tw.json"
```

完成後，翻譯好的地圖位於 `sandbox/範例地圖`。進遊戲確認一切運作正常後，再手動複製回 `.minecraft/saves` 即可。

---

## 待翻檔長怎樣

產出的 `sandbox/.mcmt-out/範例地圖/translations.zh_tw.json` 是整個流程中**唯一由你填寫內容的檔案**：

```jsonc
{
  "entries": {
    "u:sign:1a2b3c4d5e6f7a8b": {
      "source": "Welcome to the\nExample Hall",
      "target": "歡迎來到\n範例大廳",
      "note": "sign · 寬度上限 90px（約 10 個中文字） · 出現 3 次",
      "where": "overworld 128,71,-64"
    }
  }
}
```

### 編輯規則

* **只看 `target` 欄位**：`apply` 只讀取 `target` 內容；留空代表「尚未翻譯」（保留原文）；若填入 `"status": "skip"` 則代表「刻意不翻」。
* **注意字寬限制**：`note` 會標記像素寬度（例如告示牌每行約 10 個中文字）。若文字過長超出邊界，工具在寫回時會**主動拒絕並記錄於報告**，避免遊戲內文字破版。
* **格式標記 `[[0]]`、`[[1]]` 不可增減**：它們是**段落格式標記**，標出原文裡某段顏色／樣式的起點。**譯文必須保留完全相同的標記數量**（順序可隨語意調整），少一個就會讓格式碼染到整段結尾。

---

## 讓 AI 幫你翻譯（LLM Prompt 範本）

如果你打算將 `translations.zh_tw.json` 交給 ChatGPT 或 Claude 等 AI 批次翻譯，可以直接複製以下提示詞：

> **提示詞範本**：
> 
> 你現在是一位專業的 Minecraft 繁體中文（台灣）本地化譯者。請幫我翻譯以下 JSON 格式的地圖文字資料。
> 
> **翻譯規則：**
> 1. 僅填寫每一筆的 `"target"` 欄位，其餘欄位（`source`、`note`、`where`）及 key 值請原樣保留。
> 2. 專有名詞與道具名稱請嚴格遵循 Minecraft 官方繁體中文（zh_tw）習慣（如：Nether 翻為「地獄/下界」、Emerald 翻為「綠寶石」）。
> 3. 若原文包含換行符號 `\n`，請在譯文中適當保留。
> 4. **【極度重要】** 若原文包含格式代碼（如 `[[0]]`、`[[1]]`），譯文中必須**完整保留所有編號標記**，數量不得增減，可依中文語序調整位置。
> 5. 請參考 `note` 內的字寬限制，翻譯務求通順精練，切勿超出限制長度。
> 6. 請直接回傳合法的 JSON 內容，不要包含任何開場白或多餘解釋。
> 
> 【待翻譯資料】：
> （在此貼上你的 JSON 內容）

---

## 常用指令

| 指令 | 說明與進階技巧 |
|---|---|
| `mcmt doctor <世界>` | **唯讀健檢**：檢查地圖版本（DataVersion）分佈與節點狀態，評估是否能被正確處理。可直接對 `.minecraft/saves/` 執行。 |
| `mcmt sandbox import <世界>` | **安全匯入**：將目標地圖複製進 `sandbox/` 工作區並記錄校驗指紋，是進入沙盒的唯一入口。 |
| `mcmt extract <sandbox世界>` | **提取文字**：唯讀掃描沙盒地圖中的文字，產出待翻 JSON 檔至 `sandbox/.mcmt-out/`。 |
| `mcmt apply <sandbox世界>` | **寫回與打包**：讀取翻好的 JSON，產生資源包並寫回存檔。<br>• **試跑預覽**：加上 `--dry-run` 可以在不更動存檔的情況下預覽改動計畫。<br>• **自動備份**：寫回前會自動在 `sandbox/.mcmt-backups/` 備份，備份失敗立即中止。<br>• **錯誤報告**：若有文字因太長或格式碼不合未寫入，原因會記錄在 `apply_report.json`。 |

---

## 系統需求與注意事項

* **執行環境**：Python 3.11 以上。
* **Windows 終端機設定**：請一律加上 `-X utf8` 避免中文報告出現亂碼：
  ```bash
  .venv\Scripts\python -X utf8 -m mcmt.cli <指令>
  ```
* **輕量相依**：核心僅依賴 `amulet-nbt` 與標準函式庫。

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
