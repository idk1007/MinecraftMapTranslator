# SPDX-License-Identifier: GPL-3.0-or-later
"""「什麼算一個世界資料夾」——只定義一次。

`doctor`、`extract`、之後的 `apply` 都要回答這個問題。定義散在三個地方時，會出現
「doctor 說這不是世界，extract 卻掃出 0 個單位並宣稱成功」這種各說各話的狀況。
"""

from pathlib import Path

from mcmt.errors import NotAWorldError, WorldNotFoundError
from mcmt.safety.paths import ReadOnlyPath, ensure_readable

__all__ = ["open_world", "region_dirs_of"]


def open_world(path: Path | str) -> ReadOnlyPath:
    """確認這是一個世界資料夾，回傳唯讀 handle。

    判準是「底下有 `region` 目錄」——`level.dat` 不算，因為壞掉的世界可能沒有它，
    而我們處理的東西全部在 region 裡。
    """
    world = Path(path)
    if not world.is_dir():
        raise WorldNotFoundError(world)

    readable = ensure_readable(world)
    if not region_dirs_of(readable):
        raise NotAWorldError(world)
    return readable


def region_dirs_of(world: ReadOnlyPath) -> list[str]:
    """世界裡所有 region 目錄，相對於世界根、依名稱排序。"""
    return sorted(d.relative_to(world) for d in world.rglob("region") if d.is_dir())
