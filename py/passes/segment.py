"""Pass 1: split the amud into natural sugyot. Local LM (gpt-oss-120b).
Prompt is a near-verbatim port of v2/src/lib/pipeline/1-segmentation.ts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import LMStudioClient
from schema import SugyaBoundary
from sefaria import DafSource

SYSTEM = """You are an expert in classical Talmudic structure. Given the FULL Hebrew/Aramaic text of one amud of Gemara, your job is to:

1. Identify the main topic of the amud in plain English.
2. Write a 2-3 sentence overview describing the flow of the amud.
3. Segment the amud into its natural sugyot (discrete topical/argumentative units).

A "sugya" is a self-contained argumentative or topical unit. Do NOT cut by arbitrary line count. A sugya may be:
- A Mishnah + its accompanying Gemara analysis (treat as one sugya)
- A single discussion launched by an opening question (e.g. תנו רבנן, איתמר, איבעיא להו, מנא הני מילי) and ending when the discussion clearly concludes or pivots to a new topic
- A perek transition (Hadran + new perek opening) is the END of one sugya and START of another — never combined

For each sugya, return:
- sugyaNumber: 1-indexed
- startLine: the 1-indexed line number (from the input) where the sugya BEGINS
- endLine: the 1-indexed line number where the sugya ENDS (inclusive)
- topic: a short HEBREW phrase (under 10 words) naming the sugya. Hebrew script, real Talmudic terminology. Examples: "מציאה ברשות הרבים", "השוואת מציאה למקח וממכר", "דין שבועה במחלוקת על בעלות". Do NOT translate to English. Do NOT transliterate.
- gist: a one-sentence Hebrew description of what is debated/established. Hebrew script throughout.
- openingFormula: the literal Aramaic words that open the sugya (e.g. "תנו רבנן", "אמר רבי יוחנן", "תנן התם"), or null

Coverage requirements:
- Every input line MUST belong to exactly one sugya. No line may be skipped, no line may belong to two sugyot.
- The first sugya MUST start at line 1. The last sugya MUST end at the final line.
- Sugyot must be contiguous: sugya N+1 starts at sugya N's endLine + 1.

CRITICAL — NO TRANSLITERATION:
In mainTopic, overview, topic, gist, openingFormula — write all Hebrew/Aramaic technical terms, sage names, masechtot, and concept names in HEBREW SCRIPT, never Latin letters.

CORRECT:  "Disputes over מציאה and the role of שבועה in resolving them."
WRONG:    "Disputes over Metzi'ah / Mitzkayah and the role of Shevuah..."

Required Hebrew script: מציאה, קניין, שבועה, הלכה, משנה, גמרא, מקח וממכר, חזקה, רבי + names, etc.

Return ONLY valid JSON matching the schema. No commentary, no markdown."""


class SegmentResult(BaseModel):
    mainTopic: str
    overview: str
    sugyot: list[SugyaBoundary] = Field(default_factory=list)


def _user_prompt(daf: DafSource) -> str:
    numbered = "\n".join(f"[{i+1}] {line}" for i, line in enumerate(daf.hebrew))
    return (
        f"Daf reference: {daf.ref}\n\n"
        f"Source text (numbered lines):\n{numbered}\n\n"
        "Segment this amud into its natural sugyot following the rules above."
    )


def _validate_coverage(
    sugyot: list[SugyaBoundary], total_lines: int
) -> list[SugyaBoundary]:
    if not sugyot:
        return [
            SugyaBoundary(
                sugyaNumber=1,
                startLine=1,
                endLine=total_lines,
                topic="Full amud",
                gist="Segmentation produced no sugyot; treating whole amud as one.",
            )
        ]
    sorted_s = sorted(sugyot, key=lambda s: s.startLine)
    repaired: list[SugyaBoundary] = []
    expected_start = 1
    for i, s in enumerate(sorted_s):
        start = max(expected_start, s.startLine)
        end = min(total_lines, s.endLine)
        if i == len(sorted_s) - 1:
            end = total_lines
        if end < start:
            end = start
        repaired.append(s.model_copy(update={"sugyaNumber": i + 1, "startLine": start, "endLine": end}))
        expected_start = end + 1
    if repaired and repaired[-1].endLine < total_lines:
        repaired[-1] = repaired[-1].model_copy(update={"endLine": total_lines})
    return repaired


def segment_amud(client: LMStudioClient, daf: DafSource) -> SegmentResult:
    raw = client.call_json(
        pass_name="segmentation",
        system=SYSTEM,
        user=_user_prompt(daf),
        response_model=SegmentResult,
        max_tokens=16000,
    )
    n_lines = len(daf.hebrew)
    # Big windows that come back with a single sugya are almost always
    # under-segmented. Retry with an explicit checklist of sugya-opener formulae.
    if len(raw.sugyot) < 2 and n_lines >= 40:
        print(
            f"[segment] only {len(raw.sugyot)} sugyot for {n_lines} lines — "
            "retrying with explicit opener-formula checklist",
            flush=True,
        )
        retry_system = SYSTEM + """

EMERGENCY OVERRIDE: the previous attempt returned only ONE sugya for a multi-amud input. That is wrong. There is essentially ALWAYS a new sugya at each of these opener formulae:
- "תנו רבנן" / "ת״ר"  → new sugya
- "אמר רב" / "אמר רבי" / "איתמר" / "אמר ר׳ X משום ר׳ Y" (a new attributed statement)  → new sugya
- "תנן" / "תנן התם"  → new sugya
- "בעי X" / "איבעיא להו" / "בעא מיניה"  → new sugya
- "מתיב X" / "תא שמע" introducing a NEW objection/source  → new sugya
- Any major topical pivot (e.g. shifting from שבועה to קניין to מקח וממכר)  → new sugya
You MUST scan the entire input for these markers and emit one sugya per discrete discussion. A 5-amud window should produce 4-10 sugyot."""
        try:
            retry = client.call_json(
                pass_name="segmentation",
                system=retry_system,
                user=_user_prompt(daf)
                + f"\n\nThe input has {n_lines} lines. You MUST produce multiple sugyot — minimum 3. Scan every line for the opener formulae listed in the system prompt.",
                response_model=SegmentResult,
                max_tokens=16000,
            )
            if len(retry.sugyot) > len(raw.sugyot):
                raw = retry
                print(f"[segment] retry succeeded: {len(retry.sugyot)} sugyot", flush=True)
        except Exception as e:
            print(f"[segment] retry failed, keeping original: {e}", flush=True)
    raw.sugyot = _validate_coverage(raw.sugyot, n_lines)
    return raw


__all__ = ["segment_amud", "SegmentResult"]
