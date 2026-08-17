# SPDX-License-Identifier: GPL-3.0-or-later
"""`level.dat` 在真實檔案上的讀寫驗證（M3.2）。

fixture 來自 `TT_WORLD_NAME_PROBE`（本專案自建的探測世界），**已移除 `Player` 與
`WorldGenSettings`**——前者含玩家 UUID 與座標，公開 repo 不需要那個；後者含種子，
也不是這個測試需要的東西。

要驗的是 L1：amulet-nbt 解析→序列化位元組一致。`[實測]` 在完整的原始 `level.dat`
（7,271 bytes NBT）上成立。
"""

import gzip
from pathlib import Path

import amulet_nbt
import pytest

from mcmt.nbtio.datfile import read_dat, write_dat
from mcmt.safety.paths import ensure_readable

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "dat" / "tt-probe.level.dat"
)


@pytest.fixture
def dat():
    return read_dat(ensure_readable(FIXTURE))


def test_the_fixture_is_a_real_level_dat(dat) -> None:
    data = dat.tag.compound["Data"]

    assert dat.compression == "gzip"
    assert str(data["LevelName"]) == "TT_WORLD_NAME_PROBE"
    assert int(data["DataVersion"]) == 4671  # 1.21.11


def test_the_fixture_carries_no_player_data(dat) -> None:
    """fixture 是要進版控的，別把玩家 UUID 一起放進去。"""
    assert "Player" not in dat.tag.compound["Data"]


def test_writing_it_back_preserves_the_nbt_byte_for_byte(project, dat) -> None:
    target = project / "sandbox" / "level.dat"

    write_dat(target, dat)

    assert gzip.decompress(target.read_bytes()) == gzip.decompress(FIXTURE.read_bytes())


def test_editing_level_name_changes_that_field_and_nothing_else(project, dat) -> None:
    """`LevelName` 是 4 個 in_place 欄位之一，M11 會這樣改它。"""
    before = {str(k) for k in dat.tag.compound["Data"].keys()}
    dat.tag.compound["Data"]["LevelName"] = amulet_nbt.StringTag("已翻譯的世界名")
    target = project / "sandbox" / "level.dat"

    write_dat(target, dat)

    written = read_dat(ensure_readable(target)).tag.compound["Data"]
    assert str(written["LevelName"]) == "已翻譯的世界名"
    assert {str(k) for k in written.keys()} == before
    assert int(written["DataVersion"]) == 4671
