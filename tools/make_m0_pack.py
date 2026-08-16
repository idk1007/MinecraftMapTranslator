"""Build the M0 verification resources.zip, then prove it is well-formed.

Step 3 of M0 has four ways to fail silently -- wrapper directory, BOM, backslash
separators, wrong namespace path -- and every one of them shows up in-game as
"the sign displays the raw key", which is the same symptom as a broken sign or a
broken command. That ambiguity is what makes the manual route expensive, so this
builds the zip deterministically and then asserts the four properties before you
ever copy it into the world.

Also a dry run of what backends/resourcepack/pack.py will do later.

Usage:
    python tools/make_m0_pack.py                     # pack_format 75 + supported_formats
    python tools/make_m0_pack.py --pack-format 55 --no-supported-formats   # step 6
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sandbox" / "m0"

NAMESPACE = "mcmt"
LANG = "zh_tw"
KEY = "mcmt.test.hello"
VALUE = "哈囉世界"


def build(pack_format: int, supported: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pack_meta = {
        "pack": {
            "pack_format": pack_format,
            "description": "mcmt M0 verification",
        }
    }
    if supported:
        pack_meta["pack"]["supported_formats"] = {"min_inclusive": 55, "max_inclusive": 99}

    lang = {KEY: VALUE}

    # Strict JSON, UTF-8 without BOM, sorted keys, LF line endings.
    # ensure_ascii=False keeps the Chinese readable in the file; Minecraft's GSON
    # accepts either, but a mojibake'd file is far harder to debug by eye.
    meta_bytes = (json.dumps(pack_meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    lang_bytes = (json.dumps(lang, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    zip_path = OUT_DIR / "resources.zip"
    lang_arc = f"assets/{NAMESPACE}/lang/{LANG}.json"

    # arcnames are written literally with forward slashes. Windows tooling
    # (and some PowerShell versions of Compress-Archive) can emit backslash
    # separators, which Minecraft will not resolve.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pack.mcmeta", meta_bytes)
        zf.writestr(lang_arc, lang_bytes)

    return zip_path


def verify(zip_path: Path) -> bool:
    print(f"\nverifying {zip_path}")
    problems = []

    if not zipfile.is_zipfile(zip_path):
        print("  FAIL  not a zip file at all")
        return False

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        meta_raw = zf.read("pack.mcmeta") if "pack.mcmeta" in names else b""
        lang_arc = f"assets/{NAMESPACE}/lang/{LANG}.json"
        lang_raw = zf.read(lang_arc) if lang_arc in names else b""

    print("  entries:")
    for n in names:
        print(f"    {n}")

    # 1. no wrapper directory -- pack.mcmeta must sit at the zip root
    if "pack.mcmeta" not in names:
        problems.append("pack.mcmeta is not at the zip root (wrapper directory?)")

    # 2. lang file at the exact namespace path
    if lang_arc not in names:
        problems.append(f"missing {lang_arc}")

    # 3. forward slashes only
    if any("\\" in n for n in names):
        problems.append("entry names contain backslashes; Minecraft will not resolve them")

    # 4. no BOM on either JSON
    for label, raw in (("pack.mcmeta", meta_raw), (lang_arc, lang_raw)):
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{label} starts with a UTF-8 BOM")

    # 5. both parse as strict JSON
    for label, raw in (("pack.mcmeta", meta_raw), (lang_arc, lang_raw)):
        try:
            json.loads(raw.decode("utf-8"))
        except Exception as e:
            problems.append(f"{label} is not strict JSON: {e}")

    # 6. the key the sign points at is actually present
    try:
        if KEY not in json.loads(lang_raw.decode("utf-8")):
            problems.append(f"lang file does not contain {KEY}")
    except Exception:
        pass

    # 7. namespace of the key matches the assets/ directory
    if not KEY.startswith(NAMESPACE + "."):
        problems.append(f"key {KEY} does not live under namespace {NAMESPACE}")

    print()
    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return False

    meta = json.loads(meta_raw.decode("utf-8"))
    print(f"  PASS  zip root is clean, no wrapper directory")
    print(f"  PASS  {lang_arc} present, no BOM, strict JSON")
    print(f"  PASS  key {KEY} -> {json.loads(lang_raw.decode('utf-8'))[KEY]}")
    print(f"  PASS  namespace {NAMESPACE} matches key prefix and assets path")
    print(f"        pack_format = {meta['pack']['pack_format']}"
          f"{'  (+ supported_formats)' if 'supported_formats' in meta['pack'] else '  (no supported_formats)'}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-format", type=int, default=75)
    ap.add_argument("--no-supported-formats", action="store_true")
    a = ap.parse_args()

    z = build(a.pack_format, supported=not a.no_supported_formats)
    okay = verify(z)

    if okay:
        print(f"\nnext: copy this file next to level.dat\n")
        print(f'  copy "{z}" "%APPDATA%\\.minecraft\\saves\\TT_WORLD_NAME_PROBE\\resources.zip"\n')
        print("  then: fully exit to the main menu, set language to 繁體中文, re-enter the world,")
        print("        and answer 是 to the resource-pack prompt.")
    sys.exit(0 if okay else 1)
