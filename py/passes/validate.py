"""Pass 6: cross-model re-read. Smaller local LM (qwen3.6-27b) audits the larger
model's output. Issues are written to a sidecar JSON next to the daf output, so
nothing gets lost — this fixes the bug we hit in the TS pipeline where the
orchestrator only logged the issue counts and dropped the details."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from llm import LMStudioClient
from schema import DafAnalysis, Step
from sefaria import DafSource

IssueKind = Literal[
    "wrong_classification",
    "missing_coverage",
    "broken_dependency",
    "hallucinated_meforesh",
    "redundant_step",
    "missing_step_split",
    "phrasing_too_long",
    "phrasing_too_vague",
    "missing_nikud",
    "other",
]

Severity = Literal["critical", "warning", "nit"]
Assessment = Literal["excellent", "good", "needs_work", "poor"]


class Issue(BaseModel):
    kind: IssueKind
    stepNumber: int | None = None
    severity: Severity
    description: str
    suggestedField: str | None = None
    suggestedValue: str | None = None


class Review(BaseModel):
    overallAssessment: Assessment
    summary: str = ""
    issues: list[Issue] = Field(default_factory=list)


SYSTEM = """You are a senior Talmud editor performing a final review of an AI-generated teaching sheet. You will receive:
1. The full source text of the daf (numbered lines).
2. The structured analysis: sugya boundaries, steps with classifications, meforshim summaries.

Audit the analysis against the source. Look for:
- wrong_classification: a step labeled מימרא that is actually a קשיא, a שאלה mislabeled as קשיא, etc. Judge by argumentative function in context, not surface grammar.
- missing_coverage: source lines that don't appear in any step's phrases (gaps in the daf).
- broken_dependency: a תירוץ that doesn't actually resolve the קשיא it claims to depend on; a דחיה that doesn't actually attack the cited ראיה.
- hallucinated_meforesh: a meforshim takeaway that contradicts or misrepresents what the verbatim Hebrew text of that meforesh actually says.
- redundant_step: two adjacent steps that say the same thing.
- missing_step_split: one step that bundles a קשיא + תירוץ that should be split into two.
- phrasing_too_long / phrasing_too_vague: whatsHappening over 2 sentences, deeperAnalysis over 3 sentences, or vague filler instead of substantive analysis.
- missing_nikud: keyTerms without vowels.

Be conservative — don't flag stylistic preferences. Flag REAL substantive problems. If the analysis is solid, return zero issues and overallAssessment: "excellent".

For each issue, set severity:
- critical: factual error or wrong classification that would mislead a learner
- warning: clearly suboptimal but not factually wrong
- nit: cosmetic / preference

Optionally suggest a fix via suggestedField + suggestedValue. Return strict JSON."""


def _slim(step: Step) -> dict:
    return {
        "stepNumber": step.stepNumber,
        "hebrewStepName": step.hebrewStepName,
        "title": step.title,
        "whatsHappening": step.whatsHappening,
        "deeperAnalysis": step.deeperAnalysis,
        "keyTerms": [k.term for k in step.keyTerms],
        "classificationConfidence": step.classificationConfidence,
        "dependsOnStepNumbers": step.dependsOnStepNumbers,
        "kashyaTarget": step.kashyaTarget,
        "terutzResolutionType": step.terutzResolutionType,
        "phrasesAramaic": " ".join(p.aramaic for p in step.phrases),
        "meforshim": {
            "rashi": [
                {"takeaway": c.takeaway, "verbatim": c.hebrew[:600]} for c in step.meforshim.rashi
            ],
            "tosafot": [
                {"takeaway": c.takeaway, "verbatim": c.hebrew[:600]} for c in step.meforshim.tosafot
            ],
        } if step.meforshim else None,
    }


def _user_prompt(daf: DafSource, analysis: DafAnalysis) -> str:
    import json

    numbered = "\n".join(f"[{i+1}] {line}" for i, line in enumerate(daf.hebrew))
    slim_analysis = {
        "mainTopic": analysis.mainTopic,
        "overview": analysis.overview,
        "sugyaBoundaries": [s.model_dump() for s in analysis.sugyaBoundaries],
        "steps": [_slim(s) for s in analysis.steps],
    }
    return (
        f"Daf reference: {daf.ref}\n\n"
        f"Source text (numbered lines):\n{numbered}\n\n"
        f"Analysis to review:\n{json.dumps(slim_analysis, ensure_ascii=False, indent=2)}\n\n"
        "Perform the audit per the rules."
    )


def review_analysis(
    client: LMStudioClient,
    daf: DafSource,
    analysis: DafAnalysis,
) -> Review:
    return client.call_json(
        pass_name="validate",
        system=SYSTEM,
        user=_user_prompt(daf, analysis),
        response_model=Review,
        max_tokens=8000,
    )


__all__ = ["review_analysis", "Review", "Issue"]
