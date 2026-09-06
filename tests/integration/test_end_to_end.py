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
from conftest import (
    RegionBuilder,
    assert_command_reparses,
    modern_chunk,
    write_region_file,
)
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


# **L2 巢狀 SNBT**：`data merge` 目標告示牌，`front_text.messages[0]` 是**原生**
# SNBT compound（`{text:"..."}`）——CLAUDE.md 四節 SPIKE_RESULT.md 那個
# `Minecraft Party 2` 的 `Star Stealer` 例子就是這個形狀：「指令內含 NBT、NBT
# 內含 component」。其餘三行是空字串，沒有可翻文字（計入 `skipped_empty`）。
# 指令方塊礦車（`command_block_minecart`）的 `Command` 走的是跟一般指令方塊
# 完全一樣的 `scan_command_string`，放進 `entities/` 而不是 `region/`，剛好
# 順便驗到 entities 容器這一側。
#
# **這裡刻意不用「字串包裝 JSON」的訊息形狀**（單引號或雙引號字串常值包一段
# 轉義過的 JSON，例如 MP2 語料裡 `'""'` 那種）——Task 11 過這條端到端鏈路時
# 發現 `write/common.py::_decode_command_leaf` 對這個子形狀的重新解碼是壞的
# （見下面 `test_a_json_string_wrapped_merge_message_is_a_known_write_gap`），
# 用它會讓這裡的 fixture 帶著一個目前寫不進去的 edit，把本來要驗證「L2 這格
# 能走通」的測試變成在驗證一個已知缺口。
CMD_L2_MERGE = (
    "data merge block ~ ~-1 ~-1 {front_text:{messages:["
    '{text:"TT_CMDBLOCK_MERGE_TEXT"},{text:""},{text:""},{text:""}'
    "]}}"
)

