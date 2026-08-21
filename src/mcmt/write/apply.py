# SPDX-License-Identifier: GPL-3.0-or-later
"""把 editplan 寫回世界（M11.2）。**高風險目錄。**

順序是不可協商的（CLAUDE.md §1.2）：

    BackupSet.protect(region)  →  改  →  write_region

備份失敗就中止，**絕不允許「備份失敗但繼續寫」**。例外發生時 `BackupSet` 自動還原
所有已備份的檔案，報告的 `outcome` 記成 `rolled_back`。

**外科式寫入由 `write_region` 保證**：沒被改到的 chunk 帶著它從磁碟讀來的原始壓縮
位元組原封送回去。報告裡的 `chunks_copied_verbatim` 就是這條規則的機器可檢查形式。

**兩條寫入路徑**，由 `node_path` 的最後一步分派：最後一步是 `index` 就是 list 元素
（告示牌四行），走 `legacy`/`native` 的世代分派；最後一步是 `key` 就是直接指派
（`CustomName` 這類不吃 translate key 的欄位），走 `in_place`，保留節點既有的形狀。

**每一筆寫入前都過 `expected_encoding` 守門。** 節點現在的形狀與 extract 當時記的不同
就拒寫那一筆（`node_changed`）——[遊戲實測 M4-4] 使用者只要在中間玩過一次遊戲，
DataFixer 就會把部分節點的形狀改掉。
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import amulet_nbt

from mcmt.errors import FormatError
from mcmt.model import SCHEMA_VERSION
from mcmt.model.component import sniff
from mcmt.model.generation import generation_of
from mcmt.model.node import NodePath
from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import ChunkWrite, read_region, write_region
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write import in_place, legacy, native

__all__ = ["ApplyOutcome", "apply_editplan"]


@dataclass
class ApplyOutcome:
    outcome: str = "applied"
    counts: Counter = field(default_factory=Counter)
    unwritten: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    backup_directory: Path | None = None
    backup_files: int = 0

    def report(self, *, world: Path, fingerprint_before: str) -> dict[str, Any]:
        return {
            "format": "mcmt-apply-report",
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "outcome": self.outcome,
            "world": {
                "path": str(world),
                "world_fingerprint_before": fingerprint_before,
                "world_fingerprint_after": None,
                "extract_fingerprint": None,
            },
            "backup": (
                {
                    "directory": str(self.backup_directory),
                    "file_count": self.backup_files,
                }
                if self.backup_directory
                else None
            ),
            "counts": {
                "edits_planned": self.counts["edits_planned"],
                "edits_written": self.counts["edits_written"],
                "chunks_touched": self.counts["chunks_touched"],
                "chunks_copied_verbatim": self.counts["chunks_copied_verbatim"],
                "files_rewritten": self.counts["files_rewritten"],
                "list_promotions": self.counts["list_promotions"],
            },
            "unwritten": self.unwritten,
            "warnings": self.warnings,
        }


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
            _apply_to_region(world_path, relative, edits, outcome, backup)
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
            _refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return

    try:
        chunks = list(read_region(ensure_readable(path)))
    except FormatError as exc:
        for edit in edits:
            _refuse(outcome, edit, "chunk_unreadable", str(exc))
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
            # **原封複製原始壓縮位元組**——連解碼都不做。
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
        return  # 這張 region 沒有任何一筆真的寫成，不要動它

    # **備份在寫入之前。** 順序反了就沒有備份。
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
    """套用一個 chunk 裡的所有 edit，回傳新的壓縮 payload（沒改成就回 None）。"""
    try:
        data = decompress_chunk(raw.payload, raw.compression_type, chunk_index=raw.index)
        root = amulet_nbt.load(data, compressed=False).compound
    except (FormatError, amulet_nbt.NBTLoadError) as exc:
        for edit in edits:
            _refuse(outcome, edit, "chunk_unreadable", str(exc))
        return None

    written = 0
    for edit in edits:
        if _apply_edit(root, edit, outcome):
            written += 1
    if not written:
        return None

    outcome.counts["edits_written"] += written
    encoded = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
    return _compress(encoded, raw.compression_type)


def _apply_edit(root, edit: dict, outcome: ApplyOutcome) -> bool:
    path = NodePath.from_json(edit["node_path"])
    steps = list(path)
    if not steps:
        _refuse(outcome, edit, "node_missing", "node_path 是空的")
        return False

    # **兩條寫入路徑，由 node_path 的最後一步分派。**
    #
    # 最後一步是 `index` → list 元素（告示牌四行），走 legacy/native 的世代分派，
    # 節點換成 `{translate: key}`，譯文住在資源包裡。
    #
    # 最後一步是 `key` → 直接指派（`CustomName` 這類不吃 translate key 的欄位），
    # 保留節點既有的形狀、只換裡面的字。[遊戲實測 M11-3]
    if steps[-1].t == "key":
        return _apply_in_place(root, steps, edit, outcome)
    if steps[-1].t != "index":
        _refuse(outcome, edit, "unsupported_encoding", "v1 的寫入路徑不支援 decode 步驟")
        return False

    index = steps[-1].i
    try:
        container = _resolve(root, steps[:-1])
    except (KeyError, IndexError) as exc:
        _refuse(outcome, edit, "node_missing", str(exc))
        return False

    if not isinstance(container, amulet_nbt.ListTag):
        _refuse(outcome, edit, "node_missing", "目標的父節點不是 list")
        return False
    if index >= len(container):
        _refuse(outcome, edit, "node_missing", f"list 只有 {len(container)} 個元素")
        return False

    # **守門**：節點現在的形狀還是 extract 當時記的那個嗎？
    try:
        current = sniff(container[index]).encoding.value
    except TypeError:
        _refuse(outcome, edit, "unsupported_encoding", "這個節點不是文字節點")
        return False
    if current != edit["expected_encoding"]:
        _refuse(
            outcome,
            edit,
            "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current}"
            f"——世界在 extract 之後被改過了（多半是在遊戲裡開過）",
        )
        return False

    # **分派**：舊世代寫 JSON 字串，新世代寫 compound。這是兩份實作的分岔點。
    writer = (
        legacy
        if generation_of(edit["container"]["data_version"]).legacy_json_is_content
        else native
    )
    result = writer.apply_to_list(container, index, writer.value_tag(edit["value"]))
    _replace_list(root, steps[:-1], result.list)
    if result.promoted:
        outcome.counts["list_promotions"] += 1
    return True


def _apply_in_place(root, steps, edit: dict, outcome: ApplyOutcome) -> bool:
    """直接指派一個 compound 的鍵。**保留節點既有的 NBT 形狀。**

    守門與 list 那條路徑一模一樣，而且順序不能換：先確認節點還在、再確認它的形狀
    還是 extract 當時記的那個，最後才決定寫什麼。[遊戲實測 M4-4] 使用者中間玩過
    一次遊戲，DataFixer 就會把部分節點的形狀改掉。
    """
    name = steps[-1].name
    try:
        parent = _resolve(root, steps[:-1])
    except (KeyError, IndexError) as exc:
        _refuse(outcome, edit, "node_missing", str(exc))
        return False

    if not isinstance(parent, amulet_nbt.CompoundTag) or name not in parent:
        _refuse(outcome, edit, "node_missing", f"找不到鍵 {name}")
        return False

    try:
        current = sniff(parent[name]).encoding.value
    except TypeError:
        _refuse(outcome, edit, "unsupported_encoding", "這個節點不是文字節點")
        return False
    if current != edit["expected_encoding"]:
        _refuse(
            outcome,
            edit,
            "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current}"
            f"——世界在 extract 之後被改過了（多半是在遊戲裡開過）",
        )
        return False

    try:
        tag = in_place.value_tag(current, edit["value"])
    except in_place.UnsupportedInPlaceShape as exc:
        _refuse(outcome, edit, "unsupported_encoding", str(exc))
        return False

    parent[name] = tag
    return True


def _resolve(root, steps):
    current = root
    for step in steps:
        if step.t == "key":
            if step.name not in current:
                raise KeyError(f"找不到鍵 {step.name}")
            current = current[step.name]
        elif step.t == "index":
            current = current[step.i]
        else:
            raise KeyError("v1 的寫入路徑不支援 decode 步驟")
    return current


def _replace_list(root, steps, new_list) -> None:
    """list 提升會產生一個新的 ListTag，要把它接回父節點。"""
    parent = _resolve(root, steps[:-1])
    last = steps[-1]
    if last.t == "key":
        parent[last.name] = new_list
    else:
        parent[last.i] = new_list


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


def _refuse(outcome: ApplyOutcome, edit: dict, reason: str, detail: str) -> None:
    outcome.unwritten.append(
        {
            "unit_id": edit["unit_id"],
            "occurrence_id": edit["occurrence_id"],
            "reason": reason,
            "detail": detail,
        }
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
