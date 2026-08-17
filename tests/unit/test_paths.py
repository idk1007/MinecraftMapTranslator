# SPDX-License-Identifier: GPL-3.0-or-later
"""M2.1 路徑圍籬（CLAUDE.md §1.1）。

寫入必須在 sandbox，讀取必須明示。這是整個工具「不會弄壞別人的地圖」的第一道
關，所以每一條規則都要有一個對應的測試，包括那些看起來很顯然的。
"""

import os
import subprocess

import pytest

from mcmt.errors import MinecraftSavesPathError, PathOutsideSandboxError
from mcmt.safety.paths import (
    ReadOnlyPath,
    ensure_readable,
    ensure_writable,
    read_log,
    reset_read_log,
    sandbox_root,
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """一個有 .git 標記的假專案，工作目錄設在它底下。"""
    (tmp_path / ".git").mkdir()
    (tmp_path / "sandbox").mkdir()
    monkeypatch.chdir(tmp_path)
    reset_read_log()
    return tmp_path


# --- sandbox 根目錄 -------------------------------------------------------


def test_sandbox_root_is_under_the_project_root(project) -> None:
    assert sandbox_root() == project / "sandbox"


def test_sandbox_root_is_the_same_from_a_subdirectory(project) -> None:
    """從 src/ 或 tests/ 底下跑指令不該變成另一個沙箱。"""
    (project / "src" / "mcmt").mkdir(parents=True)
    os.chdir(project / "src" / "mcmt")

    assert sandbox_root() == project / "sandbox"


def test_sandbox_root_falls_back_to_cwd_without_a_project_marker(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert sandbox_root() == tmp_path / "sandbox"


# --- ensure_writable ------------------------------------------------------


def test_a_path_inside_the_sandbox_is_writable(project) -> None:
    target = project / "sandbox" / "world" / "region" / "r.0.0.mca"

    assert ensure_writable(target) == target.resolve()


def test_the_sandbox_root_itself_is_writable(project) -> None:
    assert ensure_writable(project / "sandbox") == (project / "sandbox").resolve()


def test_a_path_outside_the_sandbox_is_refused(project) -> None:
    with pytest.raises(PathOutsideSandboxError):
        ensure_writable(project / "docs" / "STATUS.md")


def test_dot_dot_cannot_escape_the_sandbox(project) -> None:
    """先 resolve 再判斷，否則 sandbox/../x 會通過字串檢查。"""
    with pytest.raises(PathOutsideSandboxError):
        ensure_writable(project / "sandbox" / ".." / "escaped.txt")


def test_a_link_out_of_the_sandbox_is_refused(project) -> None:
    """符號連結建不了時改用目錄連接點（junction）。

    Windows 沒開開發者模式就建不了 symlink（WinError 1314），但 `mklink /J`
    **不需要管理員權限**，而 `Path.resolve()` 一樣會穿過去。所以這條逃逸路線在
    這台機器上是真的走得通的，測試不能因為 symlink 建不了就整條跳過。
    """
    outside = project / "outside"
    outside.mkdir()
    link = project / "sandbox" / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip("這個環境既不能建 symlink 也不能建 junction")

    with pytest.raises(PathOutsideSandboxError):
        ensure_writable(link / "world.mca")


def test_minecraft_saves_is_refused_even_inside_the_sandbox(project) -> None:
    """這條檢查優先於 sandbox 檢查——有人把 .minecraft 複製進 sandbox 也一樣擋。"""
    target = project / "sandbox" / ".minecraft" / "saves" / "world" / "level.dat"

    with pytest.raises(MinecraftSavesPathError):
        ensure_writable(target)


def test_version_isolated_saves_are_also_minecraft_saves(project) -> None:
    """語料就放在 .minecraft\\versions\\1.21.10\\saves，不是 .minecraft\\saves。

    只比對字面的 `.minecraft/saves` 會漏掉這個佈局，而那正是我們每天在讀的地方。
    """
    target = project / "sandbox" / ".minecraft" / "versions" / "1.21.10" / "saves" / "w"

    with pytest.raises(MinecraftSavesPathError):
        ensure_writable(target)


def test_a_saves_folder_unrelated_to_minecraft_is_fine(project) -> None:
    """沒有 .minecraft 成分的 `saves` 只是一個普通資料夾。"""
    target = project / "sandbox" / "saves" / "world"

    assert ensure_writable(target) == target.resolve()


# --- ensure_readable ------------------------------------------------------


def test_reading_minecraft_saves_is_allowed(project) -> None:
    source = project / ".minecraft" / "saves" / "world"
    source.mkdir(parents=True)

    assert ensure_readable(source).name == "world"


def test_reading_outside_the_sandbox_is_allowed(project) -> None:
    source = project / "anywhere.mca"
    source.write_bytes(b"x")

    assert ensure_readable(source).read_bytes() == b"x"


def test_readable_paths_are_recorded_for_the_report(project) -> None:
    a = project / "a"
    b = project / "b"
    a.mkdir()
    b.mkdir()

    ensure_readable(a)
    ensure_readable(b)
    ensure_readable(a)  # 重複的不再記一次

    assert read_log() == (a.resolve(), b.resolve())


def test_a_read_only_path_cannot_be_handed_to_open(project) -> None:
    """誤用寫入模式要在型別層就爆掉，不是靠呼叫端自律。"""
    source = project / "a.mca"
    source.write_bytes(b"x")
    readable = ensure_readable(source)

    with pytest.raises(TypeError):
        open(readable, "w")  # noqa: SIM115


def test_a_read_only_path_opens_binary_for_reading(project) -> None:
    source = project / "a.mca"
    source.write_bytes(b"hello")

    with ensure_readable(source).open_binary() as handle:
        assert handle.read() == b"hello"
        assert handle.writable() is False


def test_globbing_a_read_only_path_stays_read_only(project) -> None:
    region = project / "world" / "region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_bytes(b"x")

    (found,) = ensure_readable(region).glob("*.mca")

    assert isinstance(found, ReadOnlyPath)
    assert found.name == "r.0.0.mca"
