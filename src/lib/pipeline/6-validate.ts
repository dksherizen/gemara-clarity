import { z } from "zod";
import type { LLMRouter } from "../llm/index.js";
import type { DafAnalysis, DafSourceText, Step } from "../schema.js";
import { HEBREW_STEP_NAMES } from "../schema.js";

const ISSUE_KINDS = [
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
] as const;
type IssueKind = (typeof ISSUE_KINDS)[number];

const LooseIssueKind = z
  .union([z.string(), z.null(), z.undefined()])
  .transform((v): IssueKind => {
    if (!v) return "other";
    const normalized = String(v).trim().toLowerCase().replace(/[\s-]+/g, "_");
    const match = ISSUE_KINDS.find((k) => k === normalized);
    return match ?? "other";
  });

const LooseSeverity = z
  .union([z.string(), z.null(), z.undefined()])
  .transform((v): "critical" | "warning" | "nit" => {
    if (!v) return "warning";
    const s = String(v).trim().toLowerCase();
    if (s.startsWith("crit")) return "critical";
    if (s.startsWith("nit") || s === "low" || s === "minor") return "nit";
    return "warning";
  });

const LooseHebrewStepName = z
  .union([z.string(), z.null(), z.undefined()])
  .transform((v) => {
    if (!v) return undefined;
    const s = String(v).trim();
    const direct = HEBREW_STEP_NAMES.find((n) => n === s);
    return direct;
  });

const SuggestedFixLoose = z
  .union([
    z.string(),
    z.null(),
    z.undefined(),
    z.object({
      field: z.string().nullable().optional(),
      newHebrewStepName: z.string().nullable().optional(),
      newValue: z.string().nullable().optional(),
      addStepAfter: z.number().int().nullable().optional(),
      mergeWithStep: z.number().int().nullable().optional(),
    }),
  ])
  .transform((v) => {
    if (!v) return undefined;
    if (typeof v === "string") return { newValue: v };
    return {
      field: v.field ?? undefined,
      newHebrewStepName:
        (HEBREW_STEP_NAMES.find((n) => n === v.newHebrewStepName) as
          | (typeof HEBREW_STEP_NAMES)[number]
          | undefined) ?? undefined,
      newValue: v.newValue ?? undefined,
      addStepAfter: v.addStepAfter ?? undefined,
      mergeWithStep: v.mergeWithStep ?? undefined,
    };
  });

const IssueSchema = z.object({
  kind: LooseIssueKind,
  stepNumber: z
    .union([z.number().int(), z.string(), z.null(), z.undefined()])
    .transform((v) => {
      if (typeof v === "number") return v;
      if (typeof v === "string") {
        const n = parseInt(v, 10);
        return Number.isFinite(n) ? n : undefined;
      }
      return undefined;
    }),
  severity: LooseSeverity,
  description: z.string().default(""),
  suggestedFix: SuggestedFixLoose,
});

const ReviewSchema = z.object({
  overallAssessment: z
    .union([z.string(), z.null(), z.undefined()])
    .transform((v): "excellent" | "good" | "needs_work" | "poor" => {
      const s = (v ? String(v) : "good").trim().toLowerCase().replace(/[\s-]+/g, "_");
      if (s === "excellent" || s === "good" || s === "needs_work" || s === "poor") return s;
      if (s === "great") return "excellent";
      if (s === "ok" || s === "okay" || s === "fine") return "good";
      if (s === "bad") return "poor";
      return "good";
    }),
  summary: z.string().default(""),
  issues: z.array(IssueSchema).default([]),
});

export type ValidationIssue = z.infer<typeof IssueSchema>;
export type ValidationReview = z.infer<typeof ReviewSchema>;

const SYSTEM = `You are a senior Talmud editor performing a final review of an AI-generated teaching sheet. You will receive:
1. The full source text of the daf (numbered lines).
2. The structured analysis: sugya boundaries, steps with classifications, meforshim summaries.

Audit the analysis against the source. Look for:
- WRONG_CLASSIFICATION: a step labeled מימרא that is actually a קשיא, a שאלה mislabeled as קשיא, etc. Judge by argumentative function in context, not surface grammar.
- MISSING_COVERAGE: source lines that don't appear in any step's phrases (gaps in the daf).
- BROKEN_DEPENDENCY: a תירוץ that doesn't actually resolve the קשיא it claims to depend on; a דחיה that doesn't actually attack the cited ראיה.
- HALLUCINATED_MEFORESH: a meforshim takeaway that contradicts or misrepresents what the verbatim Hebrew text of that meforesh actually says (you'll see the verbatim Hebrew in the meforshim block).
- REDUNDANT_STEP: two adjacent steps that say the same thing (an artificial-restart artifact).
- MISSING_STEP_SPLIT: one step that bundles a קשיא + תירוץ that should be split into two.
- PHRASING_TOO_LONG / PHRASING_TOO_VAGUE: whatsHappening over 2 sentences, deeperAnalysis over 3 sentences, or vague filler instead of substantive analysis.
- MISSING_NIKUD: keyTerms without vowels.

Be conservative — don't flag stylistic preferences. Flag REAL substantive problems. If the analysis is solid, return zero issues and overallAssessment: "excellent".

For each issue, set severity:
- critical: factual error or wrong classification that would mislead a learner
- warning: clearly suboptimal but not factually wrong
- nit: cosmetic / preference

Suggest a fix when possible (newHebrewStepName, newValue text, etc.).

Return strict JSON: { overallAssessment, summary, issues: [{kind, stepNumber?, severity, description, suggestedFix?}, ...] }`;

