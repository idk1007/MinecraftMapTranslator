"""Round-2 probe, refinement pass.

The first pass answered P1/P2/P3 at world level but left three questions that change
what the answers MEAN:

  R1. P1 said 13.5% of components carry `extra`, but every sampled example was on
      /block_entities[]/LastOutput -- a denylist path we never translate. Split the
      `extra` population into translatable vs denylisted; only the translatable half
      can justify a schema change.

  R2. P2 returned zero filterable pairs. A zero is only informative if the world
      actually contains books/signs that COULD carry one. Count the book components
      and sign filtered-message slots that exist at all.

  R3. P3 found 2,340 `""` (2-char JSON-empty) strings inside DataVersion 4556 chunks,
      which are supposedly native. Locate them and dump neighbouring context.

Usage: python probe_components2.py <world_dir>...
"""
import json
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import amulet_nbt

SECTOR = 4096
LEGACY_CUTOFF = 4325

SKIP_KEYS = {
    "sections", "Sections", "block_states", "biomes", "Heightmaps", "HeightMap",
    "Lights", "PostProcessing", "structures", "Structures", "starts", "References",
    "LiquidTicks", "TileTicks", "block_ticks", "fluid_ticks", "ToBeTicked",
    "LiquidsToBeTicked", "UpgradeData", "CarvingMasks", "Palette", "BlockStates",
    "Add", "Blocks", "Data", "SkyLight", "BlockLight",
}
TEXT_BEARING_ROOTS = ("block_entities", "TileEntities", "Entities", "entities", "Level")
COMPONENT_HINT_KEYS = {"text", "translate", "extra", "", "score", "selector", "keybind"}

# Paths we will never translate. A component living here does not justify schema work.
DENYLIST_MARKERS = (
    "LastOutput",
    "profile", "properties",
    "custom_data",
    "CriteriaName",
    "RecipeBook", "recipeBook",
    "Recipes",
)


def is_denylisted(path: str) -> bool:
    return any(m in path for m in DENYLIST_MARKERS)


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
        cb = raw[pos + 4]
        if cb & 0x80:
            continue
        try:
            tag = amulet_nbt.load(decompress(raw[pos + 5:pos + 4 + length], cb & 0x7F),
                                  compressed=False)
        except Exception:
            continue
        root = tag.compound
        dv = None
        if "DataVersion" in root:
            dv = int(root["DataVersion"])
        elif "Level" in root and "DataVersion" in root["Level"]:
            dv = int(root["Level"]["DataVersion"])
        yield i, tag, dv


class S:
    def __init__(self):
        # R1
        self.extra_by_path = Counter()
        self.extra_translatable = 0
        self.extra_denylisted = 0
        self.extra_tr_depth = Counter()
        self.extra_tr_len = Counter()
        self.extra_tr_styled = 0
        self.tr_examples = []
        # R2
        self.book_components = Counter()
        self.filterable_hits = Counter()
        self.sign_sides = 0
        # R3
        self.quoted_empty_ctx = Counter()
        self.quoted_examples = []
        self.legacy_shape_in_native_dv = Counter()
        # legacy sign shape (coverage gap 3.1)
        self.sign_shape = Counter()
        self.legacy_json_array_form = 0
        self.legacy_json_invalid = 0
        self.dv = Counter()


def depth_of(node, d=0, budget=None):
    if budget is not None:
        budget[0] -= 1
        if budget[0] < 0:
            return d
    best = d
    if isinstance(node, amulet_nbt.CompoundTag) and "extra" in node:
        for c in node["extra"]:
            best = max(best, depth_of(c, d + 1, budget))
    return best


def jdepth(o, d=0):
    best = d
    if isinstance(o, dict):
        for c in o.get("extra", []) or []:
            best = max(best, jdepth(c, d + 1))
    elif isinstance(o, list):
        for c in o[1:]:
            best = max(best, jdepth(c, d + 1))
    return best


