# SPDX-License-Identifier: GPL-3.0-or-later
"""M10.2 `resources.zip` 的產生與合併（`backends/resourcepack/pack.py`）。

格式要求（CLAUDE.md 二節）：zip 而非資料夾、檔名固定 `resources.zip`、放世界根目錄、
zip 內根目錄**直接是** `assets/` 與 `pack.mcmeta`（不可有外層包裹資料夾）。

**合併既有 pack 時必須處理 `pack.mcmeta`**——[遊戲實測 M4-5] 地圖自帶的
`pack_format: 22` 被 1.21.11 直接拒絕（「無法套用伺服器資源包」），我們併進去的 lang
檔跟著陪葬。那是在改地圖自己的檔案，所以要回報。
"""

import json
import zipfile

import pytest

from mcmt.backends.resourcepack.pack import PACK_FORMAT, build_pack


def existing_pack(path, *, pack_format=22, extra=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "pack.mcmeta",
            json.dumps({"pack": {"pack_format": pack_format, "description": "地圖自己的"}}),
        )
        archive.writestr("assets/minecraft/lang/en_us.json", '{"a": "b"}')
        archive.writestr("assets/minecraft/textures/x.png", b"\x89PNG fake")
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return path


def entries(path):
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def meta(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("pack.mcmeta"))["pack"]


# --- 新建 -----------------------------------------------------------------


def test_a_fresh_pack_has_the_required_shape(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"

    build_pack(target, {"zh_tw": {"mcmt.a": "甲"}}, namespace="mcmt")

    names = entries(target)
    assert "pack.mcmeta" in names
    assert "assets/mcmt/lang/zh_tw.json" in names
    # 沒有外層包裹資料夾：根目錄的東西不會是 `something/pack.mcmeta`
    assert not any(name.endswith("/pack.mcmeta") for name in names)


def test_a_fresh_pack_declares_the_target_format(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"

    build_pack(target, {"zh_tw": {}}, namespace="mcmt")

    assert meta(target)["pack_format"] == PACK_FORMAT


def test_multiple_languages_each_get_a_file(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"

    build_pack(target, {"zh_tw": {"a": "甲"}, "ja_jp": {"a": "ア"}}, namespace="mcmt")

    assert {"assets/mcmt/lang/zh_tw.json", "assets/mcmt/lang/ja_jp.json"} <= entries(target)


def test_the_lang_file_is_strict_json_with_sorted_keys(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"

    build_pack(target, {"zh_tw": {"mcmt.b": "乙", "mcmt.a": "甲"}}, namespace="mcmt")

    with zipfile.ZipFile(target) as archive:
        text = archive.read("assets/mcmt/lang/zh_tw.json").decode("utf-8")
    assert json.loads(text) == {"mcmt.a": "甲", "mcmt.b": "乙"}
    assert text.index("mcmt.a") < text.index("mcmt.b")


def test_the_zip_is_valid(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"

    build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None


# --- 合併 -----------------------------------------------------------------


def test_merging_keeps_every_existing_entry(project) -> None:
    """地圖的材質與音效一個都不能少——覆蓋掉會讓整張地圖看起來壞掉。"""
    target = existing_pack(project / "sandbox" / "world" / "resources.zip")
    before = entries(target)

    build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    assert before <= entries(target)


def test_merging_adds_our_lang_file(project) -> None:
    target = existing_pack(project / "sandbox" / "world" / "resources.zip")

    build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    assert "assets/mcmt/lang/zh_tw.json" in entries(target)


def test_merging_does_not_touch_the_maps_own_lang_files(project) -> None:
    target = existing_pack(project / "sandbox" / "world" / "resources.zip")

    build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    with zipfile.ZipFile(target) as archive:
        assert archive.read("assets/minecraft/lang/en_us.json").decode() == '{"a": "b"}'


def test_rerunning_replaces_our_own_lang_file(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"
    build_pack(target, {"zh_tw": {"a": "舊的"}}, namespace="mcmt")

    build_pack(target, {"zh_tw": {"a": "新的"}}, namespace="mcmt")

    with zipfile.ZipFile(target) as archive:
        assert json.loads(archive.read("assets/mcmt/lang/zh_tw.json")) == {"a": "新的"}
        assert archive.namelist().count("assets/mcmt/lang/zh_tw.json") == 1


# --- pack_format：M4-5 的教訓 ---------------------------------------------


def test_an_outdated_pack_gains_supported_formats(project) -> None:
    """[遊戲實測 M4-5] `pack_format: 22` 被 1.21.11 拒絕，我們的 lang 檔跟著陪葬。"""
    target = existing_pack(project / "sandbox" / "world" / "resources.zip", pack_format=22)

    report = build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    supported = meta(target)["supported_formats"]
    assert supported["min_inclusive"] <= 22
    assert supported["max_inclusive"] >= PACK_FORMAT
    assert report.pack_meta_changed is True


def test_the_maps_own_pack_format_number_is_left_alone(project) -> None:
    """只加相容區間，不改它宣告的版本——那是地圖作者寫的東西。"""
    target = existing_pack(project / "sandbox" / "world" / "resources.zip", pack_format=22)

    build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    assert meta(target)["pack_format"] == 22


def test_a_current_pack_is_not_touched(project) -> None:
    target = existing_pack(
        project / "sandbox" / "world" / "resources.zip", pack_format=PACK_FORMAT
    )

    report = build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    assert report.pack_meta_changed is False


def test_a_pack_that_already_declares_a_wide_range_is_not_touched(project) -> None:
    target = project / "sandbox" / "world" / "resources.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            "pack.mcmeta",
            json.dumps(
                {
                    "pack": {
                        "pack_format": 22,
                        "supported_formats": {"min_inclusive": 22, "max_inclusive": 99},
                    }
                }
            ),
        )

    report = build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")

    assert report.pack_meta_changed is False


def test_an_unreadable_pack_mcmeta_is_reported_not_guessed(project) -> None:
    """既有 pack.mcmeta 壞掉時不猜——猜錯會讓整包被拒而使用者不知道為什麼。"""
    target = project / "sandbox" / "world" / "resources.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("pack.mcmeta", "{ 這不是 JSON")

    with pytest.raises(ValueError):
        build_pack(target, {"zh_tw": {"a": "甲"}}, namespace="mcmt")


# --- 安全 -----------------------------------------------------------------


def test_writing_outside_the_sandbox_is_refused(project) -> None:
    from mcmt.errors import PathOutsideSandboxError

    with pytest.raises(PathOutsideSandboxError):
        build_pack(project / "escaped.zip", {"zh_tw": {}}, namespace="mcmt")


def test_the_report_counts_what_it_wrote(project) -> None:
    target = existing_pack(project / "sandbox" / "world" / "resources.zip")

    report = build_pack(target, {"zh_tw": {"a": "甲", "b": "乙"}}, namespace="mcmt")

    assert report.languages == ["zh_tw"]
    assert report.key_count == 2
    # pack.mcmeta 是重寫的不是搬運的，所以搬運的是另外兩個條目。
    assert report.carried_entries == 2
