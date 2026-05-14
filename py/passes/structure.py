"""Pass 2: decompose each sugya into argumentative steps. Local LM (gpt-oss-120b).
Verbatim port of v2/src/lib/pipeline/2-structure.ts prompt. The strict json_schema
mode eliminates all the LooseHebrewStepName / LooseSeverity coercion machinery — if
the model returns a value outside the enum, LM Studio rejects it server-side."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import LMStudioClient
from schema import (
    BranchRole,
    Confidence,
    HebrewStepName,
    KeyTerm,
    MacroPhase,
    ScopeOfStep,
    Step,
    SugyaBoundary,
)
from sefaria import DafSource

SYSTEM = """You are an expert chavrusa breaking down a single sugya of Gemara into discrete argumentative steps. Input: the Aramaic/Hebrew of one sugya plus a reference English translation. Output: strict JSON matching the schema.

# STEP TYPES (assign exactly one to hebrewStepName)

- מימרא — freestanding statement, ruling, or attributed teaching.
- קשיא — challenge / objection ATTACKING an earlier statement.
- תירוץ — resolution of a קשיא, typically exposing a הוה אמינא → מסקנא.
- ראיה — proof or supporting source.
- דחיה — rejection of a proof or earlier line of reasoning.
- שאלה — neutral REQUEST for information (NOT an objection).
- תשובה — answer to a שאלה (NOT a תירוץ to a קשיא).
- מסקנא — final conclusion or summary.

# CLASSIFICATION — function over form

Classify by argumentative FUNCTION, not surface grammar.

- קשיא vs שאלה: if the Gemara is pressuring / attacking earlier text → קשיא. Only neutral information requests are שאלה. Mislabeling a קשיא as שאלה makes the learner miss the pressure.
- תירוץ vs תשובה: if a difficulty was being defended against → תירוץ. תשובה is only for neutral שאלה. תירוץ ≠ תשובה.
- Attribution-only lines ("אמר רבי X משום רבי Y") fold into the step they introduce — they're not their own steps.
- A Hadran is a מסקנא; the first line of a new perek is a fresh מימרא.

## Canonical patterns (memorize)

These map opener-phrases → label deterministically:

