# SPDX-License-Identifier: GPL-3.0-or-later
"""M11.2 把 editplan 寫回世界（`write/apply.py`）。

順序是不可協商的：**備份 → 改 → 寫**。備份失敗就中止，例外發生時全部還原。

**外科式寫入的機器可檢查形式**是 `counts.chunks_copied_verbatim`——沒被改到的 chunk
帶著原始壓縮位元組原封送回去，連解碼都不做。
"""

import json
import zlib
from pathlib import Path

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import read_region
from mcmt.safety.paths import ensure_readable
from mcmt.write.apply import apply_editplan

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


@pytest.fixture(scope="module")
def report_validator():
    registry = Registry()
    schemas = {}
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text("utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        schemas[path.name.split(".")[0]] = schema
    return Draft202012Validator(schemas["apply_report"], registry=registry)


def sign(*lines, compounds=False):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name in ("x", "y", "z"):
        tag[name] = amulet_nbt.IntTag(1)
    face = amulet_nbt.CompoundTag()
    if compounds:
        face["messages"] = amulet_nbt.ListTag(
            [amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(l)}) for l in lines]
        )
    else:
        face["messages"] = amulet_nbt.ListTag(
            [amulet_nbt.StringTag(l) for l in lines]
        )
    tag["front_text"] = face
    return tag


def build_world(project, *chunk_specs, name="world"):
    """`chunk_specs` 是 (chunk_index, 方塊實體, data_version)。"""
    world = project / "sandbox" / name
    builder = RegionBuilder()
    for index, entity, data_version in chunk_specs:
        root = modern_chunk(data_version=data_version)
        root["block_entities"] = amulet_nbt.ListTag([entity])
        builder.add_chunk_nbt(index, root)
    write_region_file(world / "region", builder.build(), "r.0.0.mca")
    return world


def edit(*, index=0, encoding="bare_string", data_version=4671, chunk=(0, 0), value=None):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:sign:0123456789abcdef",
        "container": {
            "kind": "region_chunk",
            "path": "region/r.0.0.mca",
            "dimension": "minecraft:overworld",
            "chunk": {"cx": chunk[0], "cz": chunk[1]},
            "data_version": data_version,
            "compression": 2,
            "external": False,
        },
        "node_path": [
            {"t": "key", "name": "block_entities"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "front_text"},
            {"t": "key", "name": "messages"},
            {"t": "index", "i": index},
        ],
        "expected_encoding": encoding,
        "value": value or {"kind": "translate", "key": "mcmt.sign.0123456789abcdef", "style": None},
    }


def plan(*edits):
    return {"edits": list(edits), "unwritten": []}


def messages_of(world, chunk_index=0):
    path = world / "region" / "r.0.0.mca"
    chunk = {c.index: c for c in read_region(ensure_readable(path))}[chunk_index]
    data = decompress_chunk(chunk.payload, chunk.compression_type, chunk_index=chunk.index)
    root = amulet_nbt.load(data, compressed=False).compound
    return root["block_entities"][0]["front_text"]["messages"]


# --- 寫得進去 -------------------------------------------------------------


def test_a_native_chunk_gets_a_compound(project) -> None:
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))

    outcome = apply_editplan(world, plan(edit()))

    written = messages_of(world)
    assert outcome.counts["edits_written"] == 1
    assert isinstance(written[0], amulet_nbt.CompoundTag)
    assert str(written[0]["translate"]) == "mcmt.sign.0123456789abcdef"


def test_a_native_string_list_is_promoted_and_counted(project) -> None:
    world = build_world(project, (0, sign("歡迎光臨", "第二行", "", ""), 4671))

    outcome = apply_editplan(world, plan(edit()))

    written = messages_of(world)
    assert outcome.counts["list_promotions"] == 1
    assert all(isinstance(x, amulet_nbt.CompoundTag) for x in written)
    assert str(written[1]["text"]) == "第二行"  # 其餘行的字一模一樣


def test_a_legacy_chunk_gets_a_json_string(project) -> None:
    """[遊戲實測 M4-1] 舊世代寫 JSON 字串，而且 list 型別不變。"""
    world = build_world(project, (0, sign('"原文"', '""', '""', '""'), 3700))

    outcome = apply_editplan(
        world, plan(edit(encoding="json_string_scalar", data_version=3700))
    )

    written = messages_of(world)
    assert outcome.counts["list_promotions"] == 0
    assert all(isinstance(x, amulet_nbt.StringTag) for x in written)
    assert json.loads(str(written[0]))["translate"] == "mcmt.sign.0123456789abcdef"


