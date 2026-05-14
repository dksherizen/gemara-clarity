"""Master post-batch fix-up orchestrator. Run AFTER the batch finishes.

Steps:
1. Rebuild library index.
2. Backfill per-amud mainTopic + overview.
3. Run heuristic audit to surface known suspicious patterns.
4. Run LM verifier on classifications (slowest step, ~6-8 hours for full BM).
5. Run LM title cleanup (transliteration fix).
6. Final audit + summary.

Local-only — Qwen via LMStudioClient. No cloud calls.

Usage:
    py fixup_all.py                       # full BM cleanup
    py fixup_all.py Bava_Metzia_2*.json   # just the 2x dapim
    py fixup_all.py --no-verifier         # skip the slow verifier
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PY_DIR = Path(__file__).resolve().parent


def run(label: str, cmd: list[str]) -> None:
    print(f"\n{'='*60}\n=== {label}\n{'='*60}", flush=True)
    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=PY_DIR)
    elapsed = time.monotonic() - t0
    print(f"\n=== {label} done in {elapsed/60:.1f} min (exit {result.returncode}) ===\n", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default="Bava_Metzia_*.json")
    p.add_argument("--no-verifier", action="store_true", help="skip LM classification verifier (saves hours)")
    p.add_argument("--no-titles", action="store_true", help="skip LM title cleanup")
    p.add_argument("--audit-only", action="store_true", help="just run audits, no modifications")
    args = p.parse_args()

    print(f"Pattern: {args.pattern}")
    print(f"Verifier: {'OFF' if args.no_verifier or args.audit_only else 'ON'}")
    print(f"Title cleanup: {'OFF' if args.no_titles or args.audit_only else 'ON'}")

    # Step 1: index + overviews (cheap, no LM)
    run("1. Rebuild library index", ["py", "update_index.py"])
    run("2. Backfill per-amud overviews", ["py", "postprocess_overviews.py", args.pattern])

    # Step 3: heuristic audit (pre-verifier, baseline)
    run("3. Heuristic audit (baseline)", ["py", "audit_classifications.py", args.pattern])

    if args.audit_only:
        print("\n--audit-only: stopping before LM passes.")
        return 0

    # Step 4: LM classification verifier (slow)
    if not args.no_verifier:
        run("4. LM classification verifier (slow)", ["py", "verify_classifications.py", args.pattern])

    # Step 5: LM title cleanup
    if not args.no_titles:
        run("5. LM title cleanup", ["py", "fix_titles.py", args.pattern])

    # Step 6: Rebuild index again (in case titles changed) + final audit
    run("6. Rebuild library index (post-fixup)", ["py", "update_index.py"])
    run("7. Heuristic audit (post-fixup)", ["py", "audit_classifications.py", args.pattern])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
