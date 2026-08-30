"""Validate the mcmt contracts and their sample fixtures.

Two halves, and the second matters more than the first:

  POSITIVE -- every sample fixture validates against its schema.
  NEGATIVE -- documents that break the rules we added are actually REJECTED.

A conditional rule nobody ever saw fail is indistinguishable from a rule that
does nothing. Every `if/then` added to the schema gets a negative case here.

Becomes tests/unit/test_contracts.py once the package exists.

Usage: python tools/validate_contracts.py
"""
import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# Test names carry Chinese evidence tags; a cp950 console would mangle them.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "docs" / "contracts"
FIXTURES = ROOT / "tests" / "fixtures" / "contracts"

SCHEMAS = {
    "extract": "extract.schema.json",
    "translations": "translations.schema.json",
    "editplan": "editplan.schema.json",
    "apply_report": "apply_report.schema.json",
}

SAMPLES = {
    "extract": "extract.sample.json",
    "translations": "translations.zh_tw.sample.json",
    "editplan": "editplan.sample.json",
    "apply_report": "apply_report.sample.json",
}

ok = 0
fail = 0


def report(name, passed, detail=""):
    global ok, fail
    if passed:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}")
        if detail:
            for line in str(detail).splitlines()[:6]:
                print(f"        {line}")


# ---------------------------------------------------------------- load schemas
loaded = {}
for key, fn in SCHEMAS.items():
    loaded[key] = json.loads((CONTRACTS / fn).read_text(encoding="utf-8"))

registry = Registry().with_resources(
    [(s["$id"], Resource.from_contents(s)) for s in loaded.values()]
)


def validator_for(key):
    return Draft202012Validator(loaded[key], registry=registry)


print("\n=== 1. schemas are themselves valid JSON Schema (draft 2020-12) ===")
for key, schema in loaded.items():
    try:
        Draft202012Validator.check_schema(schema)
        report(f"{key}.schema.json is a valid metaschema instance", True)
    except Exception as e:
        report(f"{key}.schema.json is a valid metaschema instance", False, e)


print("\n=== 2. SCHEMA_VERSION is identical across all four contracts ===")
versions = {k: s["properties"]["schema_version"]["const"] for k, s in loaded.items()}
report(f"all four declare the same version {set(versions.values())}",
       len(set(versions.values())) == 1, versions)


