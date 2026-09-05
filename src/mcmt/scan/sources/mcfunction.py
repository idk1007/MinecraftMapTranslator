# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack `.mcfunction` 裡的可翻文字。

物理字串單位是**一行**，不是整個檔案（見
docs/superpowers/specs/2026-09-05-command-text-design.md §6）。換行符全程當
不透明資料——只切 `\n`，每行連同它自己的結尾（`"\r\n"`／`"\n"`／空字串）一起
記下來，span 定位、白名單比對只作用在去掉結尾的那段文字上，重組時原封貼回去。

1.20.2+ 的行尾反斜線延續語法目前**明確不支援**——涉及延續的邏輯指令整批跳過，
計入 `stats.skipped_command_line_continuation`（spec §1／§6）。
"""

import zipfile
from collections import Counter
from typing import Any, Iterator

from mcmt.model.node import NodePath, key_step
from mcmt.safety.paths import ReadOnlyPath
from mcmt.scan.command import scan_command_string
from mcmt.scan.node import ScannedNode

__all__ = ["scan", "split_lines"]

_ANCHOR = {"kind": "file", "id": None, "x": None, "y": None, "z": None, "uuid": None}


def scan(world: ReadOnlyPath, stats: Counter) -> Iterator[ScannedNode]:
    root = world / "datapacks"
    if not root.exists():
        return
    for entry in root.glob("*"):
        if entry.is_dir():
            yield from _scan_folder_pack(world, entry, stats)
        elif entry.name.endswith(".zip"):
            yield from _scan_zip_pack(world, entry, stats)


def _scan_folder_pack(
    world: ReadOnlyPath, pack_dir: ReadOnlyPath, stats: Counter
) -> Iterator[ScannedNode]:
    for path in pack_dir.glob("data/*/function/**/*.mcfunction"):
        relative = str(path.relative_to(world)).replace("\\", "/")
        try:
            data = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            stats["skipped_command_unsupported_shape"] += 1
            continue
        yield from _scan_lines(data, relative, stats)


def _scan_zip_pack(
    world: ReadOnlyPath, zip_path: ReadOnlyPath, stats: Counter
) -> Iterator[ScannedNode]:
    zip_relative = str(zip_path.relative_to(world)).replace("\\", "/")
    try:
        with zipfile.ZipFile(str(zip_path)) as archive:
            names = [
                n for n in archive.namelist()
                if n.endswith(".mcfunction") and _is_function_entry(n)
            ]
            for name in sorted(names):
                try:
                    data = archive.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    stats["skipped_command_unsupported_shape"] += 1
                    continue
                yield from _scan_lines(data, f"{zip_relative}/{name}", stats)
    except (zipfile.BadZipFile, OSError):
        stats["skipped_datapack_zip"] += 1


def _is_function_entry(name: str) -> bool:
    parts = name.split("/")
    return len(parts) >= 4 and parts[0] == "data" and parts[2] == "function"


def split_lines(text: str) -> list[tuple[str, str]]:
    """只切 `\n`，回傳 `(command_text, terminator)` 對——`terminator` 是
    `"\r\n"`、`"\n"`，或最後一行沒有結尾換行時的空字串。**不用
    `str.splitlines()`**：那個函式連 `\v`／`\f`／` ` 都當換行界線，
    而且會把換行符吃掉，重組時會把 CRLF 檔案整份改成 LF。"""
    lines: list[tuple[str, str]] = []
    start = 0
    n = len(text)
    while start <= n:
        idx = text.find("\n", start)
        if idx == -1:
            if start < n:
                lines.append((text[start:], ""))
            break
        if idx > start and text[idx - 1] == "\r":
            lines.append((text[start : idx - 1], "\r\n"))
        else:
            lines.append((text[start:idx], "\n"))
        start = idx + 1
    return lines


def _scan_lines(text: str, relative: str, stats: Counter) -> Iterator[ScannedNode]:
    lines = split_lines(text)
    continuation_indexes = {
        i for i, (command, _) in enumerate(lines) if command.endswith("\\")
    }
    # 一個延續行的「下一行」也算在同一條邏輯指令裡，整批跳過。
    skip_indexes: set[int] = set()
    for i in continuation_indexes:
        skip_indexes.add(i)
        skip_indexes.add(i + 1)

    for index, (command, _terminator) in enumerate(lines):
        stripped = command.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if index in skip_indexes:
            stats["skipped_command_line_continuation"] += 1
            continue
        container = _container(relative, index)
        base_path = NodePath([key_step(f"{relative}:{index}")])
        for node in scan_command_string(
            command, base_path=base_path, anchor=_ANCHOR, stats=stats
        ):
            yield ScannedNode(node=node, container=container)


def _container(relative: str, line_index: int) -> dict[str, Any]:
    return {
        "kind": "datapack_mcfunction_file",
        "path": f"{relative}:{line_index + 1}",
        "dimension": None,
        "chunk": None,
        "data_version": None,
        "compression": None,
        "external": False,
    }
