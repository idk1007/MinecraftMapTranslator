# SPDX-License-Identifier: GPL-3.0-or-later
"""工作執行緒 → 畫面執行緒。

流程（`mcmt.flow`）在背景執行緒跑——掃描大地圖要幾十秒，放在畫面執行緒上視窗就
凍住了。但 tkinter 只能在建立它的那條執行緒上碰，所以背景執行緒要畫對話框、加一行
進度時，把那件事排進佇列，由畫面執行緒定時（`pump`）拿出來做。

- `post(fn)`：排進去就走，不等（進度文字）。
- `call(fn)`：排進去並**等它做完**，把回傳值（使用者按了哪個按鈕）帶回來；
  在畫面那邊拋的例外會原樣在呼叫端拋出。
"""

import queue
import threading
from typing import Any, Callable

__all__ = ["MainThreadBridge"]


class MainThreadBridge:
    def __init__(self) -> None:
        self._jobs: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._main = threading.current_thread()

    def post(self, fn: Callable[..., Any], *args: Any) -> None:
        if threading.current_thread() is self._main:
            fn(*args)
            return
        self._jobs.put(lambda: fn(*args))

    def call(self, fn: Callable[..., Any], *args: Any) -> Any:
        if threading.current_thread() is self._main:
            return fn(*args)  # 在畫面執行緒上就直接做：排進佇列再等自己會卡死
        done = threading.Event()
        box: dict[str, Any] = {}

        def job() -> None:
            try:
                box["value"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001 —— 原樣交回呼叫端
                box["error"] = exc
            finally:
                done.set()

        self._jobs.put(job)
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def pump(self) -> None:
        """在畫面執行緒上把排隊的事做完。"""
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            job()
