"""Heuristic audit of step classifications across built amud JSONs.

Looks for known mis-classification patterns from the gold-standard critique:
- "תא שמע" / "תניא" / "תנן" introducing a source → almost always קשיא, not מימרא
- "לא, דאמר ליה" / "לא, ב..." resolving a difficulty → תירוץ, not תשובה
- "ואידך" / "ואידך סבר" stating another sage's view → מימרא, not שאלה/תשובה
- Bare "וצריכא" → מימרא, not שאלה
- "למה לי" / "ליתני חדא" / "וליתני" → קשיא (redundancy attack), not שאלה
- "אי תנא X הוה אמינא Y" → תירוץ, not תשובה

For each amud, prints flagged steps and a summary count of suspicious classifications."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

# (pattern, expected_class, description)
# pattern matched against trigger language OR first phrase Aramaic
PATTERNS = [
    (re.compile(r"^\s*תָּא\s*שְׁמַע|^\s*ת\"ש"), "קשיא", "תא שמע citing source as challenge"),
    (re.compile(r"^\s*תָּנֵי |^\s*תָּנְיָא|^\s*תָּנוּ\s*רַבָּנַן"), None, "תניא/תנו רבנן (could be מימרא if standalone, but flag for review)"),
    (re.compile(r"^\s*לָא, דַּאֲמַר|^\s*לָא,\s+ב"), "תירוץ", "לא, [different case] resolving difficulty"),
    (re.compile(r"^\s*וְאִידָּךְ|^\s*וְאִידַּךְ"), "מימרא", "ואידך stating alternative view"),
    (re.compile(r"^\s*וּצְרִיכָא"), "מימרא", "וצריכא asserting necessity"),
    (re.compile(r"^\s*לָמָּה\s*לִי|^\s*וְלִיתְנֵי|^\s*לִיתְנֵי\s+חֲדָא"), "קשיא", "redundancy attack on wording"),
    (re.compile(r"^\s*אִי\s*תְּנָא"), "תירוץ", "אי תנא X הוה אמינא… (תירוץ pattern)"),
    (re.compile(r"^\s*וְהָא"), "קשיא", "והא [contradiction]"),
    (re.compile(r"^\s*וּמִי\s*מָצֵית"), "קשיא", "ומי מצית — challenging the previous interpretation"),
]


def _strip_nikud(s: str) -> str:
    return re.sub(r"[֑-ׇ]", "", s)


def audit_step(step: dict) -> list[str]:
    """Return list of issue descriptions for this step."""
    issues: list[str] = []
    trigger = step.get("triggerLanguage") or ""
    first_phrase = ""
    if step.get("phrases"):
        first_phrase = step["phrases"][0].get("aramaic") or ""
    sample = trigger or first_phrase
    if not sample:
        return issues
    label = step.get("hebrewStepName")
    for pattern, expected, desc in PATTERNS:
        if pattern.search(sample):
            if expected is None:
                issues.append(f"REVIEW: opener pattern '{desc}' present; check label='{label}'")
            elif label != expected:
                issues.append(f"MISMATCH: label='{label}' but pattern says should be '{expected}' ({desc})")
            break
    # Heuristic: step labeled "תשובה" right after a "קשיא" is suspicious — should usually be תירוץ.
    return issues


def audit_amud(path: Path) -> tuple[int, int, list[str]]:
    """Returns (n_steps, n_flagged, lines_to_print)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    steps = d.get("steps") or []
    output: list[str] = []
    flagged = 0
    prev_label = None
    for s in steps:
        issues = audit_step(s)
        # Sequence heuristic: תשובה after קשיא almost always means תירוץ.
        if prev_label == "קשיא" and s.get("hebrewStepName") == "תשובה":
            issues.append("SEQUENCE: 'תשובה' immediately after 'קשיא' — almost always תירוץ")
        # Sequence: שאלה after קשיא without an intervening תירוץ is suspicious.
        if prev_label == "קשיא" and s.get("hebrewStepName") == "שאלה":
            issues.append("SEQUENCE: 'שאלה' immediately after 'קשיא' without resolution — usually a follow-up קשיא")
        if issues:
            flagged += 1
            title = (s.get("title") or "")[:60]
            output.append(f"  step {s['stepNumber']} [{s['hebrewStepName']}] {title}")
            for i in issues:
                output.append(f"     · {i}")
        prev_label = s.get("hebrewStepName")
    return len(steps), flagged, output


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "Bava_Metzia_*.json"
    files = sorted(DATA_DIR.glob(pattern))
    files = [
        f for f in files
        if re.match(r"^[A-Za-z_]+_\d+[ab]\.json$", f.name)
    ]
    if not files:
        print("no files matched")
        return 0
    total_steps = 0
    total_flagged = 0
    per_file: list[tuple[Path, int, int, list[str]]] = []
    for f in files:
        n, flagged, lines = audit_amud(f)
        total_steps += n
        total_flagged += flagged
        per_file.append((f, n, flagged, lines))
    # Sort worst-first.
    per_file.sort(key=lambda t: -t[2])
    for f, n, flagged, lines in per_file:
        pct = (flagged / n * 100) if n else 0
        if flagged == 0:
            continue
        print(f"\n=== {f.name}: {flagged}/{n} flagged ({pct:.0f}%) ===")
        for ln in lines:
            print(ln)
    print()
    print(f"OVERALL: {total_flagged}/{total_steps} steps flagged ({total_flagged/total_steps*100:.1f}%) across {len(files)} amudim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
