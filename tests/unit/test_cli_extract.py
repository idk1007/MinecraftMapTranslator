# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt extract` 的命令列外殼（M7.3）。

產出三個檔案，全部在 sandbox 底下、**與世界資料夾平行**——世界資料夾不多出任何東西，
「除了要改的地方以外什麼都沒動」才會是可以整包比對驗證的。
"""

import gzip
import json

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.cli.__main__ import main


def sign(*lines, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag([amulet_nbt.StringTag(l) for l in lines])
    tag["front_text"] = face
    return tag


def build_world(project, *, name="world"):
    world = project / "sandbox" / name
    root = modern_chunk(data_version=4671)
    entity = sign("歡迎光臨", "前方危險", "", "")
    root["block_entities"] = amulet_nbt.ListTag([entity])
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    data = amulet_nbt.CompoundTag()
    data["LevelName"] = amulet_nbt.StringTag(name)
    data["DataVersion"] = amulet_nbt.IntTag(4671)
    level = amulet_nbt.CompoundTag()
    level["Data"] = data
    (world / "level.dat").write_bytes(
        gzip.compress(amulet_nbt.NamedTag(level, "").save_to(compressed=False), mtime=0)
    )
    return world


def out_dir(project, name="world"):
    return project / "sandbox" / ".mcmt-out" / name


def test_extract_writes_three_files(project, capsys) -> None:
    world = build_world(project)

    code = main(["extract", str(world)])

    assert code == 0
    for filename in ("extract.json", "translations.zh_tw.json", "keymap.json"):
        assert (out_dir(project) / filename).is_file(), filename


def test_the_world_folder_gains_nothing(project) -> None:
    """產出與世界平行，不塞進世界裡。"""
    world = build_world(project)
    before = sorted(p.name for p in world.rglob("*"))

    main(["extract", str(world)])

    assert sorted(p.name for p in world.rglob("*")) == before


def test_the_translation_file_is_ready_to_edit(project) -> None:
    world = build_world(project)

    main(["extract", str(world)])

    document = json.loads(
        (out_dir(project) / "translations.zh_tw.json").read_text("utf-8")
    )
    sources = {e["source"] for e in document["entries"].values()}
    assert sources == {"歡迎光臨", "前方危險"}
    assert all(e["target"] == "" for e in document["entries"].values())


def test_the_report_says_what_it_found(project, capsys) -> None:
    world = build_world(project)

    main(["extract", str(world)])

    out = capsys.readouterr().out
    assert "2" in out  # 兩個單位
    assert "translations.zh_tw.json" in out


def test_a_custom_language_and_namespace_are_honoured(project) -> None:
    world = build_world(project)

    main(["extract", str(world), "--lang", "ja_jp", "--namespace", "mymap"])

    assert (out_dir(project) / "translations.ja_jp.json").is_file()
    extract = json.loads((out_dir(project) / "extract.json").read_text("utf-8"))
    assert extract["project"]["namespace"] == "mymap"
    assert extract["units"][0]["key"].startswith("mymap.")


def test_extracting_a_world_outside_the_sandbox_still_works(project) -> None:
    """讀取不限 sandbox（`doctor` 與 `extract` 都要讀 .minecraft），只有寫入限。"""
    world = build_world(project, name="outside")
    moved = project / "elsewhere"
    world.rename(moved)

    assert main(["extract", str(moved)]) == 0
    assert (project / "sandbox" / ".mcmt-out" / "elsewhere" / "extract.json").is_file()


def test_a_missing_world_exits_nonzero_without_a_traceback(project, capsys) -> None:
    code = main(["extract", str(project / "沒有這個世界")])

    assert code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_refusing_to_overwrite_without_replace(project, capsys) -> None:
    """辛苦翻了一半的檔案不該被重跑一次 extract 洗掉。"""
    world = build_world(project)
    main(["extract", str(world)])
    target = out_dir(project) / "translations.zh_tw.json"
    document = json.loads(target.read_text("utf-8"))
    first = next(iter(document["entries"]))
    document["entries"][first]["target"] = "我翻好的字"
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    code = main(["extract", str(world)])

    assert code == 2
    assert "--replace" in capsys.readouterr().err
    assert "我翻好的字" in target.read_text("utf-8")


def test_replace_overwrites(project) -> None:
    world = build_world(project)
    main(["extract", str(world)])

    assert main(["extract", str(world), "--replace"]) == 0
