# SPDX-License-Identifier: GPL-3.0-or-later
"""打包的最後一步（`tools/build_exe.py`）：把 PyInstaller 的資料夾壓成 zip、算雜湊。

PyInstaller 本身要跑好幾分鐘，不放進單元測試；這裡只驗「發出去的那個 zip 長什麼樣」：
解壓縮後是**一個**資料夾（不會把幾百個檔案灑在使用者的下載資料夾），不會把開發時
留下的沙盒包進去（裡面是別人的地圖），雜湊檔的格式是 `sha256sum -c` 讀得懂的。
"""

import hashlib
import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_build_exe():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "tools" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_bundle(tmp_path):
    bundle = tmp_path / "dist" / "mcmt"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "mcmt.exe").write_bytes(b"gui")
    (bundle / "mcmt-cli.exe").write_bytes(b"cli")
    (bundle / "_internal" / "python311.dll").write_bytes(b"dll")
    (bundle / "sandbox" / "某張地圖").mkdir(parents=True)  # 試跑留下的
    (bundle / "sandbox" / "某張地圖" / "level.dat").write_bytes(b"map")
    return bundle


def test_the_zip_holds_one_top_folder_and_no_sandbox(tmp_path) -> None:
    build_exe = load_build_exe()
    bundle = fake_bundle(tmp_path)

    archive = build_exe.make_zip(bundle, tmp_path / "out" / "mcmt-0.1.0-windows.zip")

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert {name.split("/")[0] for name in names} == {"mcmt-0.1.0-windows"}
    assert "mcmt-0.1.0-windows/mcmt.exe" in names
    assert "mcmt-0.1.0-windows/_internal/python311.dll" in names
    assert not any("/sandbox/" in name or name.endswith("/sandbox") for name in names)


def test_the_checksum_file_matches_the_zip(tmp_path) -> None:
    build_exe = load_build_exe()
    archive = build_exe.make_zip(fake_bundle(tmp_path), tmp_path / "out" / "mcmt-0.1.0-windows.zip")

    checksum = build_exe.write_checksum(archive)

    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text(encoding="ascii") == f"{expected}  {archive.name}\n"
