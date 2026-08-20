# SPDX-License-Identifier: GPL-3.0-or-later
"""M7.1 key 生成（`extract/keys.py`）。

```
translateKey = <namespace>.<category>.<discriminator>[.<segment_index>]
unitId       = u:<category>:<discriminator>
```

`discriminator` 在兩者中是**同一個字串，由同一個函式產生一次，永不分岔**。

hash 輸入是 `source.text`（攤平後的字串），**不是 raw**——帶 `extra` 的樹沒有單一
raw，而 `text` 同時編碼了字詞與段落切點，那正是決定「這是不是同一個翻譯單位」的東西。

碰撞**硬失敗**：絕不靜默覆蓋。靜默覆蓋的後果是兩段不同的文字共用一個譯文，而且沒有
任何跡象。
"""

import json
import re
import unicodedata
from pathlib import Path

import pytest

from mcmt.extract.keys import (
    KeyRegistry,
    discriminator_for,
    hash_input,
    normalize,
    translate_key,
    unit_id,
)
from mcmt.model import SCHEMA_VERSION

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def contract_pattern(name: str) -> str:
    schema = json.loads((CONTRACTS / "extract.schema.json").read_text("utf-8"))
    return schema["$defs"][name]["pattern"]


# --- 與合約綁死 -----------------------------------------------------------


def test_the_discriminator_matches_the_contract_pattern() -> None:
    value = discriminator_for("sign", "歡迎光臨")

    assert re.fullmatch(contract_pattern("discriminator"), value)


def test_the_unit_id_matches_the_contract_pattern() -> None:
    assert re.fullmatch(contract_pattern("unitId"), unit_id("sign", "歡迎光臨"))


def test_the_translate_key_matches_the_contract_pattern() -> None:
    key = translate_key("mcmt", "sign", "歡迎光臨")

    assert re.fullmatch(contract_pattern("translateKey"), key)


def test_a_segment_suffixed_key_still_matches_the_contract() -> None:
    key = translate_key("mcmt", "sign", "歡迎光臨", segment=2)

    assert re.fullmatch(contract_pattern("translateKey"), key)
    assert key.endswith(".2")


# --- 同一個字串，產生一次 -------------------------------------------------


def test_the_unit_id_and_the_key_share_the_same_discriminator() -> None:
    """兩者分岔的話，翻譯對不回節點，而且不會有任何錯誤訊息。"""
    text = "前方危險"
    digest = discriminator_for("sign", text)

    assert unit_id("sign", text) == f"u:sign:{digest}"
    assert translate_key("mcmt", "sign", text) == f"mcmt.sign.{digest}"


def test_the_discriminator_is_sixteen_hex_not_ten() -> None:
    """40 bits 在 5 萬條目下碰撞率約 11%，而掃描範圍含 2,613 個 mcfunction。"""
    assert len(discriminator_for("sign", "x")) == 16


def test_the_same_text_and_category_always_give_the_same_key() -> None:
    assert discriminator_for("sign", "歡迎") == discriminator_for("sign", "歡迎")


def test_the_category_is_part_of_the_identity() -> None:
    """同一句話出現在告示牌與書本上是兩個單位——寬度預算與寫回方式都不同。"""
    assert discriminator_for("sign", "歡迎") != discriminator_for("book_page", "歡迎")


def test_the_schema_version_is_part_of_the_hash_input() -> None:
    """合約改版時所有 key 一起換，舊的 translations 不會安靜地半套用上。"""
    assert hash_input("sign", "歡迎").startswith(f"{SCHEMA_VERSION}\x1f")


def test_the_hash_input_is_the_flattened_text_with_its_tokens() -> None:
    """切點不同必然是不同單位，因為 `[[n]]` 在 text 裡。"""
    a = discriminator_for("sign", "[[0]]價格[[1]]五元")
    b = discriminator_for("sign", "價格五元")

    assert a != b


# --- normalize 的逐條規則 -------------------------------------------------


def test_normalize_applies_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "臺灣é")

    assert normalize(decomposed) == unicodedata.normalize("NFC", "臺灣é")


def test_normalize_unifies_newlines() -> None:
    assert normalize("一\r\n二\r三") == "一\n二\n三"


