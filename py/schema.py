"""Pydantic mirror of v2/src/lib/schema.ts. The JSON output of build.py must match
the TS-side Zod schema byte-for-byte so the frontend renders unchanged."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HEBREW_STEP_NAMES = (
    "מימרא",
    "קשיא",
    "תירוץ",
    "ראיה",
    "דחיה",
    "שאלה",
    "תשובה",
    "מסקנא",
)

HebrewStepName = Literal[
    "מימרא", "קשיא", "תירוץ", "ראיה", "דחיה", "שאלה", "תשובה", "מסקנא"
]

STEP_ENGLISH: dict[str, str] = {
    "מימרא": "Statement",
    "קשיא": "Challenge",
    "תירוץ": "Resolution",
    "ראיה": "Proof",
    "דחיה": "Rejection",
    "שאלה": "Question",
    "תשובה": "Response",
    "מסקנא": "Conclusion",
}

MacroPhase = Literal[
    "mishnah",
    "opening_question",
    "source_derivation",
    "objection_defense_cycle",
    "alternate_branch",
    "clarification_of_terms",
    "narrative_aggadah",
    "conclusion",
]

BranchRole = Literal[
    "continues_current_line",
    "opens_new_branch",
    "returns_to_previous_branch",
    "alternative_approach",
    "conclusion_of_branch",
]

ScopeOfStep = Literal[
    "wording",
    "case_definition",
    "legal_rule",
    "proof_mechanism",
    "source_reading",
    "inference",
    "exception_case",
    "general_logic",
]

Confidence = Literal["High", "Medium", "Low"]


class Phrase(BaseModel):
    phraseNumber: int
    aramaic: str
    english: str
    notes: str | None = None


class KeyTerm(BaseModel):
    term: str
    meaning: str


class MeforeshComment(BaseModel):
    source: str
    ref: str
    hebrew: str
    english: str | None = None
    takeaway: str
    # Phrase-aligned Hebrew/English for the verbatim meforesh body (optional).
    phrases: list[Phrase] | None = None


class MeforshimBlock(BaseModel):
    rashi: list[MeforeshComment] = Field(default_factory=list)
    tosafot: list[MeforeshComment] = Field(default_factory=list)
    rishonim: list[MeforeshComment] = Field(default_factory=list)
    acharonim: list[MeforeshComment] = Field(default_factory=list)
    interplaySummary: str | None = None


class Step(BaseModel):
    stepNumber: int
    hebrewStepName: HebrewStepName
    title: str
    stepSummary: str
    simpleTranslation: str | None = None
    whatsHappening: str
    deeperAnalysis: str
    keyTerms: list[KeyTerm]
    whatToRemember: str | None = None
    confusionAlert: str | None = None
    whyThisMatters: str | None = None
    phrases: list[Phrase] = Field(default_factory=list)
    classificationConfidence: Confidence = "High"
    alternativePossibleLabel: str | None = None
    triggerLanguage: str | None = None
    macroPhase: MacroPhase | None = None
    branchRole: BranchRole | None = None
    dependsOnStepNumbers: list[int] = Field(default_factory=list)
    scopeOfStep: ScopeOfStep | None = None
    relationToPreviousStep: str | None = None
    kashyaTarget: str | None = None
    kashyaAttackLogic: str | None = None
    terutzResolutionType: str | None = None
    terutzHavaAmina: str | None = None
    terutzMaskana: str | None = None
    sheelahInformationSought: str | None = None
    teshuvahAnswerProvided: str | None = None
    raayaObject: str | None = None
    raayaSupportSource: str | None = None
    dechiyaRejectionScope: str | None = None
    dechiyaFlawIdentified: str | None = None
    mimraCoreRuling: str | None = None
    maskanaFinalTakeaway: str | None = None
    meforshim: MeforshimBlock | None = None


class SugyaBoundary(BaseModel):
    sugyaNumber: int
    startLine: int
    endLine: int
    topic: str
    gist: str
    openingFormula: str | None = None
    firstStepNumber: int | None = None
    lastStepNumber: int | None = None


class CostBreakdown(BaseModel):
    totalUSD: float = 0.0
    totalInputTokens: int = 0
    totalOutputTokens: int = 0
    byPass: dict[str, float] = Field(default_factory=dict)


class DafAnalysis(BaseModel):
    ref: str
    masechet: str
    daf: int
    amud: Literal["a", "b"]
    mainTopic: str
    overview: str
    sugyaBoundaries: list[SugyaBoundary]
    steps: list[Step]
    pipelineVersion: str
    generatedAt: str
    modelsUsed: dict[str, str]
    cost: CostBreakdown | None = None


class DafSourceText(BaseModel):
    ref: str
    masechet: str
    daf: int
    amud: Literal["a", "b"]
    hebrew: list[str]
    english: list[str]
