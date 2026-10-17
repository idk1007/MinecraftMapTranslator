# SPDX-License-Identifier: GPL-3.0-or-later
"""mcmt 的視窗：一塊拖放區、「選擇資料夾…」「選擇翻譯檔…」兩個按鈕、一排處理進度。

流程本身在 `mcmt.flow`；這裡只負責畫面：把地圖交給流程（在背景執行緒跑），流程要
問問題時畫對話框、把使用者按的按鈕交回去，出錯時畫錯誤對話框。對話框的標題與內容
跟終端機版是同一份（`docs/error-messages-review.md`）。
"""

import os
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Sequence

from mcmt.errors import McmtError
from mcmt.flow import CLOSE, run_flow
from mcmt.gui import dnd
from mcmt.gui.bridge import MainThreadBridge
from mcmt.usererror import UNEXPECTED_TITLE, title_of, write_error_log

__all__ = ["App", "main"]

WINDOW_TITLE = "mcmt — Minecraft 地圖翻譯"
OPEN_LOG = "開啟日誌資料夾"
LANGUAGES = (
    ("zh_tw", "繁體中文"),
    ("zh_cn", "簡體中文"),
    ("en_us", "英文"),
)
_LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}_[a-z]{2,3}$")
_POLL_MS = 40


class ButtonDialog(tk.Toplevel):
    """標題＋內容＋一排按鈕。回傳按下的按鈕文字；直接關掉視窗回傳 `None`。"""

    def __init__(self, app: "App", title: str, body: str, buttons: Sequence[str]) -> None:
        super().__init__(app.root)
        self.app = app
        self.result: str | None = None
        self.title(title)
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", lambda: self.choose(None))
        self.bind("<Escape>", lambda _event: self.choose(None))

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text=body, wraplength=480, justify="left").pack(
            anchor="w", pady=(8, 16)
        )
        row = ttk.Frame(frame)
        row.pack(anchor="e")
        self.buttons: dict[str, ttk.Button] = {}
        for label in buttons:
            button = ttk.Button(row, text=label, command=lambda value=label: self.choose(value))
            button.pack(side="left", padx=(8, 0))
            self.buttons[label] = button
        if buttons:
            self.buttons[buttons[0]].focus_set()

    def choose(self, value: str | None) -> None:
        self.result = value
        self.destroy()

    def show(self) -> str | None:
        self.app.dialogs.append(self)
        try:
            _modal(self)
            self.wait_window()
        finally:
            self.app.dialogs.remove(self)
        return self.result


class LanguageDialog(tk.Toplevel):
    """選目標語言。下拉選單之外也可以直接打語言代碼（例如 ja_jp）。"""

    def __init__(self, app: "App", default: str) -> None:
        super().__init__(app.root)
        self.app = app
        self.result: str | None = None
        self.title("選擇目標語言")
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", lambda: self.choose(None))

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="要翻譯成哪一種語言？", font=("", 11, "bold")).pack(anchor="w")
        ttk.Label(
            frame, text="清單裡沒有的，可以直接輸入 Minecraft 的語言代碼（例如 ja_jp）。"
        ).pack(anchor="w", pady=(6, 8))
        choices = [f"{code}  {name}" for code, name in LANGUAGES]
        self.value = tk.StringVar(
            value=next((c for c in choices if c.split()[0] == default), default)
        )
        self.combo = ttk.Combobox(frame, textvariable=self.value, values=choices, width=28)
        self.combo.pack(anchor="w")
        self.error = ttk.Label(frame, text="", foreground="#b00020")
        self.error.pack(anchor="w", pady=(4, 8))
        row = ttk.Frame(frame)
        row.pack(anchor="e")
        ttk.Button(row, text="確定", command=self.confirm).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="取消", command=lambda: self.choose(None)).pack(
            side="left", padx=(8, 0)
        )
        self.bind("<Return>", lambda _event: self.confirm())
        self.bind("<Escape>", lambda _event: self.choose(None))

    def confirm(self) -> None:
        code = self.value.get().strip().split()[0] if self.value.get().strip() else ""
        if not _LANGUAGE_CODE.match(code):
            self.error.configure(text="語言代碼的格式是「小寫字母_小寫字母」，例如 zh_tw。")
            return
        self.choose(code)

    def choose(self, value: str | None) -> None:
        self.result = value
        self.destroy()

    def show(self) -> str | None:
        self.app.dialogs.append(self)
        try:
            _modal(self)
            self.wait_window()
        finally:
            self.app.dialogs.remove(self)
            # tkinter 的變數只能在畫面執行緒上被回收：留著它，對話框物件之後被背景
            # 執行緒的垃圾回收清掉時，會在錯的執行緒上碰 Tk。這裡就地放掉。
            self.value = None
        return self.result


