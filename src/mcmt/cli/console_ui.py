# SPDX-License-Identifier: GPL-3.0-or-later
"""流程（`mcmt.flow`）的終端機介面。

對話框變成「標題＋內容＋編號選項」，按鈕變成輸入編號。這是視窗版出來之前，把整條
流程在真實地圖上走一遍的方式；之後它仍是沒有圖形環境時的後備。
"""

import os
import sys
from pathlib import Path
from typing import Sequence

__all__ = ["ConsoleUi"]


class ConsoleUi:
    def log(self, message: str) -> None:
        print(f"… {message}", flush=True)

    def ask(self, title: str, body: str, buttons: Sequence[str]) -> str | None:
        print(f"\n【{title}】\n{body}")
        for number, button in enumerate(buttons, 1):
            print(f"  {number}) {button}")
        while True:
            try:
                raw = input("請輸入編號：").strip()
            except EOFError:
                return None  # 輸入被關掉：當作取消，不要無限重問
            if raw.isdigit() and 1 <= int(raw) <= len(buttons):
                return buttons[int(raw) - 1]
            print(f"請輸入 1 到 {len(buttons)} 之間的編號。")

    def choose_language(self, default: str) -> str | None:
        try:
            raw = input(f"目標語言代碼（Enter 使用 {default}）：").strip()
        except EOFError:
            return None
        return raw or default

    def open_path(self, path: Path) -> None:
        print(f"（資料夾：{path}）")
        opener = getattr(os, "startfile", None)  # 只有 Windows 有
        if opener is not None and sys.stdin.isatty():
            try:
                opener(str(path))
            except OSError:
                pass  # 開不起來不是錯誤，路徑已經印出來了