def test_a_legacy_chunk_leaves_the_other_lines_untouched(project) -> None:
    world = build_world(project, (0, sign('"原文"', '"第二行"', '""', '""'), 3700))

    apply_editplan(world, plan(edit(encoding="json_string_scalar", data_version=3700)))

    assert [str(x) for x in messages_of(world)[1:]] == ['"第二行"', '""', '""']


# --- 外科式 ---------------------------------------------------------------


def test_untouched_chunks_are_copied_verbatim(project) -> None:
    """**外科式寫入的機器可檢查形式。** 沒改到的 chunk 連解碼都不做。"""
    world = build_world(
        project,
        (0, sign("要改的", "", "", ""), 4671),
        (1, sign("不動的", "", "", ""), 4671),
        (2, sign("也不動", "", "", ""), 4671),
    )
    before = {c.index: c.payload for c in read_region(ensure_readable(world / "region" / "r.0.0.mca"))}

    outcome = apply_editplan(world, plan(edit()))

    after = {c.index: c.payload for c in read_region(ensure_readable(world / "region" / "r.0.0.mca"))}
    assert outcome.counts["chunks_copied_verbatim"] == 2
    assert outcome.counts["chunks_touched"] == 1
    assert after[1] == before[1]
    assert after[2] == before[2]


def test_untouched_timestamps_are_carried_over(project) -> None:
    world = build_world(
        project, (0, sign("要改的", "", "", ""), 4671), (1, sign("不動的", "", "", ""), 4671)
    )
    path = world / "region" / "r.0.0.mca"
    before = {c.index: c.timestamp for c in read_region(ensure_readable(path))}

    apply_editplan(world, plan(edit()))

    after = {c.index: c.timestamp for c in read_region(ensure_readable(path))}
    assert after[1] == before[1]


# --- 備份 -----------------------------------------------------------------


def test_the_region_is_backed_up_before_it_is_written(project) -> None:
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    original = (world / "region" / "r.0.0.mca").read_bytes()

    outcome = apply_editplan(world, plan(edit()))

    backup = outcome.backup_directory / "region" / "r.0.0.mca"
    assert backup.read_bytes() == original
    assert outcome.backup_files == 1


def test_a_failure_mid_write_rolls_everything_back(project, monkeypatch) -> None:
    """例外發生時全部還原——這是 BackupSet 的職責，這裡驗它真的接上了。"""
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    original = (world / "region" / "r.0.0.mca").read_bytes()

    import mcmt.write.apply as apply_module

    def explode(*args, **kwargs):
        raise RuntimeError("模擬寫到一半掛掉")

    monkeypatch.setattr(apply_module, "write_region", explode)

    with pytest.raises(RuntimeError):
        apply_editplan(world, plan(edit()))

    assert (world / "region" / "r.0.0.mca").read_bytes() == original


def test_nothing_is_written_in_a_dry_run(project) -> None:
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    original = (world / "region" / "r.0.0.mca").read_bytes()

    outcome = apply_editplan(world, plan(edit()), dry_run=True)

    assert outcome.outcome == "dry_run"
    assert (world / "region" / "r.0.0.mca").read_bytes() == original
    assert outcome.backup_directory is None


# --- 守門 -----------------------------------------------------------------


def test_a_changed_node_is_refused_not_overwritten(project) -> None:
    """[遊戲實測 M4-4] 使用者在中間玩過一次遊戲，形狀就可能已經變了。"""
    world = build_world(project, (0, sign("歡迎光臨", "", "", "", compounds=True), 4671))

    outcome = apply_editplan(world, plan(edit(encoding="bare_string")))

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"
    assert "text_compound" in outcome.unwritten[0]["detail"]


def test_a_refused_edit_leaves_the_file_alone(project) -> None:
    world = build_world(project, (0, sign("歡迎光臨", "", "", "", compounds=True), 4671))
    original = (world / "region" / "r.0.0.mca").read_bytes()

    apply_editplan(world, plan(edit(encoding="bare_string")))

    assert (world / "region" / "r.0.0.mca").read_bytes() == original