function buildUser(daf: DafSourceText, analysis: DafAnalysis): string {
  const numberedSource = daf.hebrew
    .map((line, i) => `[${i + 1}] ${line}`)
    .join("\n");

  const slimAnalysis = {
    mainTopic: analysis.mainTopic,
    overview: analysis.overview,
    sugyaBoundaries: analysis.sugyaBoundaries,
    steps: analysis.steps.map((s) => ({
      stepNumber: s.stepNumber,
      hebrewStepName: s.hebrewStepName,
      title: s.title,
      whatsHappening: s.whatsHappening,
      deeperAnalysis: s.deeperAnalysis,
      keyTerms: s.keyTerms.map((k) => k.term),
      classificationConfidence: s.classificationConfidence,
      dependsOnStepNumbers: s.dependsOnStepNumbers,
      kashyaTarget: s.kashyaTarget,
      terutzResolutionType: s.terutzResolutionType,
      phrasesAramaic: s.phrases.map((p) => p.aramaic).join(" "),
      meforshim: s.meforshim
        ? {
            rashi: s.meforshim.rashi.map((c) => ({
              takeaway: c.takeaway,
              verbatimHebrew: c.hebrew.slice(0, 600),
            })),
            tosafot: s.meforshim.tosafot.map((c) => ({
              takeaway: c.takeaway,
              verbatimHebrew: c.hebrew.slice(0, 600),
            })),
            rishonim: s.meforshim.rishonim.map((c) => ({
              source: c.source,
              takeaway: c.takeaway,
              verbatimHebrew: c.hebrew.slice(0, 400),
            })),
          }
        : undefined,
    })),
  };

  return `Daf reference: ${daf.ref}

Source text (numbered lines):
${numberedSource}

Analysis to review:
${JSON.stringify(slimAnalysis, null, 2)}

Perform the audit per the rules. Return ONLY JSON.`;
}

export async function reviewAnalysis(
  router: LLMRouter,
  daf: DafSourceText,
  analysis: DafAnalysis,
): Promise<ValidationReview> {
  const adapter = router.for("validate");
  const result = await adapter.callJSON<z.infer<typeof ReviewSchema>>({
    system: SYSTEM,
    user: buildUser(daf, analysis),
    maxTokens: 8000,
    temperature: 0.1,
  });
  return ReviewSchema.parse(result.data);
}

export interface ApplyResult {
  patched: DafAnalysis;
  applied: ValidationIssue[];
  skipped: ValidationIssue[];
}

export function applyAutomaticFixes(
  analysis: DafAnalysis,
  review: ValidationReview,
): ApplyResult {
  const stepsByNumber = new Map(analysis.steps.map((s) => [s.stepNumber, s]));
  const applied: ValidationIssue[] = [];
  const skipped: ValidationIssue[] = [];

  for (const issue of review.issues) {
    if (
      issue.kind === "wrong_classification" &&
      issue.suggestedFix?.newHebrewStepName &&
      issue.stepNumber !== undefined
    ) {
      const step = stepsByNumber.get(issue.stepNumber);
      if (step && issue.severity !== "nit") {
        step.hebrewStepName = issue.suggestedFix.newHebrewStepName;
        applied.push(issue);
        continue;
      }
    }

    if (
      issue.suggestedFix?.field &&
      issue.suggestedFix.newValue !== undefined &&
      issue.stepNumber !== undefined
    ) {
      const step = stepsByNumber.get(issue.stepNumber);
      if (step && isPatchableField(issue.suggestedFix.field)) {
        (step as unknown as Record<string, unknown>)[issue.suggestedFix.field] =
          issue.suggestedFix.newValue;
        applied.push(issue);
        continue;
      }
    }

    skipped.push(issue);
  }

  return {
    patched: { ...analysis, steps: Array.from(stepsByNumber.values()) },
    applied,
    skipped,
  };
}

const PATCHABLE_FIELDS = new Set<keyof Step>([
  "title",
  "stepSummary",
  "whatsHappening",
  "deeperAnalysis",
  "whatToRemember",
  "confusionAlert",
  "whyThisMatters",
  "kashyaTarget",
  "kashyaAttackLogic",
  "terutzHavaAmina",
  "terutzMaskana",
  "sheelahInformationSought",
  "teshuvahAnswerProvided",
  "raayaObject",
  "raayaSupportSource",
  "dechiyaFlawIdentified",
  "mimraCoreRuling",
  "maskanaFinalTakeaway",
  "relationToPreviousStep",
]);

function isPatchableField(field: string): field is keyof Step {
  return PATCHABLE_FIELDS.has(field as keyof Step);
}
