import { z } from "zod";
import type { LLMRouter } from "../llm/index.js";
import type { DafSourceText, SugyaBoundary, Step } from "../schema.js";
import {
  HEBREW_STEP_NAMES,
  MACRO_PHASES,
  BRANCH_ROLES,
  SCOPE_OF_STEP,
  type HebrewStepName,
} from "../schema.js";

// Permissive — accepts strings or partial objects, normalizes to {term, meaning}.
const KeyTermLoose = z
  .union([
    z.string(),
    z.object({
      term: z.string().nullable().optional(),
      meaning: z.string().nullable().optional(),
    }),
  ])
  .transform((v) => {
    if (typeof v === "string") return { term: v, meaning: "" };
    return { term: (v.term ?? "").trim(), meaning: (v.meaning ?? "").trim() };
  });

const LooseString = z
  .union([z.string(), z.null(), z.undefined()])
  .transform((v) => (v ? String(v) : undefined));

const LooseHebrewStepName = z
  .union([z.string(), z.null(), z.undefined()])
  .transform((v): HebrewStepName | undefined => {
    if (!v) return undefined;
    const s = String(v).trim();
    const direct = (HEBREW_STEP_NAMES as readonly string[]).find((n) => n === s);
    if (direct) return direct as HebrewStepName;
    const map: Record<string, HebrewStepName> = {
      statement: "מימרא",
      challenge: "קשיא",
      objection: "קשיא",
      resolution: "תירוץ",
      proof: "ראיה",
      rejection: "דחיה",
      question: "שאלה",
      response: "תשובה",
      answer: "תשובה",
      conclusion: "מסקנא",
      mimra: "מימרא",
      kashya: "קשיא",
      terutz: "תירוץ",
      raaya: "ראיה",
      dechiya: "דחיה",
      sheelah: "שאלה",
      teshuvah: "תשובה",
      maskana: "מסקנא",
    };
    return map[s.toLowerCase()];
  });

function looseEnum<T extends string>(
  values: readonly T[],
  normalizers: Record<string, T> = {},
) {
  return z
    .union([z.string(), z.null(), z.undefined()])
    .transform((v): T | undefined => {
      if (!v) return undefined;
      const s = String(v).trim();
      const direct = values.find((x) => x === s);
      if (direct) return direct;
      const lower = s.toLowerCase().replace(/[\s-]+/g, "_");
      const direct2 = values.find((x) => x === lower);
      if (direct2) return direct2;
      if (normalizers[lower]) return normalizers[lower];
      if (normalizers[s.toLowerCase()]) return normalizers[s.toLowerCase()];
      return undefined;
    });
}

