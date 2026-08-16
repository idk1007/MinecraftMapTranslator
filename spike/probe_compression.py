"""Spike probe: separate the three layers of "byte-identical", and survey
compression types actually present in real region files.

Throwaway. Answers two review questions that the first round-trip probe
conflated:

  (a) at which layer is a re-encoded chunk identical to the original?
        L1  decompressed NBT bytes      (parse -> serialise)
        L2  recompressed payload bytes  (parse -> serialise -> deflate)
        L3  raw compressed bytes copied verbatim
  (b) which compression type ids appear in the wild? type 4 (LZ4) would break
      a reader that only knows gzip(1)/zlib(2)/none(3). The high bit (0x80)
      marks a chunk stored externally in an .mcc file.

Usage: python probe_compression.py <world_dir> [<world_dir> ...]
"""
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

import amulet_nbt

SECTOR = 4096
TYPE_NAMES = {1: "gzip", 2: "zlib", 3: "uncompressed", 4: "LZ4", 127: "custom"}


def decompress(payload, comp):
    if comp == 1:
        return zlib.decompress(payload, 16 + zlib.MAX_WBITS)
    if comp == 2:
        return zlib.decompress(payload)
    if comp == 3:
        return payload
    raise ValueError(f"no decoder for compression type {comp}")


for world_arg in sys.argv[1:]:
    world = Path(world_arg)
    print("=" * 78)
    print(f"WORLD: {world.name}")
    print("=" * 78)

    type_hist = Counter()
    external = 0
    empty_slots = 0
    total_chunks = 0

    # ---- (b) compression type survey over every region file ----------------
    for sub in ("region", "entities", "poi"):
        d = world / sub
        if not d.exists():
            continue
        for rf in sorted(d.glob("*.mca")):
            raw = rf.read_bytes()
            if len(raw) < SECTOR * 2:
                continue
            for i in range(1024):
                loc = raw[i * 4:i * 4 + 4]
                off = int.from_bytes(loc[:3], "big")
                if off == 0:
                    empty_slots += 1
                    continue
                pos = off * SECTOR
                if pos + 5 > len(raw):
                    continue
                (length,) = struct.unpack(">I", raw[pos:pos + 4])
                comp = raw[pos + 4]
                total_chunks += 1
                if comp & 0x80:
                    external += 1
                    comp &= 0x7F
                type_hist[comp] += 1

    print(f"  chunks: {total_chunks}   empty slots: {empty_slots}   "
          f"external .mcc: {external}")
    print("  compression type distribution:")
    for t, n in sorted(type_hist.items()):
        print(f"     type {t:3d} ({TYPE_NAMES.get(t, 'UNKNOWN'):12s}) {n:8d}")
    unknown = [t for t in type_hist if t not in (1, 2, 3)]
    if unknown:
        print(f"     -> WOULD BREAK a zlib-only reader: types {unknown}")
    else:
        print("     -> only gzip/zlib/uncompressed present here")

    # ---- (a) layer-by-layer identity on one region file ---------------------
    regions = sorted((world / "region").glob("*.mca"))
    if not regions:
        print("\n  (no region files to test identity on)\n")
        continue
    rf = regions[0]
    raw = rf.read_bytes()
    l1_same = l1_diff = 0
    l2_same = l2_diff = 0
    l2_size_delta = 0
    tested = 0

    for i in range(1024):
        loc = raw[i * 4:i * 4 + 4]
        off = int.from_bytes(loc[:3], "big")
        if off == 0:
            continue
        pos = off * SECTOR
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        comp = raw[pos + 4]
        if comp & 0x80:
            continue
        payload = raw[pos + 5:pos + 4 + length]
        try:
            data = decompress(payload, comp)
        except Exception:  # noqa: BLE001
            continue
        tag = amulet_nbt.load(data, compressed=False)
        reser = tag.save_to(compressed=False)

        # L1: decompressed NBT bytes
        if reser == data:
            l1_same += 1
        else:
            l1_diff += 1

        # L2: recompressed payload bytes, using python's default deflate
        if comp == 2:
            re_payload = zlib.compress(reser)
            if re_payload == payload:
                l2_same += 1
            else:
                l2_diff += 1
                l2_size_delta += len(re_payload) - len(payload)
        tested += 1

    print(f"\n  identity test on {rf.name} ({tested} chunks)")
    print(f"    L1 decompressed NBT bytes identical : {l1_same}/{l1_same + l1_diff}")
    print(f"    L2 recompressed payload identical   : {l2_same}/{l2_same + l2_diff}")
    if l2_diff:
        avg = l2_size_delta / l2_diff
        print(f"       -> recompression is NOT byte-stable; mean size delta "
              f"{avg:+.0f} bytes/chunk")
        print("       -> therefore untouched chunks MUST have their original")
        print("          compressed bytes copied verbatim, never re-encoded.")
    print()
