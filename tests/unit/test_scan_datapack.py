# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 掃描（M13.7）。

[實測 2026-08-22] `Arena of Darkness` 用**複數** `advancements/`（1.20.4 舊式目錄
名）且是 **zip 檔**（`datapacks/ArenaOfDarknessDatapack_10_15.zip` 裡有 25 個
`data/worf/advancements/*.json`）。這份測試涵蓋資料夾 + zip、單數 + 複數四種組合
中真實會出現的那些。
"""

import json
import zipfile
from collections import Counter

from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources import datapack


def write_advancement(path, *, title="標題", description="描述"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": title, "description": description}}),
        encoding="utf-8",
    )


def test_a_folder_datapack_with_the_singular_directory_name_is_found(tmp_path) -> None:
    write_advancement(
        tmp_path / "datapacks" / "mypack" / "data" / "myns" / "advancement" / "quest1.json",
        title="第一個任務",
        description="打敗史萊姆",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    found = list(datapack.scan(world, stats))
    by_category = {n.node.category: str(n.node.tag) for n in found}

    assert by_category["advancement_title"] == "第一個任務"
    assert by_category["advancement_description"] == "打敗史萊姆"


def test_a_folder_datapack_with_the_plural_directory_name_is_found(tmp_path) -> None:
    """[實測] 1.20.4 及以前是複數 `advancements/`——`Arena of Darkness` 用的就是這個。"""
    write_advancement(
        tmp_path / "datapacks" / "oldpack" / "data" / "worf" / "advancements" / "barosa.json",
        title="The Prelude",
        description="Defeat Barosa... for now.",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    found = list(datapack.scan(world, stats))
    by_category = {n.node.category: str(n.node.tag) for n in found}

    assert by_category["advancement_title"] == "The Prelude"


def test_a_zip_datapack_is_found(tmp_path) -> None:
    """[實測] `Arena of Darkness` 的資料包是 zip，不是資料夾。"""
    zip_path = tmp_path / "datapacks" / "mypack.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/myns/advancement/quest1.json",
            json.dumps({"display": {"title": "壓縮包裡的任務"}}),
        )
    world = ensure_readable(tmp_path)
    stats = Counter()

    found = [n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"]

    assert len(found) == 1
    assert str(found[0].tag) == "壓縮包裡的任務"


def test_the_container_path_identifies_the_zip_and_the_entry(tmp_path) -> None:
    zip_path = tmp_path / "datapacks" / "mypack.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/myns/advancement/quest1.json",
            json.dumps({"display": {"title": "任務"}}),
        )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (first, *_) = list(datapack.scan(world, stats))

    assert first.container["kind"] == "datapack_file"
    assert first.container["path"] == "datapacks/mypack.zip/data/myns/advancement/quest1.json"
    assert first.container["data_version"] is None


def test_a_bare_string_title_is_yielded_as_a_string_tag(tmp_path) -> None:
    import amulet_nbt

    write_advancement(
        tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json",
        title="裸字串標題",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (title,) = [
        n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"
    ]

    assert isinstance(title.tag, amulet_nbt.StringTag)


def test_a_component_shaped_title_is_yielded_as_a_compound_tag(tmp_path) -> None:
    import amulet_nbt

    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": {"text": "帶格式的標題", "color": "gold"}}}),
        encoding="utf-8",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (title,) = [
        n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"
    ]

    assert isinstance(title.tag, amulet_nbt.CompoundTag)
    assert str(title.tag["text"]) == "帶格式的標題"


def test_an_advancement_without_display_yields_nothing(tmp_path) -> None:
    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"parent": "n:other", "criteria": {}}), encoding="utf-8")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []


def test_malformed_json_is_counted_not_fatal(tmp_path) -> None:
    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "broken.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []
    assert stats["skipped_advancement_unparseable"] == 1


def test_no_datapacks_directory_yields_nothing(tmp_path) -> None:
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []


def test_a_heterogeneous_component_array_title_does_not_crash(tmp_path) -> None:
    """Minecraft 官方文字 component 陣列語法 `["", {...}]`：第一個元素是裸
    字串父級，其餘是物件 extra——`_to_amulet()` 的 list 分支若天真地逐元素轉換
    再塞進 `ListTag`，會在建構當下炸掉（`amulet_nbt.ListTag` 要求同一 NBT
    型別）。這裡驗證同質化升格後不會炸，且攤平出的內容正確。"""
    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"display": {"title": ["", {"text": "Bold Part", "bold": True}]}}
        ),
        encoding="utf-8",
    )
    world = ensure_readable(tmp_path)
    stats = Counter()

    (title,) = [
        n.node for n in datapack.scan(world, stats) if n.node.category == "advancement_title"
    ]

    from mcmt.model.component import sniff
    from mcmt.model.segments import flatten

    shape = sniff(title.tag)
    assert shape.encoding.value == "compound_tree"

    def _plain(tag):
        import amulet_nbt

        if isinstance(tag, amulet_nbt.StringTag):
            return str(tag)
        if isinstance(tag, amulet_nbt.CompoundTag):
            return {str(k): _plain(v) for k, v in tag.items()}
        if isinstance(tag, amulet_nbt.ListTag):
            return [_plain(v) for v in tag]
        return str(tag)

    flattened = flatten(_plain(title.tag))
    assert "Bold Part" in flattened.plain


def test_a_non_advancement_file_in_the_pack_is_ignored(tmp_path) -> None:
    """白名單只找 `advancement(s)/*.json`，資料包裡其餘的東西（`function/`、
    `loot_table/`、`pack.mcmeta`……）連碰都不碰。"""
    base = tmp_path / "datapacks" / "p" / "data" / "n"
    (base / "function").mkdir(parents=True)
    (base / "function" / "hello.mcfunction").write_text("say hi", encoding="utf-8")
    (tmp_path / "datapacks" / "p" / "pack.mcmeta").write_text('{"pack":{}}', encoding="utf-8")
    world = ensure_readable(tmp_path)
    stats = Counter()

    assert list(datapack.scan(world, stats)) == []
