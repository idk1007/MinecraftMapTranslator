# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt extract` 的命令列外殼（M7.3）。

產出三個檔案，全部在 sandbox 底下、**與世界資料夾平行**——世界資料夾不多出任何東西，
「除了要改的地方以外什麼都沒動」才會是可以整包比對驗證的。
"""

import gzip
import json
from pathlib import Path

import amulet_nbt
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.cli.__main__ import main
from mcmt.cli.extract import format_result
from mcmt.extract.build import ExtractResult


def sign(*lines, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag([amulet_nbt.StringTag(l) for l in lines])
    tag["front_text"] = face
    return tag


def build_world(project, *, name="world"):
    world = project / "sandbox" / name
    root = modern_chunk(data_version=4671)
    entity = sign("歡迎光臨", "前方危險", "", "")
    root["block_entities"] = amulet_nbt.ListTag([entity])
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())

    data = amulet_nbt.CompoundTag()
    data["LevelName"] = amulet_nbt.StringTag(name)
    data["DataVersion"] = amulet_nbt.IntTag(4671)
    level = amulet_nbt.CompoundTag()
    level["Data"] = data
    (world / "level.dat").write_bytes(
        gzip.compress(amulet_nbt.NamedTag(level, "").save_to(compressed=False), mtime=0)
    )
    return world


def out_dir(project, name="world"):
    return project / "sandbox" / ".mcmt-out" / name


def test_extract_writes_three_files(project, capsys) -> None:
    world = build_world(project)

    code = main(["extract", str(world)])

    assert code == 0
    for filename in ("extract.json", "translations.zh_tw.json", "keymap.json"):
        assert (out_dir(project) / filename).is_file(), filename


def test_the_world_folder_gains_nothing(project) -> None:
    """產出與世界平行，不塞進世界裡。"""
    world = build_world(project)
    before = sorted(p.name for p in world.rglob("*"))

    main(["extract", str(world)])

    assert sorted(p.name for p in world.rglob("*")) == before


def test_the_translation_file_is_ready_to_edit(project) -> None:
    world = build_world(project)

    main(["extract", str(world)])

    document = json.loads(
        (out_dir(project) / "translations.zh_tw.json").read_text("utf-8")
    )
    sources = {e["source"] for e in document["entries"].values()}
    # `build_world` 的 level.dat 帶 `LevelName: "world"`——M13.5 掛上
    # `level_dat.scan` 之後這個欄位第一次被掃到，多出一個 `level_name` 單位。
    assert sources == {"歡迎光臨", "前方危險", "world"}
    assert all(e["target"] == "" for e in document["entries"].values())


def test_the_report_says_what_it_found(project, capsys) -> None:
    world = build_world(project)

    main(["extract", str(world)])

    out = capsys.readouterr().out
    assert "2" in out  # 兩個單位
    assert "translations.zh_tw.json" in out


def test_a_custom_language_and_namespace_are_honoured(project) -> None:
    world = build_world(project)

    main(["extract", str(world), "--lang", "ja_jp", "--namespace", "mymap"])

    assert (out_dir(project) / "translations.ja_jp.json").is_file()
    extract = json.loads((out_dir(project) / "extract.json").read_text("utf-8"))
    assert extract["project"]["namespace"] == "mymap"
    assert extract["units"][0]["key"].startswith("mymap.")


def test_extracting_a_world_outside_the_sandbox_still_works(project) -> None:
    """讀取不限 sandbox（`doctor` 與 `extract` 都要讀 .minecraft），只有寫入限。"""
    world = build_world(project, name="outside")
    moved = project / "elsewhere"
    world.rename(moved)

    assert main(["extract", str(moved)]) == 0
    assert (project / "sandbox" / ".mcmt-out" / "elsewhere" / "extract.json").is_file()


def test_a_missing_world_exits_nonzero_without_a_traceback(project, capsys) -> None:
    code = main(["extract", str(project / "沒有這個世界")])

    assert code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_refusing_to_overwrite_without_replace(project, capsys) -> None:
    """辛苦翻了一半的檔案不該被重跑一次 extract 洗掉。"""
    world = build_world(project)
    main(["extract", str(world)])
    target = out_dir(project) / "translations.zh_tw.json"
    document = json.loads(target.read_text("utf-8"))
    first = next(iter(document["entries"]))
    document["entries"][first]["target"] = "我翻好的字"
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    code = main(["extract", str(world)])

    assert code == 2
    assert "--replace" in capsys.readouterr().err
    assert "我翻好的字" in target.read_text("utf-8")


def test_replace_overwrites(project) -> None:
    world = build_world(project)
    main(["extract", str(world)])

    assert main(["extract", str(world), "--replace"]) == 0


def test_a_corrupt_level_dat_is_reported_not_silently_ignored(project, capsys) -> None:
    """**review Finding 4 的重現。** `skipped_level_dat` 只累積在 `result.stats`
    裡，沒有任何一條路把它帶到使用者眼前——一個讀不下去的 `level.dat` 印出來的
    摘要和「這個世界沒有東西可翻」一模一樣，而前者代表世界名、boss 條、玩家
    背包**整個沒被掃到**。"""
    world = build_world(project, name="corrupt")
    (world / "level.dat").write_bytes(b"\x1f\x8bnot a real gzip stream".ljust(40, b"\x00"))

    assert main(["extract", str(world)]) == 0

    out = capsys.readouterr().out
    assert "level.dat 讀不下去" in out

    extract = json.loads((out_dir(project, "corrupt") / "extract.json").read_text("utf-8"))
    assert extract["stats"]["skipped_level_dat"] == 1


# --- format_result()：摘要渲染器本身 ---------------------------------------
#
# 這個函式在 2026-09-06 之前**一條測試都沒有**（`grep -rn format_result tests/`
# 什麼都找不到）。它是使用者唯一看得到的東西：跳過了多少節點、為什麼跳過，全靠
# 它印出來。一個沒被印出來的計數器，跟那個節點根本沒被掃到，對使用者是同一件事。
#
# `cli/extract.py` 對 `stats` 做的是**裸鍵查詢**（`stats["skipped_command_…"]`），
# 而 `docs/contracts/extract.schema.json` 的 `stats` 刻意沒有 `required` 清單。
# 今天 `extract/emit.py` 一定會寫這三個鍵，所以會動；這幾條測試就是釘住「一定會
# 寫」這件事，而不是去合約裡加一個選擇性的 `required`（那會跟其他欄位不一致）。


def _summary(**stat_overrides) -> dict:
    """一份最小但**欄位齊全**的 summary——刻意不用 `Counter` 當 `extract.stats`。

    `Counter` 對缺鍵回傳 0，用它當 fixture 的話「渲染器查了一個 emit 根本沒寫的
    鍵」這種 bug 會被靜默吸收掉，測試永遠是綠的。這裡用普通 `dict`，少一個鍵就
    `KeyError`——這正是我們要它會痛的地方。
    """
    stats = {
        "unit_count": 3,
        "occurrence_count": 5,
        "deduped_count": 2,
        "by_category": {"sign_text": 3},
        "skipped_legacy_json_in_native_chunk": 0,
        "skipped_unparseable": 0,
        "skipped_already_localised": 0,
        "skipped_unsupported_structure": 0,
        "skipped_command_unsupported_shape": 0,
        "skipped_command_nested_reference": 0,
        "skipped_command_line_continuation": 0,
    }
    stats.update(stat_overrides)
    result = ExtractResult(chunks=7, text_nodes=9)
    # `result.stats` 在真實產物裡就是 `Counter`（`ExtractResult` 的預設），這裡
    # 照原樣，只有 `extract["stats"]` 那半刻意換成嚴格的 dict。
    return {
        "world": Path("sandbox") / "w",
        "out": Path("sandbox") / ".mcmt-out" / "w",
        "language": "zh_tw",
        "result": result,
        "extract": {"stats": stats},
        "translations_path": Path("sandbox") / ".mcmt-out" / "w" / "translations.zh_tw.json",
    }


def test_format_result_renders_the_three_command_skip_lines_when_they_are_non_zero() -> None:
    """三個指令 skip 計數器不是 0 的時候，摘要必須印出中文標籤。

    它們是「刻意跳過」而不是「失敗」，但**看不見的刻意跳過等於漏抽**——使用者
    要能從摘要看出「這張地圖有 2,613 個 mcfunction，其中這麼多條的動詞不在
    白名單」。
    """
    text = format_result(
        _summary(
            skipped_command_unsupported_shape=12,
            skipped_command_nested_reference=3,
            skipped_command_line_continuation=7,
        )
    )

    # 每個數字必須出現在**它自己那一行**（label 與 count 同一行印出），
    # 而不是隨便散落在摘要某處——`"3"` / `"7"` 在「翻譯單位：3 個」「掃過
    # chunk 7 個」裡本來就有，裸的 `"3" in text` 什麼都沒驗到。
    def line_with(label: str) -> str:
        return next(ln for ln in text.splitlines() if label in ln)

    assert "12" in line_with("暫不支援文字抽取的指令")
    assert "3" in line_with("指令巢狀引用另一條指令（L3，未支援）")
    assert "7" in line_with("指令行尾反斜線延續（1.20.2+ 語法，未支援）")


def test_format_result_warns_about_skipped_unsupported_structure_chunks() -> None:
    """**Against Iskerside 的重現。** 這個計數器不是 0 時，代表這張地圖是混合
    世代——`doctor` 會拒絕整個世界，但 `extract`／`apply` 選擇跳過那些 chunk
    並繼續（使用者要的是「警告後仍可繼續」，不是強制中止），所以警告只能靠
    這一行印出來；沒有它，使用者拿到的摘要和「整個世界都掃到了」一模一樣，
    而地圖裡有幾百上千個 chunk 從未被翻譯過。"""
    text = format_result(_summary(skipped_unsupported_structure=1519))

    def line_with(label: str) -> str:
        return next(ln for ln in text.splitlines() if label in ln)

    assert "1,519" in line_with("舊格式區塊")


def test_format_result_omits_the_command_skip_lines_when_they_are_zero() -> None:
    """0 的時候不印——`if n` 過濾器。一張沒有指令文字的地圖不該被三行
    「跳過 0 個」洗版，那會讓真正有數字的那幾行更難被看到。"""
    text = format_result(_summary())

    assert "暫不支援文字抽取的指令" not in text
    assert "指令巢狀引用另一條指令" not in text
    assert "指令行尾反斜線延續" not in text
    # 整個「跳過的節點」區塊在全部都是 0 的時候根本不該出現。
    assert "跳過的節點" not in text


def test_format_result_always_renders_the_things_the_user_needs_next() -> None:
    """摘要的另一半職責：告訴使用者**下一步做什麼**。這幾行沒了，使用者拿到
    三個檔案卻不知道該編輯哪一個。"""
    summary = _summary()
    text = format_result(summary)

    assert str(summary["world"]) in text
    assert "translations.zh_tw.json" in text
    assert "編輯這個檔案" in text
    assert "mcmt apply" in text
    assert "翻譯單位：3 個" in text


def test_format_result_does_not_swallow_a_missing_stats_key() -> None:
    """**這條測試守的是這份 fixture 本身。**

    合約的 `stats` 沒有 `required` 清單，渲染器卻做裸鍵查詢——今天成立是因為
    `extract/emit.py` 一定會寫。如果哪天有人把某個鍵從 emit 拿掉，這裡要爆炸而
    不是印出一份少一行的摘要。用 `Counter` 當 fixture 就會把它吸收掉，所以這條
    測試把「少一個鍵會痛」這件事本身釘起來。
    """
    import pytest

    summary = _summary()
    del summary["extract"]["stats"]["skipped_command_nested_reference"]

    with pytest.raises(KeyError):
        format_result(summary)
