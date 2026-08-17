# SPDX-License-Identifier: GPL-3.0-or-later
"""M2.4 `BackupSet`（CLAUDE.md §1.2）。

> 修改任何存檔前強制備份，無法備份就中止。

「備份失敗但繼續寫」在這個專案裡沒有任何可接受的版本——那正是「別人花幾千小時
做的地圖沒了」的那條路徑。所以這裡的測試有一半在測失敗的情況。
"""

import shutil

import pytest

from mcmt.errors import (
    BackupFailedError,
    BackupRestoreFailedError,
    MinecraftSavesPathError,
    PathOutsideSandboxError,
)
from mcmt.safety.backup import BackupSet


@pytest.fixture
def world(project):
    world = project / "sandbox" / "world"
    (world / "region").mkdir(parents=True)
    (world / "region" / "r.0.0.mca").write_bytes(b"original region")
    (world / "level.dat").write_bytes(b"original level")
    return world


class Boom(Exception):
    pass


# --- 備份 -----------------------------------------------------------------


def test_protect_copies_the_file_before_it_is_written(project, world) -> None:
    region = world / "region" / "r.0.0.mca"

    with BackupSet(world) as backup:
        backup.protect(region)
        region.write_bytes(b"modified")
        copy = backup.directory / "region" / "r.0.0.mca"

        assert copy.read_bytes() == b"original region"


def test_the_backup_lives_under_the_sandbox_backups_folder(project, world) -> None:
    with BackupSet(world) as backup:
        backup.protect(world / "level.dat")

        assert backup.directory.parent.parent == project / "sandbox" / ".mcmt-backups"
        assert backup.directory.parent.name == "world"


def test_protecting_twice_does_not_overwrite_the_first_copy(project, world) -> None:
    """「第一次修改前呼叫，重複呼叫不重複備份」——第二次備份會存到已改壞的內容。"""
    region = world / "region" / "r.0.0.mca"

    with BackupSet(world) as backup:
        backup.protect(region)
        region.write_bytes(b"modified once")
        backup.protect(region)

        assert (backup.directory / "region" / "r.0.0.mca").read_bytes() == b"original region"
        assert backup.file_count == 1


def test_the_backup_directory_and_file_count_are_reported(project, world) -> None:
    """這兩個值要寫進 apply_report.json 的 backup 欄位。"""
    with BackupSet(world) as backup:
        backup.protect(world / "level.dat")
        backup.protect(world / "region" / "r.0.0.mca")

        assert backup.file_count == 2
        assert backup.directory.is_absolute()


# --- 還原 -----------------------------------------------------------------


def test_an_exception_restores_every_protected_file(project, world) -> None:
    region = world / "region" / "r.0.0.mca"
    level = world / "level.dat"

    with pytest.raises(Boom):
        with BackupSet(world) as backup:
            backup.protect(region)
            backup.protect(level)
            region.write_bytes(b"broken")
            level.write_bytes(b"broken")
            raise Boom

    assert region.read_bytes() == b"original region"
    assert level.read_bytes() == b"original level"


def test_a_file_that_did_not_exist_is_removed_on_rollback(project, world) -> None:
    """新建的檔案也要能回滾——不然失敗後世界裡會多出我們留下的東西。"""
    new_file = world / "resources.zip"

    with pytest.raises(Boom):
        with BackupSet(world) as backup:
            backup.protect(new_file)
            new_file.write_bytes(b"half-written")
            raise Boom

    assert not new_file.exists()


def test_success_keeps_the_changes_and_the_backup(project, world) -> None:
    region = world / "region" / "r.0.0.mca"

    with BackupSet(world) as backup:
        backup.protect(region)
        region.write_bytes(b"modified")

    assert region.read_bytes() == b"modified"
    assert (backup.directory / "region" / "r.0.0.mca").exists()


def test_a_failed_restore_names_the_backup_directory(project, world, monkeypatch) -> None:
    """使用者永遠要有一條救回來的路，所以訊息裡要有絕對路徑。"""
    region = world / "region" / "r.0.0.mca"
    seen = {}

    with pytest.raises(BackupRestoreFailedError) as exc:
        with BackupSet(world) as backup:
            backup.protect(region)
            seen["directory"] = backup.directory
            # 備份已經做好了才讓還原壞掉——在 protect 之前壞掉是另一條路徑
            # （BackupFailedError，中止而非回滾）。
            monkeypatch.setattr(shutil, "copyfile", _explode)
            region.write_bytes(b"broken")
            raise Boom

    assert seen["directory"].is_absolute()
    assert str(seen["directory"]) in str(exc.value)


def test_two_backup_sets_do_not_share_a_directory(project, world) -> None:
    """同一秒內開第二個備份集，不能蓋掉第一個的內容。"""
    with BackupSet(world) as first:
        first.protect(world / "level.dat")
    with BackupSet(world) as second:
        second.protect(world / "level.dat")

    assert first.directory != second.directory


def test_a_failed_restore_still_reports_the_original_failure(project, world, monkeypatch) -> None:
    """回滾失敗不該把「本來為什麼失敗」蓋掉。"""
    region = world / "region" / "r.0.0.mca"

    with pytest.raises(BackupRestoreFailedError) as exc:
        with BackupSet(world) as backup:
            backup.protect(region)
            monkeypatch.setattr(shutil, "copyfile", _explode)
            raise Boom("原始失敗原因")

    assert isinstance(exc.value.__cause__, Boom)


# --- 拒絕 -----------------------------------------------------------------


def test_a_world_in_minecraft_saves_is_refused(project) -> None:
    """備份層不是繞過路徑圍籬的後門。"""
    saves = project / "sandbox" / ".minecraft" / "saves" / "world"
    saves.mkdir(parents=True)

    with pytest.raises(MinecraftSavesPathError):
        BackupSet(saves)


def test_a_world_outside_the_sandbox_is_refused(project) -> None:
    outside = project / "outside"
    outside.mkdir()

    with pytest.raises(PathOutsideSandboxError):
        BackupSet(outside)


def test_protecting_a_file_outside_the_world_is_refused(project, world) -> None:
    other = project / "sandbox" / "other.mca"
    other.write_bytes(b"x")

    with BackupSet(world) as backup:
        with pytest.raises(BackupFailedError):
            backup.protect(other)


def test_a_backup_that_cannot_be_written_aborts(project, world) -> None:
    """磁碟滿、權限不足、目標唯讀——一律中止，絕不「備份失敗但繼續寫」。"""
    backups = project / "sandbox" / ".mcmt-backups"
    backups.write_text("這是一個檔案，不是資料夾", encoding="utf-8")

    with pytest.raises(BackupFailedError):
        with BackupSet(world) as backup:
            backup.protect(world / "level.dat")


def test_the_file_is_untouched_when_the_backup_fails(project, world) -> None:
    backups = project / "sandbox" / ".mcmt-backups"
    backups.write_text("這是一個檔案，不是資料夾", encoding="utf-8")
    region = world / "region" / "r.0.0.mca"

    with pytest.raises(BackupFailedError):
        with BackupSet(world) as backup:
            backup.protect(region)
            region.write_text("這一行不該被執行到", encoding="utf-8")

    assert region.read_bytes() == b"original region"


def _explode(*args, **kwargs):
    raise OSError("模擬還原失敗")