print("\n=== 3. POSITIVE: sample fixtures validate ===")
samples = {}
for key, fn in SAMPLES.items():
    doc = json.loads((FIXTURES / fn).read_text(encoding="utf-8"))
    samples[key] = doc
    errs = sorted(validator_for(key).iter_errors(doc), key=lambda e: list(e.absolute_path))
    report(f"{fn} validates",
           not errs,
           "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errs[:4]))


print("\n=== 4. NEGATIVE: rule violations must be rejected ===")


def must_reject(name, key, mutate):
    doc = copy.deepcopy(samples[key])
    mutate(doc)
    errs = list(validator_for(key).iter_errors(doc))
    report(name, bool(errs), "document was ACCEPTED but should have been rejected")


def unit_by_category(doc, cat):
    return next(u for u in doc["units"] if u["category"] == cat)


# --- 2.2 category <-> strategy binding
must_reject(
    "book_title with strategy=translate_key  [遊戲實測: renders the raw key]",
    "extract",
    lambda d: d["units"].append({
        **copy.deepcopy(unit_by_category(d, "sign")),
        "unit_id": "u:book_title:1111111111111111",
        "key": "mcmt.book_title.1111111111111111",
        "category": "book_title",
        "strategy": "translate_key",
    }),
)

must_reject(
    "block_entity_name with strategy=translate_key  [遊戲實測 M11-3: CustomName 顯示字面文字]",
    "extract",
    lambda d: unit_by_category(d, "block_entity_name").update({
        "strategy": "translate_key",
        "key": "mcmt.block_entity_name.3c9f0a5b17d24e68",
    }),
)

must_reject(
    "level_name with strategy=translate_key",
    "extract",
    lambda d: unit_by_category(d, "level_name").update({
        "strategy": "translate_key",
        "key": "mcmt.level_name.c4b8210f9e3a7d51",
    }),
)

# --- 2.2 encoding plain_string forces in_place
must_reject(
    "encoding=plain_string with strategy=translate_key",
    "extract",
    lambda d: unit_by_category(d, "sign")["occurrences"][0].update({"encoding": "plain_string"}),
)

# --- collapsible=false forces translate_key
must_reject(
    "collapsible=false with strategy=in_place",
    "extract",
    lambda d: unit_by_category(d, "level_name").update({"collapsible": False}),
)

# --- strategy/key coupling
must_reject(
    "strategy=translate_key with key=null",
    "extract",
    lambda d: unit_by_category(d, "sign").update({"key": None}),
)
must_reject(
    "strategy=in_place with a non-null key",
    "extract",
    lambda d: unit_by_category(d, "level_name").update({"key": "mcmt.level_name.c4b8210f9e3a7d51"}),
)

# --- 1.2 discriminator width
must_reject(
    "unit_id with a 10-hex discriminator (the old 40-bit width)",
    "extract",
    lambda d: unit_by_category(d, "sign").update({"unit_id": "u:sign:7f3a91c204"}),
)
must_reject(
    "translateKey with a 10-hex discriminator",
    "extract",
    lambda d: unit_by_category(d, "sign").update({"key": "mcmt.sign.7f3a91c204"}),
)

# --- namespace must not be minecraft
must_reject(
    "namespace=minecraft (would overwrite vanilla keys)",
    "extract",
    lambda d: d["project"].update({"namespace": "minecraft"}),
)

# --- 2.6 chunk required for *_chunk containers
must_reject(
    "region_chunk container without chunk coordinates",
    "extract",
    lambda d: unit_by_category(d, "sign")["occurrences"][0]["container"].pop("chunk"),
)

# --- container must not carry a resurrected `generation` field
must_reject(
    "container carrying a `generation` field (removed: DataVersion does not decide shape)",
    "extract",
    lambda d: unit_by_category(d, "sign")["occurrences"][0]["container"].update(
        {"generation": "native_nbt"}),
)

# --- encoding vocabulary is closed
must_reject(
    "unknown encoding value",
    "extract",
    lambda d: unit_by_category(d, "sign")["occurrences"][0].update({"encoding": "guessed"}),
)

# --- SCHEMA_VERSION mismatch is fatal, never migrated
must_reject(
    "schema_version=1 (no backwards compatibility)",
    "extract",
    lambda d: d.update({"schema_version": 1}),
)

# --- translations: unit_id key shape
must_reject(
    "translations entry keyed by a 10-hex unit_id",
    "translations",
    lambda d: d["entries"].update({"u:sign:7f3a91c204": d["entries"]["u:sign:7f3a91c204d5e618"]}),
)
must_reject(
    "translations missing extract_fingerprint (world_fingerprint alone is insufficient)",
    "translations",
    lambda d: d["extract_ref"].pop("extract_fingerprint"),
)
must_reject(
    "unknown translation status",
    "translations",
    lambda d: d["entries"]["u:sign:7f3a91c204d5e618"].update({"status": "probably_fine"}),
)

# --- editplan: value union is closed
must_reject(
    "editplan value with an unknown kind",
    "editplan",
    lambda d: d["edits"][0].update({"value": {"kind": "guess", "key": "x"}}),
)
must_reject(
    "editplan edit missing expected_encoding (the stale-world guard)",
    "editplan",
    lambda d: d["edits"][0].pop("expected_encoding"),
)
must_reject(
    "editplan translate value carrying an extra unknown field",
    "editplan",
    lambda d: d["edits"][0]["value"].update({"tree": {}}),
)

# --- apply_report: writer-side reason vocabulary is closed and disjoint
must_reject(
    "apply_report using a backend-side reason (untranslated)",
    "apply_report",
    lambda d: d["unwritten"][0].update({"reason": "untranslated"}),
)
must_reject(
    "apply_report missing counts.chunks_copied_verbatim (the surgical-write assertion)",
    "apply_report",
    lambda d: d["counts"].pop("chunks_copied_verbatim"),
)
# [遊戲實測 M0-3] a native chunk renders a legacy JSON string literally, so writing a
# translated one back there is pointless damage. The schema forbids it outright.
must_reject(
    "editplan writing a legacy JSON encoding into a native chunk (data_version >= 4325)",
    "editplan",
    lambda d: d["edits"][0]["container"].update({"data_version": 4556})
    or d["edits"][0].update({"expected_encoding": "json_string_object"}),
)


print("\n=== 5. cross-contract consistency ===")

ex_units = {u["unit_id"] for u in samples["extract"]["units"]}
tr_units = set(samples["translations"]["entries"])
ep_units = {e["unit_id"] for e in samples["editplan"]["edits"]}
ep_unwritten = {u["unit_id"] for u in samples["editplan"]["unwritten"]}

report("every translations entry refers to a unit in extract", tr_units <= ex_units,
       f"orphans: {tr_units - ex_units}")
report("every editplan edit refers to a unit in extract", ep_units <= ex_units,
       f"orphans: {ep_units - ex_units}")
report("editplan covers each translated unit exactly once (written or explicitly unwritten)",
       (ep_units | ep_unwritten) == tr_units,
       f"missing: {tr_units - ep_units - ep_unwritten}  extra: {ep_units - tr_units}")
report("extract_fingerprint matches across extract/translations/editplan",
       samples["extract"]["world"]["extract_fingerprint"]
       == samples["translations"]["extract_ref"]["extract_fingerprint"]
       == samples["editplan"]["extract_ref"]["extract_fingerprint"])

ex_occ = {o["occurrence_id"] for u in samples["extract"]["units"] for o in u["occurrences"]}
ep_occ = {e["occurrence_id"] for e in samples["editplan"]["edits"]}
report("every editplan occurrence exists in extract", ep_occ <= ex_occ,
       f"orphans: {ep_occ - ex_occ}")

# an occurrence extract marked excluded must never reach the writer. The exclusion is
# per-occurrence: the same unit is still translated for its other, writable occurrences.
excluded_occ = {o["occurrence_id"]: o["excluded"]["reason"]
                for u in samples["extract"]["units"] for o in u["occurrences"]
                if o.get("excluded")}
leaked = sorted(ep_occ & set(excluded_occ))
report("no editplan edit targets an occurrence excluded by extract", not leaked,
       f"leaked: {[(o, excluded_occ[o]) for o in leaked]}")
report("an excluded occurrence does not suppress its unit's other occurrences",
       any(u["unit_id"] in ep_units
           for u in samples["extract"]["units"]
           if any(o.get("excluded") for o in u["occurrences"])),
       "the sample no longer exercises the per-occurrence exclusion asymmetry")

# expected_encoding must mirror what extract recorded, or the stale-guard is a lie
enc = {o["occurrence_id"]: o["encoding"]
       for u in samples["extract"]["units"] for o in u["occurrences"]}
mismatched = [e["occurrence_id"] for e in samples["editplan"]["edits"]
              if enc.get(e["occurrence_id"]) != e["expected_encoding"]]
report("editplan expected_encoding mirrors extract encoding", not mismatched,
       f"mismatched: {mismatched}")

# raw_snapshot must mirror what extract recorded too, or the same-shape-different-
# content guard is comparing against a value nobody actually extracted.
snap = {o["occurrence_id"]: o["raw_snapshot"]
        for u in samples["extract"]["units"] for o in u["occurrences"]}
snap_mismatched = [e["occurrence_id"] for e in samples["editplan"]["edits"]
                    if snap.get(e["occurrence_id"]) != e["raw_snapshot"]]
report("editplan raw_snapshot mirrors extract raw_snapshot", not snap_mismatched,
       f"mismatched: {snap_mismatched}")

# a non-collapsible unit must be written as a rebuilt tree, never collapsed
noncollapsible = {u["unit_id"] for u in samples["extract"]["units"] if not u["collapsible"]}
bad = [e["unit_id"] for e in samples["editplan"]["edits"]
       if e["unit_id"] in noncollapsible and e["value"]["kind"] != "component"]
report("non-collapsible units are written as component trees", not bad, f"collapsed: {bad}")

# in_place units must be written as literals, never as translate keys
inplace = {u["unit_id"] for u in samples["extract"]["units"] if u["strategy"] == "in_place"}
bad = [e["unit_id"] for e in samples["editplan"]["edits"]
       if e["unit_id"] in inplace and e["value"]["kind"] != "literal"]
report("in_place units are written as literals", not bad, f"wrong kind: {bad}")

# no [[n]] may survive into a literal value
residue = [e["unit_id"] for e in samples["editplan"]["edits"]
           if e["value"]["kind"] == "literal" and "[[" in e["value"]["text"]]
report("no placeholder residue in literal values", not residue, f"residue: {residue}")

# per-segment keys must be <unit key>.<i> and cover every segment
seg_counts = {u["unit_id"]: len(u["source"]["segments"]) for u in samples["extract"]["units"]}
keys_by_unit = {u["unit_id"]: u["key"] for u in samples["extract"]["units"]}
problems = []
for e in samples["editplan"]["edits"]:
    if e["value"]["kind"] != "component":
        continue
    base = keys_by_unit[e["unit_id"]]
    found = sorted(
        k for k in json.dumps(e["value"]["tree"]).split('"') if k.startswith(base + ".")
    )
    want = sorted(f"{base}.{i}" for i in range(seg_counts[e["unit_id"]]))
    if found != want:
        problems.append((e["unit_id"], found, want))
report("component trees use exactly <key>.<segment> for every segment", not problems, problems)

# placeholder multiset must match between source and translation.
# An empty target means "not translated yet" and is checked separately.
ph = lambda s: sorted(t for t in __import__("re").findall(r"\[\[\?\d+\]\]", s))
src = {u["unit_id"]: u["source"]["text"] for u in samples["extract"]["units"]}
bad = [uid for uid, entry in samples["translations"]["entries"].items()
       if entry["target"] and ph(src[uid]) != ph(entry["target"])]
report("placeholder multiset preserved in every translation", not bad, f"mismatched: {bad}")

# the file a human edits must show the source text, or they are translating blind
missing = [uid for uid, entry in samples["translations"]["entries"].items()
           if entry.get("source", "") != src[uid]]
report("every translations entry echoes its source text for the human",
       not missing, f"missing/blank source: {missing}")

# an empty target is untranslated, never a silent empty string written onto a sign
blank = [uid for uid, entry in samples["translations"]["entries"].items()
         if not entry["target"] and entry.get("status") not in (None, "untranslated", "skip")]
report("an empty target is only ever untranslated or a deliberate skip", not blank, blank)


print(f"\n{'=' * 60}\n  {ok} passed, {fail} failed\n{'=' * 60}")
sys.exit(1 if fail else 0)
