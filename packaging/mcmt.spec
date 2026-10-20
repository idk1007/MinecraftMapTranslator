# SPDX-License-Identifier: GPL-3.0-or-later
# PyInstaller 設定：一個資料夾、兩個執行檔，共用同一份 Python 與函式庫。
#
#   mcmt.exe      視窗版（console=False，不會跳黑色視窗）
#   mcmt-cli.exe  命令列版
#
# 刻意的選擇（已定案，見 docs/STATUS.md）：
# - 資料夾版不是單檔版：單檔版每次啟動都要先解壓到暫存資料夾，慢，也更容易被防毒誤判。
# - 關掉 UPX：壓縮過的執行檔是防毒誤報的常見原因，省下的空間不值得。
# - 帶 lz4：讀 LZ4 壓縮（type 4）的 chunk 要用；程式是執行期才 import，PyInstaller
#   看不到，要明講。
# 用 `python tools/build_exe.py` 建置，不要直接跑這個檔。

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
SRC = str(ROOT / "src")

common = dict(
    pathex=[SRC],
    datas=collect_data_files("mcmt"),  # fontdata/*.json（M8 的字寬量測表）
    hiddenimports=["lz4.block"],
    excludes=["pytest", "jsonschema", "referencing", "PyInstaller"],
)

gui = Analysis([str(ROOT / "packaging" / "entry_gui.py")], **common)
cli = Analysis([str(ROOT / "packaging" / "entry_cli.py")], **common)

gui_exe = EXE(
    PYZ(gui.pure),
    gui.scripts,
    [],
    exclude_binaries=True,
    name="mcmt",
    console=False,
    upx=False,
)
cli_exe = EXE(
    PYZ(cli.pure),
    cli.scripts,
    [],
    exclude_binaries=True,
    name="mcmt-cli",
    console=True,
    upx=False,
)

COLLECT(
    gui_exe,
    gui.binaries,
    gui.datas,
    cli_exe,
    cli.binaries,
    cli.datas,
    upx=False,
    name="mcmt",
)
