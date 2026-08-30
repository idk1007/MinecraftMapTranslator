# SPDX-License-Identifier: GPL-3.0-or-later
"""四份合約的程式碼投影。**高風險目錄**——改動必須是獨立 commit。

`docs/ownership.md`：`model/` 被所有層 import，因此它**不得 import 任何其他 mcmt
模組**。這裡只依賴 stdlib 與 `amulet-nbt`。

`SCHEMA_VERSION` 是四份合約共用的單一版本號。讀到不符即失敗，訊息說明「請重新
產生」，**不實作任何向下相容、不寫 migration**（CLAUDE.md §四）。
"""

SCHEMA_VERSION = 6

__all__ = ["SCHEMA_VERSION"]
