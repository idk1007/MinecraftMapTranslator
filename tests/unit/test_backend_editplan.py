# SPDX-License-Identifier: GPL-3.0-or-later
"""M10.3 editplan 產出（`backends/resourcepack/backend.py`）。

後端決定**值是什麼**，寫入層決定**怎麼安全地放進去**。editplan 是兩者之間那份
**可以檢查的中間產物**——`--dry-run` 靠它印出「打算改哪些節點、改成什麼」。
"""

import json
from pathlib import Path

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mcmt.backends.resourcepack.backend import build_editplan
from mcmt.extract.build import build_units
from mcmt.extract.emit import build_extract_document, build_translations_document

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


@pytest.fixture(scope="module")
def editplan_validator():
    registry = Registry()
    schemas = {}
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text("utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        schemas[path.name.split(".")[0]] = schema
    return Draft202012Validator(schemas["editplan"], registry=registry)


def sign(*lines, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag([amulet_nbt.StringTag(l) for l in lines])
    tag["front_text"] = face
    return tag


def prepare(tmp_path, *entities, data_version=4671):
    world = tmp_path / "world"
    root = modern_chunk(data_version=data_version)
    root["block_entities"] = amulet_nbt.ListTag(list(entities))
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    result = build_units(world)
    extract = build_extract_document(
        result,
        world_name="world",
        world_fingerprint="blake2b:0011223344556677",
        level_data_version=4671,
        namespace="mcmt",
        target_languages=["zh_tw"],
    )
    translations = build_translations_document(
        result, language="zh_tw", extract_document=extract
    )
    return extract, translations


def translate(translations, mapping):
    """把 `原文 → 譯文` 填進待翻檔，模擬使用者編輯。"""
    for entry in translations["entries"].values():
        if entry["source"] in mapping:
            entry["target"] = mapping[entry["source"]]
    return translations


# --- 合約驗證 -------------------------------------------------------------


def test_the_editplan_validates_against_the_schema(tmp_path, editplan_validator) -> None:
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translate(translations, {"歡迎光臨": "Welcome"})

    plan = build_editplan(extract, translations, language="zh_tw")

    errors = sorted(editplan_validator.iter_errors(plan.document), key=str)
    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors[:5]]


# --- 三種值 ---------------------------------------------------------------


def test_a_collapsible_unit_becomes_a_translate_value(tmp_path) -> None:
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translate(translations, {"歡迎光臨": "Welcome"})

    plan = build_editplan(extract, translations, language="zh_tw")

    (edit,) = plan.document["edits"]
    assert edit["value"]["kind"] == "translate"
    assert edit["value"]["key"] == extract["units"][0]["key"]


def test_the_lang_entry_carries_the_translation(tmp_path) -> None:
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translate(translations, {"歡迎光臨": "Welcome"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert list(plan.lang["zh_tw"].values()) == ["Welcome"]


def test_a_non_collapsible_unit_becomes_a_rebuilt_tree(tmp_path) -> None:
    """[實測] 84% 的 extra 子元素自帶格式——**不是原封搬運**，要照骨架長回去。"""
    entity = sign("", "", "", "")
    entity["front_text"]["messages"] = amulet_nbt.ListTag(
        [
            amulet_nbt.CompoundTag(
                {
                    "text": amulet_nbt.StringTag("點我"),
                    "click_event": amulet_nbt.CompoundTag(
                        {"action": amulet_nbt.StringTag("run_command")}
                    ),
                }
            )
        ]
    )
    extract, translations = prepare(tmp_path, entity)
    translate(translations, {"點我": "Click me"})

    plan = build_editplan(extract, translations, language="zh_tw")

    (edit,) = plan.document["edits"]
    assert edit["value"]["kind"] == "component"
    tree = edit["value"]["tree"]
    assert tree["translate"].endswith(".0")
    # 樣式要跟著長回去，不然點擊就沒了
    assert "click_event" in tree


def test_a_rebuilt_tree_keeps_the_nesting(tmp_path) -> None:
    entity = sign("", "", "", "")
    entity["front_text"]["messages"] = amulet_nbt.ListTag(
        [
            amulet_nbt.CompoundTag(
                {
                    "text": amulet_nbt.StringTag("父"),
                    "font": amulet_nbt.StringTag("minecraft:alt"),
                    "extra": amulet_nbt.ListTag(
                        [amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("子")})]
                    ),
                }
            )
        ]
    )
    extract, translations = prepare(tmp_path, entity)
    translate(translations, {"[[0]]父[[1]]子": "[[0]]parent[[1]]child"})

    plan = build_editplan(extract, translations, language="zh_tw")

    tree = plan.document["edits"][0]["value"]["tree"]
    assert tree["extra"][0]["translate"].endswith(".1")


def test_each_segment_of_a_rebuilt_tree_has_its_own_lang_key(tmp_path) -> None:
    entity = sign("", "", "", "")
    entity["front_text"]["messages"] = amulet_nbt.ListTag(
        [
            amulet_nbt.CompoundTag(
                {
                    "text": amulet_nbt.StringTag("父"),
                    "font": amulet_nbt.StringTag("minecraft:alt"),
                    "extra": amulet_nbt.ListTag(
                        [amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("子")})]
                    ),
                }
            )
        ]
    )
    extract, translations = prepare(tmp_path, entity)
    translate(translations, {"[[0]]父[[1]]子": "[[0]]parent[[1]]child"})

    plan = build_editplan(extract, translations, language="zh_tw")

    keys = sorted(plan.lang["zh_tw"])
    assert keys[0].endswith(".0") and keys[1].endswith(".1")


