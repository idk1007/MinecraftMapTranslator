# SPDX-License-Identifier: GPL-3.0-or-later
"""M12 自動化端到端：`sandbox import → extract → 填譯文 → apply`。

M11 那次完整來回是**手動跑的**，結論寫在 `docs/STATUS.md` 裡。手動跑過一次證明得了
「這條鏈通了」，證明不了「明天改完別的東西之後它還通」——而這條鏈橫跨掃描、規則、
key、後端、寫入、資源包六層，任何一層漂移都會讓它安靜地斷掉。

所以這份測試把那次來回釘住，而且**斷言到位元組層級**：改的地方改了，沒改的地方
連 timestamp 都一樣。

fixture 是 `TT_WORLD_NAME_PROBE`（本專案自建的探測世界）的 `r.0.0.mca` 前 30 個
chunk，外加兩張測試自己合成的檔案（`region/r.0.1.mca` 與 `entities/r.0.0.mca`）。

## 為什麼要湊滿四種組合

寫入層的分派有兩個維度，`node_path` 的最後一步（`key` / `index`）與 `value.kind`
（`literal` / translate key）。**四種組合都得走到，否則這份測試會漏掉一整格。**

M13a 之前它只有兩格：告示牌（index + translate key）與 `CustomName`（key + literal）。
那剛好是「key ⇒ in_place、index ⇒ translate key」這個假等價關係成立的兩格，所以
`apply.py` 依路徑形狀分派的缺陷這份測試一條都抓不到——直到 M13a 的物品掃描把另外
兩格帶進來，才在真實地圖上炸出 9 個被寫成 JSON 字串的草稿書頁與 3,788 個被拒寫的
物品名。**漏掉的那兩格不是巧合，是同一個錯誤假設的兩面。**

現在四格都在：

| | `literal` | translate key |
|---|---|---|
| `index` | 舊格式草稿書頁 `tag/pages/[i]` | 告示牌 `messages[i]`、`lore[i]` |
| `key` | `CustomName`、`title.raw`、`author` | 物品 `custom_name`/`item_name`、`entity_name`、`text_display`、`pages[].raw` |

合成的兩張檔案補的是探測世界沒有的東西：舊格式（1.20.5 之前的 `tag`）的物品，
以及 `entities/*.mca`。探測世界是在 1.21.11 裡蓋的，弄不出舊格式的物品。

> **不用語料地圖切 fixture**：那些是別人做的冒險地圖，放進要公開發布的 GPLv3 repo
> 等於重新散布別人的作品（見 M3 的同一條決定）。
"""

import json
import shutil
import zipfile
from pathlib import Path

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mcmt.cli.apply import run_apply
from mcmt.cli.extract import run_extract
from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import read_region
from mcmt.safety.paths import ensure_readable
from mcmt.sandbox import import_world

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "regions" / "tt-probe.r.0.0.slice.mca"
CONTRACTS = ROOT / "docs" / "contracts"

# fixture 裡唯一有方塊實體的 chunk。其餘 29 個必須一個位元都不變。
LIVE_CHUNK = 0

# 合成檔案裡「有東西要改」的那個 chunk；另一個是空的，必須原封不動。
SYNTHETIC_LIVE = 0
SYNTHETIC_DEAD = 1


