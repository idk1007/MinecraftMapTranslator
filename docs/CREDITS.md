# 致謝與第三方

## 相依套件

- **執行期**：[`amulet-nbt`](https://pypi.org/project/amulet-nbt/) + Python 標準函式庫。
  少數用 LZ4 壓縮的地圖另外需要 `lz4`（`pip install -e ".[lz4]"`）。
- **開發／測試**：`pytest`、`jsonschema`、`referencing`（`pip install -e ".[dev]"`）。
  這幾個不是執行期相依。
- `spike/` 是開發初期的唯讀探針腳本，不是相依套件，也不該被 import。

## 先行專案

架構模式（規則反覆標記直到收斂）參考自
[`to2mbn/maptranslator`](https://github.com/to2mbn/maptranslator) 的公開說明。

**本專案不含任何來自該專案的程式碼。** 它是 GPLv2-only，而 mcmt 是 GPLv3；逐段
對照其原始碼會產生高度相似的實作結構，對一個要公開發布的 GPLv3 專案是實質的
授權相容性風險。判斷過程與界線見 `docs/adr/0007-prior-art-and-licensing.md`。
