"""Spike probe: level.dat, scoreboard.dat, and resources.zip of a real map.

Throwaway. Answers Q2 (paths in level.dat / scoreboard) and Q4 (resources.zip shape)
against an actual shipped adventure map rather than documentation claims.

Usage: python probe_world_meta.py <world_dir>
"""
import json
import sys
import zipfile
from pathlib import Path

import amulet_nbt


def load(path):
    return amulet_nbt.load(str(path))


def scalar(tag):
    for attr in ("py_str", "py_int", "py_float", "py_data"):
        if hasattr(tag, attr):
            try:
                return repr(getattr(tag, attr))
            except Exception:  # noqa: BLE001
                pass
    return repr(tag)


def walk(tag, prefix="", depth=0, max_depth=4, out=None):
    """Yield (path, type, preview) for a bounded walk of an NBT tree."""
    if out is None:
        out = []
    if depth > max_depth:
        return out
    tname = type(tag).__name__
    if isinstance(tag, amulet_nbt.CompoundTag):
        for k, v in tag.items():
            walk(v, f"{prefix}.{k}" if prefix else str(k), depth + 1, max_depth, out)
    elif isinstance(tag, amulet_nbt.ListTag):
        out.append((prefix, tname, f"<{len(tag)} entries>"))
        for i, v in enumerate(list(tag)[:3]):
            walk(v, f"{prefix}[{i}]", depth + 1, max_depth, out)
    else:
        out.append((prefix, tname, scalar(tag)[:160]))
    return out


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


world = Path(sys.argv[1])

section(f"level.dat  ({world.name})")
lvl = load(world / "level.dat")
root = lvl.compound
data = root["Data"]
for key in ("DataVersion", "LevelName", "Version", "WasModded"):
    if key in data:
        print(f"  Data.{key:24s} = {data[key]}")
print("\n  -- top-level Data keys --")
print("  " + ", ".join(sorted(str(k) for k in data.keys())))

# the fields that matter for a translation tool
section("level.dat :: text-bearing + resource-pack-related fields")
for path, tname, val in walk(data, "Data", max_depth=3):
    low = path.lower()
    if any(w in low for w in ("name", "pack", "resource", "motd", "text", "title")):
        print(f"  {path:52s} {tname:16s} {val}")

section("scoreboard.dat")
sb = world / "data" / "scoreboard.dat"
if sb.exists():
    sbt = load(sb)
    for path, tname, val in walk(sbt.compound, max_depth=5):
        print(f"  {path:56s} {tname:16s} {val}")
else:
    print("  (absent)")

section("resources.zip")
rz = world / "resources.zip"
if rz.exists():
    print(f"  size: {rz.stat().st_size:,} bytes")
    with zipfile.ZipFile(rz) as z:
        names = z.namelist()
        print(f"  entries: {len(names)}")
        for n in names[:40]:
            print(f"    {n}")
        if len(names) > 40:
            print(f"    ... and {len(names) - 40} more")
        if "pack.mcmeta" in names:
            print("\n  -- pack.mcmeta --")
            print("  " + z.read("pack.mcmeta").decode("utf-8-sig").replace("\n", "\n  "))
        langs = [n for n in names if "/lang/" in n and n.endswith(".json")]
        print(f"\n  -- lang files: {len(langs)} --")
        for n in langs[:10]:
            raw = z.read(n).decode("utf-8-sig")
            try:
                d = json.loads(raw)
                items = list(d.items())[:5]
                print(f"    {n}  ({len(d)} keys)")
                for k, v in items:
                    print(f"       {k!r}: {v!r}")
            except Exception as e:  # noqa: BLE001
                print(f"    {n}  UNPARSEABLE {e}")
else:
    print("  (absent)")
