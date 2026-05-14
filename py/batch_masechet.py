"""Batch-build every amud of a tractate. Designed to run for days unattended.

Features:
  - Auto-discovers daf count from Sefaria (no hardcoded ranges).
  - Resumable: skips amudim whose JSON output already exists (unless --redo).
  - Failure-tolerant: on a per-amud crash, logs and continues to the next.
  - Failed amudim are retried at the end of the run.
  - Progress is written to a manifest so a restart picks up where it left off.

Usage:
    py batch_masechet.py Bava_Metzia
    py batch_masechet.py Bava_Metzia --start 5a --end 10b
    py batch_masechet.py Bava_Metzia --redo   # rebuild everything
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx

import update_index
import window_orchestrator
from sefaria import SEFARIA_BASE

WINDOW_SIZE = 5

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"
MANIFEST = DATA_DIR / "_batch_manifest.json"
LOG_FILE = DATA_DIR / "_batch_log.txt"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def fetch_amud_count(masechet: str) -> int:
    """Sefaria /api/index/<book>.schema.lengths[0] is the AMUD count (not daf
    count). For Bava Metzia this is 237: dapim 2 through ~120 with the last daf
    often being a-only (where the Hadran sits) and possibly an empty trailing
    stub or two. We treat any empty-source amud as 'doesn't exist' downstream."""
    url = f"{SEFARIA_BASE}/index/{masechet}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    lengths = data.get("schema", {}).get("lengths") or data.get("lengths")
    if isinstance(lengths, list) and lengths:
        return int(lengths[0])
    raise RuntimeError(f"Could not determine amud count for {masechet}; raw: {data!r}")


def parse_amud(s: str) -> tuple[int, str]:
    s = s.strip().lower()
    if not s or s[-1] not in {"a", "b"} or not s[:-1].isdigit():
        raise ValueError(f"bad daf_amud: {s}")
    return int(s[:-1]), s[-1]


def amud_label(daf: int, amud: str) -> str:
    return f"{daf}{amud}"


def expected_output(masechet: str, daf: int, amud: str) -> Path:
    return DATA_DIR / f"{masechet}_{daf}{amud}.json"


def _load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"runs": [], "results": {}}


def _save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def build_window_safe(masechet: str, amud_pairs: list[tuple[int, str]]) -> tuple[str, str]:
    """Window-build wrapper. Returns (status, message). Catches everything so
    the batch never dies on a single window's failure."""
    try:
        window_orchestrator.build_window(masechet, amud_pairs)
        return "ok", "ok"
    except KeyboardInterrupt:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        return "failed", f"{type(e).__name__}: {e}\n{tb}"


