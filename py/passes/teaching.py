"""Pass 5: polish the teaching layer — tighten prose, dedupe key terms, prune
fluff fields. Local LM (gpt-oss-120b)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import LMStudioClient
from schema import KeyTerm, Step

SYSTEM = """You are polishing the teaching layer of an existing Gemara analysis. You will receive an array of steps; for each, return a tightened version that follows these strict rules:

1. whatsHappening: STRICT MAX 2 plain-English sentences. State exactly what the Gemara is doing right now. If it's a setup/transition line, say so explicitly. No vague paraphrasing.
2. deeperAnalysis: STRICT MAX 3 short sentences. Explain the logic clearly. State exactly what changed, what is being challenged, or what new information is added.
3. keyTerms: keep only NEW or uniquely important terms for this step. Aim for 3-6 terms per step. NEVER repeat terms that appeared in earlier steps (the prior batch's terms are listed below).

   MANDATORY: Every Hebrew/Aramaic keyTerm must have FULL NIKUD (vowels) on every letter that takes one. This is non-negotiable.
   CORRECT: "שְׁנַיִם", "קַל וָחוֹמֶר", "מָמוֹן", "מִקַּח וּמִמְכָּר", "רַבִּי יוֹחָנָן", "הַמּוֹצִיא מֵחֲבֵירוֹ".
   WRONG:   "שנים", "קל וחומר", "ממון", "מקח וממכר", "רבי יוחנן" — any bare unpointed Hebrew is a failure.
   The "meaning" field stays in English (translation of the term).
4. whatToRemember: KEEP only if it captures a genuine takeaway from a major section conclusion. Otherwise leave null. Never put filler here.
5. confusionAlert: KEEP only if there is a real, classic trap a beginner would fall into. Otherwise null. Be hyper-conservative.
6. whyThisMatters: KEEP only if there is genuine lasting halachic or conceptual significance. Otherwise null.
7. title: clean English phrase. NO tags like "ALT", "Alternative", קשיא, דחיה in the title. APPLY THE SAME NO-TRANSLITERATION RULE TO TITLES: write "What is the קַל וָחוֹמֶר?" not "What is the Kal V'chomer?"; write "Challenge from בֶּן נַנָּס" not "Challenge from Ben Nannas".

CRITICAL — NO TRANSLITERATION:
Write all Talmudic/halachic technical terms, sage names, masechtot, and concept names in HEBREW SCRIPT, never Latin letters.
CORRECT: "The רש״י's reading of מציאה implies a שבועה is needed."
WRONG:   "The Rashi's reading of Metziah implies a Shevuah is needed."
Required Hebrew script: מציאה, קניין, שבועה, הלכה, משנה, גמרא, רש״י, תוספות, רב/רבי + names, מקח וממכר, חזקה, etc. Any Hebrew/Aramaic term in Latin letters is a failure.

Return strict JSON matching the schema."""


class PolishedStep(BaseModel):
    stepNumber: int
    title: str
    whatsHappening: str
    deeperAnalysis: str
    keyTerms: list[KeyTerm]
    whatToRemember: str | None = None
    confusionAlert: str | None = None
    whyThisMatters: str | None = None


class PolishResponse(BaseModel):
    steps: list[PolishedStep] = Field(default_factory=list)


def _compact(step: Step) -> dict:
    return {
        "stepNumber": step.stepNumber,
        "hebrewStepName": step.hebrewStepName,
        "title": step.title,
        "whatsHappening": step.whatsHappening,
        "deeperAnalysis": step.deeperAnalysis,
        "keyTerms": [{"term": k.term, "meaning": k.meaning} for k in step.keyTerms],
        "whatToRemember": step.whatToRemember,
        "confusionAlert": step.confusionAlert,
        "whyThisMatters": step.whyThisMatters,
    }


def _nonempty(s: str | None) -> str | None:
    if not s:
        return None
    t = s.strip()
    if not t:
        return None
    if t.lower() in {"n/a", "na", "none", "skip"}:
        return None
    return t


def polish_steps(
    client: LMStudioClient,
    steps: list[Step],
    batch_size: int = 8,
) -> list[Step]:
    if not steps:
        return steps
    polished: list[Step] = []
    for i in range(0, len(steps), batch_size):
        batch = steps[i : i + batch_size]
        import json

        prior_terms = [t.term for s in polished for t in s.keyTerms][-40:]
        user = (
            "Steps already polished (do NOT repeat their keyTerms):\n"
            + (", ".join(prior_terms) if prior_terms else "(none yet — first batch)")
            + "\n\nSteps to polish in this batch:\n"
            + json.dumps([_compact(s) for s in batch], ensure_ascii=False, indent=2)
        )
        try:
            parsed = client.call_json(
                pass_name="teaching",
                system=SYSTEM,
                user=user,
                response_model=PolishResponse,
                max_tokens=16000,
            )
        except Exception as e:
            print(f"[teaching] batch starting at step {batch[0].stepNumber} failed: {e}")
            polished.extend(batch)
            continue
        by_num = {p.stepNumber: p for p in parsed.steps}
        for original in batch:
            p = by_num.get(original.stepNumber)
            if not p:
                polished.append(original)
                continue
            polished.append(
                original.model_copy(
                    update={
                        "title": p.title or original.title,
                        "whatsHappening": p.whatsHappening or original.whatsHappening,
                        "deeperAnalysis": p.deeperAnalysis or original.deeperAnalysis,
                        "keyTerms": p.keyTerms or original.keyTerms,
                        "whatToRemember": _nonempty(p.whatToRemember),
                        "confusionAlert": _nonempty(p.confusionAlert),
                        "whyThisMatters": _nonempty(p.whyThisMatters),
                    }
                )
            )
    return polished


__all__ = ["polish_steps"]
