# SPDX-License-Identifier: GPL-3.0-or-later
"""category ⇒ strategy 的綁定（`model/strategy.py`）。

有些欄位**不吃 translate key**：放進去顯示的是 key 本身或字面文字，不是譯文。
那不是偏好問題，是遊戲行為，所以合約用一條 `if/then` 把它機器強制了。這個模組是
那條規則的程式碼投影，這份測試負責讓兩邊不能漂移。

`block_entity_name` 是 2026-08-21 加進來的第五個：[遊戲實測 M11-3] native chunk 的
`CustomName` 寫進 SNBT 的 `{translate:…}`，容器 GUI 顯示的是字面的大括號。
"""

import json
from pathlib import Path

from mcmt.model.strategy import IN_PLACE_CATEGORIES, strategy_for

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def contract_in_place_categories() -> set[str]:
    """從 extract.schema.json 裡把那條 `if/then` 的 category 清單挖出來。"""
    schema = json.loads((CONTRACTS / "extract.schema.json").read_text("utf-8"))
    for rule in schema["$defs"]["unit"]["allOf"]:
        condition = rule.get("if", {}).get("properties", {}).get("category", {})
        if "enum" in condition and rule["then"]["properties"]["strategy"] == {
            "const": "in_place"
        }:
            return set(condition["enum"])
    raise AssertionError("合約裡找不到 category ⇒ in_place 那條規則")


def test_the_in_place_category_set_is_exactly_the_contracts():
    """漂移要同時改兩邊才做得到——那正是合約改動流程想擋的事。"""
    assert IN_PLACE_CATEGORIES == contract_in_place_categories()


def test_block_entity_name_is_in_place():
    """[遊戲實測 M11-3] CustomName 只吃字面文字。"""
    assert strategy_for("block_entity_name") == "in_place"


def test_sign_is_translate_key():
    """告示牌走資源包路線——這是整個工具的主路徑，不能被一起改掉。"""
    assert strategy_for("sign") == "translate_key"


def test_an_unknown_category_defaults_to_translate_key():
    """M13 補掃描廣度時會冒出新的 category。預設走主路徑，要例外得明確加進清單。"""
    assert strategy_for("objective") == "translate_key"


def test_command_say_text_is_in_place():
    """command_say_text 的內容不能用 component 語法，只能直接替換文字。"""
    assert strategy_for("command_say_text") == "in_place"


def test_command_component_text_is_translate_key():
    """command_component_text 可以用 component 語法插入 translate key。"""
    assert strategy_for("command_component_text") == "translate_key"


# --- 哪些形狀有 in_place 的寫入依據 ---------------------------------------


def test_the_in_place_encodings_are_the_six_with_evidence():
    """多一個就是猜的。這個集合讓「加一個形狀」變成一個刻意的動作。

    | encoding | 依據 |
    |---|---|
    | `bare_string` / `plain_string` | [遊戲實測 M0-3 / M11-3] native 的 TAG_String 是字面文字 |
    | `text_compound` | 官方文件記載的形狀 |
    | `empty_key_compound` | [遊戲實測 M4-2] Mojang NbtOps 自己的輸出 |
    | `json_string_scalar` / `json_string_object` | [遊戲實測 2026-08-21] legacy chunk 的 CustomName 兩種都正確顯示 |

    `json_string_array` 不在裡面——沒測過。
    """
    from mcmt.model.strategy import IN_PLACE_ENCODINGS

    assert IN_PLACE_ENCODINGS == {
        "bare_string",
        "plain_string",
        "text_compound",
        "empty_key_compound",
        "json_string_scalar",
        "json_string_object",
    }


def test_every_in_place_encoding_is_a_real_encoding():
    """打錯字會讓一整類節點安靜地被排除掉，而那看起來像「本來就沒有那種節點」。"""
    from mcmt.model.component import Encoding
    from mcmt.model.strategy import IN_PLACE_ENCODINGS

    assert IN_PLACE_ENCODINGS <= {e.value for e in Encoding}
