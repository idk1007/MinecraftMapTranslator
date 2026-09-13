# SPDX-License-Identifier: GPL-3.0-or-later
"""M5.5 從 chunk 掃出文字節點（`scan/sources/region.py`）。

這一層只負責**找到節點並記下它在哪裡**——形狀交給嗅探器、攤平交給 `segments`。
掃出來的每個節點都帶一條 `node_path`，寫入層之後靠它走回同一個位置。

**掃描廣度是 M13 的事。** 這裡先做方塊實體：告示牌（含吊掛式）與 `CustomName`。
沒做的東西列在 `scan/sources/region.py` 的 docstring 裡，不是忘了。
"""

import json
from collections import Counter
from pathlib import Path

import amulet_nbt
import pytest
from conftest import RegionBuilder, legacy_chunk, modern_chunk, write_region_file

from mcmt.safety.paths import ensure_readable
from mcmt.scan.sources.region import scan, scan_chunk

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def sign(x: int = 1, y: int = 2, z: int = 3, *, block_id: str = "minecraft:oak_sign",
         front=("第一行", "第二行", "", ""), back=None):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag(block_id)
    tag["x"] = amulet_nbt.IntTag(x)
    tag["y"] = amulet_nbt.IntTag(y)
    tag["z"] = amulet_nbt.IntTag(z)
    for side, lines in (("front_text", front), ("back_text", back)):
        if lines is None:
            continue
        face = amulet_nbt.CompoundTag()
        face["messages"] = amulet_nbt.ListTag(
            [amulet_nbt.StringTag(line) for line in lines]
        )
        tag[side] = face
    return tag


def chunk_with(*block_entities) -> amulet_nbt.CompoundTag:
    root = amulet_nbt.CompoundTag()
    root["DataVersion"] = amulet_nbt.IntTag(4671)
    root["block_entities"] = amulet_nbt.ListTag(list(block_entities))
    return root


# --- 與合約綁死 -----------------------------------------------------------


def test_every_category_we_emit_is_in_the_contract() -> None:
    schema = json.loads((CONTRACTS / "extract.schema.json").read_text("utf-8"))
    allowed = set(schema["$defs"]["category"]["enum"])

    nodes = list(scan_chunk(chunk_with(sign())))

    assert nodes
    assert {n.category for n in nodes} <= allowed


# --- 告示牌 ---------------------------------------------------------------


def test_all_four_lines_of_a_face_are_emitted_including_empty_ones() -> None:
    """空行也要掃出來——list 同型規則要知道整個 list 長什麼樣。"""
    nodes = list(scan_chunk(chunk_with(sign())))

    assert len(nodes) == 4
    assert [str(n.tag) for n in nodes] == ["第一行", "第二行", "", ""]


def test_both_faces_are_scanned() -> None:
    nodes = list(scan_chunk(chunk_with(sign(back=("背面", "", "", "")))))

    assert len(nodes) == 8
    assert str(nodes[4].tag) == "背面"


def test_the_node_path_walks_back_to_the_same_node() -> None:
    from mcmt.model.node import resolve

    root = chunk_with(sign())
    node = list(scan_chunk(root))[1]

    assert str(resolve(root, node.path)) == "第二行"


def test_the_node_path_serialises_to_the_contract_shape() -> None:
    node = list(scan_chunk(chunk_with(sign())))[1]

    assert node.path.to_json() == [
        {"t": "key", "name": "block_entities"},
        {"t": "index", "i": 0},
        {"t": "key", "name": "front_text"},
        {"t": "key", "name": "messages"},
        {"t": "index", "i": 1},
    ]


def test_the_anchor_records_where_the_block_is() -> None:
    node = list(scan_chunk(chunk_with(sign(x=123, y=64, z=-45))))[0]

    assert node.anchor == {
        "kind": "block",
        "id": "minecraft:oak_sign",
        "x": 123,
        "y": 64,
        "z": -45,
        "uuid": None,
    }


def test_a_hanging_sign_has_its_own_category() -> None:
    node = list(scan_chunk(chunk_with(sign(block_id="minecraft:oak_hanging_sign"))))[0]

    assert node.category == "hanging_sign"


def test_the_list_context_is_recorded() -> None:
    """NBT list 同型：寫入層要知道這個 list 現在是什麼元素型別、有幾個。"""
    node = list(scan_chunk(chunk_with(sign())))[0]

    assert node.list_context == {
        "list_size": 4,
        "index": 0,
        "element_type": "string",
        "homogeneity_required": True,
    }


