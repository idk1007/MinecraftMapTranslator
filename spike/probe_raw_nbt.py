"""Spike probe: byte-level NBT parse, independent of any NBT library.

Throwaway. The claim under test - "a plain string inside a heterogeneous text
component list is stored on disk as TAG_Compound{'': TAG_String}" - decides how
the tool must write sign text, so it should not rest on one library's
representation. This reads the raw bytes and reports tag ids directly.

Usage: python probe_raw_nbt.py <world_dir>
"""
import struct
import sys
import zlib
from pathlib import Path

SECTOR = 4096
END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE = 0, 1, 2, 3, 4, 5, 6
BYTE_ARRAY, STRING, LIST, COMPOUND, INT_ARRAY, LONG_ARRAY = 7, 8, 9, 10, 11, 12
NAMES = {0: "END", 1: "Byte", 2: "Short", 3: "Int", 4: "Long", 5: "Float",
         6: "Double", 7: "ByteArray", 8: "String", 9: "List", 10: "Compound",
         11: "IntArray", 12: "LongArray"}


class Reader:
    def __init__(self, buf):
        self.b = buf
        self.i = 0

    def u1(self):
        v = self.b[self.i]
        self.i += 1
        return v

    def u2(self):
        v = struct.unpack_from(">H", self.b, self.i)[0]
        self.i += 2
        return v

    def i4(self):
        v = struct.unpack_from(">i", self.b, self.i)[0]
        self.i += 4
        return v

    def skip(self, n):
        self.i += n

    def string(self):
        n = self.u2()
        s = self.b[self.i:self.i + n]
        self.i += n
        # NBT uses Modified UTF-8; for BMP text it matches UTF-8 byte for byte
        return s.decode("utf-8", errors="replace")


def read_payload(r, tid):
    """Return a python value, preserving the distinction we care about."""
    if tid == BYTE:
        r.skip(1)
        return None
    if tid == SHORT:
        r.skip(2)
        return None
    if tid in (INT, FLOAT):
        r.skip(4)
        return None
    if tid in (LONG, DOUBLE):
        r.skip(8)
        return None
    if tid == BYTE_ARRAY:
        r.skip(r.i4())
        return None
    if tid == STRING:
        return ("str", r.string())
    if tid == LIST:
        etid = r.u1()
        n = r.i4()
        return ("list", etid, [read_payload(r, etid) for _ in range(n)])
    if tid == COMPOUND:
        out = []
        while True:
            child = r.u1()
            if child == END:
                break
            name = r.string()
            out.append((name, child, read_payload(r, child)))
        return ("compound", out)
    if tid == INT_ARRAY:
        r.skip(r.i4() * 4)
        return None
    if tid == LONG_ARRAY:
        r.skip(r.i4() * 8)
        return None
    raise ValueError(f"bad tag id {tid}")


def find(node, needle, path="", hits=None):
    if hits is None:
        hits = []
    if node is None:
        return hits
    kind = node[0]
    if kind == "str":
        if needle in node[1]:
            hits.append((path, node[1]))
    elif kind == "compound":
        for name, tid, val in node[1]:
            find(val, needle, f"{path}.{name}" if path else name, hits)
    elif kind == "list":
        for idx, v in enumerate(node[2]):
            find(v, needle, f"{path}[{idx}]", hits)
    return hits


def dump(node, indent=0, label=""):
    pad = "  " * indent
    if node is None:
        print(f"{pad}{label}<scalar>")
        return
    kind = node[0]
    if kind == "str":
        print(f"{pad}{label}TAG_String {node[1]!r}")
    elif kind == "compound":
        print(f"{pad}{label}TAG_Compound  ({len(node[1])} entries)")
        for name, tid, val in node[1]:
            dump(val, indent + 1, f"name={name!r} type=TAG_{NAMES[tid]}  ")
    elif kind == "list":
        print(f"{pad}{label}TAG_List of TAG_{NAMES[node[1]]}  ({len(node[2])} items)")
        for v in node[2]:
            dump(v, indent + 1)


world = Path(sys.argv[1])
target = sys.argv[2] if len(sys.argv) > 2 else "TT_SIGN_TRANSLATE_PROBE"

for rf in sorted((world / "region").glob("*.mca")):
    raw = rf.read_bytes()
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
        except Exception:  # noqa: BLE001
            continue
        if target.encode() not in data:
            continue

        r = Reader(data)
        root_tid = r.u1()
        r.string()  # root name
        root = read_payload(r, root_tid)

        hits = find(root, target)
        print("=" * 74)
        print(f"{rf.name}: found {target!r} at")
        for p, v in hits:
            print(f"   {p}  =  {v!r}")
        print("=" * 74)

        # dump the enclosing sign block entity
        for name, tid, val in root[1]:
            if name != "block_entities":
                continue
            for be in val[2]:
                if not find(be, target):
                    continue
                print("\nraw on-disk structure of the containing block entity:\n")
                dump(be)
                sys.exit(0)
print(f"{target!r} not found")
