# SPDX-License-Identifier: GPL-3.0-or-later
"""深度計數的 span 定位器——不做語意解析，只數括號、引號、逗號的深度。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §3。這是指令文字
掃描與寫回共用的核心元件：只回答「這段文字在哪裡」，不回答「這段文字是什麼
意思」——語意交給既有的 json_component/snbt codec 處理。
"""

from typing import Sequence

__all__ = [
    "LocateError",
    "find_balanced_span",
    "find_unquoted_token",
    "locate_path_span",
]


class LocateError(ValueError):
    """找不到指定的範圍或路徑。呼叫端把這個當「這次不猜、跳過並計數」的訊號。"""


_OPENERS = {"{": "}", "[": "]"}


def find_balanced_span(text: str, start: int) -> tuple[int, int]:
    """從 `start`（必須是 `{` 或 `[`）開始，回傳 (start, end) 使得
    `text[start:end]` 是一段括號平衡、引號感知的區間（`end` 是配對括號的下一個
    位置）。只數深度，不理解值的意義；`{`/`}`/`[`/`]` 出現在字串常值裡不會被
    誤判成結構字元。"""
    if start >= len(text) or text[start] not in _OPENERS:
        raise LocateError(
            f"位置 {start} 不是 '{{' 或 '[' 開頭：{text[start:start + 20]!r}"
        )
    depth = 0
    i = start
    in_string = False
    quote_char = ""
    escape = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            i += 1
            continue
        if ch in "\"'":
            in_string = True
            quote_char = ch
            i += 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        i += 1
    raise LocateError(f"從位置 {start} 開始找不到配對的括號（原文太短或沒有結尾）")


def find_unquoted_token(text: str, start: int, token: str) -> int:
    """從 `start` 開始找 `token`（例如 `" run "`）第一次出現在括號深度 0、且不在
    引號內的位置；找不到回傳 -1。用來剝 `execute ... run <command>` 的前綴，
    不能用普通字串搜尋——指令文字裡可能真的含有 token 這個子字串
    （`tellraw @a {"text":"run for it"}`）。"""
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    i = start
    n = len(token)
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            i += 1
            continue
        if ch in "\"'":
            in_string = True
            quote_char = ch
            i += 1
            continue
        if ch in "{[":
            depth += 1
            i += 1
            continue
        if ch in "}]":
            depth -= 1
            i += 1
            continue
        if depth == 0 and text.startswith(token, i):
            return i
        i += 1
    return -1


def locate_path_span(
    text: str, span: tuple[int, int], path: Sequence[str | int]
) -> tuple[int, int]:
    """在 `text[span[0]:span[1]]`（必須是一段括號平衡的 compound 或 list 文字）
    裡，沿著 `path`（compound 用字串 key、list 用整數 index）逐層縮小，回傳
    目標值在**原始 `text`** 裡的絕對 `(start, end)`。"""
    start, end = span
    if not path:
        return (start, end)
    body = text[start:end]
    opener = body[0]
    step = path[0]

    if opener == "[":
        if not isinstance(step, int):
            raise LocateError(f"list 需要整數 index，收到 {step!r}")
        elements = _split_top_level(body[1:-1])
        if step >= len(elements):
            raise LocateError(
                f"list index {step} 超出範圍（共 {len(elements)} 個元素）"
            )
        rel_start, rel_end = elements[step]
        abs_start = start + 1 + rel_start
        abs_end = start + 1 + rel_end
    elif opener == "{":
        if not isinstance(step, str):
            raise LocateError(f"compound 需要字串 key，收到 {step!r}")
        found = _find_key_value(body[1:-1], step)
        if found is None:
            raise LocateError(f"compound 裡找不到 key {step!r}")
        rel_start, rel_end = found
        abs_start = start + 1 + rel_start
        abs_end = start + 1 + rel_end
    else:
        raise LocateError(f"span 開頭不是 '{{' 或 '['：{opener!r}")

    remaining = path[1:]
    if not remaining:
        return (abs_start, abs_end)
    if abs_start >= len(text) or text[abs_start] not in _OPENERS:
        raise LocateError("路徑還沒走完，但這個值不是 compound/list，走不下去")
    inner_span = find_balanced_span(text, abs_start)
    return locate_path_span(text, inner_span, remaining)


def _split_top_level(body: str) -> list[tuple[int, int]]:
    """把 `body`（list 拿掉外層 `[`/`]` 之後的內容）依深度 0 的逗號切成元素，
    回傳每個元素相對 `body` 的 `(start, end)`（不含前後空白）。"""
    elements: list[tuple[int, int]] = []
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    elem_start = 0
    i = 0
    n = len(body)
    while i <= n:
        ch = body[i] if i < n else ","  # 補一個假逗號讓最後一個元素也被收進來
        if in_string:
            if i < n:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote_char:
                    in_string = False
            i += 1
            continue
        if i < n and ch in "\"'":
            in_string = True
            quote_char = ch
            i += 1
            continue
        if i < n and ch in "{[":
            depth += 1
            i += 1
            continue
        if i < n and ch in "}]":
            depth -= 1
            i += 1
            continue
        if ch == "," and depth == 0:
            raw = body[elem_start:i]
            stripped_start = elem_start + (len(raw) - len(raw.lstrip()))
            stripped_end = i - (len(raw) - len(raw.rstrip()))
            if stripped_start < stripped_end:
                elements.append((stripped_start, stripped_end))
            elem_start = i + 1
        i += 1
    return elements


def _find_key_value(body: str, key: str) -> tuple[int, int] | None:
    """在 `body`（compound 拿掉外層 `{`/`}` 之後的內容）裡找 `key`（SNBT 無引號
    或 JSON `"key"` 兩種寫法都認），回傳它的值相對 `body` 的 `(start, end)`。"""
    for elem_start, elem_end in _split_top_level(body):
        piece = body[elem_start:elem_end]
        colon = _find_top_level_colon(piece)
        if colon is None:
            continue
        raw_key = piece[:colon].strip().strip("\"'")
        if raw_key == key:
            value = piece[colon + 1 :]
            value_start = elem_start + colon + 1 + (len(value) - len(value.lstrip()))
            value_end = elem_end - (len(value) - len(value.rstrip()))
            return (value_start, value_end)
    return None


def _find_top_level_colon(piece: str) -> int | None:
    depth = 0
    in_string = False
    quote_char = ""
    escape = False
    for i, ch in enumerate(piece):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            continue
        if ch in "\"'":
            in_string = True
            quote_char = ch
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == ":" and depth == 0:
            return i
    return None