@pytest.fixture(scope="module")
def validators():
    registry = Registry()
    schemas = {}
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text("utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        schemas[path.name.split(".")[0]] = schema
    return {
        name: Draft202012Validator(schema, registry=registry)
        for name, schema in schemas.items()
    }


def old_format_chest():
    """DV 3700 的箱子，裡面是**舊格式（1.20.5 之前的 `tag`）**的物品。

    [實測] `Arena of Darkness`（1.20.4）整張地圖都是這一套：`tag/display/Name` 3,696
    個、`tag/pages[]` 的草稿書 9 個。探測世界是在 1.21.11 裡蓋的，弄不出這種物品，
    所以合成一個。

    草稿書那一格是這份測試最重要的新東西：它的 `node_path` 以 `index` 結尾（`pages`
    是 String 的 list），而它的 strategy 是 `in_place`——**四種組合裡唯一會靜默把
    存檔寫壞的那一格**。
    """
    draft = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:writable_book")})
    draft["tag"] = amulet_nbt.CompoundTag(
        {
            "pages": amulet_nbt.ListTag(
                [
                    amulet_nbt.StringTag("TT_DRAFT_PAGE_1"),
                    amulet_nbt.StringTag("TT_DRAFT_PAGE_2"),
                ]
            )
        }
    )
    sword = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:diamond_sword")})
    sword["tag"] = amulet_nbt.CompoundTag(
        {
            "display": amulet_nbt.CompoundTag(
                {"Name": amulet_nbt.StringTag('{"text":"TT_OLD_ITEM_NAME"}')}
            )
        }
    )
    chest = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:chest")})
    for coordinate in ("x", "y", "z"):
        chest[coordinate] = amulet_nbt.IntTag(7)
    chest["Items"] = amulet_nbt.ListTag([draft, sword])
    return chest


def old_format_region():
    root = modern_chunk(data_version=3700)
    root["block_entities"] = amulet_nbt.ListTag([old_format_chest()])
    return (
        RegionBuilder()
        .add_chunk_nbt(SYNTHETIC_LIVE, root)
        .add_chunk_nbt(SYNTHETIC_DEAD, modern_chunk(data_version=3700))
        .build()
    )


def entities_region():
    """`entities/*.mca`：具名實體、`text_display`、展示框裡的物品。

    格式與 `region/` 完全一樣，所以這裡驗的不是「寫入器認不認得它」（它就是同一個），
    而是**整條鏈**——掃描找得到、指紋算得進去、apply 寫得回去、外科式保證仍然成立。
    """
    stand = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:armor_stand")})
    stand["CustomName"] = amulet_nbt.StringTag("TT_ENTITY_NAME")
    display = amulet_nbt.CompoundTag(
        {"id": amulet_nbt.StringTag("minecraft:text_display")}
    )
    display["text"] = amulet_nbt.CompoundTag(
        {"text": amulet_nbt.StringTag("TT_TEXT_DISPLAY")}
    )
    frame = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:item_frame")})
    frame["Item"] = amulet_nbt.CompoundTag(
        {
            "id": amulet_nbt.StringTag("minecraft:diamond"),
            "components": amulet_nbt.CompoundTag(
                {
                    "minecraft:custom_name": amulet_nbt.CompoundTag(
                        {"text": amulet_nbt.StringTag("TT_FRAME_ITEM_NAME")}
                    )
                }
            ),
        }
    )
    root = modern_chunk(data_version=4671)
    root["Entities"] = amulet_nbt.ListTag([stand, display, frame])
    return (
        RegionBuilder()
        .add_chunk_nbt(SYNTHETIC_LIVE, root)
        .add_chunk_nbt(SYNTHETIC_DEAD, modern_chunk(data_version=4671))
        .build()
    )


def _write_dat_raw(path: Path, tag: "amulet_nbt.CompoundTag") -> None:
    """`source_world` 建在 sandbox **之外**（見 fixture docstring），`write_dat`
    會強制過 `ensure_writable` 而在這裡炸掉——所以合成 fixture 檔案跟
    `write_region_file` 一樣繞過安全層直接寫位元組，只有這裡的測試 helper
    可以這樣做（真正的寫入路徑仍然一律走 `write_dat`）。"""
    import gzip

    import amulet_nbt as _nbt

    named = _nbt.NamedTag(tag, "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(named.save_to(compressed=False), mtime=0))


def level_dat_for(world: Path) -> None:
    """`LevelName`（in_place）+ `CustomBossEvents`（translate key）+
    `Player.Inventory`（走 `scan_item`）。"""
    import amulet_nbt

    sword = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:diamond_sword")})
    sword["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag("TT_INVENTORY_ITEM_NAME")}
    )
    events = amulet_nbt.CompoundTag(
        {"tt:probe": amulet_nbt.CompoundTag({"Name": amulet_nbt.StringTag("TT_BOSSBAR_NAME")})}
    )
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag("TT_LEVEL_NAME"),
            "DataVersion": amulet_nbt.IntTag(4671),
            "CustomBossEvents": events,
            "Player": amulet_nbt.CompoundTag(
                {"Inventory": amulet_nbt.ListTag([sword])}
            ),
        }
    )
    _write_dat_raw(world / "level.dat", amulet_nbt.CompoundTag({"Data": data}))


def scoreboard_dat_for(world: Path) -> None:
    import amulet_nbt

    data = amulet_nbt.CompoundTag(
        {
            "Objectives": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {
                            "Name": amulet_nbt.StringTag("obj"),
                            "CriteriaName": amulet_nbt.StringTag("dummy"),
                            "DisplayName": amulet_nbt.StringTag("TT_OBJECTIVE_NAME"),
                        }
                    )
                ]
            ),
            "Teams": amulet_nbt.ListTag(
                [
                    amulet_nbt.CompoundTag(
                        {
                            "Name": amulet_nbt.StringTag("team"),
                            "DisplayName": amulet_nbt.StringTag("TT_TEAM_NAME"),
                        }
                    )
                ]
            ),
        }
    )
    root = amulet_nbt.CompoundTag({"data": data, "DataVersion": amulet_nbt.IntTag(4671)})
    _write_dat_raw(world / "data" / "scoreboard.dat", root)