def _modal(window: tk.Toplevel) -> None:
    try:
        window.grab_set()
    except tk.TclError:
        pass  # 主視窗沒顯示出來時（測試）抓不到焦點，不影響對話框本身


class TkUi:
    """`mcmt.flow.Ui` 的視窗實作。每個方法都在背景執行緒被呼叫，畫面的事一律經過
    `MainThreadBridge` 交給畫面執行緒做。"""

    def __init__(self, app: "App") -> None:
        self.app = app

    def log(self, message: str) -> None:
        self.app.bridge.post(self.app.append_log, message)

    def ask(self, title: str, body: str, buttons: Sequence[str]) -> str | None:
        # 對話框的字同時留在視窗的紀錄裡：很多人看到按鈕就按，對話框關掉後才發現
        # 沒看清楚要做什麼。
        self.log(f"【{title}】\n{body}")
        return self.app.bridge.call(
            lambda: ButtonDialog(self.app, title, body, list(buttons)).show()
        )

    def choose_language(self, default: str) -> str | None:
        return self.app.bridge.call(lambda: LanguageDialog(self.app, default).show())

    def open_path(self, path: Path) -> None:
        self.app.bridge.post(_open_in_explorer, Path(path))


def _open_in_explorer(path: Path) -> None:
    opener = getattr(os, "startfile", None)
    if opener is None:
        return
    try:
        opener(str(path))
    except OSError:
        pass  # 開不起來不是錯誤；路徑已經寫在對話框裡


