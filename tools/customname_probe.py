# SPDX-License-Identifier: GPL-3.0-or-later
"""CustomName 的寫入形狀探測（M11 的 `[待驗]`）。

    python tools/customname_probe.py "sandbox/<世界>"

**問題**：v1 目前拒寫方塊實體的 `CustomName`。[實測] 它在兩個世代都是 **String 節點**
——native（DV 4671）裡是裸字串、legacy（DV 3700）裡是 JSON 純量 `'"@"'`。要放
translate key 進去，native 那邊該寫什麼形狀沒有實測依據：

* 寫 **compound** 會改掉那個欄位的 NBT 型別 → 可能整個方塊實體壞掉
* 寫 **JSON 字串** 又踩到 [遊戲實測 M0-3]（native chunk 的 `TAG_String` 是字面文字）

`Arena of Darkness` 有 **9,579 個**這種節點，不解決等於漏掉一大類。

**這個腳本只寫 String**，不動 NBT 型別——最壞的情況是顯示成字面亂碼，不會讓 chunk
讀不進去。三個變體各放一個方塊實體，一趟進遊戲就分得出來：

    A  '{"translate":"mcmt.test.customname"}'   舊式 JSON 物件
    B  '{translate:"mcmt.test.customname"}'     SNBT 形式
    C  '對照組 純文字'                            控制組：確認裸字串本來就顯示得出來

C 顯示得出來、A/B 都顯示成字面大括號 → CustomName 在 native chunk 只吃裸字串，
translate key 這條路在那裡走不通（v1 維持拒寫是對的）。
A 或 B 顯示出中文 → 那個形狀就是答案，M11 可以補上寫入。

---

## 2026-08-21：native 已答，legacy 還沒

[遊戲實測 M11-3] native 那一輪的結果是 **C 顯示得出來、A/B 都是字面大括號**。所以
`block_entity_name` 改走 `in_place`（把譯文直接寫進節點，保留原形狀），已經實作完成。

**剩下 legacy（DV < 4325）那一半。** 那裡 DataFixerUpper 會解析這個欄位，native 的
答案不能轉移過去。[實測 2026-08-21] `Arena of Darkness` 的 **9,579 個 CustomName
全部是舊世代**（DV 3700 的 JSON 純量 9,259 個 + DV 3465 的 JSON 物件 320 個，
native 的 0 個），目前**全數以 `untested_write_shape` 排除**——也就是這張地圖的
CustomName 一個都還寫不出去。這一輪要解開的就是它。

    python tools/customname_probe.py "sandbox/Arena of Darkness" --generation legacy --find
    python tools/customname_probe.py "sandbox/Arena of Darkness" --generation legacy \
        --region region/r.-1.-1.mca --chunk 1022

legacy 的三個變體對應三種寫法，一趟就分得出該寫哪一種：

    A  '"譯文"'                          JSON 純量：**保留原形狀**（這張地圖自己就在用）
    B  '{"translate":"mcmt.test.customname"}'  JSON 物件的 translate key
    C  '譯文'                             裸字串：非 JSON 的東西進 DataFixer 會怎樣

A 顯示譯文 → `in_place` 只要多支援 `json_string_scalar`，9,579 個節點就解開了。
B 也顯示譯文 → 更好：legacy 可以走 translate key，一份存檔支援多語言。
C 顯示譯文 → DataFixer 對非 JSON 的字串是寬容的，那也是一條路（但 A 更保守）。
三個都不對 → 維持排除，而且我們知道了那不是保守過頭。
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import amulet_nbt  # noqa: E402

from mcmt.nbtio.compression import decompress_chunk  # noqa: E402
from mcmt.nbtio.region import ChunkWrite, read_region, write_region  # noqa: E402
from mcmt.safety.backup import BackupSet  # noqa: E402
from mcmt.safety.paths import ensure_readable, ensure_writable  # noqa: E402

TEST_KEY = "mcmt.test.customname"
TEST_VALUE = "自訂名稱翻譯成功"

# 順序就是優先順序：最可能成立的放第一個，因為**只有容器方塊看得到 CustomName**
# （開啟時顯示在 GUI 標題），而一個 chunk 裡的容器通常沒幾個。
#
# 為什麼 SNBT 排第一：探測世界的箱子存的是裸字串 `TT_CHEST_CUSTOM_NAME`，那既是
# 合法的 SNBT（未加引號的字串）也是合法的文字 component（折疊成裸字串）。若
# CustomName 真的是「component 的 SNBT」，`{translate:"…"}` 就會成立。
VARIANT_SETS = {
    # native（DV >= 4325）：遊戲不跑 DataFixer，TAG_String 就是字面文字。
    # **這一組已經驗完了**（M11-3：C 顯示得出來、A/B 都是字面大括號），留著是為了
    # 換版本時能重跑。
    "native": [
        ("A SNBT 形式", '{translate:"' + TEST_KEY + '"}'),
        ("B 舊式 JSON 物件", json.dumps({"translate": TEST_KEY}, separators=(",", ":"))),
        ("C 對照組 純文字", "對照組 純文字"),
    ],
    # legacy（DV < 4325）：DataFixerUpper 會解析這個欄位，所以問題完全不同——
    # 不是「它解不解析」，是「它接受哪一種」。
    # **三個變體的文字刻意都不一樣。** 若三者都用同一句譯文，玩家開了三個箱子看到
    # 三個一樣的標題，還得回頭對座標才知道哪個是哪個——那正是最容易記錯的一步。
    "legacy": [
        ("A JSON 純量（保留原形狀）", json.dumps("A 純量成功", ensure_ascii=False)),
        ("B JSON 物件的 translate key",
         json.dumps({"translate": TEST_KEY}, separators=(",", ":"))),
        ("C 裸字串（非 JSON）", "C 裸字串成功"),
    ],
}

# 看得到 CustomName 的方塊：開啟時 GUI 標題會顯示。其餘方塊實體存得進去但看不到。
_VISIBLE = (
    "chest", "barrel", "shulker_box", "furnace", "smoker", "blast_furnace",
    "hopper", "dispenser", "dropper", "brewing_stand", "beacon",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world")
    parser.add_argument("--region", default="region/r.0.0.mca")
    parser.add_argument("--chunk", type=int, default=0)
    parser.add_argument(
        "--generation",
        choices=tuple(VARIANT_SETS),
        default="native",
        help="要驗哪一個世代的形狀。native 已完成（M11-3），legacy 尚待驗證",
    )
    parser.add_argument(
        "--find",
        action="store_true",
        help="只掃描：列出符合這個世代、而且有容器方塊實體的 chunk，不寫任何東西",
    )
    args = parser.parse_args()

    world = Path(args.world).resolve()
    if args.find:
        return find(world, args.generation)
    variants = VARIANT_SETS[args.generation]
    region_path = world / args.region

    original = list(read_region(ensure_readable(region_path)))
    target = next((c for c in original if c.index == args.chunk), None)
    if target is None:
        print(f"chunk {args.chunk} 不在 {args.region} 裡", file=sys.stderr)
        return 2

    root = amulet_nbt.load(
        decompress_chunk(target.payload, target.compression_type, chunk_index=target.index),
        compressed=False,
    ).compound
    data_version = int(root["DataVersion"])

    # 挑幾個方塊實體來放變體。優先用本來就有 CustomName 的，其餘補上。
    candidates = [
        be for be in root["block_entities"]
        if isinstance(be, amulet_nbt.CompoundTag) and "front_text" not in be
    ]
    # **容器優先**——只有它們的 CustomName 看得到。剩下的變體只能靠 /data get 看
    # 儲存值，看不出算繪結果，所以腳本會標出來。
    candidates.sort(key=lambda be: 0 if any(v in str(be.get("id", "")) for v in _VISIBLE) else 1)
    if len(candidates) < len(variants):
        print(f"這個 chunk 只有 {len(candidates)} 個可用的方塊實體", file=sys.stderr)
        return 2

    placed = []
    for (label, value), entity in zip(variants, candidates):
        entity["CustomName"] = amulet_nbt.StringTag(value)
        placed.append((label, value, str(entity.get("id", "")),
                       int(entity["x"]), int(entity["y"]), int(entity["z"])))

    import zlib

    payload = zlib.compress(amulet_nbt.NamedTag(root, "").save_to(compressed=False))

    with BackupSet(world) as backup:
        backup.protect(region_path)
        write_region(
            region_path,
            [
                ChunkWrite.replaced(c, payload) if c.index == args.chunk
                else ChunkWrite.unchanged(c)
                for c in original
            ],
        )
        backup.protect(world / "resources.zip")
        _add_key(world / "resources.zip")

    print(f"世界：{world}")
    print(f"chunk {args.chunk}（DataVersion {data_version}，{args.generation} 變體組）")
    if (data_version >= 4325) != (args.generation == "native"):
        print(
            f"  ⚠ 這個 chunk 的 DataVersion 是 {data_version}，"
            f"和 --generation {args.generation} 對不上——4325 是分水嶺。"
            f"驗出來的結果會是另一個世代的答案。",
            file=sys.stderr,
        )
    print()
    for label, value, block_id, x, y, z in placed:
        visible = any(v in block_id for v in _VISIBLE)
        print(f"  {label}  {'← 看得到（開啟時 GUI 標題）' if visible else '（看不到，只能 /data get）'}")
        print(f"    方塊：{block_id} at ({x},{y},{z})")
        print(f"    寫入：{value}")
        print(f"    /tp @s {x} {y + 2} {z}")
    print()
    print(f"備份：{backup.directory}")
    print(f"資源包已加入 {TEST_KEY} → {TEST_VALUE}")
    return 0


def find(world: Path, generation: str) -> int:
    """掃出「世代對得上、而且有看得見 CustomName 的方塊」的 chunk。**唯讀。**

    只有容器的 `CustomName` 看得到（開啟時顯示在 GUI 標題）。一個 chunk 裡的容器
    通常沒幾個，所以隨便挑一個 chunk 多半湊不齊三個變體——那一趟進遊戲就白跑了。
    """
    from mcmt.nbtio.region import region_files

    wanted_legacy = generation == "legacy"
    hits = []
    for region_path in region_files(ensure_readable(world)):
        for raw in read_region(region_path):
            if raw.is_external:
                continue
            root = amulet_nbt.load(
                decompress_chunk(raw.payload, raw.compression_type, chunk_index=raw.index),
                compressed=False,
            ).compound
            data_version = root.get("DataVersion")
            if data_version is None:
                continue
            data_version = int(data_version)
            if (data_version < 4325) != wanted_legacy:
                continue
            entities = root.get("block_entities")
            if not isinstance(entities, amulet_nbt.ListTag):
                continue
            containers = [
                be
                for be in entities
                if isinstance(be, amulet_nbt.CompoundTag)
                and any(v in str(be.get("id", "")) for v in _VISIBLE)
            ]
            if len(containers) < 3:
                continue
            first = containers[0]
            hits.append(
                (
                    str(region_path).replace(str(world) + "\\", "").replace("\\", "/"),
                    raw.index,
                    data_version,
                    len(containers),
                    (int(first["x"]), int(first["y"]), int(first["z"])),
                )
            )
            if len(hits) >= 20:
                break
        if len(hits) >= 20:
            break

    if not hits:
        print(f"找不到 {generation} 世代、且有 3 個以上容器的 chunk", file=sys.stderr)
        return 2

    print(f"{generation} 世代、容器夠多的 chunk（最多列 20 個）：")
    for relative, index, data_version, count, (x, y, z) in hits:
        print(
            f"  --region {relative} --chunk {index}"
            f"   DV {data_version}・容器 {count} 個・第一個在 ({x},{y},{z})"
        )
    return 0


def _add_key(path: Path) -> None:
    """把測試 key 併進既有的 resources.zip。"""
    target = ensure_writable(path)
    name = "assets/mcmt/lang/zh_tw.json"
    existing: dict[str, str] = {}
    carried = []
    if target.exists():
        with zipfile.ZipFile(str(ensure_readable(target))) as archive:
            for info in archive.infolist():
                if info.filename == name:
                    existing = json.loads(archive.read(name))
                else:
                    carried.append((info, archive.read(info.filename)))
    existing[TEST_KEY] = TEST_VALUE

    temporary = ensure_writable(target.with_name(target.name + ".mcmt-tmp"))
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, data in carried:
            archive.writestr(info, data)
        archive.writestr(name, json.dumps(existing, ensure_ascii=False, indent=2))
    temporary.replace(target)


if __name__ == "__main__":
    raise SystemExit(main())
