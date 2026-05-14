"""Post-process: ensure every Hebrew keyTerm has full nikud (vowels).

Scans every step's keyTerms across all built amud JSONs. For any term whose
Hebrew text contains NO nikud characters, sends a batch to Qwen 27B to add the
correct vocalization, then writes back in place.

100% local — uses LMStudioClient → Qwen 27B at http://10.6.15.101:1234.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from llm import LMStudioClient

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

# Hebrew nikud (vowels + cantillation): Unicode block U+0591-U+05C7
NIKUD_RE = re.compile(r"[֑-ׇ]")
HEBREW_LETTER_RE = re.compile(r"[א-ת]")


def has_nikud(s: str) -> bool:
    return bool(NIKUD_RE.search(s or ""))


def has_hebrew(s: str) -> bool:
    return bool(HEBREW_LETTER_RE.search(s or ""))


class VocalizedTerms(BaseModel):
    vocalized: list[str] = Field(default_factory=list)


SYSTEM = """You are vocalizing (adding nikud / vowels) to Hebrew/Aramaic Talmudic terms. Input is an ordered list of Hebrew strings, some of which already have nikud and some of which don't.

For each input string, return the SAME content but with FULL nikud added if missing. Use traditional Talmudic vocalization (i.e., how the word would be pointed in a Mishnah/Gemara).

Rules:
1. Only ADD nikud to consonant letters. Do NOT change the consonants or word order.
2. If the input already has correct nikud, return it unchanged (or improve it if obviously deficient).
3. If a string is not Hebrew (e.g., punctuation, an English word), return it unchanged.
4. Output array MUST have exactly the same length as the input array.

Examples:
  Input:  ["שנים אוחזין בטלית", "קל וחומר", "מָמוֹן", "המוציא מחבירו"]
  Output: ["שְׁנַיִם אוֹחֲזִין בְּטַלִּית", "קַל וָחוֹמֶר", "מָמוֹן", "הַמּוֹצִיא מֵחֲבֵירוֹ"]

Return strict JSON: { vocalized: [str, str, ...] } with exactly the same length as the input list."""


def vocalize_terms(client: LMStudioClient, terms: list[str]) -> list[str]:
    if not terms:
        return terms
    user = "Add full nikud to each of these Hebrew terms:\n" + "\n".join(
        f"[{i+1}] {t}" for i, t in enumerate(terms)
    )
    try:
        result = client.call_json(
            pass_name="teaching",
            system=SYSTEM,
            user=user,
            response_model=VocalizedTerms,
            max_tokens=4000,
        )
    except Exception as e:
        print(f"  vocalize failed: {e}")
        return terms
    out = list(result.vocalized)
    if len(out) != len(terms):
        if len(out) < len(terms):
            out = out + terms[len(out):]
        else:
            out = out[: len(terms)]
    # Preserve original if model returned empty for that slot.
    return [v.strip() if v.strip() else t for v, t in zip(out, terms)]


def fix_amud(client: LMStudioClient, path: Path) -> tuple[int, int]:
    d = json.loads(path.read_text(encoding="utf-8"))
    steps = d.get("steps") or []
    if not steps:
        return 0, 0

    # Collect all keyTerms across all steps that need nikud.
    to_fix: list[tuple[int, int, str]] = []  # (step_idx, term_idx, original_term)
    for si, step in enumerate(steps):
        for ti, kt in enumerate(step.get("keyTerms") or []):
            term = (kt.get("term") or "").strip()
            if not term:
                continue
            if has_hebrew(term) and not has_nikud(term):
                to_fix.append((si, ti, term))

    if not to_fix:
        return sum(len(s.get("keyTerms") or []) for s in steps), 0

    # Batch them through the vocalizer (one call per amud).
    terms_only = [t[2] for t in to_fix]
    vocalized = vocalize_terms(client, terms_only)

    # Apply.
    for (si, ti, _orig), new in zip(to_fix, vocalized):
        steps[si]["keyTerms"][ti]["term"] = new

    d["steps"] = steps
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(s.get("keyTerms") or []) for s in steps)
    return total, len(to_fix)


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
    print(f"adding nikud across {len(files)} amudim…", flush=True)
    total_terms = 0
    total_fixed = 0
    with LMStudioClient() as client:
        for f in files:
            t0 = time.monotonic()
            n, fixed = fix_amud(client, f)
            elapsed = time.monotonic() - t0
            total_terms += n
            total_fixed += fixed
            status = f"({elapsed:.0f}s)"
            if fixed:
                print(f"  ✓ {f.name}: {fixed}/{n} terms vocalized {status}", flush=True)
            else:
                print(f"  {f.name}: all {n} terms already have nikud {status}", flush=True)
    print(f"\nTotal: {total_fixed}/{total_terms} terms vocalized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