# **L2 裸字串訊息**：同樣是 `data merge` 目標告示牌，但四個 `messages[]` 元素
# 都是**純字串**，不是 compound——`data merge` 直接寫一句沒有格式的文字，一行字
# ＋三行空，是最常見的告示牌形狀。
#
# 這一格（2026-09-06 的 C2）跟上面那個只差在元素型別，而那個差別決定了寫回去的
# 方式完全不同：`TAG_List` 在 NBT 格式層帶單一元素型別 id，所以這一行**不能**
# 換成 `{translate:…}` compound（會變成遊戲解析不了的異質 list，指令方塊寫得進
# 磁碟卻再也跑不動，報告還說 `unwritten: []`）。它走 in_place，只換掉字串常值的
# 內容。少了這格 fixture，`("entities_chunk","snbt","literal")` 這個 dispatch
# 組合在端到端一次都不會被走到——正是 CLAUDE.md 五節說的「擴大範圍時要列出新的
# **組合**，不是只列新的項目」。
CMD_L2_MERGE_BARE = (
    "data merge block ~ ~-2 ~-1 {front_text:{messages:["
    '"TT_CMDBLOCK_MERGE_BARE_TEXT","","",""'
    "]}}"
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
    minecart = amulet_nbt.CompoundTag(
        {"id": amulet_nbt.StringTag("minecraft:command_block_minecart")}
    )
    minecart["Command"] = amulet_nbt.StringTag(CMD_L2_MERGE)
    bare_minecart = amulet_nbt.CompoundTag(
        {"id": amulet_nbt.StringTag("minecraft:command_block_minecart")}
    )
    bare_minecart["Command"] = amulet_nbt.StringTag(CMD_L2_MERGE_BARE)
    root = modern_chunk(data_version=4671)
    # **新的實體一律往後加。** 上面幾條測試用位置索引（`entities[0]`、`[1]`、
    # `[2]`）取節點，插在中間會讓它們安靜地驗到別的東西。
    root["Entities"] = amulet_nbt.ListTag(
        [stand, display, frame, minecart, bare_minecart]
    )
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


def mcfunction_for(world: Path) -> None:
    """`datapacks/tt_probe/data/tt/function/hello.mcfunction`——同一個 pack，同一套
    白名單動詞解析（`scan/command.py`），只是物理字串單位換成整行而非 `Command`
    欄位。一行 `say`（in_place）＋一行 `tellraw`（translate key）湊滿
    `datapack_mcfunction_file` 那兩格 dispatch 組合。"""
    path = world / "datapacks" / "tt_probe" / "data" / "tt" / "function" / "hello.mcfunction"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "say TT_MCFUNCTION_SAY_TEXT\n"
        'tellraw @a {"text":"TT_MCFUNCTION_TELLRAW_TEXT"}\n',
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
    mcfunction_for(world)
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
    # 指令方塊（Task 11：command_say_text 走 in_place，其餘走 translate key）
    "TT_CMDBLOCK_SAY_TEXT": "指令說話文字",
    "TT_CMDBLOCK_TELLRAW_TEXT": "指令提示文字",
    "TT_CMDBLOCK_TITLE_TEXT": "指令標題文字",
    # `TT_CMDBLOCK_NESTED_ITEM_NAME`（`give` 的巢狀 `minecraft:custom_name`）
    # 刻意不填——它目前整批被 `scan/command.py` 跳過，見
    # `test_a_give_commands_namespaced_component_is_a_known_scan_gap`。
    # L2 巢狀 SNBT（`data merge` 目標告示牌的原生 compound 訊息）
    "TT_CMDBLOCK_MERGE_TEXT": "合併寫入的告示牌文字",
    # L2 裸字串訊息（C2：走 in_place，list 維持全字串）
    "TT_CMDBLOCK_MERGE_BARE_TEXT": "裸字串告示牌文字",
    # datapack `.mcfunction`
    "TT_MCFUNCTION_SAY_TEXT": "腳本說話文字",
    "TT_MCFUNCTION_TELLRAW_TEXT": "腳本提示文字",
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
    # 三張 region 檔 + level.dat + scoreboard.dat + 一個 advancement json + 兩行
    # `.mcfunction`。`apply_editplan` 依 `container.path` 分組，`.mcfunction`
    # 的 `container.path` 帶行號後綴（`hello.mcfunction:1`／`:2`），同一個實體
    # 檔案的兩行各自算一次 `files_rewritten`——這不是重複寫入同一份資料，是
    # 這個計數器的既有定義（見 `scan/sources/mcfunction.py::_container`）。
    assert counts["files_rewritten"] == 8


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


# --- 指令文字（Task 11：command-block / .mcfunction 五種新 dispatch 組合）---
#
# 這一節對應 docs/superpowers/specs/2026-09-05-command-text-design.md §9.1
# 的五行表格。掃描本身（Task 6/9）與寫入本身（Task 7/8/10）在各自的單元測試
# 裡都已經測過；這裡驗的是**接上 `_WRITERS`／`scan/registry.py` 之後，整條鏈
# 真的把這五格都走過一次**——不是「沒有 crash」，是實際寫回去的文字內容對、
# 動詞前綴沒被吃掉。


def commands_of(world):
    """`region/r.0.0.mca`（真實探測世界切片）`LIVE_CHUNK` 裡指令方塊的
    `Command` 字串——`say`（in_place）、`tellraw`／`title`（L1 translate key）
    已經是這張 fixture 原本就帶的，見 SPIKE_RESULT.md。（fixture 還有第四個
    `give` 指令方塊，見下面 `test_a_give_commands_namespaced_component_is_a_known_scan_gap`。）
    """
    return [
        str(entity["Command"])
        for entity in block_entities_of(world)
        if "Command" in entity
    ]


def test_a_command_block_say_line_keeps_its_verb_prefix(round_trip) -> None:
    """**region chunk × in_place（say/me）。** `command_say_text` 沒有 component
    語法可插 key，只能直接替換文字——`say ` 前綴不能被一起換掉。"""
    commands = commands_of(round_trip["world"])
    say_commands = [c for c in commands if c.startswith("say ")]

    assert say_commands == ["say 指令說話文字"]


def test_a_command_block_tellraw_line_becomes_a_translate_component(round_trip) -> None:
    """**region chunk × translate key（L1）。** `tellraw` 的 JSON 引數換成
    `{"translate": key}`，譯文住資源包，`tellraw @a ` 前綴原封不動。"""
    commands = commands_of(round_trip["world"])
    (tellraw,) = [c for c in commands if c.startswith("tellraw @a ")]

    assert tellraw.startswith("tellraw @a ")
    payload = json.loads(tellraw[len("tellraw @a ") :])
    assert payload["translate"].startswith("mcmt.")


def test_a_give_commands_namespaced_component_is_a_known_scan_gap(round_trip) -> None:
    """**已知缺口，Task 11 端到端才照出來，不在本任務授權修改的檔案清單裡。**

    這張 fixture 第四個指令方塊是 `give @s minecraft:stone[minecraft:custom_name=
    {text:"..."}]`——1.20.5+ 的物品組件語法本身帶 `minecraft:` 命名空間，這正是
    SPIKE_RESULT.md 記錄的真實樣本形狀。但 `scan/command.py::_find_component`
    拿字面 `"custom_name"`（沒有命名空間）去跟組件鍵比對，永遠比不到帶命名空間
    的鍵，於是 `stats["skipped_command_unsupported_shape"]` 加一、整條指令一個
    字都沒被抽出來——`tests/unit/test_scan_command.py::test_give_finds_the_custom_name_component`
    用的組件鍵剛好沒帶命名空間，繞過了這個問題，所以單元測試層級一直是綠的。

    這裡釘住現狀（`give` 的 `custom_name` 進不了待翻檔，也就不會被翻譯），
    不是慶祝現況——這是需要一個後續任務去修 `scan/command.py::_find_component`
    的真實缺口（多接受一個帶命名空間的鍵，或比對時忽略命名空間前綴）。
    """
    commands = commands_of(round_trip["world"])
    (give,) = [c for c in commands if c.startswith("give @s ")]

    assert "TT_CMDBLOCK_NESTED_ITEM_NAME" in give
    assert "mcmt." not in give


def test_a_command_block_minecart_merge_writes_the_nested_snbt_message(round_trip) -> None:
    """**entities chunk × translate key（L2 巢狀 SNBT，原生 compound 訊息）。**

    `data merge` 目標告示牌 `front_text.messages[0]` 是原生 SNBT compound
    （`{text:"..."}`）——指令字串包 SNBT、SNBT 裡又包一棵 component 樹，跟
    SPIKE_RESULT.md『Minecraft Party 2』的 `Star Stealer` 例子同一個形狀。其餘
    三行是空字串，沒有可翻文字，維持原樣。
    """
    entities = entities_of(round_trip["world"])
    minecart = next(
        e for e in entities if str(e.get("id")) == "minecraft:command_block_minecart"
    )
    command = str(minecart["Command"])

    assert command.startswith("data merge block ~ ~-1 ~-1 {front_text:{messages:[")
    arg = command[command.index("{") :]
    document = amulet_nbt.from_snbt(arg)
    messages = document["front_text"]["messages"]

    assert str(messages[0]["translate"]).startswith("mcmt.")
    assert [str(m.get("text", "")) for m in messages[1:]] == ["", "", ""]


def test_a_bare_string_merge_message_is_written_in_place_and_stays_a_string(
    round_trip,
) -> None:
    """**entities chunk × in_place（L2 裸字串訊息）。** C2 的端到端版本。

    `data merge` 的訊息是純字串時，四個 `messages[]` 元素都是字串——`TAG_List`
    在格式層帶單一元素型別 id，所以這一行**只能**換掉字串常值的內容，不能換成
    `{translate:…}` compound。修好之前這裡寫出去的是異質 list，`amulet_nbt.
    from_snbt` 與遊戲的指令解析器都吃不下，而 `apply_report` 說 `unwritten: []`。

    在地化的譯文住在存檔裡（in_place），不在資源包的 lang 檔裡——這也是為什麼
    這條測試直接讀指令字串本身，而不是去翻 lang 檔。
    """
    entities = entities_of(round_trip["world"])
    (command,) = [
        str(e["Command"])
        for e in entities
        if "Command" in e and "messages:[\"" in str(e["Command"])
    ]

    assert_command_reparses(command)
    document = amulet_nbt.from_snbt(command[command.index("{") :])
    messages = document["front_text"]["messages"]

    assert all(isinstance(m, amulet_nbt.StringTag) for m in messages)
    assert [str(m) for m in messages] == ["裸字串告示牌文字", "", "", ""]


def all_commands_in(world) -> list[str]:
    """整個世界寫回去之後，磁碟上每一條被我們碰得到的指令文字——指令方塊、
    指令方塊礦車、`.mcfunction` 的每一行。"""
    commands = list(commands_of(world))
    commands += [
        str(entity["Command"])
        for entity in entities_of(world)
        if "Command" in entity
    ]
    commands += [
        line
        for line in mcfunction_text(world).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return commands


def test_every_command_written_back_still_reparses(round_trip) -> None:
    """**安全網的第二條線，跨整個世界跑一次。**

    `write/command_span.py` 只知道「這一段字串換成那一段字串」，它的第一條安全網
    是 span 定位器抓對範圍。C2 證明那不夠：span 可以完全正確而塞進去的東西**型別**
    是錯的，結果是一條寫得進磁碟、卻再也跑不動的指令，加上一份說 `unwritten: []`
    的報告——沒有任何既有斷言會紅。

    所以這裡對**每一條**指令問一次「這還解得回來嗎」，而不是只問新加的那一條。
    每一格 dispatch 組合都會經過這裡，包括還沒出問題的那幾格。
    """
    commands = all_commands_in(round_trip["world"])

    assert len(commands) >= 6, "指令太少，這條測試沒掃到東西"
    for command in commands:
        assert_command_reparses(command)


def mcfunction_text(world) -> str:
    path = world / "datapacks" / "tt_probe" / "data" / "tt" / "function" / "hello.mcfunction"
    return path.read_text("utf-8")


def test_an_mcfunction_say_line_keeps_its_verb_prefix(round_trip) -> None:
    """**`datapack_mcfunction_file` × in_place（say）。**"""
    lines = mcfunction_text(round_trip["world"]).splitlines()

    assert lines[0] == "say 腳本說話文字"


def test_an_mcfunction_tellraw_line_becomes_a_translate_component(round_trip) -> None:
    """**`datapack_mcfunction_file` × translate key（tellraw）。**"""
    lines = mcfunction_text(round_trip["world"]).splitlines()

    assert lines[1].startswith("tellraw @a ")
    payload = json.loads(lines[1][len("tellraw @a ") :])
    assert payload["translate"].startswith("mcmt.")


def decode_steps_of(edit) -> list[dict]:
    return [step for step in edit["node_path"] if step["t"] == "decode"]


def command_dispatch_combination(edit) -> tuple[str, str, str] | None:
    """把一筆 edit 分到 §9.1 表格的哪一格：`(容器種類, 最後一個 decode 步驟的
    codec, value.kind)`。

    `combinations_in()`（`(node_path 最後一步的 t, value.kind)`）分不開這五格
    ——它們的最後一步全是 `decode`。真正分得開的是最後一個 decode 步驟用哪個
    codec：`say`/`me` 是 `command`（自己套自己，見 `scan/command.py` 的說明）；
    L1（`tellraw`／`title`…）的引數是 JSON，最後一步是 `json_component`；L2
    `data merge` 的原生 compound 訊息最後一步是 `snbt`。三者互斥，加上容器種類
    與 `value.kind`，對這五格兩兩不同。

    （`give`／`item` 的巢狀 SNBT component 理論上也會落在 `("region_chunk",
    "snbt", "translate")` 這格，跟 L2 撞在一起——但 `give` 目前整條被
    `scan/command.py` 跳過，見上面 `test_a_give_commands_namespaced_component_
    is_a_known_scan_gap`，所以這裡不會真的收到那筆 edit。等那個缺口修好，
    這個分類函式需要多一個維度才分得開兩者。）"""
    container = edit["container"]["kind"]
    if container not in ("region_chunk", "entities_chunk", "datapack_mcfunction_file"):
        return None
    steps = decode_steps_of(edit)
    if not steps or steps[0]["codec"] != "command":
        return None
    return (container, steps[-1]["codec"], edit["value"]["kind"])


EXPECTED_COMMAND_COMBINATIONS = {
    ("region_chunk", "command", "literal"),  # region/entities × in_place（say/me）
    ("region_chunk", "json_component", "translate"),  # region/entities × translate key，L1
    ("entities_chunk", "snbt", "translate"),  # region/entities × translate key，L2 巢狀 SNBT
    ("entities_chunk", "snbt", "literal"),  # region/entities × in_place，L2 裸字串訊息（C2）
    ("datapack_mcfunction_file", "command", "literal"),  # .mcfunction × in_place
    ("datapack_mcfunction_file", "json_component", "translate"),  # .mcfunction × translate key
}


def test_the_round_trip_exercises_all_six_command_dispatch_combinations(
    round_trip,
) -> None:
    """**這份測試自己的守門，照抄 `..._all_four_dispatch_combinations` 的做法。**

    六格都得走到，否則某一格的 writer/scan 接線斷了也不會有任何測試變紅——
    這正是 M13a 那次「舊不變式在新範圍下靜默失效」的同一種盲點。

    第六格（`("entities_chunk","snbt","literal")`）是 2026-09-06 C2 補的：同一個
    `snbt` codec、同一個容器，只因為 `messages[]` 元素是裸字串而不是 compound，
    寫回方式就從 translate key 變成 in_place。**`(codec, value.kind)` 才是分派的
    座標，只看 codec 會把這兩格當成同一格**——而它們的寫入路徑完全不同，混為
    一談的後果就是 C2（一個異質 list 與一條再也跑不動的指令）。
    """
    combinations = {
        combo
        for combo in (
            command_dispatch_combination(edit)
            for edit in round_trip["applied"]["plan"].document["edits"]
        )
        if combo is not None
    }

    assert combinations == EXPECTED_COMMAND_COMBINATIONS


def test_no_command_edit_is_refused_for_an_unsupported_encoding(round_trip) -> None:
    """**F2 驗收條件的指令文字版。** 接上 `_WRITERS`／`scan/registry.py` 之前，
    `datapack_mcfunction_file` 沒有任何寫入器，這五格裡最後一格整批會被拒寫。

    `give` 的巢狀命名空間組件不在這裡的涵蓋範圍內——它在**掃描**這關就被跳過
    （見 `test_a_give_commands_namespaced_component_is_a_known_scan_gap`），
    根本沒有 edit 產生，所以也不會出現在這裡的 `unwritten` 清單裡。這條測試
    驗的是「有 edit 被產生了，但因為容器/形狀沒有寫入器而被拒」這件事。
    """
    unwritten = round_trip["applied"]["report"]["unwritten"]

    assert [item for item in unwritten if item["reason"] == "unsupported_encoding"] == []


def test_a_json_string_wrapped_merge_message_is_a_known_write_gap() -> None:
    """**已知缺口，Task 11 端到端才照出來，不在本任務授權修改的檔案清單裡
    （`write/common.py` 屬於 CLAUDE.md 安全規則要求獨立 commit 的目錄）。**

    `data merge` 目標告示牌的訊息若是**字串包裝 JSON**（單引號或雙引號字串
    常值包一段轉義過的 JSON——CLAUDE.md 二節「舊式 JSON 也可能出現在 SNBT
    裡」的那個形狀，MP2 語料的 `'""'` 就是這一類的空訊息版本），`decode_chain`
    是三步 `command → snbt → json_component`。

    `write/common.py::_decode_command_leaf` 只看鏈上**最後一步**的 codec，對
    `json_component` 一律直接 `json.loads(原始 span 文字)`——但那段 span 文字
    是 SNBT 字串常值本身（含引號，可能還帶跳脫），不是已經被 SNBT 解開過的
    JSON 內容。單引號字串（MP2 那種）直接 JSON 解析失敗，整筆被拒寫成
    `unsupported_encoding`；雙引號字串（`tests/unit/test_scan_command.py` 自己
    的測試樣本用的那種）恰好因為 JSON 也用雙引號跳脫，`json.loads` 語法上
    「解析成功」，但解出來的是**一個字串**（`'{"text":"Hello"}'` 這串文字
    本身），不是那個 JSON 物件——`_guarded_encoding` 拿它的嗅探結果
    （`json_string_object`）跟 `expected_encoding`（`text_compound`）比對，
    形狀對不上，一樣被拒寫成 `node_changed`。兩種引號風格都走不通，只是拒寫
    的理由不同，所以這裡兩種都接受。

    這裡釘住現狀：這筆合法、沒被使用者動過的翻譯被拒寫了。修法方向：
    `_decode_command_leaf` 在鏈上出現 `snbt` 接著 `json_component` 時，該先用
    `snbt` codec 把外層的字串常值解開拿到內容，再對內容跑 `json_component`
    ——跟 `command_span.py::_compose_replacement` 寫入時的反向邏輯對稱（它靠
    `codecs[-2] == "snbt"` 判斷要不要包一層 SNBT 字串常值）。
    """
    from collections import Counter

    from mcmt.model.node import NodePath, key_step
    from mcmt.scan.command import scan_command_string
    from mcmt.write.common import ApplyOutcome, apply_edits

    cmd = 'data merge block ~ ~ ~ {messages:[\'{"text":"Hello"}\']}'
    stats: Counter = Counter()
    (node,) = list(
        scan_command_string(
            cmd, base_path=NodePath([key_step("Command")]), anchor=None, stats=stats
        )
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_component_text:cccccccccccccccc",
        "container": {"kind": "region_chunk", "path": "r.0.0.mca", "data_version": 4671},
        "node_path": [step.to_json() for step in node.path],
        "expected_encoding": "text_compound",
        "value": {
            "kind": "translate",
            "key": "mcmt.command_component_text.cccccccccccccccc",
            "fallback": "Hello",
            "style": None,
        },
    }
    root = amulet_nbt.CompoundTag({"Command": amulet_nbt.StringTag(cmd)})
    outcome = ApplyOutcome()

    written = apply_edits(root, [edit], outcome)

    assert written == 0
    assert [item["reason"] for item in outcome.unwritten] in (
        ["unsupported_encoding"],
        ["node_changed"],
    )


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
    #
    # `.mcfunction`（Task 11）同理沒有 chunk 世代——`container.data_version`
    # 也合法是 `None`（見 `scan/sources/mcfunction.py::_container`）。指令文字
    # 的 translate key 一律至少帶 `translate`＋`fallback` 兩個鍵，跟 region／
    # entities chunk 裡 native 世代那條分支殊途同歸，同樣落在 `compound_tree`。
    if edit["container"]["kind"] in ("datapack_file", "datapack_mcfunction_file"):
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


def is_command_edit(edit) -> bool:
    """`node_path` 以 `decode` 步驟結尾——指令文字（`Command` 欄位／`.mcfunction`
    整行）不是普通的 NBT key/index 節點，見下面三條 `..._for_ordinary_nbt_edits`
    測試前的說明。"""
    return edit["node_path"][-1]["t"] == "decode"


def test_replaying_the_same_plan_is_refused_wherever_a_snapshot_was_captured_for_ordinary_nbt_edits(
    round_trip,
) -> None:
    """[遊戲實測 M4-4] 世界在 extract 之後被改過，守門就該擋下來。

    這裡「被改過」的是我們自己剛剛寫的那一次——守門分不出也不該分出是誰改的。

    **這條測試在 M13a 換過一次判準，`raw_snapshot` 接上之後又換了一次，換的
    理由本身是結論。** M13a 之後的版本斷言「只有會改變形狀的 edit 會被擋
    下」——那漏了一半：舊世代把 JSON 物件字串換成另一個 JSON 物件字串、
    native 把一棵 `compound_tree` 換成另一棵、`in_place` 保留形狀，這三種寫入
    形狀不變，重放時舊守門完全看不見，會若無其事地把「上一次寫入的譯文」
    當成「這次也是同一份原文」再蓋一次。

    `raw_snapshot` 補上的是「內容比對」——重放時節點裡的字已經是上一次寫入
    的**譯文**，跟 raw_snapshot 記的**原文**對不上，不管形狀有沒有變。所以
    現在真正的判準是「這個 occurrence 有沒有捕捉到 raw_snapshot」，不是
    「這次寫入會不會改變形狀」——`compound_tree` 永遠沒有 raw_snapshot（見
    下面 `test_a_compound_tree_replay_is_the_one_remaining_gap`），是唯一
    的例外。

    **`_for_ordinary_nbt_edits`（Task 11 加的限定）**：`written_encoding`／
    `shape_changing` 這一套判準是照著「key/index 結尾、整節點替換」的寫入
    模型量身打造的。指令文字（`decode` 結尾）不吃這一套——它們共用同一個
    物理字串，重放時真正先擋下它們的是 `_command_length_matches`（同一個
    字串裡任何一筆改過，整條字串的長度就變了），跟這裡的 shape/raw_snapshot
    判準是兩回事，混在一起比對只會撞出假陽性。指令文字自己的重放行為見
    `test_a_translated_region_or_entities_command_edit_is_refused_on_replay`
    與 `tests/unit/test_write_mcfunction_apply.py` 的那四條 `.mcfunction` 守門測試。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    edits = [e for e in plan["edits"] if not is_command_edit(e)]
    with_snapshot = [e for e in edits if e.get("raw_snapshot") is not None]
    # 這條測試存在的理由：至少要有一筆 edit 是「形狀沒變、但仍然被 raw_snapshot
    # 擋下來」——不然這條測試量不到 M13a 判準與現在判準的差異，跟只測
    # shape_changing 的舊版本沒有兩樣。
    shape_preserving_with_snapshot = [e for e in with_snapshot if not shape_changing(e)]
    outcome = apply_editplan(round_trip["world"], plan)

    assert with_snapshot, "這趟來回沒有任何帶 raw_snapshot 的 edit，測試沒驗到東西"
    assert shape_preserving_with_snapshot, (
        "這趟來回沒有任何『形狀沒變但內容變了』的 edit，測試驗不到 raw_snapshot "
        "比 expected_encoding 多擋下的那一半"
    )
    # `apply_editplan` 跑的是**整份** plan（含指令文字），`outcome.unwritten`
    # 裡本來就會混著指令文字自己那套守門（`_command_length_matches`）拒寫的
    # occurrence——那些不屬於這條測試要驗的東西，比對前先篩掉。
    ordinary_ids = {e["occurrence_id"] for e in edits}
    refused = {
        item["occurrence_id"]
        for item in outcome.unwritten
        if item["reason"] == "node_changed" and item["occurrence_id"] in ordinary_ids
    }
    assert refused == {e["occurrence_id"] for e in with_snapshot}


def test_a_compound_tree_replay_is_the_one_remaining_gap(round_trip) -> None:
    """**一個誠實的、比修之前小得多的缺口，寫成測試而不是註解。**

    `raw_snapshot` 對 `compound_tree` 永遠是 `None`——帶 `extra`／`click_event`
    等結構的樹沒有單一字串能代表整個節點，硬湊一個只會讓「只改樣式沒改字」
    被誤判成「內容變了」。所以這一類節點如果重放時形狀也剛好沒變（本來就是
    `compound_tree`，寫完還是 `compound_tree`），守門看不出這是重放，會再寫
    一次同樣的值——內容上是 no-op，沒有損害，但這就是現在唯一還留著的縫。

    這條測試不是在慶祝現況，是在把縮小後的缺口釘在一個會被讀到的地方。

    只看**非指令文字**的 edits——理由跟上一條測試同一個限定：指令文字有自己
    獨立的重放守門（`_command_length_matches`），不吃這裡的 shape 判準。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    no_snapshot = [
        e for e in plan["edits"] if not is_command_edit(e) and e.get("raw_snapshot") is None
    ]
    shape_preserving_no_snapshot = [e for e in no_snapshot if not shape_changing(e)]
    outcome = apply_editplan(round_trip["world"], plan)

    assert shape_preserving_no_snapshot, (
        "這趟來回沒有『raw_snapshot 是 null 而且形狀沒變』的 edit，"
        "測試驗不到這個縫"
    )
    survivors = {e["occurrence_id"] for e in shape_preserving_no_snapshot}
    refused = {item["occurrence_id"] for item in outcome.unwritten}
    assert survivors.isdisjoint(refused)


def test_an_in_place_replay_is_now_caught_by_the_raw_snapshot_guard(round_trip) -> None:
    """**這條測試原本釘著一個誠實的缺口，現在釘著它已經被 raw_snapshot 補上。**

    `in_place` 保留節點既有的形狀，所以重放同一份 plan 時 `expected_encoding`
    看不出任何變化——舊守門會若無其事地再寫一次同樣的值，使用者自己在
    extract 之後改的名字會被蓋掉也一樣看不出來。`raw_snapshot` 現在補上了
    「內容比對」這一層：重放時節點裡的字已經是**上一次寫入的譯文**，跟
    raw_snapshot 記的**原文**對不上，於是被擋下來，而不是被靜默覆寫。

    只看**非指令文字**的 in_place edits——`command_say_text` 也是 in_place，
    但它在 region/entities 與 `.mcfunction` 走的重放守門完全不同（見下面兩條
    指令文字專屬的測試），混進來會讓這條測試斷言錯誤的東西。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    in_place_edits = [
        e for e in plan["edits"]
        if e["value"]["kind"] == "literal" and not is_command_edit(e)
    ]
    outcome = apply_editplan(round_trip["world"], plan)

    assert in_place_edits, "這趟來回沒有走到 in_place 路徑，測試沒驗到東西"
    refused = {
        item["occurrence_id"]
        for item in outcome.unwritten
        if item["reason"] == "node_changed"
    }
    assert {e["occurrence_id"] for e in in_place_edits} <= refused
    # 沒有任何一筆 in_place edit 被重放蓋掉——內容原封不動，還是第一次寫入的譯文。
    assert {
        str(entity["CustomName"])
        for entity in block_entities_of(round_trip["world"])
        if "CustomName" in entity
    } == {"補給箱", "指令方塊"}


def test_a_translated_region_or_entities_command_edit_is_refused_on_replay(
    round_trip,
) -> None:
    """**指令文字自己的重放守門，跟一般 NBT 節點是不同的機制。**

    `write/common.py::_apply_decode_group` 在委派給 `command_span.py` 之前，
    先用 `_command_length_matches` 擋一次：`decode_chain` 第一步固定記著
    「extract 當下 `Command` 字串的長度」，splice 過一次之後這個長度幾乎必然
    變了（譯文長度跟原文不同），下一次重放時長度對不上，直接判定「世界被
    改過」——不管這筆 edit 的 `raw_snapshot` 是不是 `None`、形狀有沒有變。
    這比 `written_encoding`／`shape_changing` 那一套（照著 key/index 結尾的
    NBT 節點設計）更粗但更保守：**同一個 `Command` 字串裡任何一筆被寫過，
    這個字串裡剩下所有 edit 在重放時全部一起被擋下來**。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    command_edits = [
        e for e in plan["edits"]
        if is_command_edit(e) and e["container"]["kind"] in ("region_chunk", "entities_chunk")
    ]
    outcome = apply_editplan(round_trip["world"], plan)

    assert command_edits, "這趟來回沒有 region/entities 的指令文字 edit，測試沒驗到東西"
    refused = {
        item["occurrence_id"]
        for item in outcome.unwritten
        if item["reason"] == "node_changed"
    }
    assert {e["occurrence_id"] for e in command_edits} <= refused


def test_the_command_span_primitive_itself_has_no_replay_guard_by_design() -> None:
    """**這條測試換過一次意義，換的理由本身是結論。**

    它原本叫 `..._an_mcfunction_command_edit_is_not_guarded_against_replay_a_known_gap`，
    釘的是「`.mcfunction` 完全沒有重放守門」這個缺口，並把後果描述成「把已翻
    的文字再蓋一次同樣的譯文（no-op，沒有損害）」。

    **那個描述是錯的，而它之所以看起來對，就是因為這條測試挑的例子。**
    `say Hello world` → `say 你好世界` 剛好冪等：走味的 span `[4,15]` 落在 9
    字元的新字串上，仍然解析成「`say ` 之後的全部」。換一個在 extract 之後
    長度變了的指令行，同一條路徑會從一個 token 的正中央切開，寫出語法壞掉的
    指令，而 `unwritten` 是空的。**釘住現狀的測試挑了最方便的例子，於是「測試
    是綠的」被讀成「行為是無害的」。**

    2026-09-06 已補：`write/mcfunction_apply.py::_guard_by_length()`（資料夾式
    與 zip 式兩條路都接）。`.mcfunction` 的重放行為現在釘在
    `tests/unit/test_write_mcfunction_apply.py` 的四條，包括還沒補上的
    `raw_snapshot` 那一層（殘餘缺口）。

    **這條測試留下來，釘的是另一件仍然為真、而且是刻意的事**：
    `command_span.py::apply_command_edits` 這個**原語本身**不做任何 extract-當下
    快照比對，它只負責 splice。守門是呼叫端的責任（`write/common.py::
    _apply_decode_group` 與 `write/mcfunction_apply.py::_guard_by_length`）。
    把守門下放到原語裡會讓兩個呼叫端各自的分組／快照語意糊掉——所以這裡不是
    缺口，是分層。
    """
    from collections import Counter

    from mcmt.model.node import NodePath, key_step
    from mcmt.scan.command import scan_command_string
    from mcmt.write.command_span import apply_command_edits
    from mcmt.write.common import ApplyOutcome

    original = "say Hello world"
    stats: Counter = Counter()
    (node,) = list(
        scan_command_string(
            original, base_path=NodePath([key_step("line")]), anchor=None, stats=stats
        )
    )
    edit = {
        "occurrence_id": "o:00001",
        "unit_id": "u:command_say_text:dddddddddddddddd",
        "container": {"kind": "datapack_mcfunction_file", "path": "p/f.mcfunction:1"},
        "node_path": [step.to_json() for step in node.path],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": "你好世界", "style": None},
    }
    outcome = ApplyOutcome()

    # 第一次：正常寫入。
    once = apply_command_edits(original, [edit], outcome=outcome)
    assert once == "say 你好世界"
    assert not outcome.unwritten

    # 第二次：對**已經被翻譯過**的字串重放同一筆 edit——原語本身不做任何
    # extract-當下快照比對，只單純 splice，所以永遠成功。兩個呼叫端各自在
    # 委派給它之前擋（`write/common.py::_apply_decode_group` 的三層、
    # `write/mcfunction_apply.py::_guard_by_length` 的長度那層），所以**走
    # 真實入口的重放是被拒的**——那件事釘在
    # `tests/unit/test_write_mcfunction_apply.py::test_replaying_the_same_plan_on_an_mcfunction_is_refused`。
    twice = apply_command_edits(once, [edit], outcome=outcome)
    assert twice == "say 你好世界"
    assert not outcome.unwritten


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
