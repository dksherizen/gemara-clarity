"""Re-run the translate pass on existing amud JSONs to produce LITERAL
phrase translations (with optional brief notes) instead of the Steinsaltz
commentary that the earlier prompts let leak through.

100% local — uses LMStudioClient → Qwen 27B at http://10.6.15.101:1234.
No cloud calls.

For each amud:
- Load the JSON
- For each step, fetch fresh English from Sefaria for that step's line range
  (so the LM has reference text)
- Call translate_step_phrases() with the new strict prompt
- Replace the step's phrases in-place
- Save the JSON

Usage:
    py retranslate_phrases.py
    py retranslate_phrases.py "Bava_Metzia_5*.json"
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

from llm import LMStudioClient
from passes.translate import translate_step_phrases
from sefaria import fetch_daf_text

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"


def _aramaic_chunk_english(daf_hebrew, daf_english, step_phrases):
    """For an existing step, slice the daf's full English proportionally to where
    this step's aramaic content lives within the full daf."""
    full_aramaic = " ".join(daf_hebrew)
    step_aramaic = " ".join(p.get("aramaic", "") for p in step_phrases)
    if not step_aramaic.strip():
        return ""
    # Find position of step's aramaic in the full daf (approximate, by normalized match).
    def _norm(s):
        return re.sub(r"\s+", "", re.sub(r"[֑-ׇ]", "", s or ""))
    full_n = _norm(full_aramaic)
    step_n = _norm(step_aramaic)
    if not full_n or not step_n:
        return " ".join(daf_english)
    needle = step_n[:80]
    pos = full_n.find(needle)
    if pos < 0:
        # Couldn't locate; return whole English.
        return " ".join(daf_english)
    full_en = " ".join(daf_english)
    en_words = full_en.split()
    if not en_words:
        return ""
    start_frac = pos / len(full_n)
    end_frac = min(1.0, (pos + len(step_n)) / len(full_n))
    i0 = int(start_frac * len(en_words))
    i1 = max(i0 + 1, int(end_frac * len(en_words)))
    # Take ±20% padding to give the LM enough context to align.
    pad = max(20, (i1 - i0))
    i0 = max(0, i0 - pad)
    i1 = min(len(en_words), i1 + pad)
    return " ".join(en_words[i0:i1])


async def _fetch_daf(masechet: str, daf: int, amud: str):
    async with httpx.AsyncClient(timeout=60) as c:
        return await fetch_daf_text(c, masechet, daf, amud)


def _already_literal(d: dict) -> bool:
    """Heuristic: if every phrase's english is reasonably proportional to its
    aramaic word count, treat this amud as already retranslated and skip."""
    steps = d.get("steps") or []
    if not steps:
        return True
    total = bad = 0
    for s in steps:
        for p in s.get("phrases", []) or []:
            ar = (p.get("aramaic") or "").split()
            en = (p.get("english") or "").split()
            if not ar:
                continue
            total += 1
            # >3x the Aramaic word count = likely commentary leak
            if len(en) > max(20, len(ar) * 3):
                bad += 1
    if total == 0:
        return True
    return bad / total < 0.05  # less than 5% bad → already mostly clean


def retranslate_amud(client: LMStudioClient, path: Path) -> tuple[int, int]:
    """Returns (steps_total, steps_retranslated)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    steps = d.get("steps") or []
    if not steps:
        return 0, 0
    if _already_literal(d):
        return len(steps), 0  # skip — already retranslated
    masechet = d.get("masechet", "")
    daf_num = int(d.get("daf", 0))
    amud_letter = d.get("amud", "a")
    try:
        daf = asyncio.run(_fetch_daf(masechet, daf_num, amud_letter))
    except Exception as e:
        print(f"  fetch error: {e}")
        return len(steps), 0

    # Need a Step-like object that translate_step_phrases can consume.
    # The function accepts a Step with .phrases (list of Phrase objects).
    # Easiest: import Step + Phrase from schema and reconstruct.
    from schema import Step, Phrase

    retranslated = 0
    for i, step_dict in enumerate(steps):
        try:
            step_obj = Step.model_validate(step_dict)
        except Exception as e:
            print(f"  step {step_dict.get('stepNumber')} validate failed: {e}")
            continue
        # Compute the English reference chunk for this step.
        step_english = _aramaic_chunk_english(daf.hebrew, daf.english, step_dict.get("phrases", []))
        # Run translate pass.
        try:
            new_phrases = translate_step_phrases(client, step_obj, step_english)
        except Exception as e:
            print(f"  step {step_obj.stepNumber} retranslate failed: {e}")
            continue
        # Serialize phrases back into the dict.
        steps[i]["phrases"] = [p.model_dump(exclude_none=True) for p in new_phrases]
        retranslated += 1

    d["steps"] = steps
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(steps), retranslated


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default="Bava_Metzia_*.json")
    args = p.parse_args()
    files = sorted(
        f for f in DATA_DIR.glob(args.pattern)
        if re.match(r"^[A-Za-z_]+_\d+[ab]\.json$", f.name)
    )
    if not files:
        print("no files matched")
        return 0
    print(f"retranslating {len(files)} amudim with strict literal prompt…", flush=True)
    total_steps = 0
    total_retranslated = 0
    with LMStudioClient() as client:
        for f in files:
            t0 = time.monotonic()
            try:
                n, r = retranslate_amud(client, f)
            except Exception as e:
                print(f"  {f.name}: ERROR — {e}", flush=True)
                continue
            elapsed = time.monotonic() - t0
            total_steps += n
            total_retranslated += r
            if r == 0 and n > 0:
                print(f"  {f.name}: skipped — already literal ({elapsed:.0f}s)", flush=True)
            else:
                print(f"  {f.name}: {r}/{n} steps retranslated ({elapsed:.0f}s)", flush=True)
    print(f"\nTotal: {total_retranslated}/{total_steps} steps retranslated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
