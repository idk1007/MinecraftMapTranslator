"""Spike probe Q4: how does a real shipped map wire up its forced resource pack?

Throwaway. The map under test already uses exactly the architecture we are
proposing, so it is a reference implementation rather than a guess: read its
pack.mcmeta, its lang files, and how the world references the pack.

Usage: python probe_resourcepack.py <world_dir>
"""
import json
import sys
import zipfile
from pathlib import Path

import amulet_nbt

world = Path(sys.argv[1])
rz = world / "resources.zip"

print("=" * 74)
print("world-side wiring")
print("=" * 74)
print(f"  resources.zip present : {rz.exists()}")
if rz.exists():
    print(f"  size                  : {rz.stat().st_size:,} bytes")
    print(f"  is a real zip         : {zipfile.is_zipfile(rz)}")

lvl = amulet_nbt.load(str(world / "level.dat")).compound["Data"]
refs = [k for k in lvl.keys() if "pack" in str(k).lower() or "resource" in str(k).lower()]
print(f"  level.dat keys mentioning pack/resource: {refs}")
print("  (a world-side resources.zip needs no level.dat entry - it is implicit)")

if not rz.exists():
    sys.exit(0)

print()
print("=" * 74)
print("pack.mcmeta")
print("=" * 74)
with zipfile.ZipFile(rz) as z:
    names = z.namelist()
    raw = z.read("pack.mcmeta").decode("utf-8-sig")
    print(raw)
    meta = json.loads(raw)
    pf = meta["pack"].get("pack_format")
    print(f"  declared pack_format : {pf}")
    print(f"  supported_formats    : {meta['pack'].get('supported_formats', 'ABSENT')}")
    print("  NOTE: 1.21.11 wants resource pack_format 75; this map ships"
          f" {pf} and still loads,")
    print("        i.e. a stale pack_format degrades to a warning, not a refusal.")

    print()
    print("=" * 74)
    print("archive layout")
    print("=" * 74)
    tops = sorted({n.split("/")[0] for n in names})
    print(f"  top-level entries: {tops}")
    has_dir_prefix = any(n.count("/") and not n.startswith(("assets/", "pack."))
                         for n in names)
    print(f"  pack.mcmeta at archive root: {'pack.mcmeta' in names}")
    print(f"  stray wrapper directory    : {has_dir_prefix}")

    print()
    print("=" * 74)
    print("lang files - the output format we would be generating")
    print("=" * 74)
    langs = sorted(n for n in names if "/lang/" in n and n.endswith(".json"))
    for n in langs:
        raw = z.read(n).decode("utf-8-sig")
        size = len(raw)
        try:
            d = json.loads(raw)
            status = f"strict JSON OK, {len(d)} keys"
        except json.JSONDecodeError as e:
            status = f"NOT strict JSON ({e.msg} at line {e.lineno})"
            d = None
        print(f"\n  {n}  [{size:,} bytes]  {status}")
        # show the first few raw lines so we can see *why* it fails strict JSON
        for line in raw.split("\n")[:8]:
            print(f"      | {line[:110]}")
        if d:
            for k, v in list(d.items())[:5]:
                print(f"      {k!r}: {v!r}")
