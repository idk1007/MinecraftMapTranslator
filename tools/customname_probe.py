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
VARIANTS = [
    ("A SNBT 形式", '{translate:"' + TEST_KEY + '"}'),
    ("B 舊式 JSON 物件", json.dumps({"translate": TEST_KEY}, separators=(",", ":"))),
    ("C 對照組 純文字", "對照組 純文字"),
]

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
    args = parser.parse_args()

    world = Path(args.world).resolve()
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
    if len(candidates) < len(VARIANTS):
        print(f"這個 chunk 只有 {len(candidates)} 個可用的方塊實體", file=sys.stderr)
        return 2

    placed = []
    for (label, value), entity in zip(VARIANTS, candidates):
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
    print(f"chunk {args.chunk}（DataVersion {data_version}）")
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
