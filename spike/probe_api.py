"""Spike probe: discover the real amulet-nbt / amulet-core public API.

Throwaway. The installed version's API differs from most tutorials online,
so we introspect instead of trusting docs.
"""
import inspect

import amulet_nbt

print("amulet_nbt version:", getattr(amulet_nbt, "__version__", "?"))
names = [n for n in dir(amulet_nbt) if not n.startswith("_")]
loaders = [n for n in names if any(w in n.lower() for w in ("load", "read", "from", "file", "write", "save"))]
print("LOADER/WRITER NAMES:", loaders)
print()
for n in loaders:
    obj = getattr(amulet_nbt, n)
    try:
        sig = str(inspect.signature(obj))
    except Exception:  # noqa: BLE001
        sig = "(?)"
    doc = (inspect.getdoc(obj) or "").split("\n")[0]
    print(f"  {n}{sig}")
    if doc:
        print(f"      {doc[:150]}")
print()
print("ALL PUBLIC:", ", ".join(names))

print()
print("=" * 60)
try:
    import amulet

    print("amulet (core) version:", getattr(amulet, "__version__", "?"))
    anames = [n for n in dir(amulet) if not n.startswith("_")]
    print("amulet public:", ", ".join(anames))
    for n in ("load_level", "load_format"):
        if hasattr(amulet, n):
            obj = getattr(amulet, n)
            try:
                print(f"  {n}{inspect.signature(obj)}")
            except Exception:  # noqa: BLE001
                print(f"  {n}(?)")
            print("     ", (inspect.getdoc(obj) or "").split("\n")[0][:150])
except Exception as e:  # noqa: BLE001
    print("amulet import failed:", type(e).__name__, e)
