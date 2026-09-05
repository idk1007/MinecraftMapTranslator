# SPDX-License-Identifier: GPL-3.0-or-later
"""`.mcfunction` 的寫入器。**高風險目錄。**

架構抄 `write/datapack_apply.py`：資料夾直接覆寫（暫存 → 回讀驗證 → 原子替換）、
zip 整份重建。差別是這裡的「文件」是純文字、逐行處理，不是 JSON 樹——見
docs/superpowers/specs/2026-09-05-command-text-design.md §6。

**全程當 bytes／不透明換行符**：讀寫都不經過 Python 的文字模式 `open()`，
換行符只被 `scan/sources/mcfunction.py::split_lines()` 認出、存起來、原封貼
回去，從未被任何字串運算正規化過。

**行號只從 `relative`（呼叫端傳進來的 `container.path` 字串）解析。**
`scan/sources/mcfunction.py::_container()` 把它組成
`f"{relative}:{line_index + 1}"`——1-based。`_scan_lines()` 裡另外還有一個
`base_path` 用的 `key_step(f"{relative}:{index}")`（0-based），那個純粹是
`NodePath` 內部的區分標籤，不是給 write 層解析的東西；這裡完全不碰
`node_path` 的 key 步驟去找行號，只解析 `relative` 本身，兩個數字系統才不會
被搞混而錯一行。
"""

import zipfile
from pathlib import Path

from mcmt.errors import DatapackWriteVerificationError
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.scan.sources.mcfunction import split_lines
from mcmt.write.command_span import apply_command_edits
from mcmt.write.common import ApplyOutcome, refuse

__all__ = ["apply_to_mcfunction_file"]


def apply_to_mcfunction_file(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    """`relative` 是 `apply_editplan` 的 `by_file` 分組鍵，形如
    `datapacks/p/data/n/function/hello.mcfunction:<行號 1-based>`——同一個檔案
    不同行落進不同分組，跟 `datapack_apply.py` 的 zip 條目分組是同一個道理。"""
    file_relative, _, line_part = relative.rpartition(":")
    if not file_relative:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"無法解析 container.path：{relative}")
        return
    try:
        line_number = int(line_part)
    except ValueError:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"無法解析行號：{relative}")
        return

    zip_relative, entry = _split_zip(file_relative)
    if zip_relative is not None:
        _apply_to_zip_line(world, zip_relative, entry, line_number, edits, outcome, backup)
        return
    _apply_to_folder_line(world, file_relative, line_number, edits, outcome, backup)


def _apply_to_folder_line(
    world: Path,
    relative: str,
    line_number: int,
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
        text = ensure_readable(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    lines = split_lines(text)
    index = line_number - 1
    if index < 0 or index >= len(lines):
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"第 {line_number} 行不存在")
        return

    command, terminator = lines[index]
    before = len(outcome.unwritten)
    new_command = apply_command_edits(command, edits, outcome=outcome)
    if new_command is None:
        return
    written = len(edits) - (len(outcome.unwritten) - before)
    lines[index] = (new_command, terminator)

    new_text = "".join(line_text + line_terminator for line_text, line_terminator in lines)
    outcome.counts["edits_written"] += written
    backup.protect(path)
    _write_bytes_atomically(ensure_writable(path), new_text.encode("utf-8"))
    outcome.counts["files_rewritten"] += 1


def _apply_to_zip_line(
    world: Path,
    zip_relative: str,
    entry_name: str,
    line_number: int,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    path = world / zip_relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {zip_relative}")
        return
    try:
        with zipfile.ZipFile(str(ensure_readable(path))) as archive:
            entries = {
                info.filename: (info, archive.read(info.filename))
                for info in archive.infolist()
            }
    except (zipfile.BadZipFile, OSError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    info, raw = entries.get(entry_name, (None, None))
    if info is None:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"zip 裡找不到 {entry_name}")
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    lines = split_lines(text)
    index = line_number - 1
    if index < 0 or index >= len(lines):
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"第 {line_number} 行不存在")
        return

    command, terminator = lines[index]
    before = len(outcome.unwritten)
    new_command = apply_command_edits(command, edits, outcome=outcome)
    if new_command is None:
        return
    written = len(edits) - (len(outcome.unwritten) - before)
    lines[index] = (new_command, terminator)
    new_text = "".join(line_text + line_terminator for line_text, line_terminator in lines)

    entries[entry_name] = (info, new_text.encode("utf-8"))
    outcome.counts["edits_written"] += written
    backup.protect(path)
    _rewrite_zip(ensure_writable(path), entries, verify_entry=entry_name)
    outcome.counts["files_rewritten"] += 1


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    """暫存 → 回讀驗證（UTF-8 可解碼）→ 原子替換。跟 `datapack_apply.py::
    _write_json_atomically` 是同一個模式，換成純位元組比對而不是重新 parse
    JSON——這裡的「文件」是純文字，沒有結構可以 parse。"""
    temporary = ensure_writable(path.with_name(path.name + ".mcmt-tmp"))
    temporary.write_bytes(data)
    try:
        readback = temporary.read_bytes()
        readback.decode("utf-8")
        if readback != data:
            raise DatapackWriteVerificationError(
                f"寫出去的內容讀不回來（位元組不一致），已中止：{path}。原檔沒有被動過。"
            )
    except UnicodeDecodeError as exc:
        temporary.unlink()
        raise DatapackWriteVerificationError(
            f"寫出去的內容不是合法 UTF-8，已中止：{path}。原檔沒有被動過。"
        ) from exc
    except DatapackWriteVerificationError:
        temporary.unlink()
        raise
    temporary.replace(path)


def _rewrite_zip(path: Path, entries: dict[str, tuple], *, verify_entry: str) -> None:
    """整份重建：暫存 → 回讀驗證（CRC + UTF-8 可解碼）→ 原子替換。"""
    temporary = ensure_writable(path.with_name(path.name + ".mcmt-tmp"))
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, (info, data) in sorted(entries.items()):
                archive.writestr(info, data)
        with zipfile.ZipFile(str(ensure_readable(temporary))) as archive:
            broken = archive.testzip()
            if broken is not None:
                raise DatapackWriteVerificationError(
                    f"重建出來的 zip 有條目 CRC 對不上（{broken}），已中止：{path}。"
                    f"原檔沒有被動過。"
                )
            archive.read(verify_entry).decode("utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _split_zip(relative: str) -> tuple[str | None, str | None]:
    parts = relative.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.endswith(".zip"):
            return "/".join(parts[: index + 1]), "/".join(parts[index + 1 :])
    return None, None