def datapack_for(world: Path) -> None:
    import json

    path = world / "datapacks" / "tt_probe" / "data" / "tt" / "advancement" / "quest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": "TT_ADVANCEMENT_TITLE", "description": "TT_ADVANCEMENT_DESC"}}),
        encoding="utf-8",
    )


@pytest.fixture
def source_world(project):
    """一個 sandbox **之外**的世界，模擬使用者的 `.minecraft/saves`。

    `sandbox import` 是唯一合法的入口，所以來源必須真的在外面——把它建在 sandbox
    裡再 import，測到的就不是那條路徑了。
    """
    world = project / "outside" / "TT_PROBE"
    (world / "region").mkdir(parents=True)
    shutil.copyfile(FIXTURE, world / "region" / "r.0.0.mca")
    write_region_file(world / "region", old_format_region(), "r.0.1.mca")
    write_region_file(world / "entities", entities_region(), "r.0.0.mca")
    level_dat_for(world)
    scoreboard_dat_for(world)
    datapack_for(world)
    return world


def chunks_of(world, name="r.0.0.mca", directory="region"):
    return {
        c.index: c for c in read_region(ensure_readable(world / directory / name))
    }


def nbt_of(chunk):
    data = decompress_chunk(
        chunk.payload, chunk.compression_type, chunk_index=chunk.index
    )
    return amulet_nbt.load(data, compressed=False).compound


def node_at(world, relative, chunk_index, *steps):
    """照 `node_path` 的形狀走到一個節點——`str` 是鍵、`int` 是索引。"""
    directory, name = relative.split("/")
    node = nbt_of(chunks_of(world, name, directory)[chunk_index])
    for step in steps:
        node = node[step]
    return node


def block_entities_of(world, chunk_index=LIVE_CHUNK):
    chunk = chunks_of(world)[chunk_index]
    data = decompress_chunk(
        chunk.payload, chunk.compression_type, chunk_index=chunk.index
    )
    return amulet_nbt.load(data, compressed=False).compound["block_entities"]


def fill(translations_path: Path, mapping: dict[str, str]) -> None:
    """模擬使用者用編輯器把 target 填上。**只碰 target**，其餘欄位不動。"""
    document = json.loads(translations_path.read_text("utf-8"))
    for entry in document["entries"].values():
        if entry["source"] in mapping:
            entry["target"] = mapping[entry["source"]]
    translated = sum(1 for e in document["entries"].values() if e["target"])
    document["stats"]["translated"] = translated
    document["stats"]["untranslated"] = document["stats"]["total"] - translated
    translations_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


TRANSLATIONS = {
    # key + literal（in_place：保留節點既有的形狀）
    "TT_CHEST_CUSTOM_NAME": "補給箱",
    "TT_CMDBLOCK_CUSTOM_NAME": "指令方塊",
    "TT_LECTERN_BOOK_TITLE": "講台上的書",
    "TT_LECTERN_AUTHOR": "作者",
    # index + literal（**M13a 之前這一格會被寫成 JSON 字串**）
    "TT_DRAFT_PAGE_1": "草稿第一頁",
    # key + translate key（**M13a 之前這一格整批被拒寫**）
    "TT_ITEM_CUSTOM_NAME": "鑽石劍",
    "TT_ITEM_NAME_COMPONENT": "石頭",
    "TT_OLD_ITEM_NAME": "舊格式物品名",
    "TT_ENTITY_NAME": "衛兵",
    "TT_TEXT_DISPLAY": "往這走",
    "TT_FRAME_ITEM_NAME": "展示的鑽石",
    "TT_LECTERN_PAGE_1": "講台第一頁",
    # index + translate key
    "TT_ITEM_LORE_1": "第一行說明",
    # level.dat / scoreboard.dat / datapack
    "TT_LEVEL_NAME": "探測世界",
    "TT_BOSSBAR_NAME": "頭目",
    "TT_INVENTORY_ITEM_NAME": "背包裡的劍",
    "TT_OBJECTIVE_NAME": "分數板",
    "TT_TEAM_NAME": "隊伍",
    "TT_ADVANCEMENT_TITLE": "進度標題",
    "TT_ADVANCEMENT_DESC": "進度描述",
}

# `TRANSLATIONS` 裡每一筆該落在哪一格。**測試自己驗這張表真的湊滿四格**，
# 不然哪天某個 category 的路徑形狀變了，這份測試會安靜地退回只測兩格。
EXPECTED_COMBINATIONS = {("key", "literal"), ("key", "translate"), ("index", "literal")}


