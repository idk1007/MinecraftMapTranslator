# SPDX-License-Identifier: GPL-3.0-or-later
"""使用者會看到的錯誤訊息（`docs/error-messages-review.md` 的 A–E）。

每則訊息是「標題＋內容」：標題給對話框，內容給正文。這裡驗的是**使用者讀到什麼**，
不是例外怎麼被拋——所以斷言寫在標題與內容的關鍵字上，不寫整句，措辭微調不會
讓測試跟著壞，但「少了哪個重點」會。
"""

import json
from pathlib import Path

import pytest
from test_cli_extract import build_world

from mcmt.cli.__main__ import main
from mcmt.cli.apply import run_apply
from mcmt.cli.extract import run_extract
from mcmt.errors import (
    BackupFailedError,
    BackupRestoreFailedError,
    InputFileNotFoundError,
    InvalidJsonFileError,
    MinecraftSavesPathError,
    NamespaceConflictError,
    NotAWorldError,
    PathOutsideSandboxError,
    SandboxTargetExistsError,
    TranslationsExistError,
    TranslationsMismatchError,
    WorldChangedSinceExtractError,
    WorldNotFoundError,
)
from mcmt.safety.paths import ensure_writable
from mcmt.world import open_world


def shown(exc: Exception) -> str:
    """標題＋內容，跟對話框／終端機會顯示的一樣。"""
    return f"{exc.title}\n{exc}"


# --- A：使用者操作 ------------------------------------------------------------


def test_a1_a_missing_folder_is_not_confused_with_a_non_world(project) -> None:
    with pytest.raises(WorldNotFoundError) as caught:
        open_world(project / "nope")

    assert not isinstance(caught.value, NotAWorldError)
    assert caught.value.title == "找不到資料夾"
    assert "nope" in str(caught.value)


def test_a2_a_folder_without_region_says_it_is_not_a_world(project) -> None:
    (project / "somewhere").mkdir()

    with pytest.raises(NotAWorldError) as caught:
        open_world(project / "somewhere")

    assert caught.value.title == "不是有效的地圖"
    assert "level.dat" in str(caught.value)
    assert "輸出資料夾" not in str(caught.value)


def test_a2_the_output_folder_gets_an_extra_hint(project) -> None:
    folder = project / "sandbox" / ".mcmt-out" / "world"
    folder.mkdir(parents=True)

    with pytest.raises(NotAWorldError) as caught:
        open_world(folder)

    assert "輸出資料夾" in str(caught.value)
    assert "sandbox" in str(caught.value)


def test_a3_a_missing_translations_file_names_the_file(project) -> None:
    world = build_world(project)

    with pytest.raises(InputFileNotFoundError) as caught:
        run_apply(world, project / "nope" / "translations.zh_tw.json")

    assert isinstance(caught.value, FileNotFoundError)  # 既有呼叫端照舊抓得到
    assert caught.value.title == "找不到翻譯檔"
    assert "translations.zh_tw.json" in str(caught.value)
    assert "Errno" not in str(caught.value)


def test_a4_a_broken_translations_file_points_at_the_line(project) -> None:
    world = build_world(project)
    broken = project / "sandbox" / "translations.zh_tw.json"
    broken.write_text('{\n  "a": 1,\n  "b": 2,\n  "c" 3,\n  "d": 4\n}\n', encoding="utf-8")

    with pytest.raises(InvalidJsonFileError) as caught:
        run_apply(world, broken)

    text = shown(caught.value)
    assert caught.value.title == "翻譯檔無法讀取"
    assert "第 4 行" in text
    assert '"c" 3,' in text  # 出錯那一行
    assert '"b": 2,' in text  # 前文
    assert '"d": 4' in text  # 後文
    assert "未變更任何檔案" in text
    assert "Expecting" not in text


