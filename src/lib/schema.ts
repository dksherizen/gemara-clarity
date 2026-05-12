import { z } from "zod";

export const HEBREW_STEP_NAMES = [
  "מימרא",
  "קשיא",
  "תירוץ",
  "ראיה",
  "דחיה",
  "שאלה",
  "תשובה",
  "מסקנא",
] as const;

export type HebrewStepName = (typeof HEBREW_STEP_NAMES)[number];

export const STEP_ENGLISH: Record<HebrewStepName, string> = {
  מימרא: "Statement",
  קשיא: "Challenge",
  תירוץ: "Resolution",
  ראיה: "Proof",
  דחיה: "Rejection",
  שאלה: "Question",
  תשובה: "Response",
  מסקנא: "Conclusion",
};

export const MACRO_PHASES = [
  "mishnah",
  "opening_question",
  "source_derivation",
  "objection_defense_cycle",
  "alternate_branch",
  "clarification_of_terms",
  "narrative_aggadah",
  "conclusion",
] as const;

export const BRANCH_ROLES = [
  "continues_current_line",
  "opens_new_branch",
  "returns_to_previous_branch",
  "alternative_approach",
  "conclusion_of_branch",
] as const;

export const SCOPE_OF_STEP = [
  "wording",
  "case_definition",
  "legal_rule",
  "proof_mechanism",
  "source_reading",
  "inference",
  "exception_case",
  "general_logic",
] as const;

export const PhraseSchema = z.object({
  phraseNumber: z.number().int(),
  aramaic: z.string(),
  english: z.string(),
  notes: z.string().optional(),
});
export type Phrase = z.infer<typeof PhraseSchema>;

export const KeyTermSchema = z.object({
  term: z.string(),
  meaning: z.string(),
});
export type KeyTerm = z.infer<typeof KeyTermSchema>;

export const MeforeshCommentSchema = z.object({
  source: z.string(),
  ref: z.string(),
  hebrew: z.string(),
  english: z.string().optional(),
  takeaway: z.string(),
});
export type MeforeshComment = z.infer<typeof MeforeshCommentSchema>;

export const MeforshimBlockSchema = z.object({
  rashi: z.array(MeforeshCommentSchema).default([]),
  tosafot: z.array(MeforeshCommentSchema).default([]),
  rishonim: z.array(MeforeshCommentSchema).default([]),
  acharonim: z.array(MeforeshCommentSchema).default([]),
  interplaySummary: z.string().optional(),
});
export type MeforshimBlock = z.infer<typeof MeforshimBlockSchema>;

export const StepSchema = z.object({
  stepNumber: z.number().int(),
  hebrewStepName: z.enum(HEBREW_STEP_NAMES),
  title: z.string(),
  stepSummary: z.string(),
  simpleTranslation: z.string().optional(),
  whatsHappening: z.string(),
  deeperAnalysis: z.string(),
  keyTerms: z.array(KeyTermSchema),
  whatToRemember: z.string().optional(),
  confusionAlert: z.string().optional(),
  whyThisMatters: z.string().optional(),
  phrases: z.array(PhraseSchema).min(1),
  classificationConfidence: z.enum(["High", "Medium", "Low"]).default("High"),
  alternativePossibleLabel: z.string().optional(),
  triggerLanguage: z.string().optional(),
  macroPhase: z.enum(MACRO_PHASES).optional(),
  branchRole: z.enum(BRANCH_ROLES).optional(),
  dependsOnStepNumbers: z.array(z.number().int()).default([]),
  scopeOfStep: z.enum(SCOPE_OF_STEP).optional(),
  relationToPreviousStep: z.string().optional(),
  kashyaTarget: z.string().optional(),
  kashyaAttackLogic: z.string().optional(),
  terutzResolutionType: z.string().optional(),
  terutzHavaAmina: z.string().optional(),
  terutzMaskana: z.string().optional(),
  sheelahInformationSought: z.string().optional(),
  teshuvahAnswerProvided: z.string().optional(),
  raayaObject: z.string().optional(),
  raayaSupportSource: z.string().optional(),
  dechiyaRejectionScope: z.string().optional(),
  dechiyaFlawIdentified: z.string().optional(),
  mimraCoreRuling: z.string().optional(),
  maskanaFinalTakeaway: z.string().optional(),
  meforshim: MeforshimBlockSchema.optional(),
});
export type Step = z.infer<typeof StepSchema>;

export const SugyaBoundarySchema = z.object({
  sugyaNumber: z.number().int(),
  startLine: z.number().int(),
  endLine: z.number().int(),
  topic: z.string(),
  gist: z.string(),
  openingFormula: z.string().optional(),
  firstStepNumber: z.number().int().optional(),
  lastStepNumber: z.number().int().optional(),
});
export type SugyaBoundary = z.infer<typeof SugyaBoundarySchema>;

export const CostBreakdownSchema = z.object({
  totalUSD: z.number(),
  totalInputTokens: z.number(),
  totalOutputTokens: z.number(),
  byPass: z.record(z.number()),
});

export const DafAnalysisSchema = z.object({
  ref: z.string(),
  masechet: z.string(),
  daf: z.number().int(),
  amud: z.enum(["a", "b"]),
  mainTopic: z.string(),
  overview: z.string(),
  sugyaBoundaries: z.array(SugyaBoundarySchema),
  steps: z.array(StepSchema),
  pipelineVersion: z.string(),
  generatedAt: z.string(),
  modelsUsed: z.record(z.string()),
  cost: CostBreakdownSchema.optional(),
});
export type DafAnalysis = z.infer<typeof DafAnalysisSchema>;

export interface DafSourceText {
  ref: string;
  masechet: string;
  daf: number;
  amud: "a" | "b";
  hebrew: string[];
  english: string[];
}
