# SPDX-License-Identifier: GPL-3.0-or-later
"""M5.4 節點路徑（`model/node.py`）。

`node_path` 是「從 chunk 根一路走到這個文字節點」的完整指路。三種步驟：

    {"t":"key","name":"front_text"}     走進一個鍵
    {"t":"index","i":1}                 走進 list 的第 n 個
    {"t":"decode","codec":"json_component","span":[12,40]}
                                        **這裡以下是另一份文件**

`decode` 是這三者裡最重要的一個：它標記「父字串裡包著一份獨立的文件」。寫入層由內
往外逐層重新編碼，而**同一父字串內的多處編輯必須由後往前**——改完第一處，其餘的
span 全部失效（CLAUDE.md 四節）。
"""

import json
from pathlib import Path

import amulet_nbt
import pytest

from mcmt.model.node import (
    NodePath,
    decode_step,
    index_step,
    key_step,
    resolve,
    span_order,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


# --- 與合約綁死 -----------------------------------------------------------


def test_the_codecs_are_exactly_the_contracts() -> None:
    schema = json.loads((CONTRACTS / "extract.schema.json").read_text("utf-8"))
    codecs = schema["$defs"]["pathStep"]["oneOf"][2]["properties"]["codec"]["enum"]

    from mcmt.model.node import Codec

    assert {c.value for c in Codec} == set(codecs)


def test_a_path_serialises_to_the_contract_shape() -> None:
    """和合約 sample 裡的那條路徑逐項相同。"""
    path = NodePath(
        [
            key_step("block_entities"),
            index_step(3),
            key_step("front_text"),
            key_step("messages"),
            index_step(1),
        ]
    )

    assert path.to_json() == [
        {"t": "key", "name": "block_entities"},
        {"t": "index", "i": 3},
        {"t": "key", "name": "front_text"},
        {"t": "key", "name": "messages"},
        {"t": "index", "i": 1},
    ]


def test_a_decode_step_serialises_with_its_span() -> None:
    step = decode_step("json_component", span=(12, 40))

    assert step.to_json() == {
        "t": "decode",
        "codec": "json_component",
        "arg": None,
        "span": [12, 40],
    }


def test_a_decode_step_without_a_span_is_still_valid() -> None:
    """整個父字串就是那份文件時沒有 span——例如告示牌的一行舊式 JSON。"""
    assert decode_step("json_component").to_json()["span"] is None


def test_a_path_round_trips_through_json() -> None:
    path = NodePath([key_step("front_text"), index_step(0), decode_step("snbt")])

    assert NodePath.from_json(path.to_json()) == path


# --- 走訪 -----------------------------------------------------------------


@pytest.fixture
def chunk():
    sign = amulet_nbt.CompoundTag()
    sign["id"] = amulet_nbt.StringTag("minecraft:sign")
    front = amulet_nbt.CompoundTag()
    front["messages"] = amulet_nbt.ListTag(
        [amulet_nbt.StringTag("第一行"), amulet_nbt.StringTag("第二行")]
    )
    sign["front_text"] = front
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([sign])
    return root


def test_resolve_walks_to_the_node(chunk) -> None:
    path = NodePath(
        [
            key_step("block_entities"),
            index_step(0),
            key_step("front_text"),
            key_step("messages"),
            index_step(1),
        ]
    )

    assert str(resolve(chunk, path)) == "第二行"


def test_resolve_stops_at_a_decode_step(chunk) -> None:
    """`decode` 以下是另一份文件，解碼是 codec 的事，不是走訪的事。"""
    path = NodePath(
        [
            key_step("block_entities"),
            index_step(0),
            key_step("front_text"),
            key_step("messages"),
            index_step(0),
            decode_step("json_component"),
        ]
    )

    assert str(resolve(chunk, path)) == "第一行"


def test_resolving_a_missing_key_says_where_it_stopped(chunk) -> None:
    path = NodePath([key_step("block_entities"), index_step(0), key_step("back_text")])

    with pytest.raises(KeyError) as exc:
        resolve(chunk, path)
    assert "back_text" in str(exc.value)


def test_resolving_past_the_end_of_a_list_says_where_it_stopped(chunk) -> None:
    path = NodePath(
        [
            key_step("block_entities"),
            index_step(0),
            key_step("front_text"),
            key_step("messages"),
            index_step(9),
        ]
    )

    with pytest.raises(IndexError):
        resolve(chunk, path)


# --- 同一父字串內的多處編輯 -----------------------------------------------


def test_edits_in_one_parent_string_are_ordered_back_to_front() -> None:
    """改完第一處，其餘 span 全部失效——所以必須由後往前。

    [實測] 三層巢狀（指令含 NBT、NBT 含 component）確實存在，這個坑會踩到。
    """
    paths = [
        NodePath([key_step("Command"), decode_step("command", span=(10, 20))]),
        NodePath([key_step("Command"), decode_step("command", span=(40, 50))]),
        NodePath([key_step("Command"), decode_step("command", span=(25, 30))]),
    ]

    ordered = span_order(paths)

    assert [p.last_span for p in ordered] == [(40, 50), (25, 30), (10, 20)]


def test_paths_without_spans_keep_their_relative_order() -> None:
    a = NodePath([key_step("a")])
    b = NodePath([key_step("b")])

    assert span_order([a, b]) == [a, b]


def test_the_last_span_is_the_innermost_one() -> None:
    """三層巢狀時，要排序的是最內層那個 span。"""
    path = NodePath(
        [
            key_step("Command"),
            decode_step("command", span=(0, 100)),
            decode_step("snbt", span=(10, 60)),
            decode_step("json_component", span=(20, 30)),
        ]
    )

    assert path.last_span == (20, 30)
