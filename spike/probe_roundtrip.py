"""Spike probe Q1c: prove a surgical read-modify-write of a region file.

Throwaway, but this is the load-bearing experiment. A translation tool must
rewrite a handful of strings and leave everything else *bit-for-bit alone*.
So we measure three things:

  1. can we re-serialise a chunk we did not touch and get identical NBT back?
  2. can we edit one string and have the change survive a reload?
  3. do untouched chunks stay byte-identical in the rewritten region?

Also sizes the "write it yourself" option for Q1: the whole anvil layer is
the ~90 lines below.

Usage: python probe_roundtrip.py <world_dir_COPY>
"""
import shutil
import struct
import sys
import zlib
from io import BytesIO
from pathlib import Path

import amulet_nbt

SECTOR = 4096


# ------------------------------------------------------------------ anvil io
def read_region(path):
    """Return {(cx,cz): (nbt_bytes, compression_id)} plus the raw header."""
    raw = path.read_bytes()
    out = {}
    for i in range(1024):
        loc = raw[i * 4:i * 4 + 4]
        off = int.from_bytes(loc[:3], "big")
        if off == 0:
            continue
        pos = off * SECTOR
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        comp = raw[pos + 4]
        payload = raw[pos + 5:pos + 4 + length]
        out[(i % 32, i // 32)] = (payload, comp)
    return out, raw


def decompress(payload, comp):
    if comp == 1:
        return zlib.decompress(payload, 16 + zlib.MAX_WBITS)  # gzip
    if comp == 2:
        return zlib.decompress(payload)  # zlib
    if comp == 3:
        return payload  # uncompressed
    raise ValueError(f"unsupported compression id {comp}")


def compress(data, comp):
    if comp == 1:
        c = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
        return c.compress(data) + c.flush()
    if comp == 2:
        return zlib.compress(data)
    if comp == 3:
        return data
    raise ValueError(f"unsupported compression id {comp}")


def write_region(path, chunks, timestamps_src):
    """Rebuild a region file from {(cx,cz): (payload, comp)}."""
    loc_table = bytearray(SECTOR)
    ts_table = bytearray(timestamps_src[SECTOR:SECTOR * 2])
    body = BytesIO()
    sector_cursor = 2  # first two sectors are the tables

    for i in range(1024):
        key = (i % 32, i // 32)
        if key not in chunks:
            continue
        payload, comp = chunks[key]
        blob = struct.pack(">I", len(payload) + 1) + bytes([comp]) + payload
        pad = (-len(blob)) % SECTOR
        blob += b"\x00" * pad
        count = len(blob) // SECTOR
        if count > 255:
            raise ValueError("oversized chunk needs the external .mcc path")
        loc_table[i * 4:i * 4 + 3] = sector_cursor.to_bytes(3, "big")
        loc_table[i * 4 + 3] = count
        body.write(blob)
        sector_cursor += count

    path.write_bytes(bytes(loc_table) + bytes(ts_table) + body.getvalue())


# ---------------------------------------------------------------- experiment
world = Path(sys.argv[1])
region_dir = world / "region"
target = sorted(region_dir.glob("*.mca"))[0]

backup = target.with_suffix(".mca.spikebak")
if not backup.exists():
    shutil.copy2(target, backup)
print(f"region under test : {target.name}  ({target.stat().st_size:,} bytes)")

chunks, raw = read_region(target)
print(f"chunks present    : {len(chunks)}")

# --- experiment 1: NBT re-serialisation fidelity, no edits -------------------
identical = 0
differing = []
for key, (payload, comp) in chunks.items():
    data = decompress(payload, comp)
    tag = amulet_nbt.load(data, compressed=False)
    reser = tag.save_to(compressed=False)
    if reser == data:
        identical += 1
    else:
        differing.append((key, len(data), len(reser)))
print(f"\n[1] NBT re-serialise without editing:")
print(f"    byte-identical : {identical}/{len(chunks)}")
if differing:
    print(f"    differing      : {len(differing)}  e.g. {differing[:3]}")
    print("    -> re-serialisation is NOT byte-stable; only rewrite touched chunks")
else:
    print("    -> re-serialisation is byte-stable")

# --- experiment 2: surgical edit survives a reload ---------------------------
# find any chunk carrying a block entity we can rename
edited_key = None
for key, (payload, comp) in chunks.items():
    data = decompress(payload, comp)
    tag = amulet_nbt.load(data, compressed=False)
    root = tag.compound
    bes = root.get("block_entities")
    if bes is None or len(bes) == 0:
        continue
    be = bes[0]
    be["SpikeMarker"] = amulet_nbt.StringTag("TT_ROUNDTRIP_MARKER")
    new_data = tag.save_to(compressed=False)
    chunks[key] = (compress(new_data, comp), comp)
    edited_key = key
    print(f"\n[2] edited chunk {key}: injected SpikeMarker into "
          f"block_entity id={be.get('id')}")
    break

if edited_key is None:
    print("\n[2] SKIPPED - no block entities in this region")
else:
    write_region(target, chunks, raw)
    print(f"    rewrote region ({target.stat().st_size:,} bytes)")

    reread, _ = read_region(target)
    payload, comp = reread[edited_key]
    tag = amulet_nbt.load(decompress(payload, comp), compressed=False)
    marker = tag.compound["block_entities"][0].get("SpikeMarker")
    ok = marker is not None and str(marker.py_str) == "TT_ROUNDTRIP_MARKER"
    print(f"    marker survived reload: {ok}  ({marker})")

    # --- experiment 3: untouched chunks unchanged ---------------------------
    orig, _ = read_region(backup)
    same = sum(1 for k in orig
               if k != edited_key and k in reread and orig[k][0] == reread[k][0])
    total = len(orig) - 1
    print(f"\n[3] untouched chunks byte-identical: {same}/{total}")
    if same == total:
        print("    -> surgical rewrite is safe")
    else:
        print("    -> WARNING: rewrite perturbed chunks we never edited")

# restore so the copy stays reusable
shutil.copy2(backup, target)
backup.unlink()
print("\nrestored original region from backup")
