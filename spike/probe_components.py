"""Round-2 probe: P1 (extra nesting), P2 (filterable), P3 (sign messages by DataVersion).

Single streaming pass per region file. One chunk is decompressed, parsed, walked and
discarded before the next is touched, so peak memory is one chunk regardless of world
size -- this doubles as the feasibility check for the per-region streaming requirement.

Only the subtrees that can hold text are walked (block_entities / TileEntities /
Entities / Level.*). Block palettes, heightmaps and biomes are skipped by name; they
are the bulk of a chunk and can never hold a text component.

Usage: python probe_components.py <world_dir> [--max-regions N] [--json out.json]
"""
import json
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import amulet_nbt

SECTOR = 4096
LEGACY_CUTOFF = 4325          # 1.21.5: text components stop being JSON strings

# Subtrees that may contain text. Everything else in a chunk is skipped.
TEXT_BEARING_ROOTS = ("block_entities", "TileEntities", "Entities", "entities", "Level")
# Never walked: pure volume, no text possible.
SKIP_KEYS = {
    "sections", "Sections", "block_states", "biomes", "Heightmaps", "HeightMap",
    "Lights", "PostProcessing", "structures", "Structures", "starts", "References",
    "LiquidTicks", "TileTicks", "block_ticks", "fluid_ticks", "ToBeTicked",
    "LiquidsToBeTicked", "UpgradeData", "CarvingMasks", "Palette", "BlockStates",
    "Add", "Blocks", "Data", "SkyLight", "BlockLight",
}

COMPONENT_HINT_KEYS = {"text", "translate", "extra", "", "score", "selector", "keybind", "nbt"}


def decompress(payload, comp):
    if comp == 1:
        return zlib.decompress(payload, 16 + zlib.MAX_WBITS)
    if comp == 2:
        return zlib.decompress(payload)
    if comp == 3:
        return payload
    if comp == 4:
        import lz4.block
        return lz4.block.decompress(payload)
    raise ValueError(f"unsupported compression id {comp}")


def iter_chunks(path):
    """Yield (index, NamedTag, data_version, compression, external) one at a time."""
    raw = path.read_bytes()
    if len(raw) < SECTOR * 2:
        return
    for i in range(1024):
        off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
        if off == 0:
            continue
        pos = off * SECTOR
        if pos + 5 > len(raw):
            continue
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        if length == 0 or pos + 4 + length > len(raw):
            continue
        comp_byte = raw[pos + 4]
        external = bool(comp_byte & 0x80)
        comp = comp_byte & 0x7F
        payload = raw[pos + 5:pos + 4 + length]
        if external:
            yield i, None, None, comp, True
            continue
        try:
            tag = amulet_nbt.load(decompress(payload, comp), compressed=False)
        except Exception:
            yield i, None, None, comp, False
            continue
        root = tag.compound
        dv = None
        if "DataVersion" in root:
            dv = int(root["DataVersion"])
        elif "Level" in root and "DataVersion" in root["Level"]:
            dv = int(root["Level"]["DataVersion"])
        yield i, tag, dv, comp, False


# --------------------------------------------------------------------- P1
def extra_depth(node, depth=0, budget=None):
    """Max nesting depth of the extra chain rooted at this component."""
    if budget is not None:
        budget[0] -= 1
        if budget[0] < 0:
            return depth
    best = depth
    if isinstance(node, amulet_nbt.CompoundTag):
        if "extra" in node:
            for child in node["extra"]:
                best = max(best, extra_depth(child, depth + 1, budget))
        # hover_event / click_event can nest components too
        for k in ("hover_event", "hoverEvent"):
            if k in node and isinstance(node[k], amulet_nbt.CompoundTag):
                best = max(best, extra_depth(node[k], depth + 1, budget))
    elif isinstance(node, amulet_nbt.ListTag):
        for child in node:
            best = max(best, extra_depth(child, depth + 1, budget))
    return best


def json_extra_depth(obj, depth=0):
    best = depth
    if isinstance(obj, dict):
        for child in obj.get("extra", []) or []:
            best = max(best, json_extra_depth(child, depth + 1))
    elif isinstance(obj, list):
        for child in obj:
            best = max(best, json_extra_depth(child, depth + 1))
    return best


