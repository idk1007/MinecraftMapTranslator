# SPDX-License-Identifier: GPL-3.0-or-later
"""denylist 對**真實 chunk 全掃**的回歸測試（M6）。

這條測試不走正式的掃描層。掃描層目前只找告示牌與 CustomName，所以拿它來驗 denylist
會是空的——**測試會通過，但什麼都沒驗到**。這裡改成走過 chunk 裡的每一個字串節點，
問規則引擎「這條路徑該不該翻」。

這樣做的價值在 M13：掃描廣度補齊之後，第一道防線（掃描層根本不去找那些欄位）會
消失，denylist 就變成唯一的防線。到那時這條測試已經在守著了。

fixture 是自建探測世界的 30 個真實 chunk。**每個 chunk 都有 `palette[].Name`**——
方塊 ID，MP2 有 113,228 個，翻了毀掉地形。那是最兇的一條，而且到處都是。
"""

import collections
from pathlib import Path

import amulet_nbt
import pytest

from mcmt.nbtio.region import read_region
from mcmt.nbtio.structure import load_chunk_root
from mcmt.rules.engine import Subject, label
from mcmt.rules.sets.denylist import DENY_LABEL, RULES, deny_reason
from mcmt.safety.paths import ensure_readable

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "regions" / "tt-probe.r.0.0.slice.mca"
)


def walk_strings(tag, keys=()):
    """走過整棵 NBT，yield 每個字串節點的 (鍵名序列, 值)。

    索引不進鍵名序列——denylist 關心的是「這是不是 palette 底下的 Name」，
    不是「第幾個 palette」。
    """
    if isinstance(tag, amulet_nbt.StringTag):
        yield keys, str(tag)
    elif isinstance(tag, amulet_nbt.CompoundTag):
        for key, value in tag.items():
            yield from walk_strings(value, keys + (str(key),))
    elif isinstance(tag, amulet_nbt.ListTag):
        for value in tag:
            yield from walk_strings(value, keys)


@pytest.fixture(scope="module")
def strings():
    found = []
    for chunk in read_region(ensure_readable(FIXTURE)):
        found.extend(walk_strings(load_chunk_root(chunk)))
    return found


def denied(keys) -> bool:
    return DENY_LABEL in label(Subject(key_path=tuple(keys)), RULES)


def test_the_fixture_really_contains_block_ids(strings) -> None:
    """先確認這條測試有東西可驗——不然它會安靜地什麼都沒測到。"""
    palette_names = [k for k, _ in strings if k[-2:] == ("palette", "Name")]

    assert len(palette_names) > 100


def test_every_block_id_is_denied(strings) -> None:
    """`palette[].Name` 一個都不能漏。翻了毀掉地形。"""
    leaked = [
        (keys, value)
        for keys, value in strings
        if keys[-2:] == ("palette", "Name") and not denied(keys)
    ]

    assert leaked == []


def test_no_minecraft_identifier_leaks_through(strings) -> None:
    """凡是 `minecraft:` 開頭的值幾乎都是識別碼，不是給人看的字。

    這條是**寬鬆的煙霧偵測器**：它不要求 denylist 擋下全部（有些 `minecraft:` 出現在
    合法的文字路徑上），只要求「沒被擋下的那些」全部落在我們認得的少數欄位裡。
    冒出新的一種，就是掃描廣度變了而 denylist 沒跟上。
    """
    leaked = collections.Counter(
        keys[-1]
        for keys, value in strings
        if value.startswith("minecraft:") and not denied(keys)
    )

    # 第一次跑這條時漏了兩種：`biomes.palette`（生態域 ID，**是字串 list 不是
    # compound**，所以 ("palette","Name") 認不到，30 個 chunk 就有 720 個）與
    # `Status`（chunk 產生狀態）。規則補上之後這裡是空的。
    assert dict(leaked) == {}


def test_the_report_can_say_why(strings) -> None:
    keys = next(k for k, _ in strings if k[-2:] == ("palette", "Name"))

    assert deny_reason(label(Subject(key_path=tuple(keys)), RULES)) == "方塊 ID，翻了毀掉地形"


def test_ordinary_text_paths_are_not_denied(strings) -> None:
    """反向確認：denylist 沒有寬到把告示牌也擋掉。"""
    assert not denied(("block_entities", "front_text", "messages"))
    assert not denied(("block_entities", "CustomName"))
