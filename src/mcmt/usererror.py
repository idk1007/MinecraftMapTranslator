# SPDX-License-Identifier: GPL-3.0-or-later
"""使用者看到的錯誤：終端機與視窗共用同一份。

每則錯誤是「標題＋內容」（`McmtError.title` 與 `str(exc)`）。沒被預期的例外不給
使用者看 Python 堆疊：寫進沙盒裡的 `mcmt-error.log`，畫面上只留一句話與日誌位置。
"""

import platform
import traceback
from datetime import datetime
from pathlib import Path

from mcmt.safety.paths import ensure_writable, sandbox_root

__all__ = ["ERROR_LOG_NAME", "UNEXPECTED_TITLE", "render_error", "title_of", "write_error_log"]

ERROR_LOG_NAME = "mcmt-error.log"
UNEXPECTED_TITLE = "發生未預期的錯誤"


def title_of(exc: BaseException) -> str:
    return getattr(exc, "title", "發生錯誤")


def render_error(exc: BaseException) -> str:
    """終端機的格式：【標題】＋內容。"""
    return f"【{title_of(exc)}】\n{exc}"


def write_error_log(exc: BaseException, *, label: str, started: datetime) -> Path | None:
    """日誌放在沙盒裡（`<沙盒>/mcmt-error.log`）：安全規則 1，任何寫入都要在沙盒
    底下，錯誤日誌也不例外。寫不出去就回傳 `None`，不能讓「記錄錯誤」本身再炸一次。"""
    try:
        path = ensure_writable(sandbox_root() / ERROR_LOG_NAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"=== {started.isoformat(timespec='seconds')} · mcmt {label} · "
            f"Python {platform.python_version()} · {platform.platform()} ===\n"
        )
        body = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(header + body + "\n")
        return path
    except Exception:  # noqa: BLE001
        return None
