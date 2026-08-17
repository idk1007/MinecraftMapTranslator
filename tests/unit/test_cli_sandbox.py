# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt sandbox import` 的命令列外殼。"""

from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.cli.__main__ import main


def build_source(project):
    world = project / "saves" / "world"
    write_region_file(
        world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
    )
    (world / "level.dat").write_bytes(b"x")
    return world


def test_import_copies_and_reports_where_it_went(project, capsys) -> None:
    code = main(["sandbox", "import", str(build_source(project))])

    out = capsys.readouterr().out
    assert code == 0
    assert (project / "sandbox" / "world" / "level.dat").exists()
    assert str(project / "sandbox" / "world") in out
    assert "blake2b:" in out


def test_importing_over_an_existing_world_exits_nonzero(project, capsys) -> None:
    source = build_source(project)
    main(["sandbox", "import", str(source)])

    code = main(["sandbox", "import", str(source)])

    assert code == 2
    assert "--replace" in capsys.readouterr().err


def test_replace_is_accepted(project) -> None:
    source = build_source(project)
    main(["sandbox", "import", str(source)])

    assert main(["sandbox", "import", str(source), "--replace"]) == 0


def test_a_source_that_is_not_a_world_exits_nonzero(project, capsys) -> None:
    (project / "nope").mkdir()

    code = main(["sandbox", "import", str(project / "nope")])

    assert code == 2
    assert "Traceback" not in capsys.readouterr().err
