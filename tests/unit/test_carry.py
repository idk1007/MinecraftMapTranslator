# SPDX-License-Identifier: GPL-3.0-or-later
"""重新抽取時沿用舊譯文（`extract --keep-translations`）。

譯文靠編號（`unit_id`）跟原文綁定，編號由原文內容算出來：原文變了編號就變了，
舊譯文就找不到對應的條目。所以「沿用」有兩個不能省的另一半——**列出對不上的
舊譯文**（地圖改了，這幾筆是白翻了還是該搬去別處，由人決定），以及**列出新出現
還沒翻的**。悶不吭聲地套用，就是 A5／A6 那類錯誤要擋的事。
"""

import json

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file
from test_cli_extract import build_world, sign

from mcmt.cli.__main__ import main
from mcmt.cli.extract import format_result, run_extract
from mcmt.extract.carry import carry_translations


def _doc(entries):
    return {
        "entries": entries,
        "stats": {"total": len(entries), "translated": 0, "untranslated": len(entries),
                  "skipped": 0, "rejected": 0},
    }


def _entry(source, target="", **extra):
    return {"source": source, "target": target, "note": "", "where": "x", **extra}


# --- 純函式 -------------------------------------------------------------------


def test_matching_ids_get_their_target_back() -> None:
    old = _doc({"u:a": _entry("Hello", "你好"), "u:b": _entry("Bye", "")})
    new = _doc({"u:a": _entry("Hello"), "u:b": _entry("Bye")})

    report = carry_translations(old, new)

    assert new["entries"]["u:a"]["target"] == "你好"
    assert new["entries"]["u:b"]["target"] == ""
    assert report.carried == 1
    assert report.orphans == []
    assert report.new_units == 0


def test_an_id_that_disappeared_is_listed_not_dropped_silently() -> None:
    """你的 Boss 血條那次：原文從「Heating the grill」變成「Display Setup」，舊譯文
    找不到對應條目。這種要明講，不能讓它無聲無息地消失。"""
    old = _doc({"u:old": _entry("Heating the grill", "預熱烤架", where="level.dat")})
    new = _doc({"u:new": _entry("Display Setup", where="level.dat")})

    report = carry_translations(old, new)

    assert report.carried == 0
    assert [(o.source, o.target, o.where) for o in report.orphans] == [
        ("Heating the grill", "預熱烤架", "level.dat")
    ]
    assert report.new_units == 1
    assert new["entries"]["u:new"]["target"] == ""


def test_an_unfilled_old_entry_that_disappeared_is_not_an_orphan() -> None:
    """沒填過的東西消失了不算「對不上的譯文」——沒有東西白翻。"""
    old = _doc({"u:gone": _entry("Nothing here", "")})
    new = _doc({})

    report = carry_translations(old, new)

    assert report.orphans == []


def test_skip_status_is_carried_too() -> None:
    """「刻意不翻」是使用者的決定，跟譯文一樣不該因為重抽而消失。"""
    old = _doc({"u:a": _entry("@", "", status="skip")})
    new = _doc({"u:a": _entry("@")})

    report = carry_translations(old, new)

    assert new["entries"]["u:a"]["status"] == "skip"
    assert report.carried == 1


def test_the_stats_are_recomputed() -> None:
    old = _doc({"u:a": _entry("A", "甲"), "u:b": _entry("B", "", status="skip")})
    new = _doc({"u:a": _entry("A"), "u:b": _entry("B"), "u:c": _entry("C")})

    carry_translations(old, new)

    assert new["stats"] == {
        "total": 3, "translated": 1, "untranslated": 1, "skipped": 1, "rejected": 0,
    }


def test_new_note_and_where_are_kept_not_overwritten_by_old() -> None:
    """備註與位置是工具重新算的（字寬預算、出現次數），不是使用者填的。"""
    old = _doc({"u:a": _entry("A", "甲", note="舊備註", where="舊位置")})
    new = _doc({"u:a": {"source": "A", "target": "", "note": "新備註", "where": "新位置"}})

    carry_translations(old, new)

    assert new["entries"]["u:a"]["note"] == "新備註"
    assert new["entries"]["u:a"]["where"] == "新位置"


# --- 接上 extract ---------------------------------------------------------------


