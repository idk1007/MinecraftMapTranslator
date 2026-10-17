# SPDX-License-Identifier: GPL-3.0-or-later
"""視窗版（`mcmt.gui`）。

三層，由能自動驗的往外：

1. `MainThreadBridge`：純執行緒邏輯，完全自動。
2. 拖放：在 Windows 上**真的**對視窗送一個 `WM_DROPFILES`（自己組 `HDROP`），
   驗證我們接得到路徑——檔案總管拖進來時送的就是這個訊息。
3. 視窗本身：真的建出 Tk 視窗與對話框，用排程自動「按按鈕」，把整條流程走一遍。

**這些測試驗不到的**：視窗長得好不好看、字有沒有被裁掉、從檔案總管拖進來的手感
——那只有人實際拖一次才知道。
"""

import json
import sys
import threading
import time

import pytest

from mcmt.gui.bridge import MainThreadBridge


# --- 1. 執行緒橋 ----------------------------------------------------------------


def test_call_waits_for_the_main_thread_and_returns_its_value() -> None:
    bridge = MainThreadBridge()
    result = {}

    worker = threading.Thread(target=lambda: result.setdefault("v", bridge.call(lambda: 42)))
    worker.start()
    deadline = time.time() + 5
    while worker.is_alive() and time.time() < deadline:
        bridge.pump()
        time.sleep(0.005)

    assert result == {"v": 42}


def test_an_error_on_the_main_thread_reaches_the_caller() -> None:
    bridge = MainThreadBridge()
    caught = {}

    def work():
        try:
            bridge.call(lambda: 1 / 0)
        except ZeroDivisionError as exc:
            caught["e"] = exc

    worker = threading.Thread(target=work)
    worker.start()
    deadline = time.time() + 5
    while worker.is_alive() and time.time() < deadline:
        bridge.pump()
        time.sleep(0.005)

    assert isinstance(caught.get("e"), ZeroDivisionError)


def test_post_does_not_wait_and_keeps_order() -> None:
    bridge = MainThreadBridge()
    seen: list[int] = []

    worker = threading.Thread(target=lambda: [bridge.post(seen.append, i) for i in range(5)])
    worker.start()
    worker.join(5)
    assert seen == []  # 還沒輪到畫面執行緒
    bridge.pump()

    assert seen == [0, 1, 2, 3, 4]


def test_calling_from_the_main_thread_runs_directly_instead_of_deadlocking() -> None:
    bridge = MainThreadBridge()

    assert bridge.call(lambda: "direct") == "direct"


# --- 共用：真的 Tk 視窗 -----------------------------------------------------------


@pytest.fixture(scope="module")
def tk_session():
    """整個測試檔共用**一個** Tk 解譯器。在 Windows 上同一個行程反覆建立、銷毀
    `Tk()`，偶爾會建不起來（[實測] `invalid command name "tcl_findLibrary"`），
    那是 Tcl 的問題，不是我們的——共用一個就不會撞到。"""
    tkinter = pytest.importorskip("tkinter")
    try:
        session = tkinter.Tk()
    except tkinter.TclError as exc:  # 真的沒有圖形環境
        pytest.skip(f"沒有圖形環境：{exc}")
    session.withdraw()
    yield session
    session.destroy()


@pytest.fixture
def tk_root(tk_session):
    """每條測試一個自己的頂層視窗（`Toplevel`），測完就關。"""
    import tkinter

    window = tkinter.Toplevel(tk_session)
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tkinter.TclError:
        pass


def pump_until(root, condition, timeout=60.0):
    deadline = time.time() + timeout
    while not condition():
        if time.time() > deadline:
            raise AssertionError("等太久了")
        root.update()
        time.sleep(0.01)


# --- 2. 拖放 --------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="WM_DROPFILES 是 Windows 的 API")
def test_a_real_wm_dropfiles_message_delivers_the_paths(tk_root, tmp_path) -> None:
    import ctypes
    from ctypes import wintypes

    from mcmt.gui import dnd

    tk_root.deiconify()
    tk_root.update()
    received: list[list[str]] = []
    assert dnd.install(tk_root, received.append)

    # 中文、空白、括號——真實地圖的資料夾名常有這些（Be-boxed+v1.2+(1.21.11)）。
    paths = [str(tmp_path / "我的 地圖 (1.21.11)"), str(tmp_path / "second")]
    _post_drop(tk_root, paths)

    pump_until(tk_root, lambda: received)
    assert received == [paths]