def test_a_missing_node_is_reported(project) -> None:
    world = build_world(project, (0, sign("只有一行"), 4671))

    outcome = apply_editplan(world, plan(edit(index=3)))

    assert outcome.unwritten[0]["reason"] == "node_missing"


def test_placeholder_residue_refuses_the_whole_plan(project) -> None:
    """殘留代表上游算錯了，不會只錯一筆——所以拒絕整份 plan。"""
    from mcmt.errors import PlaceholderResidueError

    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    bad = edit(value={"kind": "literal", "text": "還有 [[0]] 沒處理", "style": None})

    with pytest.raises(PlaceholderResidueError):
        apply_editplan(world, plan(bad))


# --- 報告 -----------------------------------------------------------------


def test_the_report_validates_against_the_schema(project, report_validator) -> None:
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    outcome = apply_editplan(world, plan(edit()))

    report = outcome.report(world=world, fingerprint_before="blake2b:0011223344556677")

    errors = sorted(report_validator.iter_errors(report), key=str)
    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def test_the_report_records_the_backup_directory(project) -> None:
    """還原失敗時使用者永遠要有一條救回來的路——所以路徑一定要在報告裡。"""
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    outcome = apply_editplan(world, plan(edit()))

    report = outcome.report(world=world, fingerprint_before="blake2b:0011223344556677")

    assert Path(report["backup"]["directory"]).is_absolute()
    assert report["backup"]["file_count"] == 1


def test_sector_realignment_is_reported(project) -> None:
    """檔案變小是磁區重整不是資料遺失，但使用者看到會恐慌。"""
    world = build_world(project, (0, sign("歡迎光臨", "", "", ""), 4671))
    path = world / "region" / "r.0.0.mca"
    path.write_bytes(path.read_bytes() + bytes(4096 * 3))

    outcome = apply_editplan(world, plan(edit()))

    kinds = [w["kind"] for w in outcome.warnings]
    assert "sector_realignment" in kinds


# --- entities/*.mca（M13.4）-------------------------------------------------


def test_an_entities_chunk_is_written_by_the_same_surgical_path(project) -> None:
    """**`entities/*.mca` 不需要新的寫入器。**

    它就是 region 格式——同一套 header、同一套壓縮——所以 `write_region` 直接可用，
    外科式保證原封不動。`_apply_to_region` 是用 container["path"] 去
    `world / relative` 讀寫的，`entities/r.0.0.mca` 就這樣走進同一條路。
    """
    world = project / "sandbox" / "world"
    root = modern_chunk(data_version=4671)
    holder = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:armor_stand")})
    holder["CustomName"] = amulet_nbt.StringTag("守衛")
    root["Entities"] = amulet_nbt.ListTag([holder])
    write_region_file(
        world / "entities", RegionBuilder().add_chunk_nbt(0, root).build(), "r.0.0.mca"
    )

    plan_document = {
        "edits": [
            {
                "occurrence_id": "o:00001",
                "unit_id": "u:entity_name:0123456789abcdef",
                "container": {
                    "kind": "entities_chunk",
                    "path": "entities/r.0.0.mca",
                    "dimension": "minecraft:overworld",
                    "chunk": {"cx": 0, "cz": 0},
                    "data_version": 4671,
                    "compression": 2,
                    "external": False,
                },
                "node_path": [
                    {"t": "key", "name": "Entities"},
                    {"t": "index", "i": 0},
                    {"t": "key", "name": "CustomName"},
                ],
                "expected_encoding": "bare_string",
                "value": {"kind": "literal", "text": "衛兵", "style": None},
            }
        ],
        "unwritten": [],
    }

    outcome = apply_editplan(world, plan_document)

    chunk = next(
        c
        for c in read_region(ensure_readable(world / "entities" / "r.0.0.mca"))
        if c.index == 0
    )
    data = decompress_chunk(chunk.payload, chunk.compression_type, chunk_index=chunk.index)
    written = amulet_nbt.load(data, compressed=False).compound
    assert outcome.counts["edits_written"] == 1
    assert str(written["Entities"][0]["CustomName"]) == "衛兵"


