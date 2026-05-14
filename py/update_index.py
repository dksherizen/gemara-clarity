"""Rebuild v2/public/data/index.json from every daf JSON sitting next to it.
The PWA's Library component reads this to know which dapim are available."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"
INDEX_FILE = DATA_DIR / "index.json"

DAF_FILE_RE = re.compile(r"^([A-Za-z_]+)_(\d+)([ab])\.json$")


def rebuild_index() -> int:
    entries = []
    for f in sorted(DATA_DIR.glob("*.json")):
        if not DAF_FILE_RE.match(f.name):
            continue
        # Skip review sidecars and backup files
        if ".review" in f.name or ".bak" in f.name or "preprompt" in f.name or "lookupbug" in f.name or "demo" in f.name:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or "ref" not in d:
            continue
        entries.append(
            {
                "ref": d.get("ref", ""),
                "masechet": d.get("masechet", ""),
                "daf": int(d.get("daf", 0)),
                "amud": d.get("amud", "a"),
                "mainTopic": d.get("mainTopic", ""),
                "generatedAt": d.get("generatedAt", ""),
                "file": f.name,
            }
        )
    # Sort by masechet, daf, amud
    entries.sort(key=lambda e: (e["masechet"], e["daf"], e["amud"]))
    out = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "entries": entries,
    }
    INDEX_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(entries)


if __name__ == "__main__":
    n = rebuild_index()
    print(f"index.json: {n} entries")