@pytest.fixture
def round_trip(project, source_world):
    """走完一整趟，回傳每一段的產出。**這就是使用者手動做的那四步。**"""
    imported = import_world(source_world, name="probe")
    before = chunks_of(imported.target)
    old_before = chunks_of(imported.target, "r.0.1.mca")
    entities_before = chunks_of(imported.target, "r.0.0.mca", "entities")

    extract = run_extract(imported.target, language="zh_tw")
    translations_path = extract["translations_path"]

    sign_sources = [
        entry["source"]
        for entry in json.loads(translations_path.read_text("utf-8"))["entries"].values()
        if entry["source"] not in TRANSLATIONS
    ]
    mapping = dict(TRANSLATIONS)
    # 告示牌的原文是探測世界自己的字串，測試不該寫死它們——填一個看得出來的譯文
    # 就好，重點是「有翻的有寫、沒翻的沒寫」。
    for index, source in enumerate(sign_sources[:2]):
        mapping[source] = f"譯文{index}"
    fill(translations_path, mapping)

    # `extract.json` 就在待翻檔隔壁，`run_apply` 預設會去那裡找——這一步刻意不
    # 指定路徑，跑到的才是使用者真的會走的那條。
    applied = run_apply(imported.target, translations_path)
    return {
        "world": imported.target,
        "before": before,
        "old_before": old_before,
        "entities_before": entities_before,
        "extract": extract,
        "applied": applied,
        "mapping": mapping,
        "untranslated": sign_sources[2:],
    }


# --- 這條鏈通了 -----------------------------------------------------------


def test_the_whole_round_trip_writes_something(round_trip) -> None:
    counts = round_trip["applied"]["report"]["counts"]

    assert counts["edits_written"] > 0
    # 三張檔案各一個 chunk：探測世界的 r.0.0、舊格式的 r.0.1、entities 的 r.0.0。
    # chunks_touched 只算 region/entities chunk，不含 level.dat/scoreboard.dat/datapack。
    assert counts["chunks_touched"] == 3
    # 三張 region 檔 + level.dat + scoreboard.dat + 一個 advancement json。
    assert counts["files_rewritten"] == 6


def test_level_dat_scoreboard_and_datapack_are_all_written(round_trip) -> None:
    import json

    from mcmt.nbtio.datfile import read_dat
    from mcmt.safety.paths import ensure_readable

    world = round_trip["world"]
    level = read_dat(ensure_readable(world / "level.dat"))
    assert str(level.tag.compound["Data"]["LevelName"]) == "探測世界"

    # `Objectives[].DisplayName` 走 translate key，DV 4671（native）寫回的是
    # `{translate: key}` compound，不是裸字串。
    scoreboard = read_dat(ensure_readable(world / "data" / "scoreboard.dat"))
    objective_display = scoreboard.tag.compound["data"]["Objectives"][0]["DisplayName"]
    assert isinstance(objective_display, amulet_nbt.CompoundTag)
    assert str(objective_display["translate"]).startswith("mcmt.objective.")

    # advancement `display.title` 同樣走 translate key，寫回的是 Python dict
    # `{"translate": key}`，直接就是要 json.dump 出去的東西。
    advancement_path = world / "datapacks" / "tt_probe" / "data" / "tt" / "advancement" / "quest.json"
    document = json.loads(advancement_path.read_text("utf-8"))
    assert document["display"]["title"]["translate"].startswith("mcmt.advancement_title.")


def combinations_in(plan_document) -> set[tuple[str, str]]:
    """這份 plan 裡出現了哪些（路徑最後一步, value.kind）組合。"""
    return {
        (edit["node_path"][-1]["t"], edit["value"]["kind"])
        for edit in plan_document["edits"]
    }


def test_the_round_trip_actually_exercises_all_four_dispatch_combinations(
    round_trip,
) -> None:
    """**這份測試自己的守門。**

    M13a 之前它只走到四格裡的兩格，而那兩格剛好是「key ⇒ in_place、index ⇒
    translate key」這個假等價關係成立的兩格——所以 `apply.py` 依路徑形狀分派的缺陷
    它一條都抓不到。fixture 有一天被簡化、或某個 category 的路徑形狀變了，這條會先紅。
    """
    combinations = combinations_in(round_trip["applied"]["plan"].document)

    assert EXPECTED_COMBINATIONS <= combinations
    assert ("index", "translate") in combinations or (
        "index",
        "component",
    ) in combinations


def translate_keys_in(world) -> list[str]:
    return [
        str(message["translate"])
        for entity in block_entities_of(world)
        for face in ("front_text", "back_text")
        if isinstance(entity.get(face), amulet_nbt.CompoundTag)
        for message in entity[face]["messages"]
        if isinstance(message, amulet_nbt.CompoundTag) and "translate" in message
    ]