def walk(tag, st, dv, path=""):
    if isinstance(tag, amulet_nbt.CompoundTag):
        keys = {str(k) for k in tag.keys()}

        # ---- R2: do book components exist at all?
        for bk in ("minecraft:written_book_content", "minecraft:writable_book_content"):
            if bk in keys:
                st.book_components[bk] += 1
                node = tag[bk]
                if isinstance(node, amulet_nbt.CompoundTag):
                    for sub in ("title", "author", "pages"):
                        if sub in node:
                            st.book_components[f"{bk}.{sub}"] += 1
                    t = node.get("title")
                    if isinstance(t, amulet_nbt.CompoundTag):
                        st.book_components["title_is_filterable_wrapper"] += 1
                        if "filtered" in {str(k) for k in t.keys()}:
                            st.filterable_hits["written_book_content.title.filtered"] += 1
                    elif t is not None:
                        st.book_components["title_is_bare_string"] += 1
                    pg = node.get("pages")
                    if isinstance(pg, amulet_nbt.ListTag):
                        for p in pg:
                            if isinstance(p, amulet_nbt.CompoundTag):
                                st.book_components["page_is_filterable_wrapper"] += 1
                                if "filtered" in {str(k) for k in p.keys()}:
                                    st.filterable_hits[f"{bk}.pages[].filtered"] += 1
                            else:
                                st.book_components["page_is_bare"] += 1
        # legacy (pre-1.20.5) book tags
        if keys & {"pages", "title", "author"} and "id" not in keys and "raw" not in keys:
            if "pages" in keys and isinstance(tag.get("pages"), amulet_nbt.ListTag):
                st.book_components["legacy_tag_pages"] += 1

        if "filtered" in keys and "raw" in keys:
            st.filterable_hits[f"generic:{path.split('/')[-1]}"] += 1

        # ---- signs
        if "front_text" in keys or "back_text" in keys:
            st.sign_shape["modern_front_back_text"] += 1
            for side in ("front_text", "back_text"):
                if side not in keys:
                    continue
                st.sign_sides += 1
                node = tag[side]
                nk = {str(k) for k in node.keys()}
                if "filtered_messages" in nk:
                    st.filterable_hits["filtered_messages"] += 1
                if "messages" in nk:
                    for i, el in enumerate(node["messages"]):
                        if isinstance(el, amulet_nbt.StringTag):
                            s = str(el.py_str)
                            if s == '""':
                                st.quoted_empty_ctx[f"dv{dv}:{side}"] += 1
                                if len(st.quoted_examples) < 6:
                                    st.quoted_examples.append({
                                        "dv": dv, "side": side, "line": i,
                                        "all_lines": [repr(str(m.py_str))[:40]
                                                      if isinstance(m, amulet_nbt.StringTag)
                                                      else f"<{type(m).__name__}>{str(m)[:40]}"
                                                      for m in node["messages"]],
                                        "sign_keys": sorted(nk),
                                    })
                            elif s and s[0] in "{[":
                                try:
                                    o = json.loads(s)
                                    if (dv or 0) >= LEGACY_CUTOFF:
                                        st.legacy_shape_in_native_dv[
                                            f"dv{dv}:{'array' if isinstance(o, list) else 'object'}"] += 1
                                    if isinstance(o, list):
                                        st.legacy_json_array_form += 1
                                except Exception:
                                    st.legacy_json_invalid += 1
        if keys & {"Text1", "Text2", "Text3", "Text4"}:
            st.sign_shape["legacy_Text1_4"] += 1
            for n in ("Text1", "Text2", "Text3", "Text4"):
                if n in keys and isinstance(tag[n], amulet_nbt.StringTag):
                    s = str(tag[n].py_str)
                    if s and s[0] == "[":
                        st.legacy_json_array_form += 1
                    elif s and s[0] == "{":
                        pass
                    elif s:
                        try:
                            json.loads(s)
                        except Exception:
                            st.legacy_json_invalid += 1

        # ---- R1: extra, split by translatability
        if COMPONENT_HINT_KEYS & keys and "extra" in keys:
            st.extra_by_path[path] += 1
            if is_denylisted(path):
                st.extra_denylisted += 1
            else:
                st.extra_translatable += 1
                st.extra_tr_len[len(tag["extra"])] += 1
                st.extra_tr_depth[depth_of(tag, 0, [400])] += 1
                for el in tag["extra"]:
                    if isinstance(el, amulet_nbt.CompoundTag) and \
                            ({str(k) for k in el.keys()} - {"text", "extra", ""}):
                        st.extra_tr_styled += 1
                        break
                if len(st.tr_examples) < 10:
                    st.tr_examples.append({"path": path, "dv": dv, "snbt": str(tag)[:500]})

        for k in tag.keys():
            ks = str(k)
            if ks in SKIP_KEYS:
                continue
            walk(tag[k], st, dv, f"{path}/{ks}")

    elif isinstance(tag, amulet_nbt.ListTag):
        for el in tag:
            walk(el, st, dv, f"{path}[]")

    elif isinstance(tag, amulet_nbt.StringTag):
        s = str(tag.py_str)
        if len(s) > 1 and s[0] in "{[" and ("text" in s or "translate" in s or "extra" in s):
            try:
                o = json.loads(s)
            except Exception:
                st.legacy_json_invalid += 1
                return
            has = (isinstance(o, dict) and "extra" in o) or (isinstance(o, list) and len(o) > 1)
            if isinstance(o, list):
                st.legacy_json_array_form += 1
            if has:
                st.extra_by_path[path] += 1
                if is_denylisted(path):
                    st.extra_denylisted += 1
                else:
                    st.extra_translatable += 1
                    n = len(o.get("extra", [])) if isinstance(o, dict) else len(o) - 1
                    st.extra_tr_len[n] += 1
                    st.extra_tr_depth[jdepth(o)] += 1
                    items = o.get("extra", []) if isinstance(o, dict) else o[1:]
                    for el in items:
                        if isinstance(el, dict) and (set(el) - {"text", "extra"}):
                            st.extra_tr_styled += 1
                            break
                    if len(st.tr_examples) < 10:
                        st.tr_examples.append({"path": path, "dv": dv, "json": s[:500]})


