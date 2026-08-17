# SPDX-License-Identifier: GPL-3.0-or-later
"""路徑圍籬（CLAUDE.md §1.1）。

**寫入必須在 sandbox，讀取必須明示。**

    target = ensure_writable(p)   # 唯一合法的取得寫入路徑的方式
    source = ensure_readable(p)   # 唯一合法的取得讀取路徑的方式

`ensure_readable` 不是為了擋讀取——它允許唯讀 `.minecraft/saves`（`doctor` 與
`extract` 需要）。它存在是為了讓「這裡在讀什麼」變成一個明示的動作，並且回傳
一個**沒有 `__fspath__` 的包裝**，讓 `open(p, "w")` 在型別層就爆掉，而不是靠
「我沒呼叫 ensure_writable 所以應該安全」這種隱性論證。

sandbox 根目錄 = `<專案根>/sandbox`，專案根是從 CWD 往上找到的第一個含 `.git`
或 `pyproject.toml` 的目錄；找不到就退回 `<CWD>/sandbox`。這樣從 `src/` 或
`tests/` 底下跑指令都指向同一個沙箱，不會因為 `cd` 就多出第二個。
"""

from pathlib import Path


from mcmt.errors import MinecraftSavesPathError, PathOutsideSandboxError

__all__ = [
    "ReadOnlyPath",
    "ensure_readable",
    "ensure_writable",
    "read_log",
    "reset_read_log",
    "sandbox_root",
]

_PROJECT_MARKERS = (".git", "pyproject.toml")
_SANDBOX_DIR_NAME = "sandbox"

# 「本次執行讀了哪些路徑」——記的是**入口**（一個世界、一個資料夾），不是底下
# 每一個被 glob 出來的檔案。20 萬個 region 檔進報告沒有意義。
_read_log: list[Path] = []


def sandbox_root() -> Path:
    """唯一允許寫入的目錄。**不建立它**——建立是 `sandbox import` 的事。"""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if any((candidate / marker).exists() for marker in _PROJECT_MARKERS):
            return candidate / _SANDBOX_DIR_NAME
    return cwd / _SANDBOX_DIR_NAME


def ensure_writable(path: Path | str) -> Path:
    """回傳可以寫入的絕對路徑，否則拋 `SafetyError`。

    任何 `open(...,"w")`、`write_bytes`、`shutil.copy`、`Path.unlink` 之前都要
    先過這裡。
    """
    resolved = Path(path).resolve()

    # 順序是規範的一部分：.minecraft 檢查優先於 sandbox 檢查。
    if _looks_like_minecraft_saves(resolved):
        raise MinecraftSavesPathError(path=resolved)

    sandbox = sandbox_root().resolve()
    if not _is_within(resolved, sandbox):
        raise PathOutsideSandboxError(path=resolved, sandbox=sandbox)
    return resolved


def ensure_readable(path: Path | str) -> "ReadOnlyPath":
    """回傳唯讀包裝，並把這個入口記進本次執行的讀取紀錄。"""
    resolved = Path(path).resolve()
    if resolved not in _read_log:
        _read_log.append(resolved)
    return ReadOnlyPath(resolved)


def read_log() -> tuple[Path, ...]:
    """本次執行讀過的入口路徑，依第一次被讀到的順序。"""
    return tuple(_read_log)


def reset_read_log() -> None:
    _read_log.clear()


class ReadOnlyPath:
    """一個只能讀的路徑。

    刻意**不實作** `__fspath__`：`open(p, "w")` 會 TypeError，`shutil.copy(p, ...)`
    也拿不到它。要寫入就得回頭走 `ensure_writable`，那是唯一的入口。
    """

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        self._path = path

    # --- 身分 ---
    @property
    def name(self) -> str:
        return self._path.name

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"ReadOnlyPath({self._path!s})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ReadOnlyPath) and other._path == self._path

    def __hash__(self) -> int:
        return hash(("ReadOnlyPath", self._path))

    # --- 讀 ---
    def open_binary(self):
        return self._path.open("rb")

    def read_bytes(self) -> bytes:
        return self._path.read_bytes()

    def size(self) -> int:
        return self._path.stat().st_size

    def exists(self) -> bool:
        return self._path.exists()

    def is_dir(self) -> bool:
        return self._path.is_dir()

    def is_file(self) -> bool:
        return self._path.is_file()

    # --- 走訪。走出來的東西一樣是唯讀的 ---
    def glob(self, pattern: str) -> list["ReadOnlyPath"]:
        return [ReadOnlyPath(p) for p in sorted(self._path.glob(pattern))]

    def rglob(self, pattern: str) -> list["ReadOnlyPath"]:
        return [ReadOnlyPath(p) for p in sorted(self._path.rglob(pattern))]

    def __truediv__(self, other: str) -> "ReadOnlyPath":
        return ReadOnlyPath(self._path / other)

    def relative_to(self, other: "ReadOnlyPath") -> str:
        try:
            return str(self._path.relative_to(other._path))
        except ValueError:
            return str(self._path)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _looks_like_minecraft_saves(path: Path) -> bool:
    """路徑是否指向 Minecraft 自己的存檔區。

    比對的不是字面的 `.minecraft/saves`，而是「有 `.minecraft` 成分，且其後有
    `saves` 成分」——語料就放在 `.minecraft\\versions\\1.21.10\\saves`，只認字面
    形式會漏掉我們每天在讀的那個位置。
    """
    parts = [p.lower() for p in path.parts]
    for index, part in enumerate(parts):
        if part == ".minecraft" and "saves" in parts[index + 1 :]:
            return True
    return False