def test_a_sign_line_becomes_a_translate_component(round_trip) -> None:
    """translate key 路線：節點換成 `{translate: key}`，譯文住在資源包裡。"""
    keys = translate_keys_in(round_trip["world"])

    assert [k for k in keys if k.startswith("mcmt.")], "一個 translate 節點都沒寫進去"


def test_the_vanilla_key_already_in_the_world_is_not_touched(round_trip) -> None:
    """**沒有誤傷。** 探測世界本來就有一個原版 key 的節點。

    這條測試是 M11 遊戲實測那次肉眼確認的自動化版本。它一開始是紅的——第一版把
    「所有 translate 節點都該是 mcmt. 開頭」寫成斷言，等於要求我們去改一個沒被要求
    改的節點。斷言錯的方向剛好是最危險的那個方向，所以留一條測試守著它。
    """
    keys = translate_keys_in(round_trip["world"])

    assert "block.minecraft.diamond_block" in keys


def test_a_custom_name_gets_the_translation_itself(round_trip) -> None:
    """in_place 路線：[遊戲實測 M11-3] 這個欄位只吃字面文字。"""
    names = {
        str(entity["CustomName"])
        for entity in block_entities_of(round_trip["world"])
        if "CustomName" in entity
    }

    assert names == {"補給箱", "指令方塊"}


def test_a_custom_name_keeps_its_nbt_type(round_trip) -> None:
    """不把 `TAG_String` 提升成 compound——那個提升從沒進過遊戲。"""
    names = [
        entity["CustomName"]
        for entity in block_entities_of(round_trip["world"])
        if "CustomName" in entity
    ]

    assert names and all(isinstance(n, amulet_nbt.StringTag) for n in names)


def test_the_resource_pack_carries_no_in_place_translation(round_trip) -> None:
    """in_place 的譯文住在存檔裡，再往 lang 檔塞一份就是兩個真相來源。

    判準是 **category**（`strategy_for` 那份清單），不是「值長什麼樣」——四個
    in_place 的 category 一個都不該在 lang 檔裡出現。
    """
    from mcmt.model.strategy import IN_PLACE_CATEGORIES

    with zipfile.ZipFile(round_trip["world"] / "resources.zip") as archive:
        assert "pack.mcmeta" in archive.namelist()
        lang = json.loads(archive.read("assets/mcmt/lang/zh_tw.json"))

    assert lang, "lang 檔是空的"
    assert all(key.startswith("mcmt.") for key in lang)
    leaked = [
        key
        for key in lang
        if key.split(".")[1] in IN_PLACE_CATEGORIES
    ]

    assert leaked == []
    # 反面：translate key 那條路的譯文**必須**在 lang 檔裡，不然玩家什麼都看不到。
    assert "鑽石劍" in lang.values()
    assert "衛兵" in lang.values()


# --- M13a 補上的兩格 ------------------------------------------------------
#
# 這一節每一條都對應真實地圖上的一批 occurrence，而且每一條在修好之前都是紅的。


def draft_pages_of(world):
    return node_at(
        world, "region/r.0.1.mca", SYNTHETIC_LIVE,
        "block_entities", 0, "Items", 0, "tag", "pages",
    )


def test_a_draft_book_page_is_written_as_a_bare_string_not_json(round_trip) -> None:
    """**index + literal**：草稿書頁本來就是無包裝的純字串。

    修好之前這裡走的是 legacy 的 list writer，寫出來是 `'{"text":"草稿第一頁"}'`
    ——玩家打開草稿書看到的是字面的大括號。[實測] Arena of Darkness 有 9 個。
    """
    pages = draft_pages_of(round_trip["world"])

    assert isinstance(pages[0], amulet_nbt.StringTag)
    assert str(pages[0]) == "草稿第一頁"


def test_the_untranslated_draft_page_beside_it_is_untouched(round_trip) -> None:
    """沒被要求改的那一頁一個字都不能動——而且 list 不能被提升。"""
    pages = draft_pages_of(round_trip["world"])

    assert [str(page) for page in pages] == ["草稿第一頁", "TT_DRAFT_PAGE_2"]
    assert all(isinstance(page, amulet_nbt.StringTag) for page in pages)


def test_an_item_custom_name_becomes_a_translate_component(round_trip) -> None:
    """**key + translate key**：物品名吃 translate key，`CustomName` 不吃。

    修好之前這一整格走進 `in_place` 然後被拒寫，理由寫著「這個欄位不吃 translate
    key」——那句話對 `block_entity_name` 是對的，對物品名是假的。[實測] Arena of
    Darkness 3,788 個、100 Ways To Die 364 個 occurrence 全數落進 unwritten。
    """
    items = node_at(
        round_trip["world"], "region/r.0.0.mca", LIVE_CHUNK, "block_entities"
    )
    chest = next(item for item in items if str(item.get("id")) == "minecraft:chest")
    name = chest["Items"][0]["components"]["minecraft:custom_name"]

    assert isinstance(name, amulet_nbt.CompoundTag)
    assert str(name["translate"]).startswith("mcmt.custom_name.")


