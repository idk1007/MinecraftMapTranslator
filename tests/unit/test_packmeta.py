# SPDX-License-Identifier: GPL-3.0-or-later
"""`pack.mcmeta` 的 supported_formats 前向加寬（`mcmt.packmeta`）。

[實測 2026-09-03] Minecraft 26.2（pack_format 88）拒載 supported_formats 上限卡在
75 的 `resources.zip`，連譯文一起失效。同一件事會發生在 datapack 的 pack.mcmeta。
"""

from mcmt.packmeta import FORWARD_PACK_FORMAT, widen_supported_formats


def test_a_bare_pack_format_gains_a_forward_range() -> None:
    meta, changed, note = widen_supported_formats({"pack": {"pack_format": 22}})

    assert changed is True
    assert meta["pack"]["pack_format"] == 22  # 宣告的版本不動
    assert meta["pack"]["supported_formats"] == {
        "min_inclusive": 22,
        "max_inclusive": FORWARD_PACK_FORMAT,
    }
    assert "22" in note


def test_an_existing_lower_min_is_kept() -> None:
    """下限維持 pack 自己宣告的最低值——pack 其他內容可能真的需要那個地板。"""
    meta, changed, _ = widen_supported_formats(
        {"pack": {"pack_format": 50, "supported_formats": {"min_inclusive": 30, "max_inclusive": 60}}}
    )

    assert changed is True
    assert meta["pack"]["supported_formats"] == {
        "min_inclusive": 30,
        "max_inclusive": FORWARD_PACK_FORMAT,
    }


def test_an_already_forward_range_is_left_alone() -> None:
    original = {
        "pack": {
            "pack_format": 22,
            "supported_formats": {"min_inclusive": 4, "max_inclusive": FORWARD_PACK_FORMAT},
        }
    }

    meta, changed, note = widen_supported_formats(original)

    assert changed is False
    assert note == ""
    assert meta is original


def test_a_range_above_the_ceiling_is_left_alone() -> None:
    original = {"pack": {"pack_format": 1, "supported_formats": {"min_inclusive": 1, "max_inclusive": 99999}}}

    _, changed, _ = widen_supported_formats(original)

    assert changed is False


def test_no_usable_lower_bound_is_not_guessed() -> None:
    """`pack_format` 不是整數、也沒有 supported_formats 的下限——不亂猜一個地板。"""
    _, changed, note = widen_supported_formats({"pack": {"description": "x"}})

    assert changed is False
    assert note == ""


def test_a_non_int_pack_format_but_a_supported_min_still_widens() -> None:
    meta, changed, _ = widen_supported_formats(
        {"pack": {"pack_format": "oops", "supported_formats": {"min_inclusive": 12}}}
    )

    assert changed is True
    assert meta["pack"]["supported_formats"] == {
        "min_inclusive": 12,
        "max_inclusive": FORWARD_PACK_FORMAT,
    }


def test_the_input_is_not_mutated() -> None:
    original = {"pack": {"pack_format": 22}}

    widen_supported_formats(original)

    assert original == {"pack": {"pack_format": 22}}
