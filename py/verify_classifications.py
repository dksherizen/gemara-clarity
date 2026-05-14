"""Post-batch fix-up: re-classify each step's hebrewStepName using strict rules
and neighbor context. Updates JSON files in-place.

For each step:
  - Show the LM the step's Aramaic + the immediate prior step + immediate next step.
  - Show the strict classification rules (the same rules from talmud_classification_rules.md).
  - Ask: given this context, is the current label correct? If not, what is?
  - If the verifier disagrees with HIGH CONFIDENCE, replace the label.
  - If the verifier is uncertain, keep the original.

100% local — uses LMStudioClient with Qwen 27B same as the main pipeline."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from llm import LMStudioClient

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

HebrewStepName = Literal[
    "מימרא", "קשיא", "תירוץ", "ראיה", "דחיה", "שאלה", "תשובה", "מסקנא"
]
Confidence = Literal["high", "medium", "low"]


class VerdictModel(BaseModel):
    correct: bool
    suggested: HebrewStepName | None = None
    confidence: Confidence
    reason: str = ""


SYSTEM = """You are auditing a Talmud teaching sheet's step classifications. Given ONE step's Aramaic and its immediate context (previous and next step), determine if its hebrewStepName label is correct.

The 8 possible labels are:
- מימרא — a freestanding statement, ruling, or attributed teaching
- קשיא — a challenge or objection against an earlier statement
- תירוץ — a resolution to a קשיא (defends the prior position by exposing הוה אמינא → מסקנא)
- ראיה — a proof or supporting source brought to back a claim
- דחיה — a rejection of a proof, source, or earlier line of reasoning
- שאלה — a clarifying request for information (NOT an objection)
- תשובה — an answer to a שאלה (NOT a תירוץ to a קשיא)
- מסקנא — a final conclusion or summary

STRICT RULES (memorize):
1. A קשיא ATTACKS a prior statement. A שאלה merely REQUESTS information. If the Gemara is pressuring/challenging earlier text, it's קשיא.
2. A תירוץ RESOLVES a קשיא, typically via "אי תנא X הוה אמינא Y" or "לא, [different case]" patterns. A תשובה only answers a neutral שאלה. תירוץ ≠ תשובה.
3. "וצריכא" / "וצריכי" alone is a מימרא (transition asserting both cases are needed), never שאלה.

