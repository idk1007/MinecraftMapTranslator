# SPDX-License-Identifier: GPL-3.0-or-later
"""寫入層。**高風險目錄**——修改必須是獨立 commit 並說明理由。

決定**怎麼安全地放進去**：per-chunk DataVersion 分派、NBT list 同型、外科式重寫、
備份與回滾。決定**值是什麼**的是 `backends/`。
"""
