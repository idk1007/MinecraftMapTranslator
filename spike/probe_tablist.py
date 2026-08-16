"""Spike probe: what feeds the tab player list, and is any of it persisted?

Throwaway. The tab list draws from several places; only some of them live in the
world save, and only those are translatable by this tool.

Usage: python probe_tablist.py <world_dir>
"""
import sys
from pathlib import Path

import amulet_nbt

world = Path(sys.argv[1])


def show(tag, indent=1, key=""):
    pad = "  " * indent
    label = f"{key!r}: " if key else ""
    if isinstance(tag, amulet_nbt.CompoundTag):
        print(f"{pad}{label}Compound {{")
        for k, v in tag.items():
            show(v, indent + 1, str(k))
        print(f"{pad}}}")
    elif isinstance(tag, amulet_nbt.ListTag):
        print(f"{pad}{label}List ({len(tag)})")
        for v in list(tag)[:6]:
            show(v, indent + 1)
    elif isinstance(tag, amulet_nbt.StringTag):
        print(f"{pad}{label}StringTag {tag.py_str!r}")
    else:
        print(f"{pad}{label}{type(tag).__name__} {tag}")


sb = world / "data" / "scoreboard.dat"
print("=" * 74)
print("data/scoreboard.dat")
print("=" * 74)
if sb.exists():
    root = amulet_nbt.load(str(sb)).compound
    data = root["data"]
    print(f"  top-level keys: {sorted(str(k) for k in data.keys())}")

    ds = data.get("DisplaySlots")
    print("\n  DisplaySlots (which objective is bound to which on-screen slot):")
    if ds is None:
        print("    (absent - nothing bound)")
    else:
        show(ds)
        print("    -> values are objective *identifiers*, not display text")

    print("\n  Objectives (DisplayName is the text actually rendered):")
    for obj in data.get("Objectives", []) or []:
        name = obj.get("Name")
        disp = obj.get("DisplayName")
        print(f"    Name={str(name)!r:24s} DisplayName type={type(disp).__name__}")
        if isinstance(disp, amulet_nbt.CompoundTag):
            show(disp, 3)
        elif disp is not None:
            print(f"       {disp.py_str!r}")

    print("\n  Teams (prefix/suffix decorate the name shown in the tab list):")
    for team in data.get("Teams", []) or []:
        print(f"    Name={str(team.get('Name'))!r}")
        for field in ("DisplayName", "MemberNamePrefix", "MemberNameSuffix"):
            v = team.get(field)
            if v is None:
                continue
            print(f"      {field}: {type(v).__name__}")
            show(v, 4)
else:
    print("  (absent)")

print()
print("=" * 74)
print("level.dat :: anything tab-list shaped?")
print("=" * 74)
data = amulet_nbt.load(str(world / "level.dat")).compound["Data"]
hits = [k for k in data.keys()
        if any(w in str(k).lower() for w in ("list", "header", "footer", "tab", "motd"))]
print(f"  keys matching list/header/footer/tab/motd: {hits}")
print("  NOTE: vanilla Java has no command that persists a tab-list header or")
print("        footer into the save - it is a packet-only feature, so a map can")
print("        only influence the tab list through teams and the 'list' slot.")
