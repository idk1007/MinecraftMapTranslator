"""Spike probe: cross-verify the {"": "text"} sign encoding with a second library.

Throwaway. The claim "a plain string inside a heterogeneous component list is
stored as a compound with an empty key" is subtle enough that it should not rest
on one library's representation. Run this in .venv_alt (nbtlib), which shares no
code with amulet-nbt.

Usage: python probe_crosscheck.py <world_dir>
"""
import struct
import sys
import zlib
from io import BytesIO
from pathlib import Path

import nbtlib

SECTOR = 4096
world = Path(sys.argv[1])


def chunks(path):
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
            yield nbtlib.File.from_buffer(BytesIO(data), byteorder="big")
        except Exception:  # noqa: BLE001
            continue


found = 0
for rf in sorted((world / "region").glob("*.mca")):
    for f in chunks(rf):
        root = f if isinstance(f, dict) else f.root
        for be in root.get("block_entities", []):
            if str(be.get("id", "")) != "minecraft:sign":
                continue
            ft = be.get("front_text")
            if not ft:
                continue
            msgs = ft.get("messages", [])
            blob = repr(msgs)
            if "TT_SIGN" not in blob:
                continue
            found += 1
            print("=" * 70)
            print(f"sign at ({be.get('x')},{be.get('y')},{be.get('z')})")
            print("=" * 70)
            for i, m in enumerate(msgs):
                print(f"  messages[{i}]  python-type={type(m).__name__}")
                if isinstance(m, dict):
                    for k, v in m.items():
                        print(f"      key={k!r}  ->  {type(v).__name__} {v!r}")
                else:
                    print(f"      value={m!r}")
            print()
            if found >= 3:
                sys.exit(0)

print(f"signs dumped: {found}")
