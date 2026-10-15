# SPDX-License-Identifier: GPL-3.0-or-later
"""拖入一張地圖之後發生什麼（`mcmt/flow.py`）。

流程邏輯跟畫面完全分開：這裡用一個假的介面（`FakeUi`）腳本化「使用者按了哪個
按鈕」，驗證每個狀態下流程做了什麼、**沒做什麼**——特別是會刪東西的那幾步（重新
開始）要在動手之前就把能失敗的事都檢查完。真正的視窗只有人實際拖一次才驗得到。
"""

import json
import shutil
from pathlib import Path

import amulet_nbt
import pytest
from conftest import RegionBuilder, legacy_chunk, modern_chunk, write_region_file
from test_cli_extract import build_world, sign

from mcmt.errors import (
    ExternalChunksFoundError,
    NotAWorldError,
    OriginMissingError,
    WorldChangedSinceExtractError,
)
from mcmt.flow import run_flow


class FakeUi:
    """按劇本回答。沒腳本的提問一律讓測試失敗——流程多問了一個沒人預期的問題，
    在真的視窗裡就是多跳一個對話框。"""

    def __init__(self, answers=None, *, language="zh_tw"):
        self.answers = dict(answers or {})
        self.language = language
        self.logs: list[str] = []
        self.asked: list[tuple[str, str, tuple[str, ...]]] = []
        self.opened: list[Path] = []
        self.language_asked = 0

    def log(self, message):
        self.logs.append(message)

    def ask(self, title, body, buttons):
        self.asked.append((title, body, tuple(buttons)))
        if title not in self.answers:
            raise AssertionError(f"沒預期到的提問：{title!r}\n{body}")
        answer = self.answers[title]
        if isinstance(answer, list):  # 同一個標題問第二次要有不同答案
            answer = answer.pop(0)
        assert answer is None or answer in buttons, (answer, buttons)
        return answer

    def choose_language(self, default):
        self.language_asked += 1
        return self.language

    def open_path(self, path):
        self.opened.append(Path(path))

    @property
    def titles(self):
        return [title for title, _, _ in self.asked]


def make_original(project, name="world"):
    """一張在沙盒外面的「原存檔」。"""
    build_world(project, name=name)
    target = project / "saves" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(project / "sandbox" / name), str(target))
    return target


def out_dir(project, name="world"):
    return project / "sandbox" / ".mcmt-out" / name


def translations_file(project, name="world", language="zh_tw"):
    return out_dir(project, name) / f"translations.{language}.json"


def fill_all(project, name="world", language="zh_tw", text="你好\n再見"):
    path = translations_file(project, name, language)
    document = json.loads(path.read_text(encoding="utf-8"))
    for entry in document["entries"].values():
        entry["target"] = text
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return document


READY = {"準備寫回": "寫回", "完成": "關閉"}


# --- 第一次拖入 -----------------------------------------------------------------


def test_a_fresh_drop_imports_extracts_and_asks_for_translations(project) -> None:
    original = make_original(project)
    ui = FakeUi({"請填寫翻譯檔": "關閉"})

    outcome = run_flow(original, ui)

    assert outcome.kind == "extracted"
    assert (project / "sandbox" / "world" / "region").is_dir()
    assert translations_file(project).is_file()
    assert ui.titles == ["請填寫翻譯檔"]
    assert "translations.zh_tw.json" in ui.asked[0][1]
    assert ui.logs  # 處理過程有進度可看


def test_the_original_is_never_touched(project) -> None:
    original = make_original(project)
    before = sorted((p.relative_to(original), p.stat().st_size) for p in original.rglob("*"))

    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))

    after = sorted((p.relative_to(original), p.stat().st_size) for p in original.rglob("*"))
    assert after == before


def test_the_chosen_language_names_the_file(project) -> None:
    original = make_original(project)
    ui = FakeUi({"請填寫翻譯檔": "關閉"}, language="en_us")

    run_flow(original, ui)

    assert translations_file(project, language="en_us").is_file()
    assert not translations_file(project).exists()


