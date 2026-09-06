# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack `.mcfunction` 裡的可翻文字。

**目錄名單複數都要認**：1.21 起改成單數 `function/`，1.20 及以前是複數
`functions/`（[實測 2026-08-22] `Arena of Darkness`，1.20.4，四個資料包共 120 個
`.mcfunction` 全部在複數 `functions/` 底下）。只認單數的話這些檔案是**完全隱形**
的——連 glob 都掃不到，所以沒有任何計數器會動，印出來的摘要跟「這張地圖沒有任何
function」一模一樣。這與 `sources/datapack.py::_ADVANCEMENT_DIR_NAMES` 是同一題、
同一個解法，兩邊要一起看。

**datapack 可以是資料夾也可以是 zip 檔，兩種都要支援**，而且兩種必須是**同一條
規則**（[實測] `Arena of Darkness` 全部是 zip）。

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

_FUNCTION_DIR_NAMES = ("function", "functions")
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
    for dir_name in _FUNCTION_DIR_NAMES:
        # **`**` 不能省。** 真實資料包把 function 分在子資料夾裡（`Arena of
        # Darkness` 的 `armor statues` 就是），只寫 `*.mcfunction` 的話那些檔案
        # 對資料夾式資料包完全隱形——跟 `datapack.py::_scan_folder_pack` 同一條
        # 理由，zip 那邊本來就是遞迴找得到的，兩種形式必須是同一條規則。
        for path in pack_dir.glob(f"data/*/{dir_name}/**/*.mcfunction"):
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
    """zip 條目路徑是不是 `data/<ns>/function(s)/…/*.mcfunction`。

    **比對的是路徑片段，不是子字串前綴**——`data/n/function_helpers/x.mcfunction`
    不是 function 目錄，不該中獎；理由與 `datapack.py::_is_advancement_entry`
    完全相同。
    """
    parts = name.split("/")
    return len(parts) >= 4 and parts[0] == "data" and parts[2] in _FUNCTION_DIR_NAMES


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


def _is_real_line(command: str) -> bool:
    """這一行去掉頭尾空白後，是不是一條「真的」指令行——非空白、不是 `#`
    註解。只有真的指令行才談得上「行尾延續」；空白行與註解行本來就沒有可以
    延續的指令內容。"""
    stripped = command.strip()
    return bool(stripped) and not stripped.startswith("#")


def _scan_lines(text: str, relative: str, stats: Counter) -> Iterator[ScannedNode]:
    lines = split_lines(text)
    # **只有「真的」指令行才能觸發延續。** 反斜線結尾如果出現在空白行或
    # `#` 註解行裡（例如 `# see also \`），那不是 1.20.2+ 的延續語法，只是
    # 註解裡剛好有一個反斜線——把它當觸發點會把它後面那條貨真價實的指令
    # 靜默吞掉，計入統計卻沒有任何可見訊號，正是 CLAUDE.md 點名最嚴重的
    # 那類 bug（靜默漏抽）。
    continuation_indexes = {
        i
        for i, (command, _) in enumerate(lines)
        if _is_real_line(command) and command.endswith("\\")
    }
    # 一個延續行的「下一行」也算在同一條邏輯指令裡，整批跳過——即使那一行
    # 本身是空白／註解（沒有可翻文字，但仍算進統計，不能因為它落進下面的
    # 「非真實行」分支而漏計）。
    skip_indexes: set[int] = set()
    for i in continuation_indexes:
        skip_indexes.add(i)
        skip_indexes.add(i + 1)

    for index, (command, _terminator) in enumerate(lines):
        if index in skip_indexes:
            stats["skipped_command_line_continuation"] += 1
            continue
        if not _is_real_line(command):
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
