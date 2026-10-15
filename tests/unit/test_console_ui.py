# SPDX-License-Identifier: GPL-3.0-or-later
"""終端機版的流程介面（`mcmt drop`）：視窗版出來之前，用它把整條流程在真實地圖上
走一遍；之後它仍是沒有圖形環境時的後備。"""

import pytest
from test_flow import make_original, out_dir, translations_file

from mcmt.cli.__main__ import main
from mcmt.cli.console_ui import ConsoleUi


def feed(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def test_ask_returns_the_chosen_button(monkeypatch, capsys) -> None:
    feed(monkeypatch, ["2"])

    answer = ConsoleUi().ask("標題", "內容", ["甲", "乙", "丙"])

    out = capsys.readouterr().out
    assert answer == "乙"
    assert "【標題】" in out and "內容" in out
    assert "1) 甲" in out and "3) 丙" in out


def test_ask_repeats_until_the_answer_is_valid(monkeypatch, capsys) -> None:
    feed(monkeypatch, ["", "9", "abc", "1"])

    assert ConsoleUi().ask("t", "b", ["甲", "乙"]) == "甲"
    assert capsys.readouterr().out.count("請輸入") >= 1


def test_closing_the_input_counts_as_cancel(monkeypatch) -> None:
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)

    assert ConsoleUi().ask("t", "b", ["甲", "乙"]) is None


def test_language_defaults_when_just_pressing_enter(monkeypatch) -> None:
    feed(monkeypatch, [""])

    assert ConsoleUi().choose_language("zh_tw") == "zh_tw"


def test_language_accepts_a_typed_code(monkeypatch) -> None:
    feed(monkeypatch, ["  en_us "])

    assert ConsoleUi().choose_language("zh_tw") == "en_us"


def test_open_path_prints_the_path_and_tries_to_open_it(monkeypatch, capsys, tmp_path) -> None:
    opened = []
    monkeypatch.setattr("os.startfile", opened.append, raising=False)

    ConsoleUi().open_path(tmp_path)

    assert str(tmp_path) in capsys.readouterr().out
    assert opened in ([], [str(tmp_path)], [tmp_path])  # 沒有圖形環境時不開也行


# --- mcmt drop -----------------------------------------------------------------


def test_drop_walks_a_fresh_world_through_import_and_extract(project, monkeypatch, capsys) -> None:
    original = make_original(project)
    # 語言（Enter＝預設）、「請填寫翻譯檔」按 [關閉]
    feed(monkeypatch, ["", "2"])

    code = main(["drop", str(original)])

    out = capsys.readouterr().out
    assert code == 0
    assert translations_file(project).is_file()
    assert "【請填寫翻譯檔】" in out
    assert out_dir(project).is_dir()


def test_drop_without_a_terminal_says_it_needs_one(project, monkeypatch, capsys) -> None:
    original = make_original(project)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)

    code = main(["drop", str(original)])

    assert code == 2
    assert "需要在終端機" in capsys.readouterr().err
    assert not (project / "sandbox" / "world").exists()


def test_drop_shows_errors_the_same_way_as_the_other_commands(project, monkeypatch, capsys) -> None:
    feed(monkeypatch, [])

    code = main(["drop", str(project / "nope")])

    assert code == 2
    assert "【找不到資料夾】" in capsys.readouterr().err