def test_cancelling_the_language_choice_imports_nothing(project) -> None:
    original = make_original(project)
    ui = FakeUi(language=None)

    outcome = run_flow(original, ui)

    assert outcome.kind == "cancelled"
    assert not (project / "sandbox" / "world").exists()


def test_the_open_folder_button_opens_the_translations_folder(project) -> None:
    original = make_original(project)
    ui = FakeUi({"請填寫翻譯檔": "開啟資料夾"})

    run_flow(original, ui)

    assert ui.opened == [out_dir(project)]


# --- 閘門：.mcc 硬中止、舊格式問一聲 ---------------------------------------------


def test_an_external_chunk_stops_everything_before_anything_is_imported(project) -> None:
    original = make_original(project)
    write_region_file(
        original / "entities", RegionBuilder().add(0, b"", compression_byte=0x82).build()
    )

    with pytest.raises(ExternalChunksFoundError) as caught:
        run_flow(original, FakeUi())

    assert "未變更任何檔案" in str(caught.value)
    assert not (project / "sandbox" / "world").exists()


def _add_legacy_region(world):
    write_region_file(
        world / "region",
        RegionBuilder().add_chunk_nbt(5, legacy_chunk()).build(),
        name="r.1.0.mca",
    )


def test_legacy_chunks_are_confirmed_and_declining_changes_nothing(project) -> None:
    original = make_original(project)
    _add_legacy_region(original)
    ui = FakeUi({"包含舊格式區塊": "取消"})

    outcome = run_flow(original, ui)

    assert outcome.kind == "cancelled"
    assert "1 個舊格式區塊" in ui.asked[0][1]
    assert not (project / "sandbox" / "world").exists()


def test_legacy_chunks_can_be_accepted_and_the_rest_is_processed(project) -> None:
    original = make_original(project)
    _add_legacy_region(original)
    ui = FakeUi({"包含舊格式區塊": "繼續", "請填寫翻譯檔": "關閉"})

    outcome = run_flow(original, ui)

    assert outcome.kind == "extracted"
    assert translations_file(project).is_file()


def test_a_folder_that_is_not_a_world_gets_the_plain_message(project) -> None:
    (project / "saves" / "nothing").mkdir(parents=True)

    with pytest.raises(NotAWorldError):
        run_flow(project / "saves" / "nothing", FakeUi())


def test_dropping_the_output_folder_explains_where_the_world_is(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))

    with pytest.raises(NotAWorldError) as caught:
        run_flow(out_dir(project), FakeUi())

    assert "輸出資料夾" in str(caught.value)


# --- 第二次拖入：有沒有譯文 -------------------------------------------------------


