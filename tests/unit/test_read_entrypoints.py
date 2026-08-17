# SPDX-License-Identifier: GPL-3.0-or-later
"""M2.5 讀取入口一律過 `ensure_readable`（CLAUDE.md §1.1）。

> 不接受「沒呼叫 ensure_writable 所以安全」這種隱性論證。

分工：**高階函式收使用者給的路徑**（`survey_world`、`world_fingerprint`）並在入口
呼叫一次 `ensure_readable`；**低階函式只收 `ReadOnlyPath`**（`read_region`）。
低階拿不到裸 `Path`，所以「忘了過圍籬」在型別層就會被擋下來，不是靠自律。

讀取紀錄記的是入口——一個世界一筆，不是 406 個 region 檔各一筆。
"""

import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.doctor import survey_world
from mcmt.fingerprint import world_fingerprint
from mcmt.nbtio.region import read_region
from mcmt.safety.paths import ensure_readable, read_log, reset_read_log


@pytest.fixture
def world(tmp_path):
    reset_read_log()
    world = tmp_path / "world"
    write_region_file(
        world / "region", RegionBuilder().add_chunk_nbt(0, modern_chunk()).build()
    )
    return world


def test_read_region_refuses_a_raw_path(world) -> None:
    """裸 Path 進不了讀取層——沒過圍籬的路徑不該有辦法被讀。"""
    with pytest.raises(TypeError) as exc:
        list(read_region(world / "region" / "r.0.0.mca"))

    assert "ensure_readable" in str(exc.value)


def test_read_region_accepts_a_read_only_path(world) -> None:
    readable = ensure_readable(world / "region" / "r.0.0.mca")

    assert [chunk.index for chunk in read_region(readable)] == [0]


def test_surveying_a_world_records_the_entry_point(world) -> None:
    survey_world(world)

    assert read_log() == (world.resolve(),)


def test_fingerprinting_a_world_records_the_entry_point(world) -> None:
    world_fingerprint(world)

    assert read_log() == (world.resolve(),)