def scan(world: Path):
    st = S()
    if not world.is_dir():
        raise SystemExit(f"FATAL: world dir does not exist: {world}")
    files = []
    for sub in ("region", "entities"):
        d = world / sub
        if d.is_dir():
            files += sorted(d.glob("*.mca"))
    if not files:
        raise SystemExit(f"FATAL: no .mca files under {world}/region or /entities")
    for n, f in enumerate(files, 1):
        for _i, tag, dv in iter_chunks(f):
            st.dv[dv] += 1
            root = tag.compound
            for key in TEXT_BEARING_ROOTS:
                if key in root:
                    walk(root[key], st, dv, f"/{key}")
            del tag
        if n % 25 == 0 or n == len(files):
            print(f"    [{n}/{len(files)}]", file=sys.stderr)
    lvl = world / "level.dat"
    if lvl.is_file():
        try:
            walk(amulet_nbt.load(lvl.read_bytes()).compound, st, None, "/level.dat")
        except Exception:
            pass
    return st


if __name__ == "__main__":
    out = []
    for w in sys.argv[1:]:
        world = Path(w)
        print(f"\n=== {world.name} ===", file=sys.stderr)
        st = scan(world)
        tot = st.extra_translatable + st.extra_denylisted
        r = {
            "world": world.name,
            "data_versions": {str(k): v for k, v in sorted(st.dv.items(), key=lambda x: (x[0] is None, x[0]))},
            "R1_extra_split": {
                "extra_total": tot,
                "extra_on_denylisted_paths": st.extra_denylisted,
                "extra_on_translatable_paths": st.extra_translatable,
                "translatable_pct_of_extra": round(100 * st.extra_translatable / tot, 2) if tot else 0,
                "translatable_depth_hist": dict(sorted(st.extra_tr_depth.items())),
                "translatable_len_hist": dict(sorted(st.extra_tr_len.items())),
                "translatable_with_styled_children": st.extra_tr_styled,
                "top_paths": dict(st.extra_by_path.most_common(15)),
                "translatable_examples": st.tr_examples,
            },
            "R2_filterable": {
                "book_component_census": dict(st.book_components),
                "sign_sides_seen": st.sign_sides,
                "filterable_hits": dict(st.filterable_hits),
            },
            "R3_legacy_in_native": {
                "quoted_empty_by_dv_side": dict(st.quoted_empty_ctx),
                "json_shape_inside_native_dv": dict(st.legacy_shape_in_native_dv),
                "examples": st.quoted_examples,
            },
            "sign_shapes": dict(st.sign_shape),
            "legacy_json_array_form": st.legacy_json_array_form,
            "legacy_json_invalid": st.legacy_json_invalid,
        }
        out.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:7000])
    Path("spike/round2_refined.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