class Stats:
    def __init__(self):
        # P1
        self.components = 0
        self.with_extra = 0
        self.extra_depth = Counter()
        self.extra_len = Counter()
        self.extra_by_gen = Counter()
        self.styled_extra = 0          # extra element carrying its own formatting
        self.p1_examples = []
        # P2
        self.filterable = Counter()
        self.p2_examples = []
        # P3
        self.msg = defaultdict(Counter)   # data_version -> element class counter
        self.sign_shape = Counter()       # which sign NBT shape
        # meta
        self.dv = Counter()
        self.comp_types = Counter()
        self.external = 0
        self.unreadable = 0
        self.chunks = 0

    def merge(self, o):
        for a in ("components", "with_extra", "styled_extra", "external", "unreadable", "chunks"):
            setattr(self, a, getattr(self, a) + getattr(o, a))
        for a in ("extra_depth", "extra_len", "extra_by_gen", "filterable",
                  "sign_shape", "dv", "comp_types"):
            getattr(self, a).update(getattr(o, a))
        for k, v in o.msg.items():
            self.msg[k].update(v)
        self.p1_examples = (self.p1_examples + o.p1_examples)[:8]
        self.p2_examples = (self.p2_examples + o.p2_examples)[:8]


def classify_message(el):
    """P3: classify one element of a sign messages[] / Text1-4 field."""
    if isinstance(el, amulet_nbt.StringTag):
        s = str(el.py_str)
        if s == "":
            return "native_empty_zero_length"
        if s == '""':
            return "legacy_json_empty_quoted"
        if s and s[0] in "{[\"":
            try:
                json.loads(s)
                return "legacy_json_content"
            except Exception:
                return "string_looks_json_but_invalid"
        return "bare_literal_nonempty"
    if isinstance(el, amulet_nbt.CompoundTag):
        if "translate" in el:
            return "native_compound_translate"
        if "" in el:
            v = str(el[""].py_str) if isinstance(el[""], amulet_nbt.StringTag) else "?"
            return "native_compound_emptykey_empty" if v == "" else "native_compound_emptykey_text"
        if "text" in el:
            v = str(el["text"].py_str) if isinstance(el["text"], amulet_nbt.StringTag) else "?"
            return "native_compound_text_empty" if v == "" else "native_compound_text_nonempty"
        return "native_compound_other"
    return f"other_{type(el).__name__}"


def looks_like_component(tag):
    return isinstance(tag, amulet_nbt.CompoundTag) and bool(COMPONENT_HINT_KEYS & set(map(str, tag.keys())))


def walk(tag, st, dv, path=""):
    """Walk a text-bearing subtree, recording P1/P2/P3 observations."""
    if isinstance(tag, amulet_nbt.CompoundTag):
        keys = {str(k) for k in tag.keys()}

        # ---- P2: filterable {raw, filtered}
        if "filtered" in keys and "raw" in keys:
            st.filterable[f"{path.split('/')[-1] or '?'}.filtered"] += 1
            if len(st.p2_examples) < 8:
                st.p2_examples.append(path)
        for fk in ("filtered_messages", "filtered_title", "filtered_author"):
            if fk in keys:
                st.filterable[fk] += 1
                if len(st.p2_examples) < 8:
                    st.p2_examples.append(f"{path}/{fk}")

        # ---- P3: sign shapes
        if "front_text" in keys or "back_text" in keys:
            st.sign_shape["modern_front_back_text"] += 1
            for side in ("front_text", "back_text"):
                if side not in keys:
                    continue
                node = tag[side]
                for listkey in ("messages", "filtered_messages"):
                    if listkey in node:
                        for el in node[listkey]:
                            st.msg[dv][f"{listkey}:{classify_message(el)}"] += 1
        if keys & {"Text1", "Text2", "Text3", "Text4"}:
            st.sign_shape["legacy_text1_4"] += 1
            for n in ("Text1", "Text2", "Text3", "Text4"):
                if n in keys:
                    st.msg[dv][f"Text1_4:{classify_message(tag[n])}"] += 1

        # ---- P1: component with extra
        if looks_like_component(tag):
            st.components += 1
            if "extra" in keys:
                st.with_extra += 1
                extra = tag["extra"]
                st.extra_len[len(extra)] += 1
                st.extra_depth[extra_depth(tag, 0, budget=[500])] += 1
                gen = "native_nbt" if (dv or 0) >= LEGACY_CUTOFF else "legacy_json"
                st.extra_by_gen[gen] += 1
                for el in extra:
                    if isinstance(el, amulet_nbt.CompoundTag):
                        if {str(k) for k in el.keys()} - {"text", "extra", ""}:
                            st.styled_extra += 1
                            break
                if len(st.p1_examples) < 8:
                    st.p1_examples.append({"path": path, "dv": dv, "snbt": str(tag)[:400]})

        for k in tag.keys():
            ks = str(k)
            if ks in SKIP_KEYS:
                continue
            walk(tag[k], st, dv, f"{path}/{ks}")

    elif isinstance(tag, amulet_nbt.ListTag):
        for el in tag:
            walk(el, st, dv, f"{path}[]")

    elif isinstance(tag, amulet_nbt.StringTag):
        # legacy: a JSON string standing in for a component
        s = str(tag.py_str)
        if len(s) > 1 and s[0] in "{[" and ("text" in s or "translate" in s or "extra" in s):
            try:
                obj = json.loads(s)
            except Exception:
                return
            st.components += 1
            has_extra = (isinstance(obj, dict) and "extra" in obj) or isinstance(obj, list)
            if has_extra:
                st.with_extra += 1
                n = len(obj.get("extra", [])) if isinstance(obj, dict) else max(0, len(obj) - 1)
                st.extra_len[n] += 1
                st.extra_depth[json_extra_depth(obj)] += 1
                st.extra_by_gen["legacy_json"] += 1
                items = obj.get("extra", []) if isinstance(obj, dict) else obj[1:]
                for el in items:
                    if isinstance(el, dict) and set(el) - {"text", "extra"}:
                        st.styled_extra += 1
                        break
                if len(st.p1_examples) < 8:
                    st.p1_examples.append({"path": path, "dv": dv, "json": s[:400]})


