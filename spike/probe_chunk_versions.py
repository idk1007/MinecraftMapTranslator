"""Spike probe: is a single world uniform in format, or a patchwork?

Throwaway. Hypothesis: Minecraft only runs DataFixerUpper on chunks it actually
loads, so a long-lived map can hold chunks from several format generations at
once - which would mean the tool cannot assume one schema per world.

Measures:
  - per-chunk DataVersion histogram vs the world-level DataVersion
  - for sign text specifically, how often it is a bare string (old JSON-in-string
    or new literal) vs a real NBT compound
  - the exact shape of the odd '""' and empty-key values seen earlier

Usage: python probe_chunk_versions.py <world_dir>
"""
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

import amulet_nbt

SECTOR = 4096
world = Path(sys.argv[1])


def read_region(path):
    raw = path.read_bytes()
    for i in range(1024):
        loc = raw[i * 4:i * 4 + 4]
        off = int.from_bytes(loc[:3], "big")
        if off == 0:
            continue
        pos = off * SECTOR
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        comp = raw[pos + 4]
        payload = raw[pos + 5:pos + 4 + length]
        try:
            if comp == 1:
                data = zlib.decompress(payload, 16 + zlib.MAX_WBITS)
            elif comp == 2:
                data = zlib.decompress(payload)
            else:
                data = payload
            yield amulet_nbt.load(data, compressed=False)
        except Exception:  # noqa: BLE001
            continue


world_dv = amulet_nbt.load(str(world / "level.dat")).compound["Data"]["DataVersion"].py_int
print(f"world-level DataVersion (level.dat): {world_dv}\n")

dv_hist = Counter()
sign_shapes = Counter()
customname_shapes = Counter()
odd_samples = []
chunks = 0

for rf in sorted((world / "region").glob("*.mca")):
    for tag in read_region(rf):
        root = tag.compound
        chunks += 1
        dv = root.get("DataVersion")
        dv_hist[dv.py_int if dv is not None else "missing"] += 1

        for be in root.get("block_entities", []) or []:
            if not isinstance(be, amulet_nbt.CompoundTag):
                continue
            bid = str(be.get("id", ""))

            cn = be.get("CustomName")
            if cn is not None:
                if isinstance(cn, amulet_nbt.StringTag):
                    v = cn.py_str
                    looks_json = v.lstrip().startswith(("{", "[", '"'))
                    customname_shapes[
                        "StringTag(JSON-ish)" if looks_json else "StringTag(literal)"] += 1
                    if looks_json and len(odd_samples) < 6:
                        odd_samples.append(("CustomName", bid, v[:120]))
                elif isinstance(cn, amulet_nbt.CompoundTag):
                    customname_shapes["CompoundTag(native)"] += 1
                else:
                    customname_shapes[type(cn).__name__] += 1

            for side in ("front_text", "back_text"):
                st = be.get(side)
                if not isinstance(st, amulet_nbt.CompoundTag):
                    continue
                for msg in st.get("messages", []) or []:
                    if isinstance(msg, amulet_nbt.StringTag):
                        v = msg.py_str
                        if v == "":
                            sign_shapes["StringTag(empty)"] += 1
                        elif v.lstrip().startswith(("{", "[", '"')):
                            sign_shapes["StringTag(JSON-ish)"] += 1
                            if len(odd_samples) < 12:
                                odd_samples.append((f"{side}.messages", bid, repr(v)[:120]))
                        else:
                            sign_shapes["StringTag(literal)"] += 1
                    elif isinstance(msg, amulet_nbt.CompoundTag):
                        keys = sorted(str(k) for k in msg.keys())
                        if "" in keys:
                            if len(odd_samples) < 12:
                                odd_samples.append(
                                    (f"{side}.messages EMPTY-KEY", bid, str(keys)))
                        if "translate" in keys:
                            sign_shapes["CompoundTag(translate)"] += 1
                        elif "text" in keys:
                            sign_shapes["CompoundTag(text)"] += 1
                        else:
                            sign_shapes[f"CompoundTag({','.join(keys)[:40]})"] += 1
                    else:
                        sign_shapes[type(msg).__name__] += 1

print(f"scanned {chunks} chunks\n")
print("=" * 70)
print("per-chunk DataVersion histogram")
print("=" * 70)
for dv, n in sorted(dv_hist.items(), key=lambda x: str(x[0])):
    mark = "  <-- matches level.dat" if dv == world_dv else ""
    print(f"  {str(dv):>10}  {n:6d} chunks{mark}")
if len([k for k in dv_hist if k != "missing"]) > 1:
    print("\n  => MIXED. Chunks are upgraded lazily; schema is per-chunk, not per-world.")
else:
    print("\n  => uniform across all chunks in this world.")

print()
print("=" * 70)
print("sign message value shapes")
print("=" * 70)
for k, n in sign_shapes.most_common():
    print(f"  {k:34s} {n:6d}")

print()
print("=" * 70)
print("block entity CustomName shapes")
print("=" * 70)
for k, n in customname_shapes.most_common():
    print(f"  {k:34s} {n:6d}")

print()
print("=" * 70)
print("odd samples")
print("=" * 70)
for where, bid, val in odd_samples:
    print(f"  [{bid}] {where}")
    print(f"      {val}")