const StepSkeletonSchema = z.object({
  stepNumber: z.number().int(),
  hebrewStepName: LooseHebrewStepName,
  title: z.string().default(""),
  stepSummary: z.string().default(""),
  startLineInSugya: z.number().int().default(1),
  endLineInSugya: z.number().int().default(1),
  whatsHappening: z.string().default(""),
  deeperAnalysis: z.string().default(""),
  whatToRemember: LooseString.optional(),
  confusionAlert: LooseString.optional(),
  whyThisMatters: LooseString.optional(),
  keyTerms: z.array(KeyTermLoose).default([]),
  classificationConfidence: z
    .union([z.enum(["High", "Medium", "Low"]), z.string(), z.null(), z.undefined()])
    .transform((v): "High" | "Medium" | "Low" => {
      if (v === "Medium" || v === "Low") return v;
      if (typeof v === "string") {
        const s = v.trim().toLowerCase();
        if (s.startsWith("med")) return "Medium";
        if (s.startsWith("low")) return "Low";
      }
      return "High";
    }),
  alternativePossibleLabel: LooseString.optional(),
  triggerLanguage: LooseString.optional(),
  macroPhase: looseEnum(MACRO_PHASES, {
    aggadah: "narrative_aggadah",
    narrative: "narrative_aggadah",
    "case study": "narrative_aggadah",
    "case_study": "narrative_aggadah",
    "illustration": "narrative_aggadah",
    "interpretive principle": "clarification_of_terms",
    "interpretive_principle": "clarification_of_terms",
    "support": "source_derivation",
    "rationale": "source_derivation",
    "support_+_rationale": "source_derivation",
    "support + rationale": "source_derivation",
  }).optional(),
  branchRole: looseEnum(BRANCH_ROLES, {
    "main_line": "continues_current_line",
    "main line": "continues_current_line",
    "primary": "continues_current_line",
    "continues": "continues_current_line",
    "new_branch": "opens_new_branch",
    "alternative": "alternative_approach",
    "conclusion": "conclusion_of_branch",
  }).optional(),
  dependsOnStepNumbers: z.array(z.number().int()).default([]),
  scopeOfStep: looseEnum(SCOPE_OF_STEP, {
    "general": "general_logic",
    "logic": "general_logic",
    "definition": "case_definition",
    "rule": "legal_rule",
    "proof": "proof_mechanism",
    "source": "source_reading",
    "exception": "exception_case",
  }).optional(),
  relationToPreviousStep: LooseString.optional(),
  kashyaTarget: LooseString.optional(),
  kashyaAttackLogic: LooseString.optional(),
  terutzResolutionType: LooseString.optional(),
  terutzHavaAmina: LooseString.optional(),
  terutzMaskana: LooseString.optional(),
  sheelahInformationSought: LooseString.optional(),
  teshuvahAnswerProvided: LooseString.optional(),
  raayaObject: LooseString.optional(),
  raayaSupportSource: LooseString.optional(),
  dechiyaRejectionScope: LooseString.optional(),
  dechiyaFlawIdentified: LooseString.optional(),
  mimraCoreRuling: LooseString.optional(),
  maskanaFinalTakeaway: LooseString.optional(),
});

const ResponseSchema = z.object({
  steps: z
    .array(StepSkeletonSchema)
    .transform((steps) =>
      steps
        .filter((s) => Boolean(s.hebrewStepName))
        .map((s) => ({
          ...s,
          keyTerms: s.keyTerms.filter((k) => k.term && k.term.length > 0),
        })),
    ),
});
export type StepSkeleton = z.infer<typeof StepSkeletonSchema>;