def scan_world(world: Path, max_regions=None):
    st = Stats()
    files = []
    for sub in ("region", "entities"):
        d = world / sub
        if d.is_dir():
            fs = sorted(d.glob("*.mca"))
            if max_regions:
                fs = fs[:max_regions]
            files += fs

    for n, f in enumerate(files, 1):
        for _idx, tag, dv, comp, external in iter_chunks(f):
            st.comp_types[comp] += 1
            if external:
                st.external += 1
                continue
            if tag is None:
                st.unreadable += 1
                continue
            st.chunks += 1
            st.dv[dv] += 1
            root = tag.compound
            for key in TEXT_BEARING_ROOTS:
                if key in root:
                    walk(root[key], st, dv, f"/{key}")
            del tag
        print(f"    [{n}/{len(files)}] {f.name}  chunks={st.chunks}", file=sys.stderr)

    lvl = world / "level.dat"
    if lvl.is_file():
        try:
            t = amulet_nbt.load(lvl.read_bytes())
            walk(t.compound, st, None, "/level.dat")
        except Exception as e:
            print(f"    level.dat unreadable: {e}", file=sys.stderr)
    return st


def report(name, st):
    out = {
        "world": name,
        "chunks_scanned": st.chunks,
        "unreadable_chunks": st.unreadable,
        "external_mcc_chunks": st.external,
        "compression_types": dict(st.comp_types),
        "data_versions": {str(k): v for k, v in sorted(st.dv.items(), key=lambda x: (x[0] is None, x[0]))},
        "P1": {
            "components_seen": st.components,
            "with_extra": st.with_extra,
            "extra_pct": round(100 * st.with_extra / st.components, 2) if st.components else 0,
            "extra_depth_hist": dict(sorted(st.extra_depth.items())),
            "extra_len_hist": dict(sorted(st.extra_len.items())),
            "extra_by_generation": dict(st.extra_by_gen),
            "extra_elements_carrying_own_format": st.styled_extra,
            "examples": st.p1_examples,
        },
        "P2": {
            "filterable_paths": dict(st.filterable),
            "examples": st.p2_examples,
        },
        "P3": {
            "sign_shapes": dict(st.sign_shape),
            "messages_by_data_version": {
                str(k): dict(sorted(v.items())) for k, v in sorted(st.msg.items(), key=lambda x: (x[0] is None, x[0]))
            },
        },
    }
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    max_regions = None
    out_path = None
    for i, a in enumerate(sys.argv):
        if a == "--max-regions":
            max_regions = int(sys.argv[i + 1])
        if a == "--json":
            out_path = Path(sys.argv[i + 1])

    results = []
    for w in args:
        world = Path(w)
        print(f"\n=== {world.name} ===", file=sys.stderr)
        st = scan_world(world, max_regions)
        r = report(world.name, st)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:4000])

    if out_path:
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {out_path}", file=sys.stderr)