def test_a_compound_element_is_reported_as_compound() -> None:
    tag = sign()
    tag["front_text"]["messages"] = amulet_nbt.ListTag(
        [amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("原生")})] * 4
    )

    node = list(scan_chunk(chunk_with(tag)))[0]

    assert node.list_context["element_type"] == "compound"


# --- CustomName -----------------------------------------------------------


def test_a_block_entity_custom_name_is_scanned() -> None:
    box = amulet_nbt.CompoundTag()
    box["id"] = amulet_nbt.StringTag("minecraft:chest")
    box["x"] = amulet_nbt.IntTag(0)
    box["y"] = amulet_nbt.IntTag(0)
    box["z"] = amulet_nbt.IntTag(0)
    box["CustomName"] = amulet_nbt.StringTag('{"text":"寶箱"}')

    (node,) = list(scan_chunk(chunk_with(box)))

    assert node.category == "block_entity_name"
    assert node.list_context is None


# --- 不該掃到的東西 -------------------------------------------------------


def test_a_chunk_without_block_entities_yields_nothing() -> None:
    root = amulet_nbt.CompoundTag()
    root["DataVersion"] = amulet_nbt.IntTag(4671)

    assert list(scan_chunk(root)) == []


def test_the_block_entity_id_itself_is_not_text() -> None:
    """`id` 是方塊型別，不是給人看的字。"""
    nodes = list(scan_chunk(chunk_with(sign())))

    assert all("minecraft:" not in str(n.tag) for n in nodes)


def test_is_waxed_and_colour_fields_are_not_text() -> None:
    tag = sign()
    tag["is_waxed"] = amulet_nbt.ByteTag(1)
    tag["front_text"]["color"] = amulet_nbt.StringTag("black")
    tag["front_text"]["has_glowing_text"] = amulet_nbt.ByteTag(0)

    nodes = list(scan_chunk(chunk_with(tag)))

    assert len(nodes) == 4
    assert "black" not in [str(n.tag) for n in nodes]


@pytest.mark.parametrize("field", ["LastOutput", "custom_data"])
def test_known_denylist_fields_are_not_scanned_here(field: str) -> None:
    """[實測] MP2 有 719 筆 `LastOutput`——執行期產物，還含原版 key。

    真正的 denylist 是 M6 規則引擎的事；掃描層先不主動去找這些欄位就少一個機會
    出錯。
    """
    box = amulet_nbt.CompoundTag()
    box["id"] = amulet_nbt.StringTag("minecraft:command_block")
    box["x"] = amulet_nbt.IntTag(0)
    box["y"] = amulet_nbt.IntTag(0)
    box["z"] = amulet_nbt.IntTag(0)
    box[field] = amulet_nbt.StringTag('{"text":"不要翻我"}')

    assert list(scan_chunk(chunk_with(box))) == []


# --- 容器裡的物品（M13.3）--------------------------------------------------


def chest_with_items(*items, x=1, y=2, z=3):
    tag = amulet_nbt.CompoundTag()
    tag["id"] = amulet_nbt.StringTag("minecraft:chest")
    for name, value in (("x", x), ("y", y), ("z", z)):
        tag[name] = amulet_nbt.IntTag(value)
    tag["Items"] = amulet_nbt.ListTag(list(items))
    return tag


def named_item(name):
    item = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:stone")})
    item["components"] = amulet_nbt.CompoundTag(
        {"minecraft:custom_name": amulet_nbt.StringTag(name)}
    )
    return item


def test_items_inside_a_container_are_scanned() -> None:
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag(
        [chest_with_items(named_item("聖劍"), named_item("盾牌"))]
    )

    names = {
        str(node.tag) for node in scan_chunk(root) if node.category == "custom_name"
    }

    assert names == {"聖劍", "盾牌"}


def test_an_item_node_carries_the_containers_coordinates() -> None:
    """譯者要走得到現場，而物品自己沒有座標——它在容器裡。"""
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag(
        [chest_with_items(named_item("聖劍"), x=10, y=20, z=30)]
    )

    (node,) = [n for n in scan_chunk(root) if n.category == "custom_name"]

    assert (node.anchor["x"], node.anchor["y"], node.anchor["z"]) == (10, 20, 30)


