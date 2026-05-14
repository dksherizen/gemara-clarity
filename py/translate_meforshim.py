"""Add phrase-aligned Hebrew/English to every meforesh in every built amud
JSON. Two effects:

1. Where Sefaria didn't provide an English translation for a meforesh, we
   generate one via Qwen — consistency across all meforshim.
2. Hebrew + English are now phrase-aligned (linear) like the main daf table,
   not two separate blocks of prose.

For each meforesh:
- Run deterministic phrase split on the Hebrew (uses passes.phrasemap)
- Run the LM alignment pass — same alignment logic used for main daf phrases —
  feeding Sefaria's English (if any) as a reference. The LM strips Davidson
  commentary, aligns to phrase boundaries, and translates literally where the
  reference is silent.
- Write back as comment.phrases.

100% local — Qwen 27B via LMStudioClient.

Usage:
    py translate_meforshim.py                 # all built BM amudim
    py translate_meforshim.py "Bava_Metzia_5*.json"   # subset
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from llm import LMStudioClient
from passes.phrasemap import build_phrases_for_step
from passes.translate import translate_step_phrases
from schema import MeforeshComment, Phrase, Step

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"


def _meforesh_already_aligned(c: dict) -> bool:
    phrases = c.get("phrases")
    if not phrases:
        return False
    # If existing phrases reconstruct the hebrew, treat as done.
    he_concat = " ".join(p.get("aramaic", "") for p in phrases).strip()
    target = (c.get("hebrew") or "").strip()
    if not target:
        return False
    # Loose check: at least 70% of target hebrew tokens should appear in phrases.
    target_tokens = re.findall(r"\S+", target)
    phrase_tokens = re.findall(r"\S+", he_concat)
    if not target_tokens:
        return True
    overlap = sum(1 for t in target_tokens if t in phrase_tokens)
    return overlap / len(target_tokens) > 0.7


def _align_one_meforesh(client: LMStudioClient, comment_dict: dict) -> bool:
    """Split + align one meforesh's Hebrew/English. Mutates comment_dict.
    Returns True on success."""
    hebrew = (comment_dict.get("hebrew") or "").strip()
    if not hebrew:
        return False
    if _meforesh_already_aligned(comment_dict):
        return False
    # Split the Hebrew into phrases (deterministic).
    english_ref = (comment_dict.get("english") or "").strip()
    phrases = build_phrases_for_step(hebrew, english_ref)
    if not phrases:
        return False
    # Wrap as a minimal Step so we can reuse translate_step_phrases.
    pseudo_step = Step(
        stepNumber=0,
        hebrewStepName="מימרא",
        title="(meforesh)",
        stepSummary="",
        whatsHappening="",
        deeperAnalysis="",
        keyTerms=[],
        phrases=phrases,
    )
    try:
        new_phrases = translate_step_phrases(client, pseudo_step, english_ref)
    except Exception as e:
        print(f"    align failed: {e}", flush=True)
        return False
    comment_dict["phrases"] = [p.model_dump(exclude_none=True) for p in new_phrases]
    return True


def process_amud(client: LMStudioClient, path: Path) -> tuple[int, int]:
    d = json.loads(path.read_text(encoding="utf-8"))
    steps = d.get("steps") or []
    aligned = 0
    total = 0
    for step in steps:
        m = step.get("meforshim") or {}
        for bucket_name in ("rashi", "tosafot", "rishonim", "acharonim"):
            for c in (m.get(bucket_name) or []):
                total += 1
                if _align_one_meforesh(client, c):
                    aligned += 1
    if aligned:
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return total, aligned


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
    print(f"aligning meforshim in {len(files)} amudim…", flush=True)
    total_meforshim = 0
    total_aligned = 0
    with LMStudioClient() as client:
        for f in files:
            t0 = time.monotonic()
            try:
                n, a = process_amud(client, f)
            except Exception as e:
                print(f"  {f.name}: ERROR — {e}", flush=True)
                continue
            elapsed = time.monotonic() - t0
            total_meforshim += n
            total_aligned += a
            print(
                f"  {f.name}: {a}/{n} meforshim aligned ({elapsed:.0f}s)",
                flush=True,
            )
    print(f"\nTotal: {total_aligned}/{total_meforshim} meforshim aligned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