# --- 分派：literal 的節點一律走 in_place，不管 node_path 長什麼樣（M13a F1）----
#
# 舊的分派只看 `node_path` 最後一步是 `key` 還是 `index`。在 M13a 之前那碰巧是對的
# ——v1 只掃告示牌（index + translate_key）與 `CustomName`（key + in_place），剛好
# 是四種組合裡的兩種。M13a 把另外兩種也掃了進來，等價關係就假了。
#
# **真正的判準是 `value["kind"]`**：literal 要保留節點既有的形狀（in_place），
# translate / component 才換成 translate key。


def draft_book_chest(*pages, item_id="minecraft:writable_book"):
    """舊格式（1.20.5 之前的 `tag`）的草稿書，裝在箱子的 `Items[]` 裡。

    草稿書頁**本來就是無包裝的純字串**，不是 component。[實測] `Arena of Darkness`
    有 9 個這種 occurrence。
    """
    book = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag(item_id)})
    book["tag"] = amulet_nbt.CompoundTag(
        {"pages": amulet_nbt.ListTag([amulet_nbt.StringTag(p) for p in pages])}
    )
    chest = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:chest")})
    for name in ("x", "y", "z"):
        chest[name] = amulet_nbt.IntTag(1)
    chest["Items"] = amulet_nbt.ListTag([book])
    return chest


def page_edit(*, index=0, encoding="bare_string", data_version=3700, text="你好世界"):
    """草稿書頁的 edit：**路徑以 index 結尾，但 value 是 literal。**"""
    return {
        "occurrence_id": "o:00002",
        "unit_id": "u:draft_book_page:0123456789abcdef",
        "container": {
            "kind": "region_chunk",
            "path": "region/r.0.0.mca",
            "dimension": "minecraft:overworld",
            "chunk": {"cx": 0, "cz": 0},
            "data_version": data_version,
            "compression": 2,
            "external": False,
        },
        "node_path": [
            {"t": "key", "name": "block_entities"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "Items"},
            {"t": "index", "i": 0},
            {"t": "key", "name": "tag"},
            {"t": "key", "name": "pages"},
            {"t": "index", "i": index},
        ],
        "expected_encoding": encoding,
        "value": {"kind": "literal", "text": text, "style": None},
    }


def pages_of(world, chunk_index=0):
    path = world / "region" / "r.0.0.mca"
    chunk = {c.index: c for c in read_region(ensure_readable(path))}[chunk_index]
    data = decompress_chunk(chunk.payload, chunk.compression_type, chunk_index=chunk.index)
    root = amulet_nbt.load(data, compressed=False).compound
    return root["block_entities"][0]["Items"][0]["tag"]["pages"]


def test_a_draft_book_page_keeps_its_bare_string_shape(project) -> None:
    """**F1（Critical）**：草稿書頁不能被寫成 JSON 字串。

    `draft_book_page` 的 strategy 是 `in_place`，但它的 `node_path` 以 index 結尾。
    舊的分派只看路徑形狀，於是把它送進 `legacy.apply_to_list`，寫出來的是
    `'{"text":"你好世界"}'`——玩家打開草稿書看到的是字面的大括號。
    """
    world = build_world(project, (0, draft_book_chest("Hello world", "page two"), 3700))

    outcome = apply_editplan(world, plan(page_edit()))

    written = pages_of(world)
    assert outcome.counts["edits_written"] == 1
    assert isinstance(written[0], amulet_nbt.StringTag)
    assert str(written[0]) == "你好世界"


def test_a_draft_book_page_does_not_promote_the_page_list(project) -> None:
    """同一個節點在 native chunk 也不能被提升成 compound 的 list。

    native 那條路徑更糟：`apply_to_list` 會把**整個 `pages` list 提升**成 compound，
    連沒被要求改的那幾頁一起重新編碼。
    """
    world = build_world(project, (0, draft_book_chest("Hello world", "page two"), 4671))

    outcome = apply_editplan(world, plan(page_edit(data_version=4671)))

    written = pages_of(world)
    assert outcome.counts["list_promotions"] == 0
    assert all(isinstance(page, amulet_nbt.StringTag) for page in written)
    assert [str(page) for page in written] == ["你好世界", "page two"]


def test_a_draft_book_page_still_passes_the_encoding_guard(project) -> None:
    """守門不因為換了一條路徑就鬆掉。"""
    world = build_world(project, (0, draft_book_chest("Hello world"), 3700))

    outcome = apply_editplan(
        world, plan(page_edit(encoding="json_string_object"))
    )

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"
    assert str(pages_of(world)[0]) == "Hello world"
