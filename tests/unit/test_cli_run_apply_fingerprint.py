# SPDX-License-Identifier: GPL-3.0-or-later
"""`run_apply` 比對世界指紋（已知缺口，2026-08-31 補齊）。

`extract.json` 記了 `world.world_fingerprint`，但 `run_apply` 此前只在寫完之後
**記錄** `world_fingerprint_after`，從不拿它跟 extract 記的那份比對。per-node 的
`expected_encoding` 守門看得到「形狀變了」，看不到「形狀沒變但內容變了」——
使用者在 extract 之後手動改了世界（哪怕改的是完全不相干的一個方塊），apply
仍然會若無其事地套用一份基於舊快照算出來的 editplan。

**這不是要取代 per-node 守門**（`occurrence.raw_snapshot` 那個更精細的缺口還在，
見 `docs/STATUS.md`），是在動任何一個位元組之前先問一次「這還是我 extract 的
那個世界嗎」——比對整份世界的指紋，比逐節點更早、更粗，但完全不用等
`raw_snapshot` 接上就能擋下最明顯的那種情況。
"""

import json

import amulet_nbt
import pytest
from conftest import RegionBuilder, modern_chunk, write_region_file

from mcmt.cli.apply import run_apply
from mcmt.cli.extract import run_extract
from mcmt.errors import SafetyError, WorldChangedSinceExtractError


def sign(*lines):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:oak_sign")
    for name in ("x", "y", "z"):
        tag[name] = amulet_nbt.IntTag(1)
    face = amulet_nbt.CompoundTag()
    face["messages"] = amulet_nbt.ListTag([amulet_nbt.StringTag(l) for l in lines])
    tag["front_text"] = face
    return tag


def build_world(project, *, name="world"):
    world = project / "sandbox" / name
    root = modern_chunk(data_version=4671)
    root["block_entities"] = amulet_nbt.ListTag([sign("歡迎光臨", "", "", "")])
    write_region_file(world / "region", RegionBuilder().add_chunk_nbt(0, root).build())
    return world


def fill(translations_path, mapping) -> None:
    document = json.loads(translations_path.read_text("utf-8"))
    for entry in document["entries"].values():
        if entry["source"] in mapping:
            entry["target"] = mapping[entry["source"]]
    translations_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def test_apply_refuses_when_the_world_changed_since_extract(project) -> None:
    world = build_world(project)
    extract = run_extract(world, language="zh_tw")
    fill(extract["translations_path"], {"歡迎光臨": "Welcome"})

    # 世界在 extract 之後被改了——加一個全新的 chunk，跟這份 plan 要寫的東西
    # 完全無關，per-node 守門看不到,只有比對整份世界的指紋才擋得住。
    other = modern_chunk(data_version=4671)
    other["block_entities"] = amulet_nbt.ListTag([sign("跟這份 plan 無關", "", "", "")])
    write_region_file(
        world / "region", RegionBuilder().add_chunk_nbt(0, world_chunk_zero(world)).add_chunk_nbt(1, other).build()
    )

    with pytest.raises(WorldChangedSinceExtractError):
        run_apply(world, extract["translations_path"])

    # 是 SafetyError 的子類——cli/__main__.py 的既有 except 子句不必為了這個新
    # 例外多寫一條分支。
    assert issubclass(WorldChangedSinceExtractError, SafetyError)


def world_chunk_zero(world):
    """讀回世界原本 chunk 0 的內容，重寫 region 時不動它——**只加一個新 chunk**。"""
    import amulet_nbt as nbt

    from mcmt.nbtio.compression import decompress_chunk
    from mcmt.nbtio.region import read_region
    from mcmt.safety.paths import ensure_readable

    path = world / "region" / "r.0.0.mca"
    chunk = next(read_region(ensure_readable(path)))
    data = decompress_chunk(chunk.payload, chunk.compression_type, chunk_index=chunk.index)
    return nbt.load(data, compressed=False).compound


def test_apply_still_works_when_the_world_is_unchanged(project) -> None:
    """對照組——沒有這條回歸，前一條測試驗不到「這個檢查沒有變成永遠拒絕」。"""
    world = build_world(project)
    extract = run_extract(world, language="zh_tw")
    fill(extract["translations_path"], {"歡迎光臨": "Welcome"})

    summary = run_apply(world, extract["translations_path"])

    assert summary["outcome"].counts["edits_written"] == 1


def test_dry_run_also_refuses_a_stale_world(project) -> None:
    """`--dry-run` 的整個賣點是「安全預覽」——預覽一份基於舊世界算出來、
    對現在的世界不成立的 editplan 沒有意義，一樣要擋。"""
    world = build_world(project)
    extract = run_extract(world, language="zh_tw")
    fill(extract["translations_path"], {"歡迎光臨": "Welcome"})

    other = modern_chunk(data_version=4671)
    other["block_entities"] = amulet_nbt.ListTag([sign("跟這份 plan 無關", "", "", "")])
    write_region_file(
        world / "region",
        RegionBuilder()
        .add_chunk_nbt(0, world_chunk_zero(world))
        .add_chunk_nbt(1, other)
        .build(),
    )

    with pytest.raises(WorldChangedSinceExtractError):
        run_apply(world, extract["translations_path"], dry_run=True)
