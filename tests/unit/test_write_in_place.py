# SPDX-License-Identifier: GPL-3.0-or-later
"""`in_place` 寫入：譯文直接進節點（`write/apply.py`）。**高風險目錄。**

`write/apply.py` 在此之前**只寫 list 元素**（告示牌四行），因為 `CustomName` 該寫
什麼形狀沒有實測依據。[遊戲實測 M11-3] 給了答案：native chunk 的 `CustomName`
不解析任何形狀，寫進去的 SNBT `{translate:…}` 在容器 GUI 顯示為字面的大括號。

所以這條路徑的規則是**保留節點既有的 NBT 形狀，只換裡面的字**：

* `bare_string` / `plain_string` → 寫回裸字串
* `text_compound` → 寫回 `{"text": …}`
* `empty_key_compound` → 寫回 `{"": …}`
* `json_string_scalar` → 寫回 `'"譯文"'`（舊世代）
* `json_string_object` → 寫回 `'{"text":"譯文"}'`（舊世代）

兩種 compound 形式**互不正規化**——路過的 `{"": …}` 順手改成 `{"text": …}` 就是
重新編碼一個沒被要求改的欄位（CLAUDE.md 二節）。而 `TAG_String` **不提升成
compound**：那個提升對 `CustomName` 從未實測過，未測過的寫入路徑比拒絕處理危險。
"""

import json

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.errors import PlaceholderResidueError
from mcmt.nbtio.compression import decompress_chunk
from mcmt.nbtio.region import read_region
from mcmt.safety.paths import ensure_readable
from mcmt.write.apply import apply_editplan


def chest(custom_name):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:chest")
    for name in ("x", "y", "z"):
        tag[name] = amulet_nbt.IntTag(1)
    tag["CustomName"] = custom_name
    return tag


def build_world(project, entity, *, data_version=4671, name="world"):
    world = project / "sandbox" / name
    root = modern_chunk(data_version=data_version)
    root["block_entities"] = amulet_nbt.ListTag([entity])
    write_region_file(
        world / "region", RegionBuilder().add_chunk_nbt(0, root).build(), "r.0.0.mca"
    )
    return world


def edit(*, encoding="bare_string", data_version=4671, text="補給箱"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:block_entity_name:0123456789abcdef",
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
            {"t": "key", "name": "CustomName"},
        ],
        "expected_encoding": encoding,
        "value": {"kind": "literal", "text": text, "style": None},
    }


def plan(*edits):
    return {"edits": list(edits), "unwritten": []}


def custom_name_of(world):
    path = world / "region" / "r.0.0.mca"
    chunk = next(c for c in read_region(ensure_readable(path)) if c.index == 0)
    data = decompress_chunk(
        chunk.payload, chunk.compression_type, chunk_index=chunk.index
    )
    root = amulet_nbt.load(data, compressed=False).compound
    return root["block_entities"][0]["CustomName"]


# --- 形狀保留 -------------------------------------------------------------


def test_a_bare_string_stays_a_bare_string(project) -> None:
    world = build_world(project, chest(amulet_nbt.StringTag("Supply Crate")))

    outcome = apply_editplan(world, plan(edit()))

    written = custom_name_of(world)
    assert outcome.counts["edits_written"] == 1
    assert isinstance(written, amulet_nbt.StringTag)
    assert str(written) == "補給箱"


def test_a_text_compound_stays_a_text_compound(project) -> None:
    world = build_world(
        project,
        chest(amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("Supply Crate")})),
    )

    apply_editplan(world, plan(edit(encoding="text_compound")))

    written = custom_name_of(world)
    assert isinstance(written, amulet_nbt.CompoundTag)
    assert str(written["text"]) == "補給箱"


def test_an_empty_key_compound_is_not_normalised_into_a_text_compound(project) -> None:
    """[遊戲實測 M4-2] `{"": …}` 是 Mojang NbtOps 自己的輸出形狀，不是怪癖。

    順手把它改成 `{"text": …}` 就是重新編碼一個沒被要求改的欄位。
    """
    world = build_world(
        project,
        chest(amulet_nbt.CompoundTag({"": amulet_nbt.StringTag("Supply Crate")})),
    )

    apply_editplan(world, plan(edit(encoding="empty_key_compound")))

    written = custom_name_of(world)
    assert list(written.keys()) == [""]
    assert str(written[""]) == "補給箱"


def test_the_string_is_never_promoted_to_a_compound(project) -> None:
    """告示牌的 list 提升過（M11-1 實測過），CustomName 沒有那條退路。"""
    world = build_world(project, chest(amulet_nbt.StringTag("Supply Crate")))

    apply_editplan(world, plan(edit()))

    assert not isinstance(custom_name_of(world), amulet_nbt.CompoundTag)


# --- 守門 -----------------------------------------------------------------


def test_a_changed_node_is_refused(project) -> None:
    """[遊戲實測 M4-4] 使用者中間玩過一次，DataFixer 就會改掉節點形狀。"""
    world = build_world(
        project,
        chest(amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("Supply Crate")})),
    )

    outcome = apply_editplan(world, plan(edit(encoding="bare_string")))

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"
    assert str(custom_name_of(world)["text"]) == "Supply Crate"


def test_a_missing_node_is_refused(project) -> None:
    tag = chest(amulet_nbt.StringTag("Supply Crate"))
    del tag["CustomName"]
    world = build_world(project, tag)

    outcome = apply_editplan(world, plan(edit()))

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_missing"


