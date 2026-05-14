"""Post-batch fix-up: rewrite step titles that contain transliterations.

Scans each step's title for Latin-letter Talmudic terms (Kal V'chomer, Bava
Metzia, Rabbi Yochanan, etc.) and asks the LM to rewrite with Hebrew script
where appropriate.

Local-only (Qwen via LMStudioClient)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from llm import LMStudioClient

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

# Patterns that probably indicate a transliterated technical term.
# (not a complete list, but heuristic enough to trigger review)
TRANSLITERATION_HINTS = re.compile(
    r"\b("
    r"Kal V'chomer|Mishnah|Mishna|Gemara|Beraita|Tannaim|Amoraim|"
    r"Rashi|Tosafot|Tosafos|Ramban|Rashba|Ritva|"
    r"Rav |Rabbi |Reb |Bar |R\. |R'|"
    r"Bava (Metzia|Kamma|Basra|Batra)|Shabbat|Berakhot|"
    r"Mitzkayah|Metzi'ah|Metziah|Shevuah|Shvua|Kinyan|Chazakah|"
    r"Kashya|Terutz|Sheelah|Teshuvah|Raaya|Dechiya|Mimra|Maskana|Mimrah|"
    r"Sumakhos|Ben Nannas|Rabbenai|Rabbanan|Rabbeinu|"
    r"Hodaa|Talmud|Halacha|Mafkid|HaZahav"
    r")\b",
    re.IGNORECASE,
)


class TitleFix(BaseModel):
    rewritten_title: str


SYSTEM = """You are rewriting English step titles for a Talmud teaching sheet so all Hebrew/Aramaic technical terms appear in Hebrew script (with vowels where appropriate), never as Latin transliterations.

Rules:
1. Keep the title CONCISE (under 10 words ideally).
2. Replace transliterations with the Hebrew script: "Kal V'chomer" → "קַל וָחוֹמֶר", "Rabbi Yochanan" → "רַבִּי יוֹחָנָן", "Bava Metzia" → "בבא מציעא".
3. Keep ordinary English connectives ("the", "of", "and", "from") as English.
4. Keep titles descriptive; preserve the title's meaning.
5. If the original title has no transliterations, return it unchanged.

Examples:
- "What is the Kal V'chomer?" → "What is the קַל וָחוֹמֶר?"
- "Challenge from Ben Nannas" → "Challenge from בֶּן נַנָּס"
- "Rashi explains the Gemara's case" → "רש״י explains the גמרא's case"
- "The Mishnah's ruling on disputed garments" → "The משנה's ruling on disputed garments"

Return JSON: { rewritten_title: "..." }."""


def needs_fix(title: str) -> bool:
    if not title:
        return False
    return bool(TRANSLITERATION_HINTS.search(title))


def fix_amud(client: LMStudioClient, path: Path, dry_run: bool = False) -> tuple[int, int, list[str]]:
    d = json.loads(path.read_text(encoding="utf-8"))
    steps = d.get("steps") or []
    if not steps:
        return 0, 0, []
    n_changed = 0
    log: list[str] = []
    for step in steps:
        title = step.get("title", "")
        if not needs_fix(title):
            continue
        try:
            result = client.call_json(
                pass_name="teaching",
                system=SYSTEM,
                user=f"Original title: {title}\n\nRewrite with Hebrew script for technical terms.",
                response_model=TitleFix,
                max_tokens=500,
            )
        except Exception as e:
            log.append(f"  step {step['stepNumber']}: title-fix error: {e}")
            continue
        new_title = result.rewritten_title.strip()
        if new_title and new_title != title:
            step["title"] = new_title
            n_changed += 1
            log.append(f"  step {step['stepNumber']}: {title!r} → {new_title!r}")
    if n_changed and not dry_run:
        d["steps"] = steps
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(steps), n_changed, log


def main() -> int:
    import argparse, sys
    p = argparse.ArgumentParser()
    p.add_argument("pattern", nargs="?", default="Bava_Metzia_*.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    files = sorted(
        f for f in DATA_DIR.glob(args.pattern)
        if re.match(r"^[A-Za-z_]+_\d+[ab]\.json$", f.name)
    )
    total = changed = 0
    with LMStudioClient() as client:
        for f in files:
            n, c, log = fix_amud(client, f, dry_run=args.dry_run)
            total += n
            changed += c
            if c:
                print(f"\n=== {f.name}: {c}/{n} titles fixed ===")
                for ln in log:
                    print(ln)
    print(f"\nTotal: {changed}/{total} titles fixed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
