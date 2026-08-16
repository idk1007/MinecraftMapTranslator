"""Spike probe: dump the raw NBT of the fixture block entities and entities.

Throwaway. The path-signature scan tells us *where* text lives; this shows the
exact tag types at those paths, which is what decides whether inserting
{"translate": ...} is a value edit or a type change.

Also chases two anomalies:
  - a path signature ending in '.'  (a compound with an empty-string key?)
  - how a {translate: ...} component is actually stored

Usage: python probe_dump_fixtures.py <world_dir>
"""
import struct
import sys
import zlib
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
            data = (zlib.decompress(payload, 16 + zlib.MAX_WBITS) if comp == 1
                    else zlib.decompress(payload) if comp == 2 else payload)
            yield amulet_nbt.load(data, compressed=False)
        except Exception:  # noqa: BLE001
            continue


def contains(tag, needle):
    if isinstance(tag, amulet_nbt.CompoundTag):
        return any(contains(v, needle) for v in tag.values())
    if isinstance(tag, amulet_nbt.ListTag):
        return any(contains(v, needle) for v in tag)
    if isinstance(tag, amulet_nbt.StringTag):
        return needle in tag.py_str
    return False


def show(tag, indent=0, key=""):
    pad = "  " * indent
    label = f"{key!r}: " if key != "" or indent else ""
    if isinstance(tag, amulet_nbt.CompoundTag):
        print(f"{pad}{label}CompoundTag {{")
        for k, v in tag.items():
            show(v, indent + 1, str(k))
        print(f"{pad}}}")
    elif isinstance(tag, amulet_nbt.ListTag):
        print(f"{pad}{label}ListTag [   ({len(tag)} items)")
        for v in tag:
            show(v, indent + 1)
        print(f"{pad}]")
    elif isinstance(tag, amulet_nbt.StringTag):
        print(f"{pad}{label}StringTag {tag.py_str!r}")
    else:
        print(f"{pad}{label}{type(tag).__name__} {tag}")


TARGETS = ["TT_SIGN_TRANSLATE_PROBE", "TT_SIGN_FRONT_1", "TT_ITEM_CUSTOM_NAME",
           "TT_BOOK_TITLE", "diamond_block"]

seen = set()
for sub in ("region", "entities"):
    d = world / sub
    if not d.exists():
        continue
    for rf in sorted(d.glob("*.mca")):
        for tag in read_region(rf):
            root = tag.compound
            for listname in ("block_entities", "Entities"):
                for be in root.get(listname, []) or []:
                    if not isinstance(be, amulet_nbt.CompoundTag):
                        continue
                    for t in TARGETS:
                        if t in seen:
                            continue
                        if contains(be, t):
                            seen.add(t)
                            bid = be.get("id", "?")
                            print("\n" + "=" * 74)
                            print(f"[{sub}] matched {t!r}   id={bid}")
                            print("=" * 74)
                            show(be)
                            break
        if len(seen) == len(TARGETS):
            break

missing = [t for t in TARGETS if t not in seen]
if missing:
    print(f"\nnot found: {missing}")
