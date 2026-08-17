# SPDX-License-Identifier: GPL-3.0-or-later
"""修改存檔前的強制備份（CLAUDE.md §1.2）。

    with BackupSet(world_dir) as bk:
        bk.protect(region_path)     # 第一次修改前呼叫，重複呼叫不重複備份
        ...                         # 例外發生時自動還原所有已備份的檔案

**備份失敗就中止。** 磁碟滿、權限不足、目標唯讀——一律 `BackupFailedError`，
絕不允許「備份失敗但繼續寫」。那條路徑的終點是「別人花幾千小時做的地圖沒了」。

備份放在 `sandbox/.mcmt-backups/<世界名>/<時間戳>/`，與世界資料夾**平行**而不是
在它裡面：世界資料夾因此完全不會多出任何檔案，「除了要改的地方以外什麼都沒動」
才會是可以整包比對驗證的。

`BackupSet` 收到 `.minecraft/saves` 底下的路徑時會拋 `MinecraftSavesPathError`
——那是 `ensure_writable` 給的，備份層不是繞過路徑圍籬的後門。

**還原失敗時訊息裡有備份目錄的絕對路徑。** 使用者永遠要有一條救回來的路，即使
我們自己的還原壞了。
"""

import shutil
from datetime import datetime
from pathlib import Path

from mcmt.errors import BackupFailedError, BackupRestoreFailedError
from mcmt.safety.paths import ensure_writable, sandbox_root

__all__ = ["BACKUPS_DIR_NAME", "BackupSet"]

BACKUPS_DIR_NAME = ".mcmt-backups"


class BackupSet:
    """一次修改作業的備份集合，同時是失敗時的回滾器。"""

    def __init__(self, world: Path | str, *, backups_root: Path | None = None) -> None:
        self.world = ensure_writable(world)
        root = Path(backups_root) if backups_root else sandbox_root() / BACKUPS_DIR_NAME
        self.directory = ensure_writable(
            _unique(root / self.world.name / _timestamp())
        )
        self._backed_up: dict[Path, Path] = {}
        self._created: set[Path] = set()

    # --- 介面 ---
    @property
    def file_count(self) -> int:
        """實際被備份起來的檔案數。要寫進 `apply_report.json` 的 `backup` 欄位。"""
        return len(self._backed_up)

    def protect(self, path: Path | str) -> None:
        """在第一次修改 `path` 之前呼叫。重複呼叫不重複備份。

        重複備份會用「已經被我們改壞的內容」蓋掉原始備份，那比沒有備份更糟——
        它看起來像有備份。
        """
        target = ensure_writable(path)
        try:
            relative = target.relative_to(self.world)
        except ValueError as exc:
            raise BackupFailedError(
                path=target,
                directory=self.directory,
                detail=f"這個路徑不在世界資料夾 {self.world} 底下",
            ) from exc

        if target in self._backed_up or target in self._created:
            return

        if not target.exists():
            # 還不存在的檔案（例如即將新建的 resources.zip）：回滾時要刪掉，
            # 不然失敗後世界裡會多出我們留下的東西。
            self._created.add(target)
            return

        destination = self.directory / relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, destination)
        except OSError as exc:
            raise BackupFailedError(
                path=target, directory=self.directory, detail=str(exc)
            ) from exc
        self._backed_up[target] = destination

    # --- context manager ---
    def __enter__(self) -> "BackupSet":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self._restore(exc)
        return False  # 原始例外照樣往上拋

    # --- 內部 ---
    def _restore(self, original: BaseException | None) -> None:
        failures: list[tuple[Path, str]] = []

        for source, backup_path in self._backed_up.items():
            try:
                shutil.copyfile(backup_path, source)
            except OSError as exc:
                failures.append((source, str(exc)))

        for created in self._created:
            try:
                if created.exists():
                    created.unlink()
            except OSError as exc:
                failures.append((created, str(exc)))

        if failures:
            raise BackupRestoreFailedError(
                directory=self.directory, failures=failures
            ) from original


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique(path: Path) -> Path:
    """同一秒內開第二個 BackupSet 時不要共用同一個目錄。"""
    if not path.exists():
        return path
    for n in range(1, 1000):
        candidate = path.with_name(f"{path.name}-{n}")
        if not candidate.exists():
            return candidate
    raise BackupFailedError(  # pragma: no cover - 同一秒 1000 次
        path=path, directory=path.parent, detail="同一秒內的備份目錄用完了"
    )
