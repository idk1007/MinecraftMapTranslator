# SPDX-License-Identifier: GPL-3.0-or-later
"""建置可以發給別人的 Windows 版：資料夾版 zip ＋ SHA256 雜湊檔。

    .venv\\Scripts\\python tools\\build_exe.py

產出在 `dist/`：

    mcmt-<版本>-windows.zip          解壓縮後是一個資料夾，裡面有 mcmt.exe 與 mcmt-cli.exe
    mcmt-<版本>-windows.zip.sha256   `sha256sum -c` 讀得懂的格式，貼到 GitHub Releases

步驟：PyInstaller（`packaging/mcmt.spec`）→ 放進 LICENSE → 跑一次 `mcmt-cli.exe --help`
確認打包出來的東西真的能啟動 → 壓縮 → 算雜湊。上傳 Releases 由人自己做。

需要 PyInstaller（開發用，不是執行期相依）：`pip install pyinstaller`。
"""

import hashlib
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
SPEC = ROOT / "packaging" / "mcmt.spec"

# 試跑打包出來的 exe 會在旁邊建沙盒，裡面是地圖副本——絕不能跟著發出去。
_NEVER_SHIP = {"sandbox"}


def version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def run_pyinstaller() -> Path:
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"),
            str(SPEC),
        ],
        check=True,
    )
    bundle = BUILD / "dist" / "mcmt"
    shutil.copyfile(ROOT / "LICENSE", bundle / "LICENSE.txt")
    return bundle


def smoke_test(bundle: Path) -> None:
    """打包漏了模組時，PyInstaller 本身不會報錯，要到執行才炸。至少啟動一次。"""
    result = subprocess.run(
        [str(bundle / "mcmt-cli.exe"), "--help"], capture_output=True, timeout=120
    )
    if result.returncode != 0:
        raise SystemExit(
            f"mcmt-cli.exe --help 失敗（{result.returncode}）：\n"
            + result.stderr.decode("utf-8", "replace")
        )


def make_zip(bundle: Path, archive: Path) -> Path:
    """壓成 zip，裡面只有一個頂層資料夾（名字跟 zip 一樣），不含沙盒。"""
    top = archive.name.removesuffix(".zip")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle.rglob("*")):
            relative = path.relative_to(bundle)
            if relative.parts[0] in _NEVER_SHIP or not path.is_file():
                continue
            zf.write(path, f"{top}/{relative.as_posix()}")
    return archive


def write_checksum(archive: Path) -> Path:
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{digest.hexdigest()}  {archive.name}\n", encoding="ascii", newline="\n")
    return checksum


def main() -> int:
    bundle = run_pyinstaller()
    smoke_test(bundle)
    archive = make_zip(bundle, DIST / f"mcmt-{version()}-windows.zip")
    checksum = write_checksum(archive)
    print(f"\n完成：\n  {archive}\n  {checksum}")
    print(checksum.read_text(encoding="ascii"), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