def test_the_item_path_starts_from_the_chunk_root() -> None:
    """node_path 是寫回去的指路，必須從 chunk 根一路走得到。"""
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([chest_with_items(named_item("聖劍"))])

    (node,) = [n for n in scan_chunk(root) if n.category == "custom_name"]
    steps = [
        step.name if step.t == "key" else f"[{step.i}]" for step in node.path
    ]

    assert steps == [
        "block_entities",
        "[0]",
        "Items",
        "[0]",
        "components",
        "minecraft:custom_name",
    ]


def test_a_lectern_book_is_scanned() -> None:
    """[實測] 講台的書在 `Book` 而不是 `Items[]`——Arena of Darkness 有 126 頁。"""
    lectern = amulet_nbt.CompoundTag()
    lectern["id"] = amulet_nbt.StringTag("minecraft:lectern")
    for name in ("x", "y", "z"):
        lectern[name] = amulet_nbt.IntTag(1)
    book = amulet_nbt.CompoundTag({"id": amulet_nbt.StringTag("minecraft:written_book")})
    book["components"] = amulet_nbt.CompoundTag(
        {
            "minecraft:written_book_content": amulet_nbt.CompoundTag(
                {
                    "pages": amulet_nbt.ListTag(
                        [amulet_nbt.CompoundTag({"raw": amulet_nbt.StringTag("第一頁")})]
                    )
                }
            )
        }
    )
    lectern["Book"] = book
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([lectern])

    pages = [n for n in scan_chunk(root) if n.category == "book_page"]

    assert [str(n.tag) for n in pages] == ["第一頁"]


def test_a_container_without_items_is_fine() -> None:
    root = amulet_nbt.CompoundTag()
    root["block_entities"] = amulet_nbt.ListTag([chest_with_items()])

    assert list(scan_chunk(root)) == []


def _chunk_with_command_block(command: str) -> amulet_nbt.CompoundTag:
    entity = amulet_nbt.CompoundTag(
        {
            "id": amulet_nbt.StringTag("minecraft:command_block"),
            "x": amulet_nbt.IntTag(0),
            "y": amulet_nbt.IntTag(0),
            "z": amulet_nbt.IntTag(0),
            "Command": amulet_nbt.StringTag(command),
        }
    )
    return amulet_nbt.CompoundTag(
        {"block_entities": amulet_nbt.ListTag([entity])}
    )


def test_a_command_block_yields_a_command_text_node() -> None:
    from collections import Counter

    stats = Counter()
    nodes = list(scan_chunk(_chunk_with_command_block("say hello"), stats=stats))
    assert any(n.category == "command_say_text" for n in nodes)


def test_scan_chunk_still_works_without_stats_for_backward_compatibility() -> None:
    nodes = list(scan_chunk(_chunk_with_command_block("say hi")))
    assert any(n.category == "command_say_text" for n in nodes)


def test_a_level_wrapper_chunk_is_counted_separately_from_generic_corruption(
    tmp_path,
) -> None:
    """`ensure_supported_structure` 拒絕的 chunk（1.12 `Level` 包裝層、
    `Text1..Text4`、缺 `DataVersion`）此前跟磁區偏移錯誤、未知壓縮類型這些
    **真正壞掉**的 chunk 共用同一個 `skipped_chunk` 計數器——兩者對使用者的
    意義完全不同：後者是資料真的讀不下去，前者是**我們認得出這是什麼、只是
    v1 不支援**（CLAUDE.md 二節「v1 拒絕處理的世界結構」）。共用一個計數器時，
    一張混合世代的地圖（`Against Iskerside [1.21.11]`，[實測] 2026-09-06）
    静默漏翻 1,519 個 chunk，`extract.json` 卻完全看不出來——這正是
    `skipped_legacy_json_in_native_chunk` 已經解決過的同一類問題，只是輪到
    這裡還沒補上。這裡先鎖住掃描層要能區分兩者；`extract.json`／CLI 摘要要不要
    印出來是下一步。"""
    world = tmp_path / "world"
    write_region_file(
        world / "region",
        RegionBuilder()
        .add_chunk_nbt(0, legacy_chunk())
        .add_chunk_nbt(1, modern_chunk())
        .build(),
    )
    stats = Counter()

    found = list(scan(ensure_readable(world), stats))

    assert stats["chunks"] == 1, "現代 chunk（index 1）仍要被掃到"
    assert stats["skipped_unsupported_structure"] == 1
    assert stats["skipped_chunk"] == 0, (
        "不支援的結構不是「壞掉」——不該混進真正損毀 chunk 的計數器"
    )
    assert found == []  # 兩棵 chunk 都沒有可翻文字，這裡只驗證計數器分得開
