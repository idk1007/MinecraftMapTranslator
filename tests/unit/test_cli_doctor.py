# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt doctor` 的命令列外殼。cli 只組裝，統計邏輯在 `mcmt.doctor`。"""

from conftest import RegionBuilder, legacy_chunk, modern_chunk, write_region_file

from mcmt.cli.__main__ import main


def build_world(tmp_path):
    world = tmp_path / "world"
    write_region_file(
        world / "region",
        RegionBuilder()
        .add_chunk_nbt(0, modern_chunk(data_version=4671))
        .add_chunk_nbt(1, modern_chunk(data_version=4556))
        .build(),
    )
    return world


def test_clean_world_exits_zero_and_prints_the_histograms(tmp_path, capsys) -> None:
    code = main(["doctor", str(build_world(tmp_path))])

    out = capsys.readouterr().out
    assert code == 0
    assert "4671" in out and "4556" in out
    assert "zlib" in out


def test_unsupported_world_exits_nonzero_and_says_why(tmp_path, capsys) -> None:
    world = build_world(tmp_path)
    write_region_file(
        world / "region",
        RegionBuilder().add_chunk_nbt(0, legacy_chunk()).build(),
        "r.0.1.mca",
    )

    code = main(["doctor", str(world)])

    out = capsys.readouterr().out
    assert code == 1
    assert "level_wrapper" in out


def test_missing_world_exits_nonzero_without_a_traceback(tmp_path, capsys) -> None:
    code = main(["doctor", str(tmp_path / "沒有這個世界")])

    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
