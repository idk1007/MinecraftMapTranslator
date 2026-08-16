"""Spike probe: the reverse test. WRITE both candidate encodings and let the
game judge which one is correct.

Throwaway, but this is the experiment that actually de-risks the writer.
Reading proved the game *stores* plain lines as TAG_Compound{'': ...}. It did
not prove that a file we author that way will render. So we write one sign with
each candidate encoding and compare in-game:

  FRONT  variant A - {'': 'text'}      (what the game itself produced)
  BACK   variant B - {'text': 'text'}  (the intuitive JSON-shaped guess)

Line 1 of both is {'translate': 'block.minecraft.diamond_block'}, which forces
the list to TAG_Compound and is the whole reason the question exists.

Demonstrates the copy-verbatim rule at the same time: only the one chunk we
touch is decoded and re-encoded; every other chunk's original compressed bytes
are written back unchanged.

Usage: python write_sign_variants.py <world_dir>
"""
import shutil
import struct
import sys
import zlib
from io import BytesIO
from pathlib import Path

import amulet_nbt

SECTOR = 4096
MARKER = "TT_SIGN_FRONT_1"

world = Path(sys.argv[1])


def read_region_raw(path):
    """{(index): (compressed_payload, compression_id)} - payload untouched."""
    raw = path.read_bytes()
    out = {}
    for i in range(1024):
        off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
        if off == 0:
            continue
        pos = off * SECTOR
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        comp = raw[pos + 4]
        out[i] = (raw[pos + 5:pos + 4 + length], comp)
    return out, raw


def write_region(path, chunks, original_raw):
    loc = bytearray(SECTOR)
    ts = bytearray(original_raw[SECTOR:SECTOR * 2])
    body = BytesIO()
    cursor = 2
    for i in range(1024):
        if i not in chunks:
            continue
        payload, comp = chunks[i]
        blob = struct.pack(">I", len(payload) + 1) + bytes([comp]) + payload
        blob += b"\x00" * ((-len(blob)) % SECTOR)
        count = len(blob) // SECTOR
        loc[i * 4:i * 4 + 3] = cursor.to_bytes(3, "big")
        loc[i * 4 + 3] = count
        body.write(blob)
        cursor += count
    path.write_bytes(bytes(loc) + bytes(ts) + body.getvalue())


def variant_a(text):
    """What the game itself writes: a compound keyed by the empty string."""
    c = amulet_nbt.CompoundTag()
    c[""] = amulet_nbt.StringTag(text)
    return c


def variant_b(text):
    """The intuitive guess: a normal text component."""
    c = amulet_nbt.CompoundTag()
    c["text"] = amulet_nbt.StringTag(text)
    return c


def translate(key):
    c = amulet_nbt.CompoundTag()
    c["translate"] = amulet_nbt.StringTag(key)
    return c


target_region = None
target_index = None
for rf in sorted((world / "region").glob("*.mca")):
    chunks, raw = read_region_raw(rf)
    for idx, (payload, comp) in chunks.items():
        data = zlib.decompress(payload) if comp == 2 else payload
        if MARKER.encode() not in data:
            continue
        target_region, target_index = rf, idx
        break
    if target_region:
        break

if target_region is None:
    sys.exit(f"sign carrying {MARKER!r} not found")

print(f"target region : {target_region.name}")
print(f"target chunk  : index {target_index}")

backup = target_region.with_suffix(".mca.prewrite")
if not backup.exists():
    shutil.copy2(target_region, backup)
    print(f"backup        : {backup.name}")

chunks, raw = read_region_raw(target_region)
payload, comp = chunks[target_index]
data = zlib.decompress(payload) if comp == 2 else payload
tag = amulet_nbt.load(data, compressed=False)

edited = None
for be in tag.compound["block_entities"]:
    ft = be.get("front_text")
    if ft is None or MARKER not in str(ft.get("messages")):
        continue

    front = amulet_nbt.ListTag()
    front.append(translate("block.minecraft.diamond_block"))
    front.append(variant_a("A2 empty-key"))
    front.append(variant_a("A3 empty-key"))
    front.append(variant_a("A4 empty-key"))
    ft["messages"] = front

    bt = be["back_text"]
    back = amulet_nbt.ListTag()
    back.append(translate("block.minecraft.diamond_block"))
    back.append(variant_b("B2 text-key"))
    back.append(variant_b("B3 text-key"))
    back.append(variant_b("B4 text-key"))
    bt["messages"] = back

    edited = (int(be["x"]), int(be["y"]), int(be["z"]))
    break

if edited is None:
    sys.exit("sign found in chunk but not matched in block_entities")

new_data = tag.save_to(compressed=False)
chunks[target_index] = (zlib.compress(new_data) if comp == 2 else new_data, comp)

# copy-verbatim rule: every other entry in `chunks` is still the original
# compressed payload, never decoded, never re-deflated.
write_region(target_region, chunks, raw)

print(f"\nedited sign at {edited}")
print("  FRONT = variant A  {'': 'text'}      <- what the game wrote itself")
print("  BACK  = variant B  {'text': 'text'}  <- the intuitive guess")
print("  line 1 of both is {'translate': 'block.minecraft.diamond_block'}")

# verify what landed on disk
chunks2, _ = read_region_raw(target_region)
p2, c2 = chunks2[target_index]
tag2 = amulet_nbt.load(zlib.decompress(p2) if c2 == 2 else p2, compressed=False)
for be in tag2.compound["block_entities"]:
    if (int(be.get("x", 0)), int(be.get("y", 0)), int(be.get("z", 0))) != edited:
        continue
    for side in ("front_text", "back_text"):
        msgs = be[side]["messages"]
        keys = [sorted(str(k) for k in m.keys()) for m in msgs]
        print(f"\n  re-read {side}: {len(msgs)} elements, keys per element = {keys}")
    break

untouched = sum(1 for i in chunks if i != target_index)
print(f"\n{untouched} other chunks in this region were copied verbatim "
      f"(never decoded, never re-compressed)")
print("\nNow open the world and compare the two sides of that sign.")