def test_a_translate_value_on_an_in_place_node_is_refused(project) -> None:
    """[遊戲實測 M11-3] 這裡放 translate key，玩家看到的是 key 本身。

    後端不會產生這種計畫，但寫入層不靠上游的自律。
    """
    world = build_world(project, chest(amulet_nbt.StringTag("Supply Crate")))
    bad = edit()
    bad["value"] = {"kind": "translate", "key": "mcmt.block_entity_name.0123456789abcdef"}

    outcome = apply_editplan(world, plan(bad))

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "unsupported_encoding"
    assert str(custom_name_of(world)) == "Supply Crate"


def test_placeholder_residue_rejects_the_whole_plan(project) -> None:
    """殘留代表上游算錯了，而算錯的東西不會只錯一筆——拒絕整份 plan。"""
    world = build_world(project, chest(amulet_nbt.StringTag("Supply Crate")))

    with pytest.raises(PlaceholderResidueError):
        apply_editplan(world, plan(edit(text="補給箱[[0]]")))


# --- 外科式寫入 -----------------------------------------------------------


def test_the_other_block_entities_in_the_chunk_are_untouched(project) -> None:
    world = project / "sandbox" / "world"
    root = modern_chunk(data_version=4671)
    other = chest(amulet_nbt.StringTag("Do Not Touch"))
    other["x"] = amulet_nbt.IntTag(99)
    root["block_entities"] = amulet_nbt.ListTag(
        [chest(amulet_nbt.StringTag("Supply Crate")), other]
    )
    write_region_file(
        world / "region", RegionBuilder().add_chunk_nbt(0, root).build(), "r.0.0.mca"
    )

    apply_editplan(world, plan(edit()))

    path = world / "region" / "r.0.0.mca"
    chunk = next(c for c in read_region(ensure_readable(path)) if c.index == 0)
    data = decompress_chunk(
        chunk.payload, chunk.compression_type, chunk_index=chunk.index
    )
    entities = amulet_nbt.load(data, compressed=False).compound["block_entities"]
    assert str(entities[1]["CustomName"]) == "Do Not Touch"


# --- 形狀表本身 -----------------------------------------------------------
#
# `plain_string` 走不到上面那條 region 路徑：它是**由欄位決定**的 encoding，而
# `sniff()` 只看值，永遠不會回傳它。有依據的欄位（LevelName / 書名 / 作者 /
# 草稿書頁）都在 level.dat 或物品裡，M13 才會掃到。先把形狀釘好，免得那時再猜一次。


def test_a_plain_string_node_gets_a_bare_string() -> None:
    from mcmt.write.in_place import value_tag

    tag = value_tag("plain_string", {"kind": "literal", "text": "我的世界"})

    assert isinstance(tag, amulet_nbt.StringTag)
    assert str(tag) == "我的世界"


def test_the_supported_shapes_match_the_model_declaration() -> None:
    """實作與宣告不能漂移。

    `model/strategy.py` 宣告「哪些形狀有實測依據」（extract 用它決定要不要排除），
    這裡是那些形狀的實作。少一邊就會出現「extract 說可以寫、寫入層卻拒絕」，
    或更糟的反向——extract 放行了一個寫入層會亂寫的形狀。
    """
    from mcmt.model.strategy import IN_PLACE_ENCODINGS
    from mcmt.write.in_place import SUPPORTED_ENCODINGS

    assert SUPPORTED_ENCODINGS == IN_PLACE_ENCODINGS


# --- legacy chunk 的形狀（DV < 4325，DataFixerUpper 會解析）----------------


def test_a_legacy_json_scalar_stays_a_json_scalar(project) -> None:
    """[遊戲實測 2026-08-21] DV 3700 的 CustomName 寫 `'"譯文"'`，容器標題顯示譯文。"""
    world = build_world(
        project, chest(amulet_nbt.StringTag('"Supply Crate"')), data_version=3700
    )

    outcome = apply_editplan(
        world, plan(edit(encoding="json_string_scalar", data_version=3700))
    )

    written = custom_name_of(world)
    assert outcome.counts["edits_written"] == 1
    assert isinstance(written, amulet_nbt.StringTag)
    assert str(written) == '"補給箱"'


def test_a_legacy_json_object_stays_a_json_object(project) -> None:
    world = build_world(
        project,
        chest(amulet_nbt.StringTag('{"text":"Supply Crate","color":"red"}')),
        data_version=3465,
    )

    apply_editplan(
        world, plan(edit(encoding="json_string_object", data_version=3465))
    )

    written = str(custom_name_of(world))
    assert json.loads(written) == {"text": "補給箱"}


def test_a_legacy_shape_is_never_swapped_for_a_bare_string(project) -> None:
    """**這一條是反面實測撐起來的。**

    [遊戲實測 2026-08-21] 在 DV 3700 的 CustomName 寫非 JSON 的裸字串，容器標題顯示
    的是原版預設名——那個欄位整個被丟掉了。所以在舊世代換形狀不只是不保守，是會
    悄無聲息地弄丟別人地圖上的名字。
    """
    world = build_world(
        project, chest(amulet_nbt.StringTag('"Supply Crate"')), data_version=3700
    )

    apply_editplan(world, plan(edit(encoding="json_string_scalar", data_version=3700)))

    assert str(custom_name_of(world)).startswith('"')


def test_a_json_array_shape_is_still_refused(project) -> None:
    """陣列形式沒測過，維持拒寫。"""
    world = build_world(
        project,
        chest(amulet_nbt.StringTag('["", {"text":"Supply Crate"}]')),
        data_version=3700,
    )

    outcome = apply_editplan(
        world, plan(edit(encoding="json_string_array", data_version=3700))
    )

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "unsupported_encoding"
