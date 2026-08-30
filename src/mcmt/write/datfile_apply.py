# SPDX-License-Identifier: GPL-3.0-or-later
"""`.dat` 檔的通用寫入器（M13.5）。**高風險目錄。**

`level.dat` 與 `data/scoreboard.dat` 共用這一份——兩者都是「一份完整的 NBT
檔，改幾個節點、整份重新編碼」，機制完全一樣，只有目標路徑不同。

**這裡完全不碰根鍵名。** `level.dat` 的根是 `Data`（大寫）、`scoreboard.dat` 的根是
`data`（小寫），但這個模組不需要知道哪個是哪個——它只照 `edit['node_path']` 一步
一步走，而 `node_path` 本來就從根開始（`[key(Data), key(LevelName)]` 或
`[key(data), key(Objectives), index(0), key(DisplayName)]`）。知道根鍵名的是
掃描來源（`scan/sources/level_dat.py` / `scan/sources/scoreboard.py`），它們各自
動態解析。

**保證只到 L1**（M3.2 的結論）：整份解析→序列化位元組一致，`write_dat` 自己的
「暫存→回讀驗證→原子替換」已經確保編壞了不會動到原檔一個位元。這裡沒有外科式
寫入這回事——原封不動的欄位靠「同一棵 CompoundTag 只有被改到的節點被改」保住，
不是靠位元組層級的原樣複製。

節點層級的「走到哪、寫什麼」邏輯在 `write/common.py`（`apply_edit_to_compound`）
——與 region 寫入器共用，不是巧合的重複（Task 1 的 commit 訊息說明了理由）。
"""

from pathlib import Path

from mcmt.errors import FormatError
from mcmt.nbtio.datfile import read_dat, write_dat
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write.common import ApplyOutcome, apply_edits, refuse

__all__ = ["apply_to_datfile"]


def apply_to_datfile(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    path = world / relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return

    try:
        dat = read_dat(ensure_readable(path))
    except FormatError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    root = dat.tag.compound
    written = apply_edits(root, edits, outcome)
    if not written:
        return

    outcome.counts["edits_written"] += written
    backup.protect(path)
    write_dat(ensure_writable(path), dat)
    outcome.counts["files_rewritten"] += 1
