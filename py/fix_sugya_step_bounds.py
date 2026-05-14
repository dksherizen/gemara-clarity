"""Backfill firstStepNumber/lastStepNumber on each sugya for already-built
amud JSONs.

The window orchestrator wasn't updating these fields when it split window
output into per-amud JSONs, so the StepOutline filter on the frontend was
matching zero steps per sugya.

Strategy: each step's first phrase' aramaic content can be matched against the
amud's Hebrew lines (fetched fresh from Sefaria) to determine which Hebrew line
the step starts at. Then we know which sugya each step belongs to.

If Sefaria fetch fails, fall back to proportional distribution: divide steps
across sugyot in proportion to each sugya's line span. Less precise but better
than leaving bounds empty.

No LM calls — pure data + Sefaria text matching."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

from sefaria import fetch_daf_text

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

NIKUD_RE = re.compile(r"[֑-ׇ]")


def _strip_nikud(s: str) -> str:
    return NIKUD_RE.sub("", s or "")


def _normalize_for_match(s: str) -> str:
    return re.sub(r"\s+", "", _strip_nikud(s))


def _find_start_line(step_aramaic: str, daf_hebrew_lines: list[str]) -> int | None:
    """Find which 1-indexed Hebrew line the step starts on, by matching the
    first ~30 chars of step phrases against the daf's concatenated Hebrew."""
    needle = _normalize_for_match(step_aramaic)[:60]
    if len(needle) < 10:
        return None
    cumulative = ""
    line_starts: list[tuple[int, int]] = []  # (1-indexed line, char position in cumulative)
    for i, line in enumerate(daf_hebrew_lines, start=1):
        line_starts.append((i, len(cumulative)))
        cumulative += _normalize_for_match(line)
    if not cumulative:
        return None
    pos = cumulative.find(needle)
    if pos < 0:
        # Try a shorter needle (12 chars) as a softer match.
        short = needle[:12]
        pos = cumulative.find(short)
        if pos < 0:
            return None
    # Find which line that position fell in.
    owner = 1
    for line_no, start_pos in line_starts:
        if start_pos <= pos:
            owner = line_no
        else:
            break
    return owner


async def _try_fetch_amud_hebrew(masechet: str, daf: int, amud: str) -> list[str] | None:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            d = await fetch_daf_text(c, masechet, daf, amud)
        return d.hebrew
    except Exception:
        return None


def _proportional_assign(n_steps: int, sugyot: list[dict]) -> list[tuple[int, int]]:
    """Fallback: split n_steps proportionally to each sugya's line span.
    Returns list of (first, last) step numbers parallel to sugyot."""
    if not sugyot:
        return []
    spans = [max(1, sg.get("endLine", 1) - sg.get("startLine", 1) + 1) for sg in sugyot]
    total = sum(spans)
    cumulative: list[float] = []
    acc = 0
    for s in spans:
        acc += s
        cumulative.append(acc / total)
    result: list[tuple[int, int]] = []
    prev_end = 0
    for i, frac in enumerate(cumulative):
        end_idx = n_steps if i == len(sugyot) - 1 else int(round(frac * n_steps))
        start = prev_end + 1
        end = max(start, end_idx)
        result.append((start, end))
        prev_end = end
    return result


def fix_one(path: Path) -> tuple[bool, str]:
    """Returns (changed, msg)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    sugyot = d.get("sugyaBoundaries") or []
    steps = d.get("steps") or []
    if not sugyot or not steps:
        return False, "no sugyot or steps"

    masechet = d.get("masechet", "")
    daf_num = int(d.get("daf", 0))
    amud_letter = d.get("amud", "a")
    hebrew = asyncio.run(_try_fetch_amud_hebrew(masechet, daf_num, amud_letter))

    # Method 1: Sefaria-text matching per step → which Hebrew line → which sugya.
    step_owner_sugya: list[int | None] = [None] * len(steps)
    if hebrew:
        for i, step in enumerate(steps):
            step_aramaic = " ".join(p.get("aramaic", "") for p in step.get("phrases", []))
            line_no = _find_start_line(step_aramaic, hebrew)
            if line_no is None:
                continue
            for j, sg in enumerate(sugyot):
                if sg.get("startLine", 0) <= line_no <= sg.get("endLine", 0):
                    step_owner_sugya[i] = j
                    break

    # Aggregate first/last step number per sugya.
    new_bounds: list[tuple[int | None, int | None]] = [(None, None)] * len(sugyot)
    for i, owner in enumerate(step_owner_sugya):
        if owner is None:
            continue
        step_num = steps[i].get("stepNumber", i + 1)
        first, last = new_bounds[owner]
        new_first = step_num if first is None else min(first, step_num)
        new_last = step_num if last is None else max(last, step_num)
        new_bounds[owner] = (new_first, new_last)

    # Method 2: fallback for sugyot with no matches → proportional.
    if any(b == (None, None) for b in new_bounds):
        proportional = _proportional_assign(len(steps), sugyot)
        for i, b in enumerate(new_bounds):
            if b == (None, None) and i < len(proportional):
                start_num = steps[proportional[i][0] - 1].get("stepNumber") if proportional[i][0] - 1 < len(steps) else None
                end_num = steps[proportional[i][1] - 1].get("stepNumber") if proportional[i][1] - 1 < len(steps) else None
                new_bounds[i] = (start_num, end_num)

    # Apply.
    changed = False
    for i, sg in enumerate(sugyot):
        first, last = new_bounds[i]
        if sg.get("firstStepNumber") != first or sg.get("lastStepNumber") != last:
            sg["firstStepNumber"] = first
            sg["lastStepNumber"] = last
            changed = True

    if changed:
        d["sugyaBoundaries"] = sugyot
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed, f"sugyot now: {[(sg.get('firstStepNumber'), sg.get('lastStepNumber')) for sg in sugyot]}"


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default="Bava_Metzia_*.json")
    args = p.parse_args()
    files = sorted(
        f for f in DATA_DIR.glob(args.pattern)
        if re.match(r"^[A-Za-z_]+_\d+[ab]\.json$", f.name)
    )
    print(f"scanning {len(files)} files…")
    n_changed = 0
    for f in files:
        try:
            changed, msg = fix_one(f)
        except Exception as e:
            print(f"  {f.name}: ERROR — {e}")
            continue
        if changed:
            n_changed += 1
            print(f"  ✓ {f.name}: {msg}")
    print(f"updated {n_changed}/{len(files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
