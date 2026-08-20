# SPDX-License-Identifier: GPL-3.0-or-later
"""M5.2 世代（`model/generation.py`）。

**DataVersion 決定「寫回哪個世代」與「遊戲會不會跑 DataFixer」，
不決定「節點是什麼形狀」。** 這兩件事很容易混，所以分成兩個模組：形狀問
`component.py` 嗅探，世代問這裡。

[實測] DataVersion 4556 的 chunk 裡有 2,340 個舊式 JSON 空字串——所以拿 DataVersion
去推導形狀已知為錯，這個模組**刻意沒有**那種函式。
"""

import json
from pathlib import Path

import pytest

from mcmt.model.generation import (
    DATAFIXER_WATERSHED,
    TARGET_DATA_VERSION,
    Generation,
    generation_of,
    runs_datafixer,
    write_back_version,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def test_the_watershed_matches_the_contract() -> None:
    """4325 在 editplan schema 裡是一個 `minimum`，所以綁得住。"""
    schema = json.loads((CONTRACTS / "editplan.schema.json").read_text("utf-8"))
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "integer" and "minimum" in node:
                found.append(node["minimum"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert DATAFIXER_WATERSHED in found


def test_the_target_version_is_1_21_11() -> None:
    assert TARGET_DATA_VERSION == 4671


# --- DataFixer 會不會跑 ---------------------------------------------------


@pytest.mark.parametrize("data_version", [1139, 1963, 3465, 3700, 3955, 4324])
def test_old_chunks_get_datafixed(data_version: int) -> None:
    """[遊戲實測 M4-2] DV 3700 的 chunk 裡三種舊式 JSON 全部被解析。"""
    assert runs_datafixer(data_version) is True


@pytest.mark.parametrize("data_version", [4325, 4438, 4556, 4671])
def test_chunks_at_or_past_the_watershed_do_not(data_version: int) -> None:
    """[遊戲實測 M0-3] 那裡的 TAG_String 就是字面文字，遊戲不試著解析 JSON。"""
    assert runs_datafixer(data_version) is False


def test_the_watershed_itself_is_on_the_native_side() -> None:
    """分水嶺是「≥ 4325 不跑」，邊界值屬於新世代那邊。"""
    assert runs_datafixer(DATAFIXER_WATERSHED) is False
    assert runs_datafixer(DATAFIXER_WATERSHED - 1) is True


# --- 世代 -----------------------------------------------------------------


def test_generations_split_at_the_watershed() -> None:
    assert generation_of(3700) is Generation.LEGACY
    assert generation_of(4671) is Generation.NATIVE


def test_a_generation_knows_whether_legacy_json_is_content() -> None:
    """同一個 `'\"\"'`：舊世代是空白，新世代是字面的兩個引號（M0-4 / M4-3 對照）。"""
    assert Generation.LEGACY.legacy_json_is_content is True
    assert Generation.NATIVE.legacy_json_is_content is False


# --- 永不升級 -------------------------------------------------------------


@pytest.mark.parametrize("data_version", [1139, 3700, 3955, 4325, 4556, 4671])
def test_we_always_write_back_the_version_we_read(data_version: int) -> None:
    """**工具永不升級格式。**

    這條寫成函式而不是註解，是為了讓「升級」變成一個要刻意去改的地方。
    [遊戲實測 M4-4] 遊戲自己會升級玩家走過的 chunk，那是使用者行為；我們不做。
    """
    assert write_back_version(data_version) == data_version


def test_there_is_no_way_to_ask_this_module_about_node_shape() -> None:
    """形狀一律逐節點嗅探。這個模組刻意不提供那種函式。

    [實測] DV 4556 的 chunk 裡有 2,340 個舊式 JSON 空字串——用 DataVersion 推導
    形狀已知為錯，留一個那樣的函式只會讓人再用一次。
    """
    import mcmt.model.generation as generation

    names = [n for n in dir(generation) if not n.startswith("_")]
    assert not [n for n in names if "encoding" in n.lower() or "shape" in n.lower()]
