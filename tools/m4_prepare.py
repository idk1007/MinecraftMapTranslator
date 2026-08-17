# SPDX-License-Identifier: GPL-3.0-or-later
"""M4 legacy 寫入驗證的準備工作（可重跑）。

    python tools/m4_prepare.py "sandbox/<世界>" --region region/r.-1.-1.mca --chunk 1022

做三件事，全部在 sandbox 內：

1. 把指定 chunk 裡**空白的**告示牌改寫成一面四行實驗（見下），走 `BackupSet` 保護。
2. 在世界根目錄產生 `resources.zip`（`mcmt.test.legacy` → 中文）。
3. 印出座標與檢查清單。

**四行實驗**——一面告示牌同時回答四個問題，四行都是 `TAG_String`（legacy 形狀），
寫進一個 DataVersion 遠低於 4325 的 chunk：

    第 1 行  '{"translate":"mcmt.test.legacy"}'   資源包的 key 在舊世代 chunk 解不解得開
    第 2 行  '{"text":"對照組A 物件"}'            舊式 JSON 物件到底有沒有被解析
    第 3 行  '"對照組B 純量"'                     json_string_scalar（這張地圖自己就在用）
    第 4 行  '""'                                 空字串在舊世代是空白，還是像 M0-4 那樣顯示引號

第 2、3 行同時是「你找對告示牌了」的訊號：就算資源包整個沒生效，它們也該出現。

**為什麼要挑本來就空白的告示牌**：這樣看到的任何東西都是我們造成的，不會和地圖
原本的內容混淆。
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
from mcmt.nbtio.structure import ensure_supported_structure  # noqa: E402
from mcmt.safety.backup import BackupSet  # noqa: E402
from mcmt.safety.paths import ensure_readable, ensure_writable  # noqa: E402

TEST_KEY = "mcmt.test.legacy"
TEST_VALUE = "哈囉舊世代"
LINES = [
    '{"translate":"' + TEST_KEY + '"}',
    '{"text":"對照組A 物件"}',
    '"對照組B 純量"',
    '""',
]
PACK_FORMAT = 75  # 1.21.11


def is_blank_sign(entry: amulet_nbt.CompoundTag) -> bool:
    front = entry.get("front_text")
    if not isinstance(front, amulet_nbt.CompoundTag):
        return False
    messages = front.get("messages")
    if not isinstance(messages, amulet_nbt.ListTag):
        return False
    return all(
        isinstance(m, amulet_nbt.StringTag) and str(m) in ('""', "")
        for m in messages
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", help="sandbox 底下的世界資料夾")
    parser.add_argument("--region", default="region/r.-1.-1.mca")
    parser.add_argument("--chunk", type=int, default=1022)
    args = parser.parse_args()

    world = Path(args.world).resolve()
    region_path = world / args.region

    original = list(read_region(ensure_readable(region_path)))
    target_chunk = next((c for c in original if c.index == args.chunk), None)
    if target_chunk is None:
        print(f"chunk {args.chunk} 不在 {args.region} 裡", file=sys.stderr)
        return 2

    root = amulet_nbt.load(
        decompress_chunk(
            target_chunk.payload,
            target_chunk.compression_type,
            chunk_index=target_chunk.index,
        ),
        compressed=False,
    ).compound
    data_version = ensure_supported_structure(root, chunk_index=target_chunk.index)

    edited = []
    for entry in root["block_entities"]:
        if not isinstance(entry, amulet_nbt.CompoundTag):
            continue
        if "sign" not in str(entry.get("id", "")) or not is_blank_sign(entry):
            continue
        messages = amulet_nbt.ListTag([amulet_nbt.StringTag(line) for line in LINES])
        entry["front_text"]["messages"] = messages
        edited.append((int(entry["x"]), int(entry["y"]), int(entry["z"])))

    if not edited:
        print(f"chunk {args.chunk} 裡沒有空白告示牌", file=sys.stderr)
        return 2

    payload = _recompress(root, target_chunk.compression_type)

    with BackupSet(world) as backup:
        backup.protect(region_path)
        report = write_region(
            region_path,
            [
                ChunkWrite.replaced(c, payload) if c.index == args.chunk
                else ChunkWrite.unchanged(c)
                for c in original
            ],
        )
        backup.protect(world / "resources.zip")
        pack_action = _write_pack(world / "resources.zip")

    print(f"世界：{world}")
    print(f"改動的 chunk：{args.region} 的 index {args.chunk}（DataVersion {data_version}）")
    print(f"改寫的告示牌 {len(edited)} 面：")
    for x, y, z in edited:
        print(f"  /tp @s {x} {y + 1} {z}")
    print(f"同 region 其餘 {report.chunks_written - 1} 個 chunk 原封未動"
          f"（磁區重整：{'是' if report.realigned else '否'}）")
    print(f"備份：{backup.directory}（{backup.file_count} 個檔案）")
    print(f"資源包：{world / 'resources.zip'} — {pack_action}"
          f"，{TEST_KEY} → {TEST_VALUE}")
    return 0


def _recompress(root: amulet_nbt.CompoundTag, compression_type: int) -> bytes:
    import zlib

    data = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
    if compression_type == 2:
        return zlib.compress(data)
    if compression_type == 1:
        import gzip

        return gzip.compress(data, mtime=0)
    raise SystemExit(f"這個腳本只處理 gzip/zlib，遇到壓縮類型 {compression_type}")


def _write_pack(path: Path) -> str:
    """把測試用的 lang 檔放進 `resources.zip`，**保留地圖原本的內容**。

    [實測] `Arena of Darkness` 自己就帶了一個 **131 MB 的 `resources.zip`**。第一次
    跑這個腳本時直接覆蓋掉它——`BackupSet` 接住了，但那正是 M10「既有 pack 合併」
    要處理的情況，而且覆蓋掉會讓整張地圖的材質與字型一起消失，M4 的觀察也就不可信了。

    合併規則：既有條目一個都不動（包含地圖自己的 `pack.mcmeta`——[遊戲實測 M0-5]
    過期的 `pack_format` 不警告也不拒載），只加上我們自己命名空間底下的 lang 檔。
    """
    target = ensure_writable(path)
    lang = json.dumps({TEST_KEY: TEST_VALUE}, ensure_ascii=False, indent=2)
    ours = {f"assets/mcmt/lang/{locale}.json": lang for locale in ("zh_tw", "en_us")}

    if not target.exists():
        meta = {
            "pack": {
                "pack_format": PACK_FORMAT,
                "supported_formats": {"min_inclusive": 55, "max_inclusive": PACK_FORMAT},
                "description": "mcmt M4 legacy 寫入驗證",
            }
        }
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("pack.mcmeta", json.dumps(meta, ensure_ascii=False, indent=2))
            for name, content in ours.items():
                archive.writestr(name, content)
        return "新建"

    # 合併：zip 沒辦法就地新增，所以整份重寫到暫存檔再換過去。
    temporary = ensure_writable(target.with_name(target.name + ".mcmt-tmp"))
    source = ensure_readable(target)
    carried = 0
    with zipfile.ZipFile(str(source)) as existing:
        names = [n for n in existing.namelist() if n not in ours]
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for info in existing.infolist():
                if info.filename not in names:
                    continue
                archive.writestr(info, existing.read(info.filename))
                carried += 1
            for name, content in ours.items():
                archive.writestr(name, content)
    temporary.replace(target)
    return f"合併（保留原有 {carried:,} 個條目）"


if __name__ == "__main__":
    raise SystemExit(main())
