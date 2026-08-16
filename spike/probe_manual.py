"""Spike probe: how does the game store text a *player typed by hand*?

Throwaway. Everything else in the fixture was created by commands. Map authors
type most real content in-game, so this checks whether hand-entered text is
stored the same way (and how non-ASCII survives Modified UTF-8).

Scans for CJK characters and dumps whatever contains them.

Usage: python probe_manual.py <world_dir>
"""
import struct
import sys
import zlib
from pathlib import Path

import amulet_nbt

SECTOR = 4096
world = Path(sys.argv[1])


def is_cjk(s):
    return any("一" <= c <= "鿿" for c in s)


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


def walk(tag, sig, hits):
    if isinstance(tag, amulet_nbt.CompoundTag):
        for k, v in tag.items():
            walk(v, f"{sig}.{k}" if sig else str(k), hits)
    elif isinstance(tag, amulet_nbt.ListTag):
        for v in tag:
            walk(v, f"{sig}[]", hits)
    elif isinstance(tag, amulet_nbt.StringTag):
        if is_cjk(tag.py_str):
            hits.append((sig, tag.py_str))


hits = []
for sub in ("region", "entities"):
    d = world / sub
    if not d.exists():
        continue
    for rf in sorted(d.glob("*.mca")):
        for tag in read_region(rf):
            walk(tag.compound, sub.upper(), hits)

for rel in ("level.dat", "data/scoreboard.dat"):
    p = world / rel
    if p.exists():
        walk(amulet_nbt.load(str(p)).compound, rel.upper(), hits)

print("=" * 74)
print("hand-typed (CJK) text and the exact path it landed in")
print("=" * 74)
seen = set()
for sig, val in hits:
    key = (sig, val)
    if key in seen:
        continue
    seen.add(key)
    print(f"\n  {sig}")
    print(f"      {val!r}")
    print(f"      utf-8 bytes: {val.encode('utf-8').hex(' ')}")

print(f"\n  total CJK-bearing tags: {len(seen)}")

# ---- also confirm how the translate probes are stored, side by side --------
print()
print("=" * 74)
print("translate-key probes as stored (Q3 cross-reference)")
print("=" * 74)
probes = []
for sub in ("region", "entities"):
    d = world / sub
    if not d.exists():
        continue
    for rf in sorted(d.glob("*.mca")):
        for tag in read_region(rf):
            walk2 = []

            def collect(t, sig):
                if isinstance(t, amulet_nbt.CompoundTag):
                    for k, v in t.items():
                        collect(v, f"{sig}.{k}" if sig else str(k))
                elif isinstance(t, amulet_nbt.ListTag):
                    for v in t:
                        collect(v, f"{sig}[]")
                elif isinstance(t, amulet_nbt.StringTag):
                    if "diamond_block" in t.py_str:
                        walk2.append((sig, t.py_str))

            collect(tag.compound, sub.upper())
            probes.extend(walk2)

for rel in ("level.dat", "data/scoreboard.dat"):
    p = world / rel
    if p.exists():
        acc = []

        def collect2(t, sig):
            if isinstance(t, amulet_nbt.CompoundTag):
                for k, v in t.items():
                    collect2(v, f"{sig}.{k}" if sig else str(k))
            elif isinstance(t, amulet_nbt.ListTag):
                for v in t:
                    collect2(v, f"{sig}[]")
            elif isinstance(t, amulet_nbt.StringTag):
                if "diamond_block" in t.py_str:
                    acc.append((sig, t.py_str))

        collect2(amulet_nbt.load(str(p)).compound, rel.upper())
        probes.extend(acc)

for sig, val in sorted(set(probes)):
    ends_translate = sig.endswith(".translate")
    verdict = "component (translate honoured)" if ends_translate else "PLAIN STRING SLOT"
    print(f"  {verdict:32s} {sig}")
