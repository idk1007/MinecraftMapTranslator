"""Spike probe: survey PyPI metadata for candidate NBT/region libraries.

Throwaway. Answers "is this library even alive?" before we spend time installing.
"""
import json
import urllib.request
from datetime import datetime

CANDIDATES = [
    "amulet-nbt",
    "amulet-core",
    "nbtlib",
    "pyanvil",
    "mcworldlib",
    "anvil-parser",
    "anvil-parser2",
    "amulet-map-editor",
]


def fetch(pkg):
    url = f"https://pypi.org/pypi/{pkg}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001 - spike code
        return {"_error": f"{type(e).__name__}: {e}"}


def newest_upload(data, version):
    files = data.get("releases", {}).get(version) or []
    stamps = [f["upload_time_iso_8601"] for f in files if f.get("upload_time_iso_8601")]
    return min(stamps) if stamps else "?"


for pkg in CANDIDATES:
    data = fetch(pkg)
    if "_error" in data:
        print(f"{pkg:20s} UNAVAILABLE  {data['_error']}")
        continue
    info = data["info"]
    ver = info["version"]
    when = newest_upload(data, ver)
    age = ""
    if when != "?":
        d = datetime.fromisoformat(when.replace("Z", "+00:00"))
        age = f"({(datetime.now(d.tzinfo) - d).days} days ago)"
    print(f"{pkg:20s} {ver:12s} {when[:10]:12s} {age:16s} py={info.get('requires_python')}")
    # how many releases, to gauge maintenance cadence
    rels = [(v, newest_upload(data, v)) for v in data.get("releases", {})]
    rels = sorted([r for r in rels if r[1] != "?"], key=lambda x: x[1])
    if rels:
        print(f"{'':20s}   first={rels[0][1][:10]}  releases={len(rels)}")
    summary = (info.get("summary") or "").strip()
    print(f"{'':20s}   {summary[:100]}")
