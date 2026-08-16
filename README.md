# mcmt

Minecraft 地圖翻譯工具。Python 3.11+ · 目標版本 Java Edition 1.21.11。

以資源包（自訂命名空間的 lang key）為主要路線翻譯冒險地圖的文字，並對無法走資源包的少數欄位做外科式就地寫入。

**這個工具會修改別人花幾千小時做的地圖存檔。** 設計上的每一條規則都是為了讓「除了要改的地方以外什麼都沒動」成為結構性保證。詳見 `CLAUDE.md`（規範）、`SPIKE_RESULT.md`（實測依據）、`docs/STATUS.md`（進度）。

**狀態：開發中。** M0 端到端驗證已通過，尚未有可用的 `src/`。

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
- 執行期相依：`amulet-nbt` + 標準函式庫。`anthropic`（`mcmt[llm]`）與 `lz4`（`mcmt[lz4]`）為可選。
- `jsonschema` / `referencing` 是 dev/test 相依，不是執行期相依。
- 本專案**不含**任何來自 to2mbn/maptranslator 的程式碼；僅採用其公開描述的架構模式。理由見 ADR-0007。
