"""Spike probe Q2: discover, empirically, where text actually lives in NBT.

Throwaway. Rather than trusting a wiki table, this walks every chunk of a real
world and reports the *path signatures* that carry text, with real samples and
counts. List indices collapse to [] so the output is a compact schema.

Usage: python probe_text_paths.py <world_dir> [--markers] [--limit N]
       --markers  only report paths whose value contains a TT_ fixture marker
"""
import json
import struct
import sys
import zlib
from collections import defaultdict
from pathlib import Path

import amulet_nbt

SECTOR = 4096

world = Path(sys.argv[1])
ONLY_MARKERS = "--markers" in sys.argv
LIMIT = 999999
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

# path signature -> {"count": n, "types": set, "samples": [...]}
paths = defaultdict(lambda: {"count": 0, "types": set(), "samples": []})


def note(sig, tag, value):
    e = paths[sig]
    e["count"] += 1
    e["types"].add(type(tag).__name__)
    if len(e["samples"]) < 3 and value not in e["samples"]:
        e["samples"].append(value)


def interesting(value):
    if not isinstance(value, str) or not value:
        return False
    if ONLY_MARKERS:
        return "TT_" in value
    return True


def walk(tag, sig):
    if isinstance(tag, amulet_nbt.CompoundTag):
        for k, v in tag.items():
            walk(v, f"{sig}.{k}" if sig else str(k))
    elif isinstance(tag, amulet_nbt.ListTag):
        for v in tag:
            walk(v, f"{sig}[]")
    elif isinstance(tag, amulet_nbt.StringTag):
        val = tag.py_str
        if interesting(val):
            note(sig, tag, val)


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


# region/ = block entities;  entities/ = mobs since 1.17;  both matter
scanned = 0
for sub, label in (("region", "REGION"), ("entities", "ENTITIES")):
    d = world / sub
    if not d.exists():
        continue
    for rf in sorted(d.glob("*.mca")):
        for tag in read_region(rf):
            walk(tag.compound, label)
            scanned += 1
            if scanned >= LIMIT:
                break
        if scanned >= LIMIT:
            break

# also the flat files
for rel in ("level.dat", "data/scoreboard.dat"):
    p = world / rel
    if p.exists():
        walk(amulet_nbt.load(str(p)).compound, rel.replace("/", "_").upper())

print(f"scanned {scanned} chunks\n")

# ---- report, sorted by how text-ish the path name looks -------------------
TEXT_HINTS = ("text", "name", "lore", "message", "title", "author", "page",
              "description", "display", "prefix", "suffix", "translate",
              "command", "customname", "value")


def rank(sig):
    low = sig.lower()
    return (0 if any(h in low for h in TEXT_HINTS) else 1, -paths[sig]["count"])


print("=" * 78)
print("PATH SIGNATURES CARRYING STRINGS  (text-ish first)")
print("=" * 78)
for sig in sorted(paths, key=rank):
    e = paths[sig]
    low = sig.lower()
    flag = "TEXT?" if any(h in low for h in TEXT_HINTS) else "     "
    print(f"\n{flag} {sig}")
    print(f"      count={e['count']}  types={sorted(e['types'])}")
    for s in e["samples"]:
        print(f"      | {s[:150]!r}")

print()
print("=" * 78)
print(f"{len(paths)} distinct path signatures")
print("=" * 78)

out = world.parent / f"{world.name}_paths.json"
out.write_text(json.dumps(
    {k: {"count": v["count"], "types": sorted(v["types"]), "samples": v["samples"]}
     for k, v in paths.items()}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"full dump -> {out}")