def test_a5_a_stale_translations_file_says_which_one_to_use(project) -> None:
    from mcmt.backends.resourcepack.backend import _check_binding

    extract = {"schema_version": 7, "world": {"extract_fingerprint": "blake2b:aaaa"}}
    translations = {
        "schema_version": 7,
        "extract_ref": {"extract_fingerprint": "blake2b:bbbb"},
    }

    with pytest.raises(TranslationsMismatchError) as caught:
        _check_binding(extract, translations)

    assert isinstance(caught.value, ValueError)
    assert caught.value.title == "翻譯檔與地圖不符"
    assert "最新" in str(caught.value)
    assert "blake2b" not in str(caught.value)  # 指紋是技術細節，不放在畫面上


def test_a6_a_changed_world_says_to_extract_again() -> None:
    error = WorldChangedSinceExtractError(world="w", expected="x", actual="y")

    assert error.title == "地圖已變更"
    assert "重新抽取" in str(error)
    assert "blake2b" not in str(error)
    assert "source/target 對得上" not in str(error)  # 舊訊息裡那句是錯的


def test_a7_extract_over_an_existing_file_raises_a_file_exists_error(project) -> None:
    world = build_world(project)
    run_extract(world)

    with pytest.raises(TranslationsExistError) as caught:
        run_extract(world)

    assert isinstance(caught.value, FileExistsError)
    assert caught.value.title == "檔案已存在"
    assert "translations.zh_tw.json" in str(caught.value)


def test_a7_replacing_keeps_the_old_file_as_a_backup(project) -> None:
    world = build_world(project)
    summary = run_extract(world)
    path = summary["translations_path"]
    edited = json.loads(path.read_text(encoding="utf-8"))
    next(iter(edited["entries"].values()))["target"] = "我辛苦翻的"
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")

    run_extract(world, replace=True)

    backups = sorted(path.parent.glob("translations.zh_tw.json.bak-*"))
    assert len(backups) == 1
    assert "我辛苦翻的" in backups[0].read_text(encoding="utf-8")


def test_a8_importing_over_an_existing_world_explains_what_is_lost() -> None:
    error = SandboxTargetExistsError(target=Path("sandbox/world"))

    assert error.title == "地圖已存在"
    assert "world" in str(error)
    assert "翻譯檔不受影響" in str(error)


def test_a9_a_path_outside_the_sandbox_points_at_import(project) -> None:
    with pytest.raises(PathOutsideSandboxError) as caught:
        ensure_writable(project / "elsewhere" / "file")

    assert caught.value.title == "只能修改沙盒"
    assert "匯入" in str(caught.value)


def test_a10_saves_gets_its_own_message_and_the_same_way_out() -> None:
    error = MinecraftSavesPathError(path=Path("C:/x/.minecraft/saves/w"))

    assert error.title == "存檔目錄受保護"
    assert "匯入" in str(error)
    assert "拖曳" in str(error)


def test_a11_a_missing_option_is_explained_in_chinese(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["apply", "world"])

    err = capsys.readouterr().err
    assert caught.value.code == 2
    assert "缺少必要選項" in err
    assert "--translations" in err
    assert "required" not in err  # 不留英文原句


def test_a12_a_permission_error_is_not_a_traceback(project, monkeypatch, capsys) -> None:
    def boom(*args, **kwargs):
        raise PermissionError(13, "存取被拒", "C:/x/y")

    monkeypatch.setattr("mcmt.cli.__main__.run_extract", boom)

    code = main(["extract", str(build_world(project))])

    err = capsys.readouterr().err
    assert code == 2
    assert "檔案存取被拒" in err
    assert "Traceback" not in err
    assert "Minecraft" in err


# --- A7／A8 的互動確認 ---------------------------------------------------------