def test_an_old_format_item_name_becomes_a_json_translate_string(round_trip) -> None:
    """同一格在**舊世代**的 chunk 裡要寫 JSON 字串，不是 compound。

    key 結尾的節點過去只走 `in_place`，而 `in_place` 完全不看 DataVersion（它保留
    形狀）。translate key 這條路一接上，世代分派就得自己做。
    """
    name = node_at(
        round_trip["world"], "region/r.0.1.mca", SYNTHETIC_LIVE,
        "block_entities", 0, "Items", 1, "tag", "display", "Name",
    )

    assert isinstance(name, amulet_nbt.StringTag)
    assert json.loads(str(name))["translate"].startswith("mcmt.custom_name.")


def test_a_book_title_keeps_the_translation_itself(round_trip) -> None:
    """**key + literal**：`title.raw` 顯示的是原始 key，所以只能 in_place。"""
    items = node_at(
        round_trip["world"], "region/r.0.0.mca", LIVE_CHUNK, "block_entities"
    )
    lectern = next(item for item in items if str(item.get("id")) == "minecraft:lectern")
    book = lectern["Book"]["components"]["minecraft:written_book_content"]

    assert isinstance(book["title"]["raw"], amulet_nbt.StringTag)
    assert str(book["title"]["raw"]) == "講台上的書"
    # 同一本書的 `pages[].raw` 吃 translate key——那個不對稱正是 strategy 的依據。
    assert isinstance(book["pages"][0]["raw"], amulet_nbt.CompoundTag)


def test_no_edit_is_refused_for_an_unsupported_encoding(round_trip) -> None:
    """整份報告裡不該再有 `unsupported_encoding`。

    這是 F2 在真實地圖上的驗收條件的測試版：AoD 的 3,788 筆全是這個理由。
    """
    unwritten = round_trip["applied"]["report"]["unwritten"]

    assert [item for item in unwritten if item["reason"] == "unsupported_encoding"] == []


# --- entities/*.mca 走完整條鏈 --------------------------------------------


def entities_of(world):
    return node_at(world, "entities/r.0.0.mca", SYNTHETIC_LIVE, "Entities")


def test_an_entity_name_becomes_a_translate_component(round_trip) -> None:
    entities = entities_of(round_trip["world"])

    assert str(entities[0]["CustomName"]["translate"]).startswith("mcmt.entity_name.")


def test_a_text_display_and_an_item_in_a_frame_are_both_written(round_trip) -> None:
    """`text_display` 與展示框裡的物品都在 `entities/`，只掃 region 會整批漏掉。"""
    entities = entities_of(round_trip["world"])
    frame_name = entities[2]["Item"]["components"]["minecraft:custom_name"]

    assert str(entities[1]["text"]["translate"]).startswith("mcmt.text_display.")
    assert str(frame_name["translate"]).startswith("mcmt.custom_name.")


def test_the_untouched_entities_chunk_is_byte_identical(round_trip) -> None:
    """外科式保證在 `entities/` 一樣成立——它走的就是同一個 `write_region`。"""
    before = round_trip["entities_before"]
    after = chunks_of(round_trip["world"], "r.0.0.mca", "entities")

    assert set(after) == set(before)
    assert after[SYNTHETIC_DEAD].payload == before[SYNTHETIC_DEAD].payload
    assert after[SYNTHETIC_DEAD].timestamp == before[SYNTHETIC_DEAD].timestamp
    assert after[SYNTHETIC_LIVE].payload != before[SYNTHETIC_LIVE].payload


def test_the_untouched_old_format_chunk_is_byte_identical(round_trip) -> None:
    before = round_trip["old_before"]
    after = chunks_of(round_trip["world"], "r.0.1.mca")

    assert after[SYNTHETIC_DEAD].payload == before[SYNTHETIC_DEAD].payload
    assert after[SYNTHETIC_DEAD].timestamp == before[SYNTHETIC_DEAD].timestamp


def test_the_old_format_chunk_is_not_upgraded(round_trip) -> None:
    """工具永不升級格式——DV 3700 的 chunk 寫回去還是 3700。"""
    root = nbt_of(chunks_of(round_trip["world"], "r.0.1.mca")[SYNTHETIC_LIVE])

    assert int(root["DataVersion"]) == 3700


# --- 外科式寫入：斷言到位元組 ---------------------------------------------