def _fill_first_target(path, text):
    document = json.loads(path.read_text(encoding="utf-8"))
    first = next(iter(document["entries"]))
    document["entries"][first]["target"] = text
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return first


def test_keep_translations_carries_the_old_targets(project) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")

    summary = run_extract(world, replace=True, keep_translations=True)

    document = json.loads(summary["translations_path"].read_text(encoding="utf-8"))
    assert "我辛苦翻的" in {e["target"] for e in document["entries"].values()}
    assert summary["carry"].carried == 1
    assert summary["carry"].orphans == []


def test_without_keep_translations_everything_starts_blank(project) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")

    summary = run_extract(world, replace=True)

    document = json.loads(summary["translations_path"].read_text(encoding="utf-8"))
    assert all(e["target"] == "" for e in document["entries"].values())
    assert summary["carry"] is None


def test_keep_translations_reports_what_no_longer_matches(project) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")
    # 地圖變了：告示牌換了一句話，舊原文從地圖裡消失。
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign("完全不同的一句", "", "", "")])
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    summary = run_extract(world, replace=True, keep_translations=True)

    carry = summary["carry"]
    assert carry.carried == 0
    assert [o.target for o in carry.orphans] == ["我辛苦翻的"]
    assert carry.new_units >= 1


def test_the_old_file_survives_as_a_backup_even_when_carrying(project) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")

    run_extract(world, replace=True, keep_translations=True)

    backups = list(first["translations_path"].parent.glob("*.bak-*"))
    assert any("我辛苦翻的" in b.read_text(encoding="utf-8") for b in backups)


def test_a_previous_apply_report_does_not_outlive_a_re_extract(project) -> None:
    """重新抽取後，舊的 apply_report.json 描述的是上一輪的結果。留著的話，
    同一張未改動的地圖重抽出同樣的指紋，舊報告會讓流程誤以為「已經寫回過」。"""
    world = build_world(project)
    first = run_extract(world)
    out = first["translations_path"].parent
    (out / "apply_report.json").write_text('{"outcome": "applied"}', encoding="utf-8")
    (out / "editplan.json").write_text("{}", encoding="utf-8")

    run_extract(world, replace=True)

    assert not (out / "apply_report.json").exists()
    assert not (out / "editplan.json").exists()
    assert list(out.glob("apply_report.json.bak-*"))


def test_the_summary_lists_the_orphans_and_the_backup(project) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign("完全不同的一句", "", "", "")])
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    text = format_result(run_extract(world, replace=True, keep_translations=True))

    assert "對不上" in text
    assert "我辛苦翻的" in text
    assert "新出現" in text
    assert ".bak-" in text


# --- CLI ------------------------------------------------------------------------


def test_cli_flag_keeps_the_old_targets(project, capsys) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")

    code = main(["extract", str(world), "--replace", "--keep-translations"])

    document = json.loads(first["translations_path"].read_text(encoding="utf-8"))
    assert code == 0
    assert "我辛苦翻的" in {e["target"] for e in document["entries"].values()}


def test_cli_asks_whether_to_keep_after_agreeing_to_overwrite(project, monkeypatch) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")
    answers = iter(["y", "y"])  # 是否覆蓋？y　是否保留舊譯文？y
    prompts: list[str] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": (prompts.append(prompt), next(answers))[1])

    code = main(["extract", str(world)])

    document = json.loads(first["translations_path"].read_text(encoding="utf-8"))
    assert code == 0
    assert len(prompts) == 2
    assert "保留舊譯文" in prompts[1]
    assert "我辛苦翻的" in {e["target"] for e in document["entries"].values()}


def test_cli_answering_no_to_keep_starts_blank(project, monkeypatch) -> None:
    world = build_world(project)
    first = run_extract(world)
    _fill_first_target(first["translations_path"], "我辛苦翻的")
    answers = iter(["y", "n"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    main(["extract", str(world)])

    document = json.loads(first["translations_path"].read_text(encoding="utf-8"))
    assert all(e["target"] == "" for e in document["entries"].values())


def test_keep_translations_without_an_existing_file_is_harmless(project) -> None:
    world = build_world(project)

    summary = run_extract(world, keep_translations=True)

    assert summary["carry"] is None
    assert summary["translations_path"].is_file()
