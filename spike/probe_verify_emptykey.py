"""Spike probe: settle the {"": "text"} claim with two independent readers
plus an annotated hex dump of the actual disk bytes.

Throwaway. The claim under review is that a plain string forced into a
heterogeneous NBT list is stored as TAG_Compound{'': TAG_String}, rather than
the intuitive TAG_Compound{'text': TAG_String}. It decides what the tool must
WRITE, and a wrong answer only shows up in-game, so one self-written parser is
not enough evidence.

Reader A: amulet-nbt 2.1.8 (third-party C extension)
Reader B: byte offsets read here, annotated, so the tag ids and name lengths
          can be checked by eye against the NBT spec.

Usage: python probe_verify_emptykey.py <world_dir>
"""
import struct
import sys
import zlib
from pathlib import Path

import amulet_nbt

SECTOR = 4096
TARGET = b"TT_SIGN_TRANSLATE_PROBE"
TAGN = {0: "TAG_End", 1: "TAG_Byte", 2: "TAG_Short", 3: "TAG_Int", 4: "TAG_Long",
        5: "TAG_Float", 6: "TAG_Double", 7: "TAG_Byte_Array", 8: "TAG_String",
        9: "TAG_List", 10: "TAG_Compound", 11: "TAG_Int_Array", 12: "TAG_Long_Array"}

world = Path(sys.argv[1])

# ------------------------------------------------------- locate the chunk ---
blob = None
for rf in sorted((world / "region").glob("*.mca")):
    raw = rf.read_bytes()
    for i in range(1024):
        off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
        if off == 0:
            continue
        pos = off * SECTOR
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        comp = raw[pos + 4]
        payload = raw[pos + 5:pos + 4 + length]
        try:
            data = zlib.decompress(payload) if comp == 2 else payload
        except Exception:  # noqa: BLE001
            continue
        if TARGET in data:
            blob = data
            print(f"chunk containing {TARGET.decode()} found in {rf.name}\n")
            break
    if blob:
        break

if blob is None:
    sys.exit(f"{TARGET.decode()} not found")

# ================================================================ READER A ===
print("=" * 78)
print("READER A - amulet-nbt 2.1.8")
print("=" * 78)
tag = amulet_nbt.load(blob, compressed=False)
for be in tag.compound["block_entities"]:
    ft = be.get("front_text")
    if ft is None:
        continue
    msgs = ft.get("messages")
    if msgs is None or TARGET.decode() not in str(msgs):
        continue
    print(f"  sign at ({be['x']}, {be['y']}, {be['z']})")
    elem_types = {type(m).__name__ for m in msgs}
    print(f"  front_text.messages -> {type(msgs).__name__}")
    print(f"  element types       -> {sorted(elem_types)}\n")
    for idx, m in enumerate(msgs):
        print(f"    messages[{idx}]  {type(m).__name__}")
        if isinstance(m, amulet_nbt.CompoundTag):
            print(f"        key count : {len(m)}")
            for k, v in m.items():
                print(f"        key={k!r}  (len {len(k)})  ->  "
                      f"{type(v).__name__} {v.py_str!r}")
        else:
            print(f"        value {m.py_str!r}")
    # also the all-plain side, for contrast
    bt = be.get("back_text")
    if bt is not None:
        bm = bt.get("messages")
        btypes = sorted({type(m).__name__ for m in bm})
        print(f"\n  back_text.messages  -> {type(bm).__name__}"
              f" of {btypes}  (all-plain control)")
    break

# ================================================================ READER B ===
print()
print("=" * 78)
print("READER B - annotated bytes at the exact disk offsets")
print("=" * 78)

# find the TAG_List named 'messages' immediately preceding the target.
# on-disk that is: 09 (TAG_List) 00 08 (name length) 'messages'
SIG = b"\x09\x00\x08messages"
tpos = blob.find(TARGET)
start = blob.rfind(SIG, 0, tpos)
if start == -1:
    sys.exit("could not locate the 'messages' TAG_List header before the target")

i = start
tid = blob[i]
namelen = struct.unpack_from(">H", blob, i + 1)[0]
name = blob[i + 3:i + 3 + namelen].decode()
print(f"  @{i:#08x}  {blob[i]:02x}                 tag id {tid} = {TAGN[tid]}")
print(f"  @{i+1:#08x}  {blob[i+1]:02x} {blob[i+2]:02x}              "
      f"name length = {namelen}")
print(f"  @{i+3:#08x}  {blob[i+3:i+3+namelen].hex(' ')}   name = {name!r}")
i += 3 + namelen

etid = blob[i]
count = struct.unpack_from(">i", blob, i + 1)[0]
print(f"  @{i:#08x}  {blob[i]:02x}                 list element type = "
      f"{etid} = {TAGN[etid]}")
print(f"  @{i+1:#08x}  {blob[i+1:i+5].hex(' ')}     list length = {count}")
i += 5

print()
for e in range(count):
    print(f"  --- element {e} ---")
    if etid == 8:  # TAG_String elements
        n = struct.unpack_from(">H", blob, i)[0]
        s = blob[i + 2:i + 2 + n]
        print(f"  @{i:#08x}  {blob[i:i+2].hex(' ')}              "
              f"string length = {n}")
        print(f"  @{i+2:#08x}  {s.hex(' ')[:60]:60s} = {s.decode()!r}")
        i += 2 + n
    elif etid == 10:  # TAG_Compound elements
        while True:
            ctid = blob[i]
            if ctid == 0:
                print(f"  @{i:#08x}  00                 TAG_End")
                i += 1
                break
            nl = struct.unpack_from(">H", blob, i + 1)[0]
            nm = blob[i + 3:i + 3 + nl]
            print(f"  @{i:#08x}  {blob[i]:02x}                 tag id {ctid} = "
                  f"{TAGN[ctid]}")
            print(f"  @{i+1:#08x}  {blob[i+1]:02x} {blob[i+2]:02x}              "
                  f"NAME LENGTH = {nl}" + ("   <-- ZERO-LENGTH KEY" if nl == 0 else ""))
            if nl:
                print(f"  @{i+3:#08x}  {nm.hex(' ')}   key = {nm.decode()!r}")
            i += 3 + nl
            if ctid == 8:
                sl = struct.unpack_from(">H", blob, i)[0]
                sv = blob[i + 2:i + 2 + sl]
                print(f"  @{i:#08x}  {blob[i:i+2].hex(' ')}              "
                      f"string length = {sl}")
                print(f"  @{i+2:#08x}  {sv.hex(' ')[:60]:60s} = {sv.decode()!r}")
                i += 2 + sl
            else:
                print("        (non-string payload, stopping annotation)")
                sys.exit(0)
    print()

print("=" * 78)
print("VERDICT")
print("=" * 78)
print("  If READER A reports key='' and READER B shows NAME LENGTH = 0 at the")
print("  same positions, the empty-key encoding is real on disk and not an")
print("  artefact of either parser.")