def test_every_untouched_chunk_is_byte_identical(round_trip) -> None:
    """沒被要求改的 chunk，一個位元都不能動。

    **但這一條單獨不夠**，而那件事是寫這份測試時用突變確認的：把 `apply.py` 改成
    「每個 chunk 都解碼再編碼」之後，這條測試**仍然是綠的**——正是 `SPIKE_RESULT.md`
    的 L2 說的那個巧合，Python `zlib.compress()` 的預設等級恰好與 Mojang 的
    `Deflater` 相同，所以重新壓縮出來的位元組一模一樣。

    抓得到那個突變的是 timestamp 那條：`ChunkWrite.unchanged` 帶著磁碟上的原始
    時間戳，`ChunkWrite.replaced` 蓋上當下時間，所以「有沒有走原封複製那條路」在
    磁碟上留得下痕跡，而位元組留不下。外科式寫入的保證不能靠 L2 的巧合，測試也不能。
    """
    before = round_trip["before"]
    after = chunks_of(round_trip["world"])

    assert set(after) == set(before)
    differing = [i for i in before if after[i].payload != before[i].payload]

    assert differing == [LIVE_CHUNK]


def test_the_report_counts_every_untouched_chunk_as_copied_verbatim(round_trip) -> None:
    """**外科式寫入的機器可檢查形式**（CLAUDE.md §1.4）。

    這條綁的是**報告與現實一致**：使用者看到「原封複製 29 個」時，那 29 真的是這張
    region 裡沒被改到的全部。它是計數器，不是磁碟上的事實——真正證明路徑的是上面
    那條 timestamp。兩者一起看才完整：一個管「做對了」，一個管「說的和做的一樣」。
    """
    counts = round_trip["applied"]["report"]["counts"]

    # 探測世界的 29 個，加上兩張合成檔案各自那個空的 chunk。
    assert counts["chunks_copied_verbatim"] == len(round_trip["before"]) - 1 + 2


def test_every_untouched_chunk_keeps_its_timestamp(round_trip) -> None:
    """整表歸零會讓遊戲誤判所有 chunk 都是新的；整表沿用會讓被改的帶著舊時間。"""
    before = round_trip["before"]
    after = chunks_of(round_trip["world"])

    stale = [i for i in before if i != LIVE_CHUNK and after[i].timestamp != before[i].timestamp]

    assert stale == []


def test_the_touched_chunk_keeps_its_compression_type(round_trip) -> None:
    """讀什麼世代寫什麼世代——壓縮類型也一樣，不順手升級。"""
    before = round_trip["before"]
    after = chunks_of(round_trip["world"])

    assert after[LIVE_CHUNK].compression_type == before[LIVE_CHUNK].compression_type


def test_the_data_version_is_not_upgraded(round_trip) -> None:
    """工具永不升級格式。"""
    chunk = chunks_of(round_trip["world"])[LIVE_CHUNK]
    root = amulet_nbt.load(
        decompress_chunk(chunk.payload, chunk.compression_type, chunk_index=chunk.index),
        compressed=False,
    ).compound

    assert int(root["DataVersion"]) == 4671


def test_the_untranslated_units_are_reported_not_silently_dropped(round_trip) -> None:
    """「還沒翻」與「刻意不翻」在報告裡要分得開，而且都不能安靜地消失。"""
    unwritten = round_trip["applied"]["plan"].document["unwritten"]
    reasons = {item["reason"] for item in unwritten}

    assert reasons == {"untranslated"}
    assert len(unwritten) == len(round_trip["untranslated"])


# --- 安全網 ---------------------------------------------------------------


def test_the_backup_exists_and_holds_the_region_file(round_trip) -> None:
    backup = round_trip["applied"]["report"]["backup"]

    assert backup is not None
    assert backup["file_count"] >= 1
    assert (Path(backup["directory"])).exists()


def test_the_world_fingerprint_changes(round_trip) -> None:
    world = round_trip["applied"]["report"]["world"]

    assert world["world_fingerprint_before"] != world["world_fingerprint_after"]


