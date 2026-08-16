"""Spike probe: the translation sources that are neither chunks nor level.dat.

Throwaway. Covers custom bossbars, the datapacks folder (.mcfunction + JSON),
player advancement files, and the naming convention a shipped map uses for its
translate keys.

Usage: python probe_misc_sources.py <world_dir>
"""
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import amulet_nbt

world = Path(sys.argv[1])


def lenient_json(raw):
    """Minecraft's lang parser tolerates // comments; json.loads does not."""
    no_block = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    no_line = re.sub(r'(?<!:)//(?![^"]*"\s*[,}]).*?$', "", no_block, flags=re.M)
    return json.loads(no_line)


print("=" * 74)
print("level.dat :: CustomBossEvents")
print("=" * 74)
data = amulet_nbt.load(str(world / "level.dat")).compound["Data"]
cbe = data.get("CustomBossEvents")
if cbe is None or len(cbe) == 0:
    print("  (none in this map)")
else:
    print(f"  {len(cbe)} bossbar(s)")
    for i, (bid, bar) in enumerate(cbe.items()):
        if i >= 3:
            break
        name = bar.get("Name")
        print(f"  id={bid}")
        print(f"     Name type={type(name).__name__}  value={str(name)[:110]}")

print()
print("=" * 74)
print("datapacks/")
print("=" * 74)
dp = world / "datapacks"
if dp.exists():
    for entry in sorted(dp.iterdir()):
        kind = "zip" if entry.is_file() else "dir"
        print(f"  [{kind}] {entry.name}")
    fns = list(dp.rglob("*.mcfunction"))
    jsons = list(dp.rglob("*.json"))
    print(f"\n  .mcfunction files : {len(fns)}")
    print(f"  .json files       : {len(jsons)}")

    # which commands carry user-visible text?
    cmd_hist = Counter()
    text_bearing = 0
    for f in fns[:2000]:
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                cmd_hist[line.split()[0]] += 1
                if any(t in line for t in ('"text"', '"translate"', "text:", "translate:",
                                           "custom_name", "item_name", "lore")):
                    text_bearing += 1
        except Exception:  # noqa: BLE001
            continue
    print(f"  lines carrying text-ish payload: {text_bearing}")
    print("  top commands in functions:")
    for c, n in cmd_hist.most_common(15):
        print(f"     {c:22s} {n}")
else:
    print("  (absent)")

print()
print("=" * 74)
print("advancements/ (player progress files, not definitions)")
print("=" * 74)
adv = world / "advancements"
if adv.exists():
    files = list(adv.glob("*.json"))
    print(f"  {len(files)} player file(s) - these hold *earned* state, no display text")
    if files:
        d = json.loads(files[0].read_text(encoding="utf-8"))
        keys = [k for k in d if not k.startswith("Data")][:6]
        print(f"  sample keys: {keys}")
else:
    print("  (absent)")

print()
print("=" * 74)
print("translate-key naming convention used by this shipped map")
print("=" * 74)
rz = world / "resources.zip"
if rz.exists():
    with zipfile.ZipFile(rz) as z:
        target = "assets/minecraft/lang/zh_cn.json"
        if target in z.namelist():
            raw = z.read(target).decode("utf-8-sig")
            try:
                d = lenient_json(raw)
            except Exception as e:  # noqa: BLE001
                print(f"  lenient parse still failed: {e}")
                d = None
            if d:
                print(f"  {target}: {len(d)} keys")
                prefixes = Counter(k.split(".")[0] for k in d)
                print("  key prefixes:")
                for p, n in prefixes.most_common(12):
                    print(f"     {p:24s} {n}")
                print("\n  sample custom (non-vanilla) keys:")
                shown = 0
                for k, v in d.items():
                    if k.startswith("mcp."):
                        print(f"     {k!r}: {v[:60]!r}")
                        shown += 1
                        if shown >= 12:
                            break
                # how many override vanilla keys vs add new ones?
                vanilla_like = sum(
                    1 for k in d
                    if k.split(".")[0] in {"block", "item", "entity", "menu", "gui",
                                           "options", "death", "advancements", "chat",
                                           "commands", "container", "key", "subtitles",
                                           "soundCategory", "language", "selectWorld"})
                print(f"\n  keys that override vanilla namespaces : {vanilla_like}")
                print(f"  keys in custom namespaces             : {len(d) - vanilla_like}")