def test_normalize_does_not_touch_whitespace() -> None:
    """**這條是硬性的。** 告示牌用前導空白做置中排版。

    折疊空白會讓 `"  歡迎  "` 與 `"歡迎"` 塌成同一個 key，排版全毀。
    """
    assert normalize("  歡迎  ") == "  歡迎  "
    assert normalize("兩個  空格") == "兩個  空格"
    assert normalize("\t定位") == "\t定位"


def test_normalize_does_not_change_case() -> None:
    assert normalize("Welcome HOME") == "Welcome HOME"


def test_normalize_keeps_sigma_codes() -> None:
    """§ 碼是內容的一部分。"""
    assert normalize("\u00a7c紅") == "\u00a7c紅"


def test_leading_whitespace_changes_the_key() -> None:
    """置中排版的告示牌與沒排版的不是同一個翻譯單位。"""
    assert discriminator_for("sign", "  歡迎  ") != discriminator_for("sign", "歡迎")


# --- 碰撞 -----------------------------------------------------------------


def test_a_registry_returns_the_same_id_for_the_same_text() -> None:
    registry = KeyRegistry()

    assert registry.register("sign", "歡迎") == registry.register("sign", "歡迎")


def test_a_collision_gets_a_suffix_instead_of_silently_overwriting(monkeypatch) -> None:
    """**絕不靜默覆蓋。** 後果是兩段不同的文字共用一個譯文，而且沒有任何跡象。"""
    import mcmt.extract.keys as keys

    monkeypatch.setattr(keys, "_digest", lambda text: "0123456789abcdef")
    registry = keys.KeyRegistry()

    first = registry.register("sign", "第一段文字")
    second = registry.register("sign", "完全不同的文字")

    assert first == "0123456789abcdef"
    assert second == "0123456789abcdef_1"


def test_a_collision_is_recorded_with_both_hash_inputs(monkeypatch) -> None:
    """keymap 要記下兩邊的 hash 輸入與解法，否則沒人查得出當初撞的是什麼。"""
    import mcmt.extract.keys as keys

    monkeypatch.setattr(keys, "_digest", lambda text: "0123456789abcdef")
    registry = keys.KeyRegistry()
    registry.register("sign", "第一段文字")
    registry.register("sign", "完全不同的文字")

    (collision,) = registry.collisions

    assert "第一段文字" in collision["hash_inputs"][0]
    assert "完全不同的文字" in collision["hash_inputs"][1]
    assert collision["resolution"] == "0123456789abcdef_1"


def test_a_collision_flags_the_unit(monkeypatch) -> None:
    import mcmt.extract.keys as keys

    monkeypatch.setattr(keys, "_digest", lambda text: "0123456789abcdef")
    registry = keys.KeyRegistry()
    registry.register("sign", "甲")
    registry.register("sign", "乙")

    assert "collision_resolved" in registry.flags_for("0123456789abcdef_1")


def test_three_way_collisions_keep_counting(monkeypatch) -> None:
    import mcmt.extract.keys as keys

    monkeypatch.setattr(keys, "_digest", lambda text: "0123456789abcdef")
    registry = keys.KeyRegistry()

    got = [registry.register("sign", t) for t in ("甲", "乙", "丙")]

    assert got == ["0123456789abcdef", "0123456789abcdef_1", "0123456789abcdef_2"]


def test_the_keymap_round_trips_as_json(monkeypatch) -> None:
    """keymap.json 進版控——它是專案的一部分，不是產物。"""
    import mcmt.extract.keys as keys

    monkeypatch.setattr(keys, "_digest", lambda text: "0123456789abcdef")
    registry = keys.KeyRegistry()
    registry.register("sign", "甲")
    registry.register("sign", "乙")

    assert json.loads(json.dumps(registry.keymap(), ensure_ascii=False))


def test_the_same_text_in_two_categories_is_not_a_collision() -> None:
    """category 進 hash 輸入，所以它們本來就不同 digest——不該被記成碰撞。"""
    registry = KeyRegistry()
    registry.register("sign", "歡迎")
    registry.register("book_page", "歡迎")

    assert registry.collisions == []
