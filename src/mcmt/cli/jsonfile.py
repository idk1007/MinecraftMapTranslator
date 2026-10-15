# SPDX-License-Identifier: GPL-3.0-or-later
"""讀使用者給的 JSON，錯誤換成使用者看得懂的訊息。"""

import json
from pathlib import Path
from typing import Any

from mcmt.errors import InputFileNotFoundError, InvalidJsonFileError
from mcmt.safety.paths import ensure_readable

__all__ = ["read_json_file"]


def read_json_file(path: Path, *, kind: str) -> Any:
    """不存在、語法錯誤都換成使用者看得懂的訊息：哪個檔案、第幾行、出錯那一行與
    前後各一行——不是 `Errno 2` 或 `Expecting property name…(char 1)`。"""
    if not path.is_file():
        raise InputFileNotFoundError(path, kind=kind)
    text = ensure_readable(path).read_bytes().decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        lines = text.splitlines()
        first = max(1, exc.lineno - 1)
        last = min(len(lines), exc.lineno + 1)
        context = [(number, lines[number - 1]) for number in range(first, last + 1)]
        raise InvalidJsonFileError(
            path=path, line=exc.lineno, column=exc.colno, context=context, kind=kind
        ) from exc
