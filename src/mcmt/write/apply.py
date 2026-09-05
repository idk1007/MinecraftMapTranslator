# SPDX-License-Identifier: GPL-3.0-or-later
"""把 editplan 寫回世界（M11.2 / M13b 分派重構）。**高風險目錄。**

順序是不可協商的（CLAUDE.md §1.2）：

    BackupSet.protect(檔案)  →  改  →  write_region / write_dat / 重寫 zip

備份失敗就中止，**絕不允許「備份失敗但繼續寫」**。

**容器種類決定用哪個寫入器，顯式對照表，不是 if/elif。** 三種寫入器的保證等級不同：

    region_chunk / entities_chunk   外科式——未改動的 chunk 原封複製原始壓縮位元組
    level_dat / scoreboard_dat      整份重編——`.dat` 沒有外科式寫入這回事（M3.2）
    datapack_file                   檔案重寫——資料夾直接覆寫、zip 整份重建

這個不對稱**必須看得見**，一個共同介面會讓它們看起來一樣安全（`docs/ownership.md`
「為什麼寫入層與輸出後端是分開的」同一條理由）。

**節點層級「走到哪、寫什麼」的邏輯在 `write/common.py`**（`apply_edit_to_compound`）
——那段與容器是 region 還是 `.dat` 無關，兩者共用同一份，不是巧合的重複。
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

import amulet_nbt

from mcmt.errors import FormatError
from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import ChunkWrite, read_region, write_region
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write.common import ApplyOutcome, apply_edits, refuse
from mcmt.write.datfile_apply import apply_to_datfile
from mcmt.write.datapack_apply import apply_to_datapack_file
from mcmt.write.mcfunction_apply import apply_to_mcfunction_file

__all__ = ["ApplyOutcome", "apply_editplan"]


def apply_editplan(
    world: Path | str,
    plan: dict[str, Any],
    *,
    dry_run: bool = False,
) -> ApplyOutcome:
    """把 plan 裡的每一筆 edit 寫回世界。"""
    world_path = Path(world).resolve()
    outcome = ApplyOutcome()
    outcome.counts["edits_planned"] = len(plan["edits"])

    by_file: dict[str, list[dict]] = defaultdict(list)
    for edit in plan["edits"]:
        by_file[edit["container"]["path"]].append(edit)

    if dry_run:
        outcome.outcome = "dry_run"
        return outcome

    with BackupSet(world_path) as backup:
        for relative, edits in sorted(by_file.items()):
            kind = edits[0]["container"]["kind"]
            writer = _WRITERS.get(kind)
            if writer is None:
                for edit in edits:
                    refuse(
                        outcome, edit, "unsupported_encoding",
                        f"沒有 {kind!r} 的寫入器",
                    )
                continue
            writer(world_path, relative, edits, outcome, backup)
        outcome.backup_directory = backup.directory
        outcome.backup_files = backup.file_count
    return outcome


def _apply_to_region(
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
        chunks = list(read_region(ensure_readable(path)))
    except FormatError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    by_chunk: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for edit in edits:
        chunk_info = edit["container"]["chunk"]
        by_chunk[(chunk_info["cx"], chunk_info["cz"])].append(edit)

    writes: list[ChunkWrite] = []
    touched = 0
    for raw in chunks:
        pending = by_chunk.get((raw.local_x, raw.local_z))
        if not pending:
            writes.append(ChunkWrite.unchanged(raw))
            outcome.counts["chunks_copied_verbatim"] += 1
            continue

        payload = _rewrite_chunk(raw, pending, outcome)
        if payload is None:
            writes.append(ChunkWrite.unchanged(raw))
            outcome.counts["chunks_copied_verbatim"] += 1
            continue
        writes.append(ChunkWrite.replaced(raw, payload))
        touched += 1

    if not touched:
        return

    backup.protect(path)
    report = write_region(ensure_writable(path), writes)
    outcome.counts["chunks_touched"] += touched
    outcome.counts["files_rewritten"] += 1
    if report.realigned:
        outcome.warnings.append(
            {
                "kind": "sector_realignment",
                "unit_id": None,
                "detail": (
                    f"{relative}：{report.size_before:,} → {report.size_after:,} bytes。"
                    f"這是磁區重整（原檔有空隙），不是資料遺失。"
                ),
            }
        )


def _rewrite_chunk(raw, edits: list[dict], outcome: ApplyOutcome) -> bytes | None:
    try:
        data = decompress_chunk(raw.payload, raw.compression_type, chunk_index=raw.index)
        root = amulet_nbt.load(data, compressed=False).compound
    except (FormatError, amulet_nbt.NBTLoadError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return None

    # **同一批呼叫，不是逐筆呼叫。** 同一個 chunk 裡同一個 native list（告示牌
    # 四行）收到兩筆以上 edit 時，逐筆呼叫會讓第一筆的 list 提升污染第二筆的
    # 守門——見 `apply_edits()` 的說明。
    written = apply_edits(root, edits, outcome)
    if not written:
        return None

    outcome.counts["edits_written"] += written
    encoded = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
    return _compress(encoded, raw.compression_type)


def _compress(data: bytes, compression_type: int) -> bytes:
    import gzip
    import zlib

    if compression_type == 2:
        return zlib.compress(data)
    if compression_type == 1:
        return gzip.compress(data, mtime=0)
    if compression_type == 3:
        return data
    raise ValueError(f"不支援寫入壓縮類型 {compression_type}")


_WRITERS = {
    "region_chunk": _apply_to_region,
    "entities_chunk": _apply_to_region,
    "level_dat": apply_to_datfile,
    "scoreboard_dat": apply_to_datfile,
    "datapack_file": apply_to_datapack_file,
    "datapack_mcfunction_file": apply_to_mcfunction_file,
}