def test_the_apply_report_validates_against_the_schema(round_trip, validators) -> None:
    errors = sorted(
        validators["apply_report"].iter_errors(round_trip["applied"]["report"]), key=str
    )

    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def test_the_extract_validates_against_the_schema(round_trip, validators) -> None:
    document = json.loads(
        (Path(round_trip["extract"]["out"]) / "extract.json").read_text("utf-8")
    )
    errors = sorted(validators["extract"].iter_errors(document), key=str)

    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def written_encoding(edit) -> str:
    """這一筆寫下去之後，嗅探器會把節點判成哪一種形狀。

    這就是 `apply.py` 的分派表倒過來看：`literal` 走 `in_place`（**定義上保留形狀**），
    非 literal 依 chunk 的世代寫 JSON 物件字串或 compound。
    """
    from mcmt.model.generation import generation_of

    if edit["value"]["kind"] == "literal":
        return edit["expected_encoding"]
    # datapack advancement JSON 沒有 chunk 世代這回事——`container.data_version`
    # 合法地是 `None`（見 `scan/sources/datapack.py`），寫進去的一律是純 Python
    # dict（`{"translate": key}`），對應 `datapack_apply.py` 的 `_sniff_json_value`
    # 判成 `compound_tree`，不走 legacy/native 二分。
    if edit["container"]["kind"] == "datapack_file":
        return "compound_tree"
    if generation_of(edit["container"]["data_version"]).legacy_json_is_content:
        return "json_string_object"
    return "compound_tree"


def shape_changing(edit) -> bool:
    """這一筆寫下去會不會**改變**節點的形狀——也就是守門在重放時看不看得見。

    三種寫入是形狀保留的，全都逃得過守門：`in_place`、舊世代把 JSON 物件字串換成
    另一個 JSON 物件字串、以及 native 把一棵 `compound_tree` 換成另一棵。
    """
    return written_encoding(edit) != edit["expected_encoding"]


def test_replaying_the_same_plan_is_refused_wherever_the_write_changed_the_shape(
    round_trip,
) -> None:
    """[遊戲實測 M4-4] 世界在 extract 之後被改過，形狀就對不上了。

    這裡「被改過」的是我們自己剛剛寫的那一次——守門分不出也不該分出是誰改的。

    **這條測試在 M13a 換了判準，而換的理由本身是結論。** 原本它斷言「每一筆非
    literal 的 edit 都會被擋下」，那在只有 native 告示牌的 fixture 上成立。加進舊格式
    的物品之後不成立了：舊世代的 translate key 寫的是 JSON 字串，而它原本就是 JSON
    字串，**形狀沒變，守門看不見**。

    所以守門真正的判準從來不是「這是不是 translate key」，是「寫入有沒有改變形狀」。
    那條界線與 `test_an_in_place_replay_is_idempotent_and_the_guard_cannot_see_it`
    釘住的是同一個缺口的兩半，兩條都在等 `occurrence.raw_snapshot` 接上。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    changing = [e for e in plan["edits"] if shape_changing(e)]
    outcome = apply_editplan(round_trip["world"], plan)

    assert changing, "這趟來回沒有任何會改變形狀的寫入，測試沒驗到東西"
    assert {item["reason"] for item in outcome.unwritten} == {"node_changed"}
    assert len(outcome.unwritten) == len(changing)


def test_an_in_place_replay_is_idempotent_and_the_guard_cannot_see_it(round_trip) -> None:
    """**一個誠實的缺口，寫成測試而不是註解。**

    `in_place` **保留節點的形狀**，所以寫完之後 `expected_encoding` 仍然對得上，
    重放會再寫一次同樣的值。內容上那是 no-op，沒有損害。

    但同一個機制也代表：使用者若在 extract 之後**自己**把箱子改名（形狀不變、只有
    字變了），`expected_encoding` 守門看不出來，apply 會蓋掉他的改名。合約裡的
    `occurrence.raw_snapshot` 正是為這件事準備的欄位，目前一律是 null、還沒有人用。

    這條測試不是在慶祝現況，是在把缺口釘在一個會被讀到的地方——哪天 raw_snapshot
    接上去，它會變紅，而那時該改的是這條測試。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    shape_preserving = [e for e in plan["edits"] if not shape_changing(e)]
    in_place_edits = [e for e in plan["edits"] if e["value"]["kind"] == "literal"]
    outcome = apply_editplan(round_trip["world"], plan)

    assert in_place_edits, "這趟來回沒有走到 in_place 路徑，測試沒驗到東西"
    assert outcome.counts["edits_written"] == len(shape_preserving)
    assert {
        str(entity["CustomName"])
        for entity in block_entities_of(round_trip["world"])
        if "CustomName" in entity
    } == {"補給箱", "指令方塊"}


# --- dry-run 完全不碰存檔 -------------------------------------------------


def test_dry_run_changes_nothing_on_disk(project, source_world) -> None:
    imported = import_world(source_world, name="dry")
    before = chunks_of(imported.target)

    extract = run_extract(imported.target, language="zh_tw")
    fill(extract["translations_path"], TRANSLATIONS)
    applied = run_apply(
        imported.target, extract["translations_path"], dry_run=True
    )

    after = chunks_of(imported.target)
    assert all(after[i].payload == before[i].payload for i in before)
    assert applied["report"]["outcome"] == "dry_run"
    assert not (imported.target / "resources.zip").exists()