const SYSTEM = `You are an expert chavrusa breaking down a single sugya of Gemara. You will receive the full Aramaic/Hebrew text of ONE sugya and an English reference translation. Decompose it into discrete argumentative steps.

Step types (use exactly one Hebrew name per step):
- מימרא — a freestanding statement, ruling, or attribution-introduced teaching
- קשיא — a challenge or objection against an earlier statement
- תירוץ — a resolution to a קשיא
- ראיה — a proof or supporting source brought to back a claim
- דחיה — a rejection of a proof, source, or earlier line of reasoning
- שאלה — a clarifying question (NOT an objection)
- תשובה — an answer to a שאלה (NOT a תירוץ to a קשיא)
- מסקנא — a final conclusion or summary

Classification rules:
- Classify by ARGUMENTATIVE FUNCTION in context, not surface grammar. An interrogative-looking line may function as a קשיא, a שאלה, or a rhetorical opening.
- Distinguish a קשיא (attacks a prior claim) from a שאלה (asks for clarification).
- A תירוץ resolves a קשיא; a תשובה answers a שאלה.
- Attribution-only lines ("אמר רבי X משום רבי Y") are NOT their own steps — fold them into the step they introduce.
- A Hadran is a מסקנא; the first line of a new perek is a fresh מימרא.

REQUIRED JSON FIELDS for every step (these are the LITERAL field names you must emit):
- "hebrewStepName": exactly one of these 8 strings — "מימרא", "קשיא", "תירוץ", "ראיה", "דחיה", "שאלה", "תשובה", or "מסקנא". This field MUST be present on every step. Do not invent other values.
- "startLineInSugya" / "endLineInSugya": integers, 1-indexed within the sugya (NOT within the daf)
- "stepNumber": integer, 1-indexed, continues across the daf (you'll be given the starting number)
- "title": clean English summary phrase. NEVER include "ALT", "Alternative", "קשיא", "דחיה" tags in the title.
- stepSummary: one-sentence English summary of this step
- whatsHappening: 1-2 plain-English sentences stating what the Gemara is doing right now. If it's a setup/transition line, say so explicitly.
- deeperAnalysis: 2-3 sentences explaining the logic. State exactly what changed, what is being challenged, what new information is added.
- keyTerms: 3-6 Hebrew/Aramaic technical terms WITH FULL NIKUD (vowels), even if the original lacks them. NEVER repeat terms that appeared in earlier steps. Common formula words (מתניתין, גמרא) should appear at most once across the entire daf.
- triggerLanguage: the actual opening Aramaic words of the step, in full (no ellipsis).
- classificationConfidence: High / Medium / Low based on how confident the labeling is.
- alternativePossibleLabel: if Medium/Low confidence, name the other plausible step type.
- macroPhase, branchRole, dependsOnStepNumbers, scopeOfStep, relationToPreviousStep: structural metadata.
- Conditional fields: fill ONLY those relevant to the step's type (kashya* for קשיא, terutz* for תירוץ, raaya* for ראיה, dechiya* for דחיה, sheelah*/teshuvah* for שאלה/תשובה, mimraCoreRuling for מימרא, maskanaFinalTakeaway for מסקנא).
- whatToRemember and confusionAlert: OPTIONAL — only when genuinely warranted, never on every step.
- whyThisMatters: OPTIONAL — only when there is real lasting halachic or conceptual significance.

HEBREW SCRIPT INLINE: In all English fields (title, stepSummary, whatsHappening, deeperAnalysis, whatToRemember, confusionAlert, whyThisMatters, etc.), write Talmudic/halachic technical terms, sage names, masechtot names, and concept names in HEBREW SCRIPT (e.g. "עדים זוממין", "קל וחומר", "רבי יהושע בן לוי", "כהונה", "משנה", "גמרא") — NOT transliteration. The audience has yeshiva background.

Coverage rules (CRITICAL — violation breaks the downstream pipeline):
- Each source line belongs to EXACTLY ONE step. If a single line plays multiple argumentative roles, you MUST pick the PRIMARY function and assign that line to one step only.
- Steps must collectively cover EVERY line of the sugya. No gaps, no overlaps.
- Adjacent steps MUST be contiguous: step N+1's startLineInSugya = step N's endLineInSugya + 1.
- The first step's startLineInSugya MUST be 1. The last step's endLineInSugya MUST be the final line of the sugya.
- If the model wants to classify the same line as both a ראיה and a מימרא, it should pick ONE primary role and use 'alternativePossibleLabel' to note the secondary one. DO NOT emit two steps with overlapping line ranges.

Return strict JSON: { steps: [...] }`;

export interface StructuredSugya {
  sugyaNumber: number;
  daftLineOffset: number;
  skeletons: StepSkeleton[];
  modelUsed: string;
}

function sugyaTexts(
  daf: DafSourceText,
  sugya: SugyaBoundary,
): { hebrew: string[]; english: string[] } {
  const hebrew = daf.hebrew.slice(sugya.startLine - 1, sugya.endLine);
  const english = daf.english.slice(sugya.startLine - 1, sugya.endLine);
  return { hebrew, english };
}