class App:
    def __init__(self, root: "tk.Tk | tk.Toplevel | None" = None) -> None:
        self.root = root or tk.Tk()
        self.bridge = MainThreadBridge()
        self.ui = TkUi(self)
        self.dialogs: list[tk.Toplevel] = []
        self.busy = False
        self.last_outcome = None

        self.root.title(WINDOW_TITLE)
        self.root.geometry("680x480")
        self.root.minsize(520, 360)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        self.drop_zone = tk.Label(
            outer,
            text="把地圖資料夾或翻譯檔拖到這裡",
            font=("", 14),
            relief="groove",
            borderwidth=2,
            height=4,
        )
        self.drop_zone.pack(fill="x")

        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(10, 10))
        self.pick_button = ttk.Button(row, text="選擇資料夾…", command=self.pick_folder)
        self.pick_button.pack(side="left")
        self.pick_file_button = ttk.Button(row, text="選擇翻譯檔…", command=self.pick_file)
        self.pick_file_button.pack(side="left", padx=(8, 0))
        self.status = ttk.Label(row, text="")
        self.status.pack(side="left", padx=(12, 0))

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.dnd_enabled = dnd.install(self.root, self.on_drop)
        if not self.dnd_enabled:
            self.drop_zone.configure(text="請用下方按鈕選擇地圖資料夾或翻譯檔")
            self.append_log("（這台電腦上無法使用拖放，請用「選擇資料夾…」或「選擇翻譯檔…」按鈕。）")

        self.root.after(_POLL_MS, self._poll)

    # --- 畫面執行緒 ---------------------------------------------------------

    def _poll(self) -> None:
        self.bridge.pump()
        self.root.after(_POLL_MS, self._poll)

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def on_drop(self, paths: list[str]) -> None:
        if not paths:
            return
        if len(paths) > 1:
            self.append_log(f"一次拖入了 {len(paths)} 個項目，只處理第一個：{paths[0]}")
        self.start(Path(paths[0]))

    def pick_folder(self) -> None:
        chosen = filedialog.askdirectory(parent=self.root, mustexist=True, title="選擇地圖資料夾")
        if chosen:
            self.start(Path(chosen))

    def pick_file(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="選擇翻譯檔",
            filetypes=[("翻譯檔", "translations.*.json"), ("JSON", "*.json")],
        )
        if chosen:
            self.start(Path(chosen))

    def start(self, path: Path) -> bool:
        """把一張地圖交給流程。正在處理別的地圖時不接（一次只做一件事）。"""
        if self.busy:
            self.append_log("還在處理上一張地圖，請等它完成。")
            return False
        self.busy = True
        self.pick_button.configure(state="disabled")
        self.pick_file_button.configure(state="disabled")
        self.status.configure(text="處理中…")
        self.append_log(f"── {path}")
        threading.Thread(target=self._work, args=(Path(path),), daemon=True).start()
        return True

    def _finish(self, outcome) -> None:
        self.busy = False
        self.last_outcome = outcome
        self.pick_button.configure(state="normal")
        self.pick_file_button.configure(state="normal")
        self.status.configure(text="")

    def on_close(self) -> None:
        if self.busy:
            # 寫回進行到一半時關掉，留下的會是一份做到一半的沙盒。
            ButtonDialog(
                self, "處理中", "正在處理地圖，請等它完成再關閉視窗。", [CLOSE]
            ).show()
            return
        self.root.destroy()

    def _show_error(self, exc: BaseException, log: Path | None) -> None:
        if isinstance(exc, McmtError):
            ButtonDialog(self, title_of(exc), str(exc), [CLOSE]).show()
            return
        body = (
            f"錯誤資訊已存至 {log}。" if log else f"{type(exc).__name__}: {exc}"
        )
        answer = ButtonDialog(self, UNEXPECTED_TITLE, body, [OPEN_LOG, CLOSE]).show()
        if answer == OPEN_LOG and log is not None:
            _open_in_explorer(log.parent)

    # --- 背景執行緒 ---------------------------------------------------------

    def _work(self, path: Path) -> None:
        started = datetime.now()
        outcome = None
        try:
            outcome = run_flow(path, self.ui)
            self.ui.log("完成。" if outcome.kind != "cancelled" else "已取消。")
        except McmtError as exc:
            self.ui.log(f"【{title_of(exc)}】\n{exc}")
            self.bridge.call(self._show_error, exc, None)
        except Exception as exc:  # noqa: BLE001 —— 最後一道網
            log = write_error_log(exc, label="gui", started=started)
            where = f"\n錯誤資訊已存至 {log}。" if log else ""
            self.ui.log(f"【{UNEXPECTED_TITLE}】{where}")
            self.bridge.call(self._show_error, exc, log)
        finally:
            self.bridge.post(self._finish, outcome)


def _sharp_on_high_dpi() -> None:
    """Windows 高解析度螢幕上不設這個，字會被放大成一片糊。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def _pin_working_directory() -> None:
    """開發環境裡，沙盒是從「目前資料夾」往上找專案根決定的；終端機這樣很合理，
    視窗版卻會被啟動的位置帶走（[實測回報] 從另一個 git 專案裡啟動，沙盒就建在
    那個專案底下）。所以視窗版一開始就把目前資料夾固定到 mcmt 自己的專案根。
    打包後的 exe 不需要：沙盒本來就固定在 exe 旁邊。"""
    if getattr(sys, "frozen", False):
        return
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            os.chdir(candidate)
            return


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # 參數裡的相對路徑要在換資料夾之前就轉成絕對路徑。
    first = Path(args[0]).resolve() if args else None
    _pin_working_directory()
    _sharp_on_high_dpi()
    app = App()
    if first is not None:
        # 把資料夾拖到 exe 圖示上：Windows 會把路徑當參數傳進來，一樣接。
        app.root.after(200, app.start, first)
    app.root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