def _post_drop(root, paths: list[str]) -> None:
    """組一個跟檔案總管送的一樣的 HDROP（DROPFILES 標頭＋UTF-16 路徑清單）送過去。"""
    import ctypes
    from ctypes import wintypes

    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", wintypes.DWORD),
            ("pt", wintypes.POINT),
            ("fNC", wintypes.BOOL),
            ("fWide", wintypes.BOOL),
        ]

    payload = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    header = DROPFILES(pFiles=ctypes.sizeof(DROPFILES), fWide=True)
    size = ctypes.sizeof(DROPFILES) + len(payload)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    handle = kernel32.GlobalAlloc(0x0042, size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, ctypes.byref(header), ctypes.sizeof(DROPFILES))
    ctypes.memmove(pointer + ctypes.sizeof(DROPFILES), payload, len(payload))
    kernel32.GlobalUnlock(handle)

    hwnd = user32.GetParent(root.winfo_id())
    assert user32.PostMessageW(hwnd, 0x0233, handle, 0)


def test_install_quietly_declines_off_windows(monkeypatch) -> None:
    from mcmt.gui import dnd

    monkeypatch.setattr(sys, "platform", "linux")

    assert dnd.install(object(), lambda paths: None) is False


# --- 3. 視窗走一遍流程 ------------------------------------------------------------


def autoanswer(app, script: dict, *, language="zh_tw"):
    """排一個定時檢查：有對話框打開，就照劇本按按鈕。劇本沒寫的對話框讓測試失敗。

    必須用 Tk 的 `after` 排程而不是測試迴圈裡直接按：對話框是 modal 的，打開時
    畫面執行緒卡在它自己的事件迴圈裡，只有排進那個迴圈的事會被執行。"""
    from mcmt.gui.app import ButtonDialog, LanguageDialog

    unexpected: list[str] = []
    # 同一條測試裡再叫一次 autoanswer 時，舊的劇本要停：不然兩個應答器搶同一個
    # 對話框，舊劇本沒寫的標題會被它按成取消（[實測] 在全套測試裡偶發）。
    generation = getattr(app, "_autoanswer_generation", 0) + 1
    app._autoanswer_generation = generation

    def check():
        if app._autoanswer_generation != generation:
            return
        for dialog in list(app.dialogs):
            if isinstance(dialog, LanguageDialog):
                dialog.value.set(language)
                dialog.confirm()
            elif isinstance(dialog, ButtonDialog):
                title = dialog.title()
                if title not in script:
                    unexpected.append(title)
                    dialog.choose(None)
                else:
                    dialog.buttons[script[title]].invoke()
        app.root.after(30, check)

    app.root.after(30, check)
    return unexpected


@pytest.fixture
def app(tk_root, project, monkeypatch):
    from mcmt.gui import app as app_module

    opened = []
    monkeypatch.setattr(app_module, "_open_in_explorer", opened.append)
    instance = app_module.App(tk_root)
    instance.opened = opened
    return instance


def test_the_window_walks_a_fresh_map_through_extract(app, project) -> None:
    from test_flow import make_original, translations_file

    original = make_original(project)
    unexpected = autoanswer(app, {"請填寫翻譯檔": "開啟資料夾"})

    assert app.start(original)
    pump_until(app.root, lambda: not app.busy)

    assert unexpected == []
    assert app.last_outcome.kind == "extracted"
    assert translations_file(project).is_file()
    assert app.opened == [project / "sandbox" / ".mcmt-out" / "world"]
    log = app.log_text.get("1.0", "end")
    assert "抽取文字" in log
    # 對話框的字也要留在視窗的紀錄裡：很多人按了按鈕才發現沒看清楚內容。
    assert "【請填寫翻譯檔】" in log
    assert "填完後把這個翻譯檔拖進來" in log.split("【請填寫翻譯檔】", 1)[1]


def test_the_window_applies_after_the_confirmation_dialog(app, project) -> None:
    from test_flow import fill_all, make_original

    original = make_original(project)
    autoanswer(app, {"請填寫翻譯檔": "關閉"})
    app.start(original)
    pump_until(app.root, lambda: not app.busy)
    fill_all(project)

    unexpected = autoanswer(app, {"準備寫回": "寫回", "完成": "關閉"})
    app.start(original)
    pump_until(app.root, lambda: not app.busy)

    assert unexpected == []
    assert app.last_outcome.kind == "applied"
    assert (project / "sandbox" / "world" / "resources.zip").is_file()


