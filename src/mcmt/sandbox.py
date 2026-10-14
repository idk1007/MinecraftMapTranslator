# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt sandbox import`（M2.3）。

**這是唯一合法的把世界帶進 sandbox 的入口**（CLAUDE.md §1.1）。

複製是**真的複製**：不是 symlink、不是硬連結。工具之後會改寫這些檔案，連結會
直接改到使用者的原始地圖上——那正是這整個專案在防的事。

複製走的是「逐檔 `ensure_readable` 讀 → 逐檔 `ensure_writable` 寫」，不是
`shutil.copytree`。差別在於**每一個寫入都經過圍籬**，而不是在根目錄檢查一次
之後讓 shutil 自己去寫。慢一點，但保證的強度不一樣。

`.mcmt-origin.json` 記三件事（規範要求）：來源絕對路徑、匯入時間、來源的
`world_fingerprint`。指紋記的是**來源**——sandbox 裡的副本之後會被改，屆時要
回答「這份副本是從哪個狀態的世界來的」只能靠這個值。
"""

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mcmt.errors import (
    NotAWorldError,
    SandboxTargetExistsError,
    SandboxTargetInsideSourceError,
    WorldNotFoundError,
)
from mcmt.fingerprint import world_fingerprint
from mcmt.safety.paths import ensure_readable, ensure_writable, sandbox_root

__all__ = ["ORIGIN_FILENAME", "ImportResult", "import_world"]

ORIGIN_FILENAME = ".mcmt-origin.json"
_COPY_BUFFER = 1024 * 1024


@dataclass(frozen=True)
class ImportResult:
    source: Path
    target: Path
    world_fingerprint: str
    imported_at: str
    file_count: int


def import_world(
    source: Path | str, *, name: str | None = None, replace: bool = False
) -> ImportResult:
    """把一個世界完整複製進 `sandbox/`，並記下它的來歷。"""
    source_path = Path(source).resolve()
    if not _looks_like_a_world(source_path):
        raise (
            NotAWorldError(source_path)
            if source_path.exists()
            else WorldNotFoundError(source_path)
        )

    target = ensure_writable(sandbox_root() / (name or source_path.name))
    if target == source_path or source_path in target.parents:
        raise SandboxTargetInsideSourceError(source=source_path, target=target)

    if target.exists():
        if not replace:
            raise SandboxTargetExistsError(target=target)
        shutil.rmtree(ensure_writable(target))

    readable = ensure_readable(source_path)
    fingerprint = world_fingerprint(source_path)

    file_count = 0
    ensure_writable(target).mkdir(parents=True)
    for entry in readable.rglob("*"):
        destination = ensure_writable(target / entry.relative_to(readable))
        if entry.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with entry.open_binary() as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, _COPY_BUFFER)
        file_count += 1

    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    origin = {
        "source": str(source_path),
        "imported_at": imported_at,
        "world_fingerprint": fingerprint,
    }
    ensure_writable(target / ORIGIN_FILENAME).write_text(
        json.dumps(origin, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return ImportResult(
        source=source_path,
        target=target,
        world_fingerprint=fingerprint,
        imported_at=imported_at,
        file_count=file_count,
    )


def _looks_like_a_world(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "level.dat").is_file():
        return True
    return any(d.is_dir() for d in path.rglob("region"))
