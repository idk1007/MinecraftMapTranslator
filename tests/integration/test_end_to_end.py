# SPDX-License-Identifier: GPL-3.0-or-later
"""M12 自動化端到端：`sandbox import → extract → 填譯文 → apply`。

M11 那次完整來回是**手動跑的**，結論寫在 `docs/STATUS.md` 裡。手動跑過一次證明得了
「這條鏈通了」，證明不了「明天改完別的東西之後它還通」——而這條鏈橫跨掃描、規則、
key、後端、寫入、資源包六層，任何一層漂移都會讓它安靜地斷掉。

所以這份測試把那次來回釘住，而且**斷言到位元組層級**：改的地方改了，沒改的地方
連 timestamp 都一樣。

fixture 是 `TT_WORLD_NAME_PROBE`（本專案自建的探測世界）的 `r.0.0.mca` 前 30 個
chunk。它剛好同時有告示牌、吊掛告示牌與兩個 `CustomName`，所以**兩條寫入路徑
（translate key 與 in_place）在同一次來回裡都會走到**。

> **不用語料地圖切 fixture**：那些是別人做的冒險地圖，放進要公開發布的 GPLv3 repo
> 等於重新散布別人的作品（見 M3 的同一條決定）。
"""

import json
import shutil
import zipfile
from pathlib import Path

import amulet_nbt
import pytest
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


@pytest.fixture
def source_world(project):
    """一個 sandbox **之外**的世界，模擬使用者的 `.minecraft/saves`。

    `sandbox import` 是唯一合法的入口，所以來源必須真的在外面——把它建在 sandbox
    裡再 import，測到的就不是那條路徑了。
    """
    world = project / "outside" / "TT_PROBE"
    (world / "region").mkdir(parents=True)
    shutil.copyfile(FIXTURE, world / "region" / "r.0.0.mca")
    return world


def chunks_of(world, name="r.0.0.mca"):
    return {c.index: c for c in read_region(ensure_readable(world / "region" / name))}


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
    "TT_CHEST_CUSTOM_NAME": "補給箱",
    "TT_CMDBLOCK_CUSTOM_NAME": "指令方塊",
}


@pytest.fixture
def round_trip(project, source_world):
    """走完一整趟，回傳每一段的產出。**這就是使用者手動做的那四步。**"""
    imported = import_world(source_world, name="probe")
    before = chunks_of(imported.target)

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
        "extract": extract,
        "applied": applied,
        "mapping": mapping,
        "untranslated": sign_sources[2:],
    }


# --- 這條鏈通了 -----------------------------------------------------------


def test_the_whole_round_trip_writes_something(round_trip) -> None:
    counts = round_trip["applied"]["report"]["counts"]

    assert counts["edits_written"] > 0
    assert counts["chunks_touched"] == 1


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


def test_the_resource_pack_carries_the_sign_keys_only(round_trip) -> None:
    """in_place 的譯文住在存檔裡，再往 lang 檔塞一份就是兩個真相來源。"""
    with zipfile.ZipFile(round_trip["world"] / "resources.zip") as archive:
        assert "pack.mcmeta" in archive.namelist()
        lang = json.loads(archive.read("assets/mcmt/lang/zh_tw.json"))

    assert lang, "lang 檔是空的"
    assert all(key.startswith("mcmt.") for key in lang)
    assert not any("block_entity_name" in key for key in lang)
    assert set(lang.values()) <= {"譯文0", "譯文1"}


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

    assert counts["chunks_copied_verbatim"] == len(round_trip["before"]) - 1


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


def test_replaying_the_same_plan_is_refused_for_every_translate_key_edit(round_trip) -> None:
    """[遊戲實測 M4-4] 世界在 extract 之後被改過，形狀就對不上了。

    這裡「被改過」的是我們自己剛剛寫的那一次——守門分不出也不該分出是誰改的。
    告示牌那條路徑的節點從 `bare_string` 變成了 compound，所以整批被擋下來。
    """
    from mcmt.write.apply import apply_editplan

    plan = round_trip["applied"]["plan"].document
    outcome = apply_editplan(round_trip["world"], plan)

    assert {item["reason"] for item in outcome.unwritten} == {"node_changed"}
    assert len(outcome.unwritten) == len(
        [e for e in plan["edits"] if e["value"]["kind"] != "literal"]
    )


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
    in_place_edits = [e for e in plan["edits"] if e["value"]["kind"] == "literal"]
    outcome = apply_editplan(round_trip["world"], plan)

    assert in_place_edits, "這趟來回沒有走到 in_place 路徑，測試沒驗到東西"
    assert outcome.counts["edits_written"] == len(in_place_edits)
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