def test_untouched_translations_are_not_overwritten_or_reextracted(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    before = translations_file(project).read_bytes()
    ui = FakeUi({"還沒有譯文": "關閉"})

    outcome = run_flow(original, ui)

    assert outcome.kind == "nothing_to_do"
    assert translations_file(project).read_bytes() == before
    assert not list(out_dir(project).glob("*.bak-*"))
    assert ui.language_asked == 0  # 已經有翻譯檔，不再問語言


def test_filled_translations_are_applied_after_a_confirmation(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    ui = FakeUi(READY)

    outcome = run_flow(original, ui)

    assert outcome.kind == "applied"
    assert (project / "sandbox" / "world" / "resources.zip").is_file()
    assert ui.titles == ["準備寫回", "完成"]
    assert "寫入" in ui.asked[0][1]
    assert "備份" in ui.asked[0][1]
    assert "saves" in ui.asked[1][1]  # 提醒要自己複製回去


def test_cancelling_the_confirmation_writes_nothing(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    before = sorted(
        (p.relative_to(project / "sandbox" / "world"), p.read_bytes())
        for p in (project / "sandbox" / "world").rglob("*")
        if p.is_file()
    )

    outcome = run_flow(original, FakeUi({"準備寫回": "取消"}))

    after = sorted(
        (p.relative_to(project / "sandbox" / "world"), p.read_bytes())
        for p in (project / "sandbox" / "world").rglob("*")
        if p.is_file()
    )
    assert outcome.kind == "cancelled"
    assert after == before
    assert not (project / "sandbox" / "world" / "resources.zip").exists()


def test_the_report_button_opens_the_report_and_asks_again(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    ui = FakeUi({"準備寫回": ["查看報告", "寫回"], "完成": "關閉"})

    outcome = run_flow(original, ui)

    assert outcome.kind == "applied"
    assert ui.opened == [out_dir(project) / "apply_report.json"]
    assert ui.titles == ["準備寫回", "準備寫回", "完成"]


def test_a_world_changed_after_extract_is_refused_before_asking(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign("被改過", "", "", "")])
    write_region_file(
        project / "sandbox" / "world" / "region",
        RegionBuilder().add_chunk_nbt(0, root).build(),
    )
    ui = FakeUi()

    with pytest.raises(WorldChangedSinceExtractError):
        run_flow(original, ui)

    assert ui.asked == []


def test_a_half_filled_file_applies_only_what_is_filled(project) -> None:
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    path = translations_file(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    first = next(iter(document["entries"].values()))
    first["target"] = "你好\n再見"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    ui = FakeUi(READY)

    outcome = run_flow(original, ui)

    assert outcome.kind == "applied"


# --- 已經寫回過：重新開始 ---------------------------------------------------------


def applied_world(project):
    original = make_original(project)
    run_flow(original, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    run_flow(original, FakeUi(READY))
    return original


def test_dropping_an_applied_world_asks_before_starting_over(project) -> None:
    original = applied_world(project)

    outcome = run_flow(original, FakeUi({"重新開始？": "取消"}))

    assert outcome.kind == "cancelled"
    assert (project / "sandbox" / "world" / "resources.zip").is_file()  # 沒動


def test_starting_over_and_keeping_the_old_translations(project) -> None:
    original = applied_world(project)
    ui = FakeUi({"重新開始？": "重新開始", "保留舊譯文？": "保留舊譯文", "請填寫翻譯檔": "關閉"})

    outcome = run_flow(original, ui)

    document = json.loads(translations_file(project).read_text(encoding="utf-8"))
    assert outcome.kind == "extracted"
    assert not (project / "sandbox" / "world" / "resources.zip").exists()  # 重新匯入了
    assert {e["target"] for e in document["entries"].values()} == {"你好\n再見"}
    assert list(out_dir(project).glob("translations.zh_tw.json.bak-*"))
    assert ui.language_asked == 0  # 沿用上次的語言


def test_starting_over_from_scratch_blanks_the_translations(project) -> None:
    original = applied_world(project)
    ui = FakeUi({"重新開始？": "重新開始", "保留舊譯文？": "全部重來", "請填寫翻譯檔": "關閉"})

    run_flow(original, ui)

    document = json.loads(translations_file(project).read_text(encoding="utf-8"))
    assert all(e["target"] == "" for e in document["entries"].values())
    assert list(out_dir(project).glob("translations.zh_tw.json.bak-*"))  # 舊的還在


def test_cancelling_the_keep_question_cancels_the_whole_restart(project) -> None:
    original = applied_world(project)
    before = translations_file(project).read_bytes()

    outcome = run_flow(original, FakeUi({"重新開始？": "重新開始", "保留舊譯文？": "取消"}))

    assert outcome.kind == "cancelled"
    assert (project / "sandbox" / "world" / "resources.zip").is_file()
    assert translations_file(project).read_bytes() == before


def test_after_a_restart_the_world_is_not_mistaken_for_already_applied(project) -> None:
    """同一張沒改過的地圖重抽出**同樣的指紋**。舊的 apply_report.json 不清掉的話，
    重新開始之後馬上又被判成「已經寫回過」，永遠走不到寫回。"""
    original = applied_world(project)
    run_flow(
        original,
        FakeUi({"重新開始？": "重新開始", "保留舊譯文？": "保留舊譯文", "請填寫翻譯檔": "關閉"}),
    )

    outcome = run_flow(original, FakeUi(READY))  # 不該再問「重新開始？」

    assert outcome.kind == "applied"


def test_the_sandbox_copy_can_be_dropped_instead_of_the_original(project) -> None:
    applied_world(project)
    ui = FakeUi({"重新開始？": "取消"})

    outcome = run_flow(project / "sandbox" / "world", ui)

    assert outcome.kind == "cancelled"
    assert ui.titles == ["重新開始？"]


def test_a_missing_original_is_found_out_before_anything_is_deleted(project) -> None:
    original = applied_world(project)
    shutil.rmtree(original)
    before = sorted(p.name for p in (project / "sandbox" / "world").rglob("*"))
    ui = FakeUi({"重新開始？": "重新開始", "保留舊譯文？": "保留舊譯文"})

    with pytest.raises(OriginMissingError) as caught:
        run_flow(project / "sandbox" / "world", ui)

    assert "未變更任何檔案" in str(caught.value)
    assert sorted(p.name for p in (project / "sandbox" / "world").rglob("*")) == before
    assert translations_file(project).is_file()


def test_an_original_that_became_unsupported_is_caught_before_deleting(project) -> None:
    original = applied_world(project)
    write_region_file(
        original / "entities", RegionBuilder().add(0, b"", compression_byte=0x82).build()
    )

    with pytest.raises(ExternalChunksFoundError):
        run_flow(
            original,
            FakeUi({"重新開始？": "重新開始", "保留舊譯文？": "保留舊譯文"}),
        )

    assert (project / "sandbox" / "world" / "resources.zip").is_file()


# --- 資料夾同名的另一張地圖 -------------------------------------------------------


def make_other_original(project, name="world"):
    """另一張地圖，資料夾名字一樣（例如預設的 New World），內容不同。"""
    # 先蓋在別的名字底下：用同名會蓋掉沙盒裡那張已經在處理的地圖。
    build_world(project, name="other-scratch")
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign("完全不同的告示牌", "", "", "")])
    write_region_file(
        project / "sandbox" / "other-scratch" / "region",
        RegionBuilder().add_chunk_nbt(0, root).build(),
    )
    target = project / "saves2" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(project / "sandbox" / "other-scratch"), str(target))
    return target


def test_a_different_map_with_the_same_folder_name_is_not_mistaken_for_the_same(project) -> None:
    first = make_original(project)
    run_flow(first, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    other = make_other_original(project)
    before = translations_file(project).read_bytes()
    ui = FakeUi({"地圖已存在": "取消"})

    outcome = run_flow(other, ui)

    assert outcome.kind == "cancelled"
    assert translations_file(project).read_bytes() == before  # 沒拿別張的譯文去寫


def test_overwriting_with_the_other_map_starts_clean_and_keeps_a_backup(project) -> None:
    first = make_original(project)
    run_flow(first, FakeUi({"請填寫翻譯檔": "關閉"}))
    fill_all(project)
    other = make_other_original(project)
    ui = FakeUi({"地圖已存在": "覆蓋", "請填寫翻譯檔": "關閉"})

    outcome = run_flow(other, ui)

    document = json.loads(translations_file(project).read_text(encoding="utf-8"))
    assert outcome.kind == "extracted"
    assert "完全不同的告示牌" in {e["source"] for e in document["entries"].values()}
    assert all(e["target"] == "" for e in document["entries"].values())
    assert list(out_dir(project).glob("translations.zh_tw.json.bak-*"))
