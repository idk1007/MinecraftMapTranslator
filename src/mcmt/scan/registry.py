# SPDX-License-Identifier: GPL-3.0-or-later
"""掃描來源的清單（M13.2）。

**來源之間是同型的**——每一個都只做「找到文字節點、記下它在哪」，讀出來之後交給
同一套嗅探／攤平／規則引擎。所以這個抽象沒有藏起任何東西。

寫入器**不**同型（外科式 vs 整份重編 vs 檔案重寫，保證等級不一樣），那邊維持
顯式分派——那個不對稱必須看得見。理由見
`docs/superpowers/specs/2026-08-22-m13-scan-breadth-design.md` 第 2 節。

形式沿用 `rules/sets/denylist.py` 的 `RULES`：就是一份函式清單，不是 Protocol 或
基底類別。每個來源的簽名是

    scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]

`stats` 由來源直接累加（`skipped_region`、`skipped_chunk`…），因為「這次掃描跳過了
什麼」是報告的一部分，不能只存在於某個來源的內部。
"""

from mcmt.scan.sources import entities, region

__all__ = ["SOURCES"]

SOURCES = [
    region.scan,
    entities.scan,
]