def test_a_known_error_becomes_an_error_dialog_not_a_crash(app, project) -> None:
    unexpected = autoanswer(app, {"找不到資料夾": "關閉"})

    app.start(project / "nope")
    pump_until(app.root, lambda: not app.busy)

    assert unexpected == []
    assert app.last_outcome is None
    log = app.log_text.get("1.0", "end")
    assert "【找不到資料夾】" in log
    assert "nope 不存在" in log  # 錯誤內容也要寫進紀錄，不只標題


def test_an_unexpected_error_is_logged_and_offers_the_log_folder(app, project, monkeypatch) -> None:
    from mcmt.gui import app as app_module

    def boom(path, ui):
        raise RuntimeError("內部爆炸")

    monkeypatch.setattr(app_module, "run_flow", boom)
    unexpected = autoanswer(app, {"發生未預期的錯誤": "開啟日誌資料夾"})

    app.start(project / "whatever")
    pump_until(app.root, lambda: not app.busy)

    log = project / "sandbox" / "mcmt-error.log"
    assert unexpected == []
    assert log.is_file() and "內部爆炸" in log.read_text(encoding="utf-8")
    assert app.opened == [log.parent]


def test_a_second_map_is_refused_while_the_first_is_running(app, project, monkeypatch) -> None:
    from mcmt.gui import app as app_module

    release = threading.Event()
    monkeypatch.setattr(app_module, "run_flow", lambda path, ui: (release.wait(10), _Done())[1])
    assert app.start(project / "a")

    assert app.start(project / "b") is False
    assert "還在處理上一張地圖" in app.log_text.get("1.0", "end")
    release.set()
    pump_until(app.root, lambda: not app.busy)
    assert app.last_outcome.kind == "nothing_to_do"


class _Done:
    kind = "nothing_to_do"


def test_closing_while_busy_is_refused(app, project, monkeypatch) -> None:
    from mcmt.gui import app as app_module

    release = threading.Event()
    monkeypatch.setattr(app_module, "run_flow", lambda path, ui: (release.wait(10), _Done())[1])
    unexpected = autoanswer(app, {"處理中": "關閉"})
    app.start(project / "a")

    app.on_close()  # 視窗不能被關掉

    assert app.root.winfo_exists()
    release.set()
    pump_until(app.root, lambda: not app.busy)
    assert unexpected == []
    assert app.last_outcome.kind == "nothing_to_do"


def test_the_language_dialog_rejects_a_malformed_code(app) -> None:
    from mcmt.gui.app import LanguageDialog

    dialog = LanguageDialog(app, "zh_tw")
    dialog.value.set("繁體中文")
    dialog.confirm()

    assert dialog.winfo_exists()
    assert "zh_tw" in dialog.error.cget("text")
    dialog.value.set("ja_jp  日文")
    dialog.confirm()
    assert dialog.result == "ja_jp"


def test_the_dev_window_pins_the_sandbox_to_the_project_not_the_launch_folder(
    monkeypatch, tmp_path
) -> None:
    """[實測回報] 從別的 git 專案資料夾啟動 mcmt-gui，沙盒跑到那個專案底下。
    視窗版不能看「從哪裡啟動」，要固定在 mcmt 自己的專案裡。"""
    from pathlib import Path

    from mcmt.gui.app import _pin_working_directory
    from mcmt.safety.paths import sandbox_root

    elsewhere = tmp_path / "other-project"
    (elsewhere / ".git").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    monkeypatch.delattr(sys, "frozen", raising=False)

    _pin_working_directory()

    project = Path(__file__).resolve().parents[2]
    assert sandbox_root() == project / "sandbox"


def test_the_window_applies_a_dropped_translations_file(app, project) -> None:
    from test_flow import fill_all, make_original, translations_file

    original = make_original(project)
    autoanswer(app, {"請填寫翻譯檔": "關閉"})
    app.start(original)
    pump_until(app.root, lambda: not app.busy)
    fill_all(project)

    unexpected = autoanswer(app, {"準備寫回": "寫回", "完成": "關閉"})
    app.on_drop([str(translations_file(project))])
    pump_until(app.root, lambda: not app.busy)

    assert unexpected == []
    assert app.last_outcome.kind == "applied"


def test_the_window_offers_a_file_picker_for_the_translations_file(app, monkeypatch) -> None:
    from mcmt.gui import app as app_module

    started = []
    monkeypatch.setattr(app, "start", started.append)
    monkeypatch.setattr(
        app_module.filedialog, "askopenfilename", lambda **kwargs: "C:/x/translations.zh_tw.json"
    )

    app.pick_file_button.invoke()

    assert started == [__import__("pathlib").Path("C:/x/translations.zh_tw.json")]
    assert "翻譯檔" in app.drop_zone.cget("text")