| Aramaic pattern | Label | Why |
|---|---|---|
| "למה לי למיתנא X" / "ליתני חדא" / "וליתני X" | קשיא | Redundancy attack on prior wording. |
| "אי תנא X, הוה אמינא…" | תירוץ | Defends wording against redundancy: without X, you'd misread. |
| "תא שמע" / "תניא" / "תנן" introducing a source TO CHALLENGE | קשיא | The source is being weaponized. NOT a מימרא. (If introducing a source that SUPPORTS a claim, it's ראיה.) |
| "לא, דאמר ליה: …" / "לא, ב…" (rejects setup, offers different case) | תירוץ | Recasts the case to escape the difficulty. NOT a תשובה. |
| "ואידך: …" / "ואידך סבר…" (presents another sage's view) | מימרא | Declarative — states the OTHER opinion. |
| "היכי דמי? לאו ב…" (forces the case to a specific reading) | קשיא | Interrogative form, but function is pressing the source toward the difficulty. |
| "והא X קאמר!" / "ומי מצית אמרת…" | קשיא | Counter-attack on prior reasoning. |
| "וצריכא" / "וצריכי" alone | מימרא | Asserts both cases are needed; sets up the upcoming צריכותא. NEVER שאלה. If it directly precedes the explanation, fold into that step. |
| "אי אמרת בשלמא… אלא אי אמרת…" | usually דחיה | Forcing one reading by showing the alternative is impossible. |

## Worked example — בבא מציעא ב. (use as your reference for what good output looks like)

This is a real worked sugya. Study the shape: alternating קשיא→תירוץ pairs, each with full skeleton fields. Match this quality + brevity in your output.

```json
{
  "stepNumber": 5,
  "hebrewStepName": "קשיא",
  "title": "Why the doubled wording in the משנה?",
  "stepSummary": "The גמרא attacks the משנה's redundancy: 'I found it' + 'all is mine' seems excessive — one phrase should suffice.",
  "startLineInSugya": 1, "endLineInSugya": 1,
  "whatsHappening": "The גמרא opens with a redundancy attack on the משנה.",
  "deeperAnalysis": "The משנה teaches both 'אני מצאתיה' and 'כולה שלי' — but if either phrase alone communicates the case, the other is superfluous. The גמרא is pressing on the textual excess.",
  "keyTerms": [
    {"term": "מָצָא", "meaning": "found"},
    {"term": "מִשְׁנָה", "meaning": "the Tannaitic teaching being analyzed"},
    {"term": "לִתְנֵי חֲדָא", "meaning": "let it teach one — i.e., one phrase would suffice"}
  ],
  "triggerLanguage": "לָמָּה לִי לְמִתְנָא זֶה אוֹמֵר אֲנִי מְצָאתִיהָ...",
  "classificationConfidence": "High"
}
```

```json
{
  "stepNumber": 6,
  "hebrewStepName": "תירוץ",
  "title": "חֲדָא קָתָנֵי — read as one combined claim",
  "stepSummary": "The גמרא resolves the redundancy: read both phrases as a single combined assertion, not two separate claims.",
  "startLineInSugya": 2, "endLineInSugya": 2,
  "whatsHappening": "תירוץ resolving step 5's קשיא.",
  "deeperAnalysis": "The משנה's doubled language is one claim: 'I found it AND therefore all is mine.' The redundancy disappears once we read it as a single composite assertion.",
  "keyTerms": [{"term": "חֲדָא קָתָנֵי", "meaning": "it teaches one [combined claim]"}],
  "triggerLanguage": "חֲדָא קָתָנֵי",
  "classificationConfidence": "High",
  "dependsOnStepNumbers": [5]
}
```

```json
{
  "stepNumber": 11,
  "hebrewStepName": "תירוץ",
  "title": "רַב פָּפָּא: רֵישָׁא בִּמְצִיאָה וְסֵיפָא בְּמִקַּח וּמִמְכָּר",
  "stepSummary": "רַב פָּפָּא splits the משנה into two distinct cases: the first half is about מציאה, the second about purchase/sale.",
  "startLineInSugya": 8, "endLineInSugya": 9,
  "whatsHappening": "רַב פָּפָּא resolves the textual difficulty by redividing the משנה into two separate cases.",
  "deeperAnalysis": "Until now the גמרא tried to read both phrases as ONE claim. רַב פָּפָּא instead splits them: the first phrase ('אני מצאתיה') deals with a found item; the second ('כולה שלי') deals with a purchase dispute. Each phrase belongs to its own case, eliminating the redundancy without forcing one composite reading.",
  "keyTerms": [
    {"term": "רֵישָׁא", "meaning": "the opening clause [of the משנה]"},
    {"term": "סֵיפָא", "meaning": "the latter clause"},
    {"term": "מִקַּח וּמִמְכָּר", "meaning": "buying and selling"}
  ],
  "triggerLanguage": "אָמַר רַב פָּפָּא… רֵישָׁא בִּמְצִיאָה וְסֵיפָא בְּמִקַּח וּמִמְכָּר",
  "classificationConfidence": "High",
  "dependsOnStepNumbers": [10]
}
```

For reference, here is the full classification sequence on BM 2a (use this as your ground truth for the dialectic shape):
1. מימרא (Mishna line 1: two holding a tallit)
2. מימרא (Mishna line 2: 'all mine' vs 'half mine')
3. מימרא (Mishna line 3: disputed animal)
4. מימרא (Mishna line 4: admission/witnesses exception)
5. **קשיא** (redundancy attack on Mishna's double wording)
6. **תירוץ** (חדא קתני — combined claim)
7. **קשיא** (why not just אני מצאתיה?)
8. **תירוץ** (without כולה שלי, you'd think ראייה קני)
9. **קשיא** (Rabbenai: ומצאתה implies possession)
10. **תירוץ** (פסוק precise, משנה everyday language)
11. **קשיא** (why not just כולה שלי?)
12. **תירוץ** (extra wording teaches ראייה לא קני)
13. **קשיא** (חדא קתני attack: doubled זה אומר)
14. **תירוץ** (Rav Pappa: רישא במציאה, סיפא במקח וממכר)
15. **מימרא** (וצריכא — transition asserting both cases needed)

## Phrasing precision — don't change the subject

When stating what a teaching teaches, name the EXACT legal claim. The point of #4 above is NOT "מציאה is not קניינית" (changes the subject — of course a מציאה can be acquired). The actual point is "בראייה לא קני" — seeing alone doesn't acquire. Subject is ראייה, not מציאה.

# REQUIRED JSON FIELDS

- hebrewStepName — exactly one of: מימרא, קשיא, תירוץ, ראיה, דחיה, שאלה, תשובה, מסקנא.
- stepNumber — 1-indexed, continues across the daf (starting number given to you).
- startLineInSugya / endLineInSugya — integers, 1-indexed within THIS sugya.
- title — clean English summary phrase. NO tags like "ALT", "Alternative", or step names. Apply the no-transliteration rule (below) to titles too.
- stepSummary — one-sentence English summary.
- whatsHappening — 1-2 plain English sentences: what the Gemara is doing NOW. If it's a setup/transition, say so.
- deeperAnalysis — 2-3 sentences explaining the logic. State exactly what changed, what is being challenged, what new info is added.
- keyTerms — 3-6 Hebrew/Aramaic technical terms WITH FULL NIKUD on every letter that takes one. NEVER repeat terms that appeared in earlier steps. Formula words (מתניתין, גמרא) appear at most ONCE across the entire daf.
- triggerLanguage — the actual opening Aramaic words of this step, in full (no ellipsis).
- classificationConfidence — High / Medium / Low.
- alternativePossibleLabel — if confidence is Medium/Low, name the other plausible step type.
- macroPhase, branchRole, dependsOnStepNumbers, scopeOfStep, relationToPreviousStep — structural metadata.
- whatToRemember / confusionAlert — optional. Use ONLY when genuinely warranted. Most steps have neither.
- whyThisMatters — optional. Use ONLY for lasting halachic / conceptual significance.

# NO TRANSLITERATION — applies to every English field, including titles

Write all Talmudic/halachic technical terms, sage names, masechtot, and concept names in HEBREW SCRIPT. A Latin-letter Hebrew term anywhere in your output is a failure.

CORRECT: "The גמרא cites a מימרא from רבי יוחנן about מציאה and שבועה."
CORRECT title: "What is the קַל וָחוֹמֶר?", "Challenge from בֶּן נַנָּס".
WRONG: "The Gemara cites a Mimra from Rabbi Yochanan about Metziah and Shevuah."
WRONG: "Mitzkayah" (misspelled transliteration is even worse).
WRONG title: "What is the Kal V'chomer?", "Challenge from Ben Nannas".

Required Hebrew script for at minimum: מציאה, קניין, שבועה, הלכה, משנה, גמרא, מקח וממכר, חזקה, עדים זוממין, קל וחומר, גזרה שוה, בית דין, מתניתין, ברייתא, סוגיא, פסוק, דין; and רב/רבי/רבן + names.

Audience has yeshiva background and reads Hebrew natively.

# COVERAGE — these break the downstream pipeline if violated

- Every source line belongs to EXACTLY ONE step. No gaps. No overlaps.
- Adjacent steps must be contiguous: step N+1's startLineInSugya = step N's endLineInSugya + 1.
- First step's startLineInSugya = 1. Last step's endLineInSugya = the sugya's final line.

# GRANULARITY — split, don't bundle

- Each קשיא is its own step. Each תירוץ is its own step. NEVER bundle a קשיא with its תירוץ.
- Each ראיה and each דחיה is its own step.
- A new שאלה following a תירוץ is its own step.
- When in doubt, split. N distinct argumentative moves → N steps, not fewer.

# NO DUPLICATE STEPS

- NEVER emit two steps with identical (startLineInSugya, endLineInSugya). If a short transition word like "וּצְרִיכָא:" stands alone, fold it into a neighbor rather than emitting a single-phrase step.
- NEVER emit two consecutive steps where the second is just a relabel of the same Aramaic content. Pick one label.

Return strict JSON matching the schema."""


class StepSkeleton(BaseModel):
    stepNumber: int
    hebrewStepName: HebrewStepName
    title: str = ""
    stepSummary: str = ""
    startLineInSugya: int = 1
    endLineInSugya: int = 1
    whatsHappening: str = ""
    deeperAnalysis: str = ""
    whatToRemember: str | None = None
    confusionAlert: str | None = None
    whyThisMatters: str | None = None
    keyTerms: list[KeyTerm] = Field(default_factory=list)
    classificationConfidence: Confidence = "High"
    alternativePossibleLabel: str | None = None
    triggerLanguage: str | None = None
    macroPhase: MacroPhase | None = None
    branchRole: BranchRole | None = None
    dependsOnStepNumbers: list[int] = Field(default_factory=list)
    scopeOfStep: ScopeOfStep | None = None
    relationToPreviousStep: str | None = None
    # Conditional kashya/terutz/raaya/etc. subfields were removed from the LM
    # prompt — the hebrewStepName classification is sufficient. The full Step
    # type still has these fields available (defaulting to None); they're just
    # never asked of the model and so are excluded from JSON output via
    # exclude_none=True.


class StructureResponse(BaseModel):
    steps: list[StepSkeleton]


def _user_prompt(
    daf: DafSource,
    sugya: SugyaBoundary,
    next_step_number: int,
) -> str:
    hebrew = daf.hebrew[sugya.startLine - 1 : sugya.endLine]
    numbered_he = "\n".join(f"[{i+1}] {line}" for i, line in enumerate(hebrew))
    # English from Sefaria's Community Translation often has fewer (consolidated)
    # segments than the Hebrew, so we slice proportionally and present it as one
    # block rather than misleadingly numbered.
    if daf.english:
        if len(daf.english) == len(daf.hebrew):
            english_text = " ".join(daf.english[sugya.startLine - 1 : sugya.endLine])
        else:
            full_en = " ".join(daf.english)
            en_words = full_en.split()
            n_he_total = sum(len(h.split()) for h in daf.hebrew) or 1
            n_he_before = sum(len(h.split()) for h in daf.hebrew[: sugya.startLine - 1])
            n_he_in_sugya = sum(len(h.split()) for h in daf.hebrew[sugya.startLine - 1 : sugya.endLine])
            i0 = int(n_he_before / n_he_total * len(en_words))
            i1 = int((n_he_before + n_he_in_sugya) / n_he_total * len(en_words))
            english_text = " ".join(en_words[i0:i1])
    else:
        english_text = ""
    return f"""Sugya {sugya.sugyaNumber} from {daf.ref}
Topic: {sugya.topic}
Gist: {sugya.gist}
Opening formula: {sugya.openingFormula or "(none)"}
Starting step number for this sugya: {next_step_number}

Sugya source (numbered Hebrew/Aramaic lines):
{numbered_he}

Reference English (Sefaria Community Translation, for cross-checking only, not line-numbered):
{english_text}

Decompose this sugya into argumentative steps per the rules. Number steps starting at {next_step_number}."""


def structure_sugya(
    client: LMStudioClient,
    daf: DafSource,
    sugya: SugyaBoundary,
    next_step_number: int,
) -> list[StepSkeleton]:
    result = client.call_json(
        pass_name="structure",
        system=SYSTEM,
        user=_user_prompt(daf, sugya, next_step_number),
        response_model=StructureResponse,
        max_tokens=32000,
    )
    return result.steps


def skeleton_to_step(sk: StepSkeleton) -> Step:
    return Step(
        stepNumber=sk.stepNumber,
        hebrewStepName=sk.hebrewStepName,
        title=sk.title,
        stepSummary=sk.stepSummary,
        whatsHappening=sk.whatsHappening,
        deeperAnalysis=sk.deeperAnalysis,
        keyTerms=sk.keyTerms,
        whatToRemember=sk.whatToRemember,
        confusionAlert=sk.confusionAlert,
        whyThisMatters=sk.whyThisMatters,
        phrases=[],
        classificationConfidence=sk.classificationConfidence,
        alternativePossibleLabel=sk.alternativePossibleLabel,
        triggerLanguage=sk.triggerLanguage,
        macroPhase=sk.macroPhase,
        branchRole=sk.branchRole,
        dependsOnStepNumbers=sk.dependsOnStepNumbers,
        scopeOfStep=sk.scopeOfStep,
        relationToPreviousStep=sk.relationToPreviousStep,
        # The kashya*/terutz*/raaya*/dechiya*/sheelah*/teshuvah*/mimra*/maskana*
        # subfields stay defaulted to None on Step; we no longer ask the model
        # to populate them.
    )


__all__ = ["structure_sugya", "skeleton_to_step", "StepSkeleton"]
