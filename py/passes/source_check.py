"""Deterministic source-grounded classification check.

For each step, examine its Aramaic content for opener patterns that have an
UNAMBIGUOUS classification. If the model's hebrewStepName disagrees with what
the pattern demands, force the override.

No LM calls — pure regex pattern matching. Runs after the structure pass.

Patterns (high-confidence overrides only):

- "תא שמע" / "ת״ש" + presence of contradiction language → קשיא
- "תא שמע" / "ת״ש" + presence of supportive context → ראיה
- "לא, דאמר ליה" / "לא, ב..." → תירוץ
- "ואידך:" / "ואידך סבר" / "ואידך אמר" → מימרא
- "וצריכא" alone (≤4 words total) → מימרא
- "ומי מצית אמרת" → קשיא
- "והא ... קאמר" → קשיא
- "אי תנא X הוה אמינא" → תירוץ
- "אי אמרת בשלמא ... אלא אי אמרת" → דחיה (often) or קשיא
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

NIKUD_RE = re.compile(r"[֑-ׇ]")


def _strip_nikud(s: str) -> str:
    return NIKUD_RE.sub("", s or "")


def _strip(s: str) -> str:
    return _strip_nikud(s).strip()


# Each rule: (regex_pattern_in_stripped_aramaic, expected_label, name)
# Patterns operate on nikud-stripped Aramaic.
HARD_RULES: list[tuple[re.Pattern[str], str, str]] = [
    # Redundancy attacks
    (re.compile(r"^\s*למה\s*לי"), "קשיא", "למה לי redundancy attack"),
    (re.compile(r"^\s*ליתני\s+חדא"), "קשיא", "ליתני חדא redundancy attack"),
    (re.compile(r"^\s*וליתני\s"), "קשיא", "וליתני redundancy attack"),
    # Counter-attacks
    (re.compile(r"^\s*ומי\s*מצית\s*אמרת"), "קשיא", "ומי מצית אמרת counter-attack"),
    (re.compile(r"^\s*והא\s.*קאמר"), "קשיא", "והא X קאמר counter-attack"),
    # Resolutions
    (re.compile(r"^\s*אי\s*תנא"), "תירוץ", "אי תנא X הוה אמינא resolution"),
    (re.compile(r"^\s*לא,\s*דאמר\s*ליה"), "תירוץ", "לא דאמר ליה recasting"),
    (re.compile(r"^\s*לא,\s*ב"), "תירוץ", "לא ב recasting"),
    (re.compile(r"^\s*חדא\s*קתני"), "תירוץ", "חדא קתני resolves redundancy"),
    # Alternative views
    (re.compile(r"^\s*ואידך[:\s]"), "מימרא", "ואידך alternative view"),
    (re.compile(r"^\s*ואידך\s*סבר"), "מימרא", "ואידך סבר alternative view"),
    # Necessity assertion
    (re.compile(r"^\s*וצריכא\s*[:.]?\s*$"), "מימרא", "וצריכא alone (transition)"),
    (re.compile(r"^\s*וצריכי\s*[:.]?\s*$"), "מימרא", "וצריכי alone (transition)"),
]


@dataclass
class CheckResult:
    step_number: int
    original_label: str
    forced_label: str | None  # None if no override
    rule_name: str | None
    matched_text: str | None


def check_step_label(step: dict) -> CheckResult:
    """Return whether the step's hebrewStepName should be forced by a rule.
    `step` is a dict (from JSON) or a Step model dumped to dict."""
    label = step.get("hebrewStepName") or ""
    # Build the Aramaic to check: trigger language first, then first phrase.
    triggers = []
    if step.get("triggerLanguage"):
        triggers.append(step["triggerLanguage"])
    phrases = step.get("phrases") or []
    if phrases and phrases[0].get("aramaic"):
        triggers.append(phrases[0]["aramaic"])

    for source_text in triggers:
        sample = _strip(source_text)
        for pattern, expected, name in HARD_RULES:
            if pattern.match(sample) and label != expected:
                return CheckResult(
                    step_number=step.get("stepNumber", 0),
                    original_label=label,
                    forced_label=expected,
                    rule_name=name,
                    matched_text=sample[:80],
                )
    return CheckResult(
        step_number=step.get("stepNumber", 0),
        original_label=label,
        forced_label=None,
        rule_name=None,
        matched_text=None,
    )


def apply_source_checks(steps: list[dict]) -> tuple[list[dict], list[CheckResult]]:
    """Walk steps; for each one where a hard rule forces a different label,
    apply the override. Returns (modified_steps, list_of_overrides)."""
    overrides: list[CheckResult] = []
    for step in steps:
        result = check_step_label(step)
        if result.forced_label and result.forced_label != result.original_label:
            step["hebrewStepName"] = result.forced_label
            overrides.append(result)
    return steps, overrides


# ============================================================================
# Stand-alone CLI: apply source checks to existing JSON files.
# ============================================================================

def main() -> int:
    import argparse
    import json
    from pathlib import Path

    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default="Bava_Metzia_*.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    DATA_DIR = Path(__file__).resolve().parent.parent.parent / "public" / "data"
    files = sorted(
        f for f in DATA_DIR.glob(args.pattern)
        if re.match(r"^[A-Za-z_]+_\d+[ab]\.json$", f.name)
    )
    if not files:
        print("no files matched")
        return 0

    total_overrides = 0
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        steps = d.get("steps") or []
        if not steps:
            continue
        # Run on copies so we don't mutate in dry-run
        if args.dry_run:
            _, overrides = apply_source_checks([dict(s) for s in steps])
        else:
            _, overrides = apply_source_checks(steps)
        if overrides:
            total_overrides += len(overrides)
            print(f"\n=== {f.name}: {len(overrides)} overrides ===")
            for o in overrides:
                print(f"  step {o.step_number}: {o.original_label} → {o.forced_label}")
                print(f"    rule: {o.rule_name}")
                print(f"    matched: {o.matched_text}")
            if not args.dry_run:
                d["steps"] = steps
                f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal overrides applied: {total_overrides}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