def enumerate_amudim(
    amud_count: int,
    start: tuple[int, str] | None,
    end: tuple[int, str] | None,
) -> list[tuple[int, str]]:
    """Sefaria's amud_count is the linear count of amudim starting at 2a. We
    convert linearly: index 1→2a, 2→2b, 3→3a, 4→3b, … For an odd amud_count the
    last amud is the 'a' side of its daf. We may overshoot by 1-2 trailing stubs
    Sefaria sometimes includes; those will fail the "no Hebrew source" check in
    build.py and get logged as skips."""
    out: list[tuple[int, str]] = []
    for k in range(1, amud_count + 1):
        daf = (k + 1) // 2 + 1
        amud = "a" if k % 2 == 1 else "b"
        out.append((daf, amud))
    if start:
        out = [p for p in out if (p[0], p[1]) >= start]
    if end:
        out = [p for p in out if (p[0], p[1]) <= end]
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("masechet")
    p.add_argument("--start", type=parse_amud, default=None, help="e.g. 5a")
    p.add_argument("--end", type=parse_amud, default=None, help="e.g. 119a")
    p.add_argument("--redo", action="store_true", help="rebuild even if output exists")
    p.add_argument("--retry-passes", type=int, default=2, help="how many retry passes for failures")
    args = p.parse_args(argv or sys.argv[1:])

    _log(f"=== batch start: {args.masechet} ===")
    amud_count = asyncio.run(fetch_amud_count(args.masechet))
    _log(f"  {args.masechet} reports {amud_count} amudim per Sefaria index.")

    plan = enumerate_amudim(amud_count, args.start, args.end)
    _log(f"  Planning {len(plan)} amudim ({(len(plan) + WINDOW_SIZE - 1) // WINDOW_SIZE} windows of {WINDOW_SIZE}).")

    # Group into WINDOW_SIZE-amud windows. Windows do NOT overlap.
    windows: list[list[tuple[int, str]]] = []
    for i in range(0, len(plan), WINDOW_SIZE):
        windows.append(plan[i : i + WINDOW_SIZE])

    manifest = _load_manifest()
    run_id = _now()
    manifest["runs"].append({"id": run_id, "masechet": args.masechet, "planned_windows": len(windows)})
    results = manifest.setdefault("results", {})

    def window_already_done(window: list[tuple[int, str]]) -> bool:
        if args.redo:
            return False
        # If every amud in the window has a JSON output, skip it.
        return all(expected_output(args.masechet, d, a).exists() for d, a in window)

    failed: list[tuple[list[tuple[int, str]], str]] = []

    t0 = time.monotonic()
    for wi, window in enumerate(windows, start=1):
        window_label = (
            f"{window[0][0]}{window[0][1]}-{window[-1][0]}{window[-1][1]}"
        )
        key = f"{args.masechet}/window/{window_label}"
        if window_already_done(window):
            _log(f"  [{wi:>3}/{len(windows)}] {window_label} — skip (all exist)")
            results[key] = {"status": "ok", "skipped": True, "at": _now()}
            _save_manifest(manifest)
            continue
        _log(f"  [{wi:>3}/{len(windows)}] {window_label} — building window…")
        status, msg = build_window_safe(args.masechet, window)
        results[key] = {
            "status": status,
            "message": "ok" if status == "ok" else msg,
            "at": _now(),
        }
        _save_manifest(manifest)
        if status == "failed":
            _log(f"  [{wi:>3}/{len(windows)}] {window_label} — FAILED: {msg.splitlines()[0]}")
            failed.append((window, msg))
        elif status == "ok":
            try:
                n = update_index.rebuild_index()
                _log(f"    library index: {n} entries")
            except Exception as e:
                _log(f"    index rebuild failed (non-fatal): {e}")
        elapsed = time.monotonic() - t0
        avg = elapsed / wi
        remaining = avg * (len(windows) - wi)
        _log(
            f"    elapsed {elapsed/60:.1f}m, avg {avg/60:.1f}m/window, est remaining {remaining/3600:.1f}h"
        )

    # Retry passes for failures.
    for retry_round in range(1, args.retry_passes + 1):
        if not failed:
            break
        _log(f"--- retry round {retry_round} ({len(failed)} windows) ---")
        still_failed: list[tuple[list[tuple[int, str]], str]] = []
        for window, _prev in failed:
            window_label = (
                f"{window[0][0]}{window[0][1]}-{window[-1][0]}{window[-1][1]}"
            )
            key = f"{args.masechet}/window/{window_label}"
            _log(f"  retry {window_label}…")
            status, msg = build_window_safe(args.masechet, window)
            results[key] = {
                "status": status,
                "message": "ok" if status == "ok" else msg,
                "at": _now(),
                "retry_round": retry_round,
            }
            _save_manifest(manifest)
            if status == "failed":
                still_failed.append((window, msg))
        failed = still_failed

    if failed:
        _log(f"=== batch DONE with {len(failed)} permanent window failures ===")
        for window, msg in failed:
            window_label = (
                f"{window[0][0]}{window[0][1]}-{window[-1][0]}{window[-1][1]}"
            )
            _log(f"  {window_label}: {msg.splitlines()[0]}")
        return 1
    _log("=== batch DONE — every window built successfully ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