def test_a7_a_terminal_user_is_asked_before_overwriting(project, monkeypatch, capsys) -> None:
    world = build_world(project)
    main(["extract", str(world)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    code = main(["extract", str(world)])

    assert code == 0
    assert list((project / "sandbox" / ".mcmt-out" / "world").glob("*.bak-*"))


def test_a7_answering_no_leaves_everything_alone(project, monkeypatch, capsys) -> None:
    world = build_world(project)
    main(["extract", str(world)])
    translations = project / "sandbox" / ".mcmt-out" / "world" / "translations.zh_tw.json"
    before = translations.read_bytes()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    code = main(["extract", str(world)])

    assert code == 2
    assert translations.read_bytes() == before
    assert not list(translations.parent.glob("*.bak-*"))


def test_a7_without_a_terminal_it_fails_and_names_the_flag(project, monkeypatch, capsys) -> None:
    world = build_world(project)
    main(["extract", str(world)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    capsys.readouterr()

    code = main(["extract", str(world)])

    err = capsys.readouterr().err
    assert code == 2
    assert "--replace" in err
    assert "【檔案已存在】" in err


# --- B：地圖格式限制 -----------------------------------------------------------


def test_b1_an_external_chunk_says_nothing_was_changed() -> None:
    from mcmt.errors import ExternalChunkError

    error = ExternalChunkError(chunk_index=5)

    assert error.title == "不支援的地圖格式"
    assert ".mcc" in str(error)
    assert "未變更任何檔案" in str(error)


def test_b3_an_oversized_chunk_says_nothing_was_changed() -> None:
    from mcmt.errors import ChunkTooLargeError

    error = ChunkTooLargeError(chunk_index=5, sectors=300)

    assert error.title == "區塊超出容量"
    assert "未變更任何檔案" in str(error)


# --- D：寫入保護 ---------------------------------------------------------------


def test_d1_a_failed_backup_says_nothing_was_changed() -> None:
    error = BackupFailedError(path="r.mca", directory="b", detail="磁碟已滿")

    assert error.title == "備份建立失敗"
    assert "未變更任何檔案" in str(error)
    assert "磁碟已滿" in str(error)


def test_d2_a_failed_restore_gives_the_backup_path() -> None:
    error = BackupRestoreFailedError(
        directory=Path("C:/sandbox/.mcmt-backups/w/1"), failures=[("r.mca", "被佔用")]
    )

    assert error.title == "自動還原未完成"
    assert ".mcmt-backups" in str(error)
    assert "r.mca" in str(error)


def test_d3_a_verification_failure_points_at_the_log() -> None:
    from mcmt.errors import DatWriteVerificationError

    error = DatWriteVerificationError("寫出去的內容讀不回來")

    assert error.title == "寫入檢查未通過"
    assert "mcmt-error.log" in shown(error)


def test_d5_the_minecraft_namespace_is_refused_before_anything_is_written(project) -> None:
    world = build_world(project)

    with pytest.raises(NamespaceConflictError) as caught:
        run_extract(world, namespace="minecraft")

    assert caught.value.title == "命名空間衝突"
    assert isinstance(caught.value, ValueError)
    assert not (project / "sandbox" / ".mcmt-out").exists()


# --- E：內部錯誤與總攔截 -------------------------------------------------------


def test_e3_an_unexpected_exception_is_logged_not_dumped(project, monkeypatch, capsys) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("內部爆炸")

    monkeypatch.setattr("mcmt.cli.__main__.survey_world", boom)

    code = main(["doctor", str(build_world(project))])

    err = capsys.readouterr().err
    log = project / "sandbox" / "mcmt-error.log"
    assert code == 3
    assert "【發生未預期的錯誤】" in err
    assert "mcmt-error.log" in err
    assert "Traceback" not in err
    assert log.is_file()
    assert "RuntimeError" in log.read_text(encoding="utf-8")
    assert "內部爆炸" in log.read_text(encoding="utf-8")


def test_e3_the_log_lives_inside_the_sandbox(project, monkeypatch) -> None:
    """安全規則 1：任何寫入都要在 sandbox 底下，錯誤日誌也不例外。"""
    monkeypatch.setattr(
        "mcmt.cli.__main__.survey_world", lambda *a, **k: (_ for _ in ()).throw(KeyError("x"))
    )

    main(["doctor", str(build_world(project))])

    assert (project / "sandbox" / "mcmt-error.log").is_file()
    assert not (project / "mcmt-error.log").exists()


def test_a_known_error_prints_its_title_and_exits_two(project, capsys) -> None:
    code = main(["doctor", str(project / "nope")])

    err = capsys.readouterr().err
    assert code == 2
    assert "【找不到資料夾】" in err
