# SPDX-License-Identifier: GPL-3.0-or-later
"""`extract/build.py` 的 `plain_string` 覆寫（M13.5）。

`LevelName` 根本不是 component——`sniff()` 只認值的形狀，猜不出「這個欄位不該被
當 JSON 猜」。世界名剛好以 `{`/`"`/`[` 開頭時，`sniff()` 會誤判成 JSON 並嘗試
解析，解析失敗就整個被當成 `unparseable_json` 跳過不翻（一個字都抽不出來，
使用者連在報告裡都看不到這個欄位存在過）。`_consider()` 用
`_PLAIN_STRING_CATEGORIES` 在 `sniff()` 跑完後立刻覆寫掉它的判斷，不等它先跑
一輪再事後修正。

這個檔案沒有走合成 chunk（`test_extract_custom_name.py` 那一套 `RegionBuilder`）
的路，因為要測的欄位住在 `level.dat` 而不是 region——走 `sandbox.import_world` +
`build_units` 讓測試真的穿過 `scan.registry.SOURCES` 那個迴圈（包含新掛上的
`level_dat.scan`），而不是繞過它直接建構節點。
"""

import gzip

import amulet_nbt

from mcmt.extract.build import build_units
from mcmt.safety.paths import ensure_readable
from mcmt.sandbox import import_world


def test_a_level_name_that_looks_like_json_is_not_mistaken_for_one(project) -> None:
    """**這是 `plain_string` 存在的理由。** `LevelName` 根本不是 component，
    但它的值和一行裸字串告示牌長得一模一樣——世界名剛好以 `{` 開頭時，
    `sniff()` 會誤判成 JSON 並嘗試解析，解析失敗就整個被當成
    `unparseable_json` 跳過不翻。這個欄位不該被 sniff() 的 JSON 偵測猜。

    `source` 刻意落在 sandbox 之外（模擬使用者真正的存檔位置）——所以這裡直接寫
    位元組，不走 `write_dat`（它會過 `ensure_writable`，只認 sandbox 底下的路徑）。
    只有 `import_world` 的目標端需要在 sandbox 裡，那由 `import_world` 自己保證。
    """
    source = project / "outside" / "TT_JSON_LOOKING_NAME"
    (source / "region").mkdir(parents=True)
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag("{這不是JSON只是剛好用大括號開頭}"),
            "DataVersion": amulet_nbt.IntTag(4671),
        }
    )
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({"Data": data}), "")
    payload = tag.save_to(compressed=False)
    (source / "level.dat").write_bytes(gzip.compress(payload))

    imported = import_world(source, name="json_looking_name")
    result = build_units(imported.target, world_root=ensure_readable(imported.target))

    level_name_units = [u for u in result.units if u.category == "level_name"]
    assert len(level_name_units) == 1
    assert level_name_units[0].occurrences[0].encoding == "plain_string"
    assert result.stats["skipped_unparseable"] == 0


def test_a_node_that_is_already_localised_via_translate_is_skipped(tmp_path, project) -> None:
    """MP2 這類自己有中文化系統的地圖，`{translate:"mcp.X"}` 不該被我們的 key
    覆蓋掉——翻了會讓一張支援 5 種語言的地圖退化成只支援一種。"""
    import amulet_nbt

    from mcmt.extract.build import build_units
    from mcmt.sandbox import import_world

    source = tmp_path / "outside" / "TT_ALREADY_LOCALISED"
    (source / "region").mkdir(parents=True)
    sign = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:oak_sign")})
    for coordinate in ("x", "y", "z"):
        sign[coordinate] = amulet_nbt.IntTag(1)
    localised = amulet_nbt.CompoundTag(
        {"translate": amulet_nbt.StringTag("mcp.SignStartSlot"), "fallback": amulet_nbt.StringTag("Start")}
    )
    blank = amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("")})
    face = amulet_nbt.CompoundTag(
        {"messages": amulet_nbt.ListTag([localised, blank, blank, blank])}
    )
    sign["front_text"] = face
    from conftest import RegionBuilder, modern_chunk, write_region_file

    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign])
    write_region_file(source / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    imported = import_world(source, name="already_localised")
    result = build_units(imported.target, world_root=ensure_readable(imported.target))

    assert all("mcp.SignStartSlot" not in u.text for u in result.units)
    assert result.stats["skipped_already_localised"] == 1


def test_a_half_localised_tree_is_also_skipped(tmp_path, project) -> None:
    """半文字半 key 的樹——重建時一樣會覆蓋掉那個巢狀 key，所以「任何一處」
    而不是「根節點是」。"""
    import amulet_nbt

    from mcmt.extract.build import build_units
    from mcmt.sandbox import import_world

    source = tmp_path / "outside" / "TT_HALF_LOCALISED"
    (source / "region").mkdir(parents=True)
    sign = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:oak_sign")})
    for coordinate in ("x", "y", "z"):
        sign[coordinate] = amulet_nbt.IntTag(1)
    nested = amulet_nbt.CompoundTag(
        {
            "text": amulet_nbt.StringTag("Hello "),
            "extra": amulet_nbt.ListTag(
                [amulet_nbt.CompoundTag({"translate": amulet_nbt.StringTag("mcp.X")})]
            ),
        }
    )
    blank = amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("")})
    face = amulet_nbt.CompoundTag(
        {"messages": amulet_nbt.ListTag([nested, blank, blank, blank])}
    )
    sign["front_text"] = face
    from conftest import RegionBuilder, modern_chunk, write_region_file

    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign])
    write_region_file(source / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    imported = import_world(source, name="half_localised")
    result = build_units(imported.target, world_root=ensure_readable(imported.target))

    assert result.stats["skipped_already_localised"] == 1
    assert result.units == []
