"""Backfill per-amud mainTopic + overview from existing JSON files.

Earlier batch runs produced 5-amud-window-level mainTopic/overview replicated
across every amud in the window. This script rewrites each amud's mainTopic and
overview to be derived from the sugyot that touch that amud — pure data
transformation, no LLM needed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"


def fix_one(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  {path.name}: read failed: {e}")
        return False

    sugyot = d.get("sugyaBoundaries") or []
    if not sugyot:
        return False

    if len(sugyot) == 1:
        new_topic = sugyot[0].get("topic") or d.get("mainTopic", "")
        new_overview = sugyot[0].get("gist") or d.get("overview", "")
    else:
        topics = [sg.get("topic", "") for sg in sugyot[:3] if sg.get("topic")]
        new_topic = " · ".join(topics)
        new_overview = " ".join(
            f"({i+1}) {sg.get('gist', '')}" for i, sg in enumerate(sugyot)
        )

    if new_topic == d.get("mainTopic") and new_overview == d.get("overview"):
        return False

    d["mainTopic"] = new_topic
    d["overview"] = new_overview
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "Bava_Metzia_*.json"
    files = sorted(DATA_DIR.glob(pattern))
    # Skip review sidecars + backups
    files = [
        f for f in files
        if not any(s in f.name for s in (".review", ".bak", "preprompt", "lookupbug", "demo"))
    ]
    print(f"scanning {len(files)} files…")
    changed = 0
    for f in files:
        if fix_one(f):
            changed += 1
            print(f"  ✓ {f.name}")
    print(f"updated {changed}/{len(files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
