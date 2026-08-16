"""Spike probe Q1: can each candidate library actually read a modern world?

Throwaway. Every library is judged on what it DOES, not what its README claims:
  1. open the world at all
  2. report the right DataVersion
  3. reach a chunk and enumerate its block entities
  4. round-trip a write without corrupting the region

Usage: python probe_libs.py <world_dir>
"""
import sys
import traceback
from pathlib import Path

WORLD = Path(sys.argv[1])
RESULTS = []


def report(lib, step, ok, detail=""):
    RESULTS.append((lib, step, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {step}: {detail}"[:300])


def section(name):
    print("\n" + "=" * 72)
    print(name)
    print("=" * 72)


# ---------------------------------------------------------------- amulet_nbt
section("amulet-nbt (raw NBT only - no region support expected)")
try:
    import amulet_nbt

    tag = amulet_nbt.load(str(WORLD / "level.dat"))
    dv = tag.compound["Data"]["DataVersion"]
    report("amulet-nbt", "read level.dat", True, f"DataVersion={dv}")
    has_region = any(
        hasattr(amulet_nbt, n) for n in ("AnvilRegion", "region", "load_region")
    )
    report("amulet-nbt", "region (.mca) support", has_region,
           "none - NBT library only, region layer must come from elsewhere")
except Exception:
    report("amulet-nbt", "read level.dat", False, traceback.format_exc(limit=1))

# --------------------------------------------------------------- amulet-core
section("amulet-core")
try:
    import amulet

    level = amulet.load_level(str(WORLD))
    report("amulet-core", "load_level", True, f"{type(level).__name__}")

    try:
        pv = level.level_wrapper.version
        report("amulet-core", "detect version", True, f"version={pv}")
    except Exception as e:  # noqa: BLE001
        report("amulet-core", "detect version", False, repr(e))

    try:
        dims = list(level.dimensions)
        report("amulet-core", "list dimensions", True, str(dims))
    except Exception as e:  # noqa: BLE001
        report("amulet-core", "list dimensions", False, repr(e))
        dims = []

    # walk chunks until we find block entities
    try:
        dim = dims[0] if dims else "minecraft:overworld"
        coords = list(level.all_chunk_coords(dim))
        report("amulet-core", "enumerate chunks", True, f"{len(coords)} chunks in {dim}")

        found_be = 0
        found_ent = 0
        scanned = 0
        sample = []
        for cx, cz in coords[:400]:
            try:
                ch = level.get_chunk(cx, cz, dim)
            except Exception:
                continue
            scanned += 1
            bes = getattr(ch, "block_entities", None)
            if bes:
                for be in bes:
                    found_be += 1
                    if len(sample) < 5:
                        sample.append(getattr(be, "base_name", "?"))
            ents = getattr(ch, "entities", None)
            if ents:
                found_ent += len(list(ents))
            if found_be > 20:
                break
        report("amulet-core", "read block entities", found_be > 0,
               f"scanned {scanned} chunks -> {found_be} block entities, "
               f"{found_ent} entities; sample={sample}")
    except Exception:
        report("amulet-core", "read chunks", False, traceback.format_exc(limit=2))

    try:
        level.close()
    except Exception:
        pass
except Exception:
    report("amulet-core", "load_level", False, traceback.format_exc(limit=3))

# -------------------------------------------------------------- raw fallback
section("hand-rolled region reader (feasibility floor for Q1)")
try:
    import struct
    import zlib

    regions = sorted((WORLD / "region").glob("*.mca"))
    if not regions:
        report("raw", "find regions", False, "no .mca files")
    else:
        rf = regions[0]
        raw = rf.read_bytes()
        # header: 4096B offset table + 4096B timestamp table
        entries = []
        for i in range(1024):
            off_raw = raw[i * 4:i * 4 + 4]
            off = int.from_bytes(off_raw[:3], "big")
            cnt = off_raw[3]
            if off:
                entries.append((i, off, cnt))
        report("raw", "parse region header", True,
               f"{rf.name}: {len(entries)}/1024 chunks present")

        # decode one chunk
        idx, off, _cnt = entries[0]
        pos = off * 4096
        length, comp = struct.unpack(">IB", raw[pos:pos + 5])
        blob = raw[pos + 5:pos + 5 + length - 1]
        data = zlib.decompress(blob) if comp == 2 else blob
        import amulet_nbt

        chunk = amulet_nbt.load(data, compressed=False)
        keys = sorted(str(k) for k in chunk.compound.keys())
        has_level = "Level" in keys
        report("raw", "decode+parse one chunk", True,
               f"compression={comp} keys={keys[:12]}")
        report("raw", "1.18+ flat layout (no 'Level' tag)", not has_level,
               f"Level tag present={has_level}")
        if "block_entities" in keys:
            bes = chunk.compound["block_entities"]
            ids = [str(b["id"]) for b in list(bes)[:5]] if len(bes) else []
            report("raw", "block_entities at chunk root", True,
                   f"{len(bes)} in this chunk; sample={ids}")
except Exception:
    report("raw", "region parse", False, traceback.format_exc(limit=3))

# -------------------------------------------------------------------- others
for modname, pipname in [("nbtlib", "nbtlib"), ("anvil", "anvil-parser2"),
                         ("mcworldlib", "mcworldlib")]:
    section(f"{pipname} (import check only - not installed yet unless present)")
    try:
        m = __import__(modname)
        report(pipname, "import", True, f"version={getattr(m, '__version__', '?')}")
    except ImportError as e:
        report(pipname, "import", False, str(e))

section("SUMMARY")
for lib, step, ok, detail in RESULTS:
    print(f"  {'PASS' if ok else 'FAIL'}  {lib:14s} {step}")
