# SPDX-License-Identifier: GPL-3.0-or-later
"""把檔案總管裡的資料夾拖進視窗（Windows）。

tkinter 本身不支援從外部拖檔案進來。這裡不加第三方套件，直接接 Windows 的拖放
訊息：對視窗呼叫 `DragAcceptFiles`，再把視窗程序換成我們的，攔下 `WM_DROPFILES`、
用 `DragQueryFileW` 讀出路徑，其餘訊息原封交回原本的視窗程序。

只有 Windows 有這套 API；其他平台 `install()` 回傳 `False`，視窗上的「選擇資料夾…」
按鈕是後備。裝不起來（API 失敗）也一樣回傳 `False`，不讓整個程式起不來。
"""

import sys
from collections import deque
from typing import Callable

__all__ = ["install"]

WM_DROPFILES = 0x0233
_GWLP_WNDPROC = -4
_DRAIN_MS = 50


def install(root, on_drop: Callable[[list[str]], None]) -> bool:
    """讓 `root` 這個 Tk 視窗接受拖放；拖進來時以「路徑清單」呼叫 `on_drop`。"""
    if sys.platform != "win32":
        return False
    try:
        return _install_windows(root, on_drop)
    except (OSError, AttributeError, ValueError):
        return False


def _install_windows(root, on_drop) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    lresult = ctypes.c_ssize_t
    wndproc_type = ctypes.WINFUNCTYPE(
        lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    user32.CallWindowProcW.restype = lresult
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragAcceptFiles.restype = None
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragFinish.restype = None

    root.update_idletasks()
    # Tk 的 winfo_id() 是內層的客戶區；真正的頂層視窗是它的父視窗。
    hwnd = user32.GetParent(root.winfo_id())
    if not hwnd:
        return False

    def read_paths(hdrop) -> list[str]:
        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths = []
        for index in range(count):
            length = shell32.DragQueryFileW(hdrop, index, None, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(hdrop, index, buffer, length + 1)
            paths.append(buffer.value)
        return paths

    state: dict = {}
    pending: deque[list[str]] = deque()

    def procedure(handle, message, wparam, lparam):
        if message == WM_DROPFILES:
            try:
                pending.append(read_paths(wparam))
            finally:
                shell32.DragFinish(wparam)
            return 0
        return user32.CallWindowProcW(state["previous"], handle, message, wparam, lparam)

    # **這裡絕對不能碰 tkinter。** 視窗程序是在 Tk 的事件迴圈處理 Windows 訊息的
    # 當下被呼叫的，那時 tkinter 已經放開 GIL；在裡面呼叫 `root.after()` 會讓
    # Python 直接崩潰（[實測] `PyEval_RestoreThread: … GIL is released`）。所以
    # 視窗程序只把路徑丟進佇列，由 Tk 自己的定時器在正常的時機拿出來交給 on_drop。
    def drain() -> None:
        while pending:
            on_drop(pending.popleft())
        root.after(_DRAIN_MS, drain)

    root.after(_DRAIN_MS, drain)

    callback = wndproc_type(procedure)
    previous = user32.SetWindowLongPtrW(
        hwnd, _GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p)
    )
    if not previous:
        return False
    state["previous"] = previous
    # 回呼物件被回收的話，Windows 下一次呼叫視窗程序就會跳進已釋放的記憶體。
    root._mcmt_dnd_keepalive = (callback, state)
    shell32.DragAcceptFiles(hwnd, True)
    return True
