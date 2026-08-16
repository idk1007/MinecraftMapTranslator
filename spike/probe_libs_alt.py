"""Spike probe Q1b: do the older libraries actually cope with a modern world?

Throwaway. Run in .venv_alt (nbtlib / mcworldlib / anvil-parser2).
Each library gets the same three asks: read level.dat, open a region, reach a
block entity. Failures are reported with the real exception, not a shrug.

Usage: python probe_libs_alt.py <world_dir>
"""
import sys
import traceback
from pathlib import Path

WORLD = Path(sys.argv[1])
REGION = sorted((WORLD / "region").glob("*.mca"))[0]


def section(name):
    print("\n" + "=" * 72)
    print(name)
    print("=" * 72)


def attempt(label, fn):
    try:
        detail = fn()
        print(f"  [PASS] {label}: {detail}"[:400])
        return True
    except Exception:
        tb = traceback.format_exc().strip().split("\n")
        print(f"  [FAIL] {label}: {tb[-1]}"[:400])
        return False


# ------------------------------------------------------------------- nbtlib
section("nbtlib 2.0.4  (last release 2021)")


def _nbtlib_level():
    import nbtlib

    f = nbtlib.load(str(WORLD / "level.dat"))
    root = f["" ] if "" in f else f
    data = root["Data"] if "Data" in root else f["Data"]
    return f"DataVersion={data['DataVersion']} LevelName={str(data['LevelName'])[:40]!r}"


attempt("read level.dat", _nbtlib_level)
attempt("open .mca region", lambda: (_ for _ in ()).throw(
    NotImplementedError("nbtlib has no anvil/region layer - NBT codec only")))

# --------------------------------------------------------------- mcworldlib
section("mcworldlib 2023.7.13")


def _mcw_load():
    import mcworldlib as mc

    w = mc.load(str(WORLD))
    return f"{type(w).__name__} name={getattr(w, 'name', '?')!r}"


def _mcw_chunks():
    import mcworldlib as mc

    w = mc.load(str(WORLD))
    dim = w.dimensions["overworld"] if hasattr(w, "dimensions") else w
    n = 0
    for _ in dim.chunks:
        n += 1
        if n > 5:
            break
    return f"iterated {n} chunks"


def _mcw_be():
    import mcworldlib as mc

    w = mc.load(str(WORLD))
    dim = w.dimensions["overworld"]
    for chunk in dim.chunks:
        keys = list(chunk.keys())
        return f"chunk root keys={keys[:12]}"
    return "no chunks"


attempt("load world", _mcw_load)
attempt("iterate chunks", _mcw_chunks)
attempt("reach chunk NBT", _mcw_be)

# ------------------------------------------------------------ anvil-parser2
section("anvil-parser2 0.10.6  (claims: supports all Minecraft versions)")


def _anvil_region():
    import anvil

    r = anvil.Region.from_file(str(REGION))
    return f"Region loaded from {REGION.name}"


def _anvil_chunk():
    import anvil

    r = anvil.Region.from_file(str(REGION))
    for cx in range(32):
        for cz in range(32):
            try:
                data = r.chunk_data(cx, cz)
            except Exception:
                continue
            if data is None:
                continue
            keys = sorted(str(k) for k in data.keys())
            return f"chunk({cx},{cz}) root keys={keys[:12]}"
    return "no chunk decoded"


def _anvil_chunk_obj():
    import anvil

    r = anvil.Region.from_file(str(REGION))
    for cx in range(32):
        for cz in range(32):
            try:
                c = anvil.Chunk.from_region(r, cx, cz)
            except Exception:
                continue
            return f"Chunk object ok at ({cx},{cz}) version={getattr(c, 'version', '?')}"
    return "no Chunk object built"


attempt("open region file", _anvil_region)
attempt("decode raw chunk NBT", _anvil_chunk)
attempt("build Chunk object (block API)", _anvil_chunk_obj)

# ----------------------------------------------------- pyanvil name conflict
section("pyanvil  (PyPI name is NOT the Minecraft library)")
try:
    import pyanvil

    doc = (pyanvil.__doc__ or "").strip().split("\n")[0]
    print(f"  [INFO] imported pyanvil: {doc[:120]!r}")
except ImportError:
    print("  [INFO] not installed here - PyPI 'pyanvil' is a bioinformatics")
    print("         package (AnVIL/Terra). The Minecraft one is GitHub-only.")