# --- 守門 -----------------------------------------------------------------


def test_every_edit_carries_the_expected_encoding(tmp_path) -> None:
    """寫入層拿它比對節點現在的形狀。使用者中間玩過一次遊戲，形狀就可能變了。"""
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translate(translations, {"歡迎光臨": "Welcome"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"][0]["expected_encoding"] == "bare_string"


def test_every_edit_carries_the_raw_snapshot(tmp_path) -> None:
    """寫入層要拿它比對節點現在的字面值，抓「形狀沒變但內容變了」——
    `expected_encoding` 那道守門對這種情況完全看不見。"""
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translate(translations, {"歡迎光臨": "Welcome"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"][0]["raw_snapshot"] == "歡迎光臨"


def test_an_untranslated_unit_produces_no_edit(tmp_path) -> None:
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"] == []
    assert plan.document["unwritten"][0]["reason"] == "untranslated"


def test_a_skipped_unit_is_recorded_as_skipped_not_untranslated(tmp_path) -> None:
    """「刻意不翻」與「忘了翻」在報告裡要分得開。"""
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    for entry in translations["entries"].values():
        entry["status"] = "skip"

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["unwritten"][0]["reason"] == "skipped"


def test_a_placeholder_mismatch_is_refused_not_written(tmp_path) -> None:
    """**hard fail。** 少一個標記就是 § 格式碼染到整行結尾。"""
    entity = sign("§a綠色§c紅色", "", "", "")
    extract, translations = prepare(tmp_path, entity)
    translate(translations, {"[[0]]綠色[[1]]紅色": "少了一個標記的譯文[[0]]"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"] == []
    assert plan.document["unwritten"][0]["reason"] == "placeholder_mismatch"
    assert plan.rejected


def test_a_stale_translation_file_is_refused(tmp_path) -> None:
    """世界或規則集變了就要重新 extract，硬套會安靜地對錯節點。"""
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translations["extract_ref"]["extract_fingerprint"] = "blake2b:deadbeefdeadbeef"

    with pytest.raises(ValueError) as exc:
        build_editplan(extract, translations, language="zh_tw")

    # 措辭改成給使用者看的（docs/error-messages-review.md A5）：指紋留在屬性裡，
    # 畫面上只說「請使用最新產生的翻譯檔」。
    assert exc.value.title == "翻譯檔與地圖不符"
    assert exc.value.found == "blake2b:deadbeefdeadbeef"


def test_a_schema_version_mismatch_is_refused(tmp_path) -> None:
    extract, translations = prepare(tmp_path, sign("歡迎光臨", "", "", ""))
    translations["schema_version"] = 999

    with pytest.raises(ValueError) as exc:
        build_editplan(extract, translations, language="zh_tw")

    assert "重新產生" in str(exc.value)


def test_one_unit_in_two_places_produces_two_edits(tmp_path) -> None:
    """翻一次，寫回每一個出現的地方。"""
    extract, translations = prepare(
        tmp_path, sign("歡迎光臨", "", "", ""), sign("歡迎光臨", "", "", "", x=9)
    )
    translate(translations, {"歡迎光臨": "Welcome"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert len(plan.document["edits"]) == 2
    assert len({e["occurrence_id"] for e in plan.document["edits"]}) == 2


# --- in_place：值是譯文，不是原文 -----------------------------------------


def chest(custom_name, *, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:chest")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    tag["CustomName"] = custom_name
    return tag


def test_an_in_place_edit_carries_the_translation_not_the_source(tmp_path) -> None:
    """這一條擋的是「in_place 把原文原封寫回去」——那會是一次沒有任何效果的
    存檔修改，而且看起來完全成功。"""
    extract, translations = prepare(
        tmp_path, chest(amulet_nbt.StringTag("Supply Crate"))
    )
    translate(translations, {"Supply Crate": "補給箱"})

    plan = build_editplan(extract, translations, language="zh_tw")

    (edit,) = plan.document["edits"]
    assert edit["value"] == {"kind": "literal", "text": "補給箱", "style": None}


def test_an_in_place_unit_puts_nothing_in_the_lang_file(tmp_path) -> None:
    """譯文住在存檔裡。再往 lang 檔塞一份就是兩個真相來源。"""
    extract, translations = prepare(
        tmp_path, chest(amulet_nbt.StringTag("Supply Crate"))
    )
    translate(translations, {"Supply Crate": "補給箱"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.lang["zh_tw"] == {}


def test_an_excluded_in_place_occurrence_produces_no_edit(tmp_path) -> None:
    """沒有實測依據的形狀不該進計畫。

    這裡用 JSON 陣列形式——舊世代的純量與物件在 2026-08-21 都驗過了，只剩陣列
    還沒有依據。
    """
    extract, translations = prepare(
        tmp_path,
        chest(amulet_nbt.StringTag('["", {"text":"Supply Crate"}]')),
        data_version=3700,
    )
    for entry in translations["entries"].values():
        entry["target"] = entry["source"]

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"] == []


def test_a_multi_segment_in_place_value_carries_inline_sigma_codes(tmp_path) -> None:
    """in_place 沒有結構可以掛樣式——多段只能轉成行內 § 碼，和塌縮的 lang 值一樣。"""
    extract, translations = prepare(
        tmp_path, chest(amulet_nbt.StringTag("§aGreen§cRed"))
    )
    translate(translations, {"[[0]]Green[[1]]Red": "[[0]]綠[[1]]紅"})

    plan = build_editplan(extract, translations, language="zh_tw")

    (edit,) = plan.document["edits"]
    assert edit["value"]["text"] == "§a綠§c紅"


# --- 寬度：校準完成後 sign 是 error，要真的擋 -----------------------------


def hanging(*lines, x=1, y=2, z=3):
    tag = sign(*lines, x=x, y=y, z=z)
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_hanging_sign")
    return tag


def test_a_translation_that_overflows_the_line_is_rejected(tmp_path) -> None:
    """校準完成前這裡只能 warn；量過之後 `error` 就得真的擋，否則那個欄位在說謊。"""
    extract, translations = prepare(tmp_path, hanging("Hi", "", "", ""))
    translate(translations, {"Hi": "這行中文字明顯太多了"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"] == []
    (refusal,) = plan.document["unwritten"]
    assert refusal["reason"] == "overflow_rejected"


def test_a_translation_that_exactly_fills_the_line_is_written(tmp_path) -> None:
    """[遊戲實測 2026-08-21] 吊掛告示牌放得下 6 個中文字。第 6 個不能被誤擋。"""
    extract, translations = prepare(tmp_path, hanging("Hi", "", "", ""))
    translate(translations, {"Hi": "六個中文字剛好"[:6]})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert len(plan.document["edits"]) == 1


def test_a_source_that_already_overflows_does_not_trap_the_translator(tmp_path) -> None:
    """原文本身就放不下是**地圖自己的排版**，不是我們造成的。

    這種節點上拒絕一個「不比原文寬」的譯文，等於要求譯者解一個原作者沒解的問題，
    而且無論他怎麼寫都過不了。
    """
    extract, translations = prepare(tmp_path, hanging("MMMMMMMMMMMMMMM", "", "", ""))
    translate(translations, {"MMMMMMMMMMMMMMM": "七個中文字放不下"[:7]})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert len(plan.document["edits"]) == 1


def test_a_translation_wider_than_an_already_overflowing_source_is_still_rejected(
    tmp_path,
) -> None:
    """豁免的界線是「不比原文更糟」，不是「原文超寬就整個不管」。"""
    extract, translations = prepare(tmp_path, hanging("MMMMMMMMMMMMMMM", "", "", ""))
    translate(translations, {"MMMMMMMMMMMMMMM": "十六個中文字絕對比原文還要寬得多了"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert plan.document["edits"] == []
    assert plan.document["unwritten"][0]["reason"] == "overflow_rejected"


def test_an_in_place_edit_ignores_a_tampered_strategy_field(tmp_path) -> None:
    """`unit["strategy"]` 是磁碟上 `extract.json` 讀來的值，使用者打得開。

    真正的權威是 `strategy_for(unit["category"])`——同一個 unit 裡就有 `category`，
    不必信任一個外部檔案裡可能被改壞的欄位。這裡把 `block_entity_name` 的
    `strategy` 竄改成 `translate_key`，值仍然必須是 in_place 的 `literal`，
    不能塌成 `{translate: key}` 寫進 native chunk（[遊戲實測 M11-3] 那樣寫出來
    玩家看到的是字面大括號）。
    """
    extract, translations = prepare(
        tmp_path, chest(amulet_nbt.StringTag("Supply Crate"))
    )
    translate(translations, {"Supply Crate": "補給箱"})
    assert extract["units"][0]["category"] == "block_entity_name"
    extract["units"][0]["strategy"] = "translate_key"

    plan = build_editplan(extract, translations, language="zh_tw")

    (edit,) = plan.document["edits"]
    assert edit["value"] == {"kind": "literal", "text": "補給箱", "style": None}
    assert plan.lang["zh_tw"] == {}


def test_a_category_without_a_width_budget_is_not_checked(tmp_path) -> None:
    """`block_entity_name` 是容器 GUI 的標題，沒有告示牌那種硬邊界。"""
    extract, translations = prepare(
        tmp_path, chest(amulet_nbt.StringTag("Supply Crate"))
    )
    translate(translations, {"Supply Crate": "這個名字非常非常非常長但是不該被擋下來"})

    plan = build_editplan(extract, translations, language="zh_tw")

    assert len(plan.document["edits"]) == 1