export async function structureSugya(
  router: LLMRouter,
  daf: DafSourceText,
  sugya: SugyaBoundary,
  nextStepNumber: number,
): Promise<StructuredSugya> {
  const adapter = router.for("structure");
  const { hebrew, english } = sugyaTexts(daf, sugya);
  const numberedHebrew = hebrew.map((l, i) => `[${i + 1}] ${l}`).join("\n");
  const numberedEnglish = english.map((l, i) => `[${i + 1}] ${l}`).join("\n");

  const user = `Sugya ${sugya.sugyaNumber} from ${daf.ref}
Topic: ${sugya.topic}
Gist: ${sugya.gist}
Opening formula: ${sugya.openingFormula ?? "(none)"}
Starting step number for this sugya: ${nextStepNumber}

Sugya source (numbered lines):
${numberedHebrew}

Reference English (Sefaria — for cross-checking, not for direct copying):
${numberedEnglish}

Decompose this sugya into argumentative steps per the rules. Number steps starting at ${nextStepNumber}. Return ONLY JSON with shape { steps: [...] }.`;

  const result = await adapter.callJSON<z.infer<typeof ResponseSchema>>({
    system: SYSTEM,
    user,
    maxTokens: 24000,
    temperature: 0.1,
  });
  if (process.env.DEBUG_PIPELINE) {
    console.log(
      `[structure debug] raw response first 800 chars:\n${result.raw.slice(0, 800)}\n`,
    );
  }
  const rawData = result.data as { steps?: Array<{ hebrewStepName?: unknown }> };
  const rawStepNames = (rawData.steps ?? []).map((s) => s.hebrewStepName);
  const parsed = ResponseSchema.parse(result.data);
  if (parsed.steps.length === 0 && (rawData.steps ?? []).length > 0) {
    const firstStepKeys = Object.keys((rawData.steps?.[0] ?? {}) as object);
    console.warn(
      `[structure] sugya ${sugya.sugyaNumber}: ${rawData.steps?.length} steps returned by model but ALL dropped at normalization.`,
    );
    console.warn(`  Raw hebrewStepName values:`, rawStepNames);
    console.warn(`  First step's actual keys:`, firstStepKeys);
    console.warn(
      `  First step JSON (first 600 chars):`,
      JSON.stringify(rawData.steps?.[0]).slice(0, 600),
    );
  }
  return {
    sugyaNumber: sugya.sugyaNumber,
    daftLineOffset: sugya.startLine,
    skeletons: parsed.steps,
    modelUsed: `${adapter.provider}/${adapter.model}`,
  };
}

export function skeletonToStep(skeleton: StepSkeleton): Step {
  if (!skeleton.hebrewStepName) {
    throw new Error(`Step ${skeleton.stepNumber} missing hebrewStepName`);
  }
  return {
    stepNumber: skeleton.stepNumber,
    hebrewStepName: skeleton.hebrewStepName,
    title: skeleton.title,
    stepSummary: skeleton.stepSummary,
    whatsHappening: skeleton.whatsHappening,
    deeperAnalysis: skeleton.deeperAnalysis,
    keyTerms: skeleton.keyTerms,
    whatToRemember: skeleton.whatToRemember,
    confusionAlert: skeleton.confusionAlert,
    whyThisMatters: skeleton.whyThisMatters,
    phrases: [],
    classificationConfidence: skeleton.classificationConfidence,
    alternativePossibleLabel: skeleton.alternativePossibleLabel,
    triggerLanguage: skeleton.triggerLanguage,
    macroPhase: skeleton.macroPhase,
    branchRole: skeleton.branchRole,
    dependsOnStepNumbers: skeleton.dependsOnStepNumbers,
    scopeOfStep: skeleton.scopeOfStep,
    relationToPreviousStep: skeleton.relationToPreviousStep,
    kashyaTarget: skeleton.kashyaTarget,
    kashyaAttackLogic: skeleton.kashyaAttackLogic,
    terutzResolutionType: skeleton.terutzResolutionType,
    terutzHavaAmina: skeleton.terutzHavaAmina,
    terutzMaskana: skeleton.terutzMaskana,
    sheelahInformationSought: skeleton.sheelahInformationSought,
    teshuvahAnswerProvided: skeleton.teshuvahAnswerProvided,
    raayaObject: skeleton.raayaObject,
    raayaSupportSource: skeleton.raayaSupportSource,
    dechiyaRejectionScope: skeleton.dechiyaRejectionScope,
    dechiyaFlawIdentified: skeleton.dechiyaFlawIdentified,
    mimraCoreRuling: skeleton.mimraCoreRuling,
    maskanaFinalTakeaway: skeleton.maskanaFinalTakeaway,
  };
}