PATTERN CHEAT SHEET:
- "תא שמע" / "תניא" / "תנן" introducing a source AS A CHALLENGE → קשיא, not מימרא.
- "תא שמע" introducing a source AS SUPPORT for a claim → ראיה, not קשיא.
- "לא, דאמר ליה: ..." / "לא, ב..." (rejecting setup, offering different case) → תירוץ, not תשובה.
- "ואידך: ..." / "ואידך סבר..." (presenting another sage's view) → מימרא, not שאלה/תשובה.
- "למה לי" / "ליתני חדא" / "וליתני X" → קשיא (redundancy attack on wording).
- "אי תנא X הוה אמינא Y" → תירוץ defending against redundancy attack.
- "והא X קאמר!" / "ומי מצית אמרת..." → קשיא (counter-attack on prior reasoning).
- "היכי דמי? לאו ב..." (forcing the case) → usually קשיא (pressing source toward difficulty).

RULES FOR YOUR VERDICT:
- correct: true if the existing label is right.
- suggested: the right label (only if correct=false).
- confidence: "high" only if you can cite a clear pattern match or argumentative function. "low" if the case is borderline.
- reason: one short sentence on why.

Be CONSERVATIVE — only flag as incorrect if you're confident. If borderline, mark correct=true."""


def _strip_nikud(s: str) -> str:
    return re.sub(r"[֑-ׇ]", "", s or "")


def _step_aramaic(step: dict) -> str:
    return " ".join(p.get("aramaic", "") for p in step.get("phrases", [])).strip()


def _build_user_prompt(
    daf_ref: str,
    step: dict,
    prev_step: dict | None,
    next_step: dict | None,
) -> str:
    target_ar = _step_aramaic(step)
    target_label = step.get("hebrewStepName", "")
    target_title = step.get("title", "")

    parts: list[str] = [f"Daf: {daf_ref}"]
    if prev_step:
        prev_ar = _step_aramaic(prev_step)[:300]
        parts.append(f"\nPREVIOUS step (#{prev_step.get('stepNumber')}):")
        parts.append(f"  label: {prev_step.get('hebrewStepName')}")
        parts.append(f"  text:  {prev_ar}")
    parts.append(f"\nTARGET step (#{step.get('stepNumber')}):")
    parts.append(f"  current label: {target_label}")
    parts.append(f"  title: {target_title}")
    parts.append(f"  text: {target_ar}")
    if next_step:
        next_ar = _step_aramaic(next_step)[:300]
        parts.append(f"\nNEXT step (#{next_step.get('stepNumber')}):")
        parts.append(f"  label: {next_step.get('hebrewStepName')}")
        parts.append(f"  text:  {next_ar}")
    parts.append("\nIs the TARGET step's current label correct? Return JSON with correct, suggested, confidence, reason.")
    return "\n".join(parts)


def _single_verdict(
    client: LMStudioClient,
    daf_ref: str,
    step: dict,
    prev_step: dict | None,
    next_step: dict | None,
    temperature: float = 0.1,
) -> VerdictModel | None:
    user = _build_user_prompt(daf_ref, step, prev_step, next_step)
    try:
        return client.call_json(
            pass_name="validate",
            system=SYSTEM,
            user=user,
            response_model=VerdictModel,
            max_tokens=4000,
            temperature=temperature,
        )
    except Exception:
        return None


def verify_steps_in_memory(
    client: LMStudioClient,
    daf_ref: str,
    steps: list[dict],
    self_consistency: bool = True,
) -> tuple[int, list[str]]:
    """Run verifier on a list of step dicts in memory; mutate hebrewStepName
    where verifier disagrees with high confidence.

    Self-consistency mode (default ON): if the first verdict is uncertain
    (correct=False but confidence < high), run 2 more verdicts at temperature
    0.3 and require 2/3 agreement before applying the override. Catches
    classifications the model is "almost sure" about but second-guesses."""
    changes: list[str] = []
    n_changed = 0
    for i, step in enumerate(steps):
        prev_step = steps[i - 1] if i > 0 else None
        next_step = steps[i + 1] if i < len(steps) - 1 else None
        v1 = _single_verdict(client, daf_ref, step, prev_step, next_step, temperature=0.1)
        if v1 is None:
            changes.append(f"  step {step.get('stepNumber')}: verifier error")
            continue

        old = step.get("hebrewStepName")
        # Case 1: high confidence + disagrees → apply immediately.
        if not v1.correct and v1.suggested and v1.confidence == "high":
            step["hebrewStepName"] = v1.suggested
            n_changed += 1
            changes.append(
                f"  step {step.get('stepNumber')}: {old} → {v1.suggested} "
                f"(high-conf, reason: {v1.reason[:100]})"
            )
            continue
        # Case 2: low/medium confidence disagrees → self-consistency vote.
        if self_consistency and not v1.correct and v1.suggested:
            v2 = _single_verdict(client, daf_ref, step, prev_step, next_step, temperature=0.3)
            v3 = _single_verdict(client, daf_ref, step, prev_step, next_step, temperature=0.3)
            verdicts = [v for v in (v1, v2, v3) if v is not None]
            from collections import Counter
            suggestions = [
                v.suggested for v in verdicts if not v.correct and v.suggested
            ]
            corrects = sum(1 for v in verdicts if v.correct)
            if suggestions and len(suggestions) >= 2:
                top, top_count = Counter(suggestions).most_common(1)[0]
                if top_count >= 2 and corrects <= 1:
                    step["hebrewStepName"] = top
                    n_changed += 1
                    changes.append(
                        f"  step {step.get('stepNumber')}: {old} → {top} "
                        f"(self-consistency vote {top_count}/3)"
                    )
                    continue
            # Case 3: three Qwen verdicts disagree → inter-model audit on Nemotron.
            saved = client.pass_models.get("validate")
            cross_verdict = None
            try:
                client.pass_models["validate"] = "nvidia/nemotron-3-super"
                cross_verdict = client.call_json(
                    pass_name="validate",
                    system=SYSTEM,
                    user=_build_user_prompt(daf_ref, step, prev_step, next_step),
                    response_model=VerdictModel,
                    max_tokens=4000,
                    temperature=0.1,
                )
            except Exception:
                cross_verdict = None
            finally:
                if saved:
                    client.pass_models["validate"] = saved
            if cross_verdict and not cross_verdict.correct and cross_verdict.suggested:
                step["hebrewStepName"] = cross_verdict.suggested
                n_changed += 1
                changes.append(
                    f"  step {step.get('stepNumber')}: {old} → {cross_verdict.suggested} "
                    f"(cross-family Nemotron tiebreaker)"
                )
    return n_changed, changes


def verify_amud(client: LMStudioClient, path: Path, dry_run: bool = False) -> tuple[int, int, list[str]]:
    """Returns (n_steps, n_changed, log_lines)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    steps: list[dict] = d.get("steps") or []
    if not steps:
        return 0, 0, []
    daf_ref = d.get("ref", path.stem)
    changes: list[str] = []
    n_changed = 0
    for i, step in enumerate(steps):
        prev_step = steps[i - 1] if i > 0 else None
        next_step = steps[i + 1] if i < len(steps) - 1 else None
        user = _build_user_prompt(daf_ref, step, prev_step, next_step)
        try:
            verdict = client.call_json(
                pass_name="validate",
                system=SYSTEM,
                user=user,
                response_model=VerdictModel,
                max_tokens=4000,
            )
        except Exception as e:
            changes.append(f"  step {step['stepNumber']}: verifier error: {e}")
            continue
        if not verdict.correct and verdict.suggested and verdict.confidence == "high":
            old = step.get("hebrewStepName")
            step["hebrewStepName"] = verdict.suggested
            n_changed += 1
            changes.append(
                f"  step {step['stepNumber']}: {old} → {verdict.suggested} "
                f"(reason: {verdict.reason[:120]})"
            )
    if n_changed and not dry_run:
        d["steps"] = steps
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(steps), n_changed, changes


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default="Bava_Metzia_*.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    files = sorted(
        f for f in DATA_DIR.glob(args.pattern)
        if re.match(r"^[A-Za-z_]+_\d+[ab]\.json$", f.name)
    )
    if not files:
        print("no files matched")
        return 0
    print(f"verifying {len(files)} amudim (dry_run={args.dry_run})…")
    total_steps = 0
    total_changed = 0
    with LMStudioClient() as client:
        for f in files:
            n, changed, log = verify_amud(client, f, dry_run=args.dry_run)
            total_steps += n
            total_changed += changed
            if changed:
                print(f"\n=== {f.name}: {changed}/{n} relabeled ===")
                for line in log:
                    print(line)
            else:
                print(f"  {f.name}: no changes ({n} steps).")
    print(f"\nTotal: {total_changed}/{total_steps} steps relabeled ({total_changed/total_steps*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
