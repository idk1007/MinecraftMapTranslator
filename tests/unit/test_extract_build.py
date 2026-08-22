# SPDX-License-Identifier: GPL-3.0-or-later
"""`extract/build.py` 的 `plain_string` 覆寫（M13.5）。

`LevelName` 根本不是 component——`sniff()` 只認值的形狀，猜不出「這個欄位不該被
當 JSON 猜」。世界名剛好以 `{`/`"`/`[` 開頭時，`sniff()` 會誤判成 JSON 並嘗試
解析，解析失敗就整個被當成 `unparseable_json` 跳過不翻（一個字都抽不出來，
使用者連在報告裡都看不到這個欄位存在過）。`_consider()` 用
`_FIELD_DETERMINED_ENCODING` 在 `sniff()` 跑完後立刻覆寫掉它的判斷，不等它先跑
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


# --- advancement 的欄位決定形狀（最終 review Finding 1） -------------------


def _advancement_world(tmp_path, **display):
    """一個只有一個資料夾式資料包的世界。回傳可讀根。"""
    import json

    path = tmp_path / "datapacks" / "p" / "data" / "n" / "advancement" / "a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"display": display}), encoding="utf-8")
    return tmp_path


def test_a_json_quoted_advancement_title_does_not_crash_extract(tmp_path) -> None:
    """**這是 review Finding 1 的重現。** `datapack.py` 的容器把 `data_version`
    填 `None`，並宣稱 advancement 的值永遠走不到 `_consider()` 的舊式 JSON 分支。
    那個宣稱是錯的：`sniff()` 照樣會對 `'"Only the brave."'` 這種「JSON 引號純量」
    判成 `json_string_scalar`，於是 `generation_of(None)` 在
    `None < DATAFIXER_WATERSHED` 當場 `TypeError`，**整次 extract 陣亡**。

    修正後：這個欄位由 category 決定形狀，根本不讓 sniff() 猜。
    """
    world = _advancement_world(tmp_path, title='"Only the brave."')

    result = build_units(world, world_root=ensure_readable(world))

    (title,) = [u for u in result.units if u.category == "advancement_title"]
    assert title.text == '"Only the brave."'
    assert title.occurrences[0].encoding == "bare_string"
    assert result.stats["skipped_legacy_json_in_native_chunk"] == 0
    assert result.stats["skipped_unparseable"] == 0


def test_a_bracketed_advancement_title_is_plain_text_not_broken_json(tmp_path) -> None:
    """`[Chapter 1] Beginning` 是一個完全正常的標題，只是剛好以 `[` 開頭。
    修正前它被 `sniff()` 判成 `json_string_array`、解析失敗、標成
    `unparseable_json`，然後以一個**錯的理由**被靜默跳過。"""
    world = _advancement_world(tmp_path, description="[Chapter 1] Beginning")

    result = build_units(world, world_root=ensure_readable(world))

    (description,) = [u for u in result.units if u.category == "advancement_description"]
    assert description.text == "[Chapter 1] Beginning"
    assert description.occurrences[0].encoding == "bare_string"
    assert result.stats["skipped_unparseable"] == 0


def test_a_component_shaped_advancement_title_is_still_sniffed(tmp_path) -> None:
    """覆寫只吃 `StringTag`——真的是 component 物件時照常走 sniff()，不能因為
    加了 category 覆寫就把整個 component 路徑關掉。"""
    world = _advancement_world(tmp_path, title={"text": "帶格式", "color": "gold"})

    result = build_units(world, world_root=ensure_readable(world))

    (title,) = [u for u in result.units if u.category == "advancement_title"]
    assert title.occurrences[0].encoding == "compound_tree"


def test_a_plain_text_compound_advancement_title_is_still_sniffed(tmp_path) -> None:
    world = _advancement_world(tmp_path, title={"text": "純文字物件"})

    result = build_units(world, world_root=ensure_readable(world))

    (title,) = [u for u in result.units if u.category == "advancement_title"]
    assert title.occurrences[0].encoding == "text_compound"


def test_the_advancement_override_is_bare_string_not_plain_string(tmp_path) -> None:
    """**這一條是把一個踩過的坑釘住。** 覆寫成 `plain_string`（照 `level_name`
    的樣子抄）會同時弄壞兩件事：

    * `extract.schema.json` 有一條機器強制的 `if/then`——任何 occurrence 的
      encoding 是 `plain_string`，這個 unit 的 strategy 就必須是 `in_place`。
      advancement 走 `translate_key`（原版自己的進度就是用 translate key），
      所以產出的 extract.json 直接通不過合約驗證。
    * 磁碟上那個值是裸字串，寫入端的守門會把每一筆 advancement 的 edit 都拒寫
      成 `node_changed`——一個字都寫不出去。
    """
    world = _advancement_world(tmp_path, title="正常標題", description="正常描述")

    result = build_units(world, world_root=ensure_readable(world))

    from mcmt.model.strategy import strategy_for

    units = [u for u in result.units if u.category.startswith("advancement_")]
    assert len(units) == 2
    for unit in units:
        assert strategy_for(unit.category) == "translate_key"
        assert unit.occurrences[0].encoding == "bare_string"
