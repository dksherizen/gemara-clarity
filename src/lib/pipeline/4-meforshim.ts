import { z } from "zod";
import {
  MeforshimBlockSchema,
  type MeforshimBlock,
  type Step,
  type DafSourceText,
} from "../schema.js";
import type { LLMRouter } from "../llm/index.js";
import {
  fetchMeforshimByAnchor,
  type MeforeshWithText,
} from "../sefaria/index.js";

const MAX_COMMENTARY_CHARS = 1800;

function bucket(title: string): keyof Omit<MeforshimBlock, "interplaySummary"> {
  if (title === "Rashi") return "rashi";
  if (title === "Tosafot") return "tosafot";
  const RISHONIM = new Set([
    "Ramban",
    "Rashba",
    "Ritva",
    "Ran",
    "Meiri",
    "Rabbeinu Yonah",
    "Rosh",
    "Mordechai",
  ]);
  return RISHONIM.has(title) ? "rishonim" : "acharonim";
}

function truncate(s: string, max = MAX_COMMENTARY_CHARS): string {
  if (s.length <= max) return s;
  return s.slice(0, max) + "…";
}

function collectMeforshimForStep(
  step: Step,
  byAnchor: Map<string, MeforeshWithText[]>,
  ref: string,
  startLine: number,
): MeforeshWithText[] {
  const out: MeforeshWithText[] = [];
  const linesInStep = step.phrases.length;
  const stepAnchors: string[] = [];

  for (let i = 0; i < linesInStep; i++) {
    const anchor = `${ref}:${startLine + i}`;
    stepAnchors.push(anchor);
    const list = byAnchor.get(anchor);
    if (list) out.push(...list);
  }

  const seen = new Set<string>();
  return out.filter((m) => {
    if (seen.has(m.sourceRef)) return false;
    seen.add(m.sourceRef);
    return true;
  });
}

const ResponseSchema = z.object({
  rashi: z
    .array(
      z.object({
        sourceRef: z.string(),
        takeaway: z.string(),
      }),
    )
    .default([]),
  tosafot: z
    .array(
      z.object({
        sourceRef: z.string(),
        takeaway: z.string(),
      }),
    )
    .default([]),
  rishonim: z
    .array(
      z.object({
        sourceRef: z.string(),
        collectiveTitle: z.string().optional(),
        takeaway: z.string(),
      }),
    )
    .default([]),
  acharonim: z
    .array(
      z.object({
        sourceRef: z.string(),
        collectiveTitle: z.string().optional(),
        takeaway: z.string(),
      }),
    )
    .default([]),
  interplaySummary: z.string().optional(),
});

const SYSTEM = `You are an expert in רש״י's commentary on the Talmud. Below you will receive:
1. A single Gemara step (with English explanation and Hebrew/Aramaic text).
2. The VERBATIM TEXTS of רש״י's comments that Sefaria has linked to that step's Gemara lines.

Your job is to:
- For each רש״י comment that is materially relevant to this Gemara step, write a one-sentence English takeaway that captures what רש״י is actually saying. Use HEBREW SCRIPT inline for technical Hebrew/Aramaic concept names (e.g. עדים זוממין, חזקה).
- DO NOT invent or paraphrase content that isn't grounded in the verbatim Hebrew you were given.
- DO NOT include comments that are empty, irrelevant to this step, or just glossing a single word with no analytical content.
- If multiple רש״י entries on the same step say substantively the same thing, consolidate.

Return strict JSON: { rashi: [{sourceRef, takeaway}], tosafot: [], rishonim: [], acharonim: [] }`;

function buildUserPrompt(
  step: Step,
  meforshim: MeforeshWithText[],
  daf: DafSourceText,
): string {
  const stepText = step.phrases.map((p) => p.aramaic).join(" ");
  const meforshimText = meforshim
    .map(
      (m) =>
        `<<${m.collectiveTitle} | ${m.sourceRef}>>\nHEBREW: ${truncate(
          m.hebrew,
        )}\nENGLISH: ${m.english ? truncate(m.english) : "[no English available]"}`,
    )
    .join("\n\n");

  return `Gemara reference: ${daf.ref}
Step #${step.stepNumber} (${step.hebrewStepName}) — ${step.title}

Gemara text for this step:
${stepText}

Plain-English summary of the step (for context):
${step.whatsHappening}
${step.deeperAnalysis}

Verbatim meforshim linked to this step's Gemara lines:
${meforshimText || "[No meforshim were linked to this step on Sefaria.]"}

Now write structured takeaways from each materially relevant meforesh. Skip irrelevant or trivially-glossing comments. Return ONLY JSON.`;
}

export interface MeforshimEnrichOptions {
  extraSeforim?: string[];
  concurrency?: number;
  skipIfNoLinks?: boolean;
}

export async function enrichStepsWithMeforshim(
  router: LLMRouter,
  daf: DafSourceText,
  steps: Step[],
  stepLineOffsets: number[],
  options: MeforshimEnrichOptions = {},
): Promise<Step[]> {
  const byAnchor = await fetchMeforshimByAnchor(
    daf.masechet,
    daf.daf,
    daf.amud,
    { extraSeforim: options.extraSeforim, concurrency: options.concurrency },
  );

  if (byAnchor.size === 0 && options.skipIfNoLinks !== false) {
    return steps;
  }

  const adapter = router.for("meforshim");
  const enriched: Step[] = [];
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const startLine = stepLineOffsets[i] ?? 1;
    const candidates = collectMeforshimForStep(step, byAnchor, daf.ref, startLine);
    if (candidates.length === 0) {
      enriched.push(step);
      continue;
    }

    try {
      const result = await adapter.callJSON<z.infer<typeof ResponseSchema>>({
        system: SYSTEM,
        user: buildUserPrompt(step, candidates, daf),
        maxTokens: 12000,
        temperature: 0.1,
      });
      const parsed = ResponseSchema.parse(result.data);
      const meforshim = assembleMeforshimBlock(parsed, candidates);
      enriched.push({ ...step, meforshim });
    } catch (err) {
      console.warn(
        `[meforshim] step ${step.stepNumber} enrichment failed: ${(err as Error).message}`,
      );
      enriched.push(step);
    }
  }
  return enriched;
}

function assembleMeforshimBlock(
  parsed: z.infer<typeof ResponseSchema>,
  candidates: MeforeshWithText[],
): MeforshimBlock {
  const lookup = new Map(candidates.map((c) => [c.sourceRef, c]));

  function toComment(p: { sourceRef: string; takeaway: string; collectiveTitle?: string }) {
    const c = lookup.get(p.sourceRef);
    return {
      source: c?.collectiveTitle ?? p.collectiveTitle ?? "Commentary",
      ref: p.sourceRef,
      hebrew: c?.hebrew ?? "",
      english: c?.english ?? undefined,
      takeaway: p.takeaway,
    };
  }

  return MeforshimBlockSchema.parse({
    rashi: parsed.rashi.map(toComment),
    tosafot: parsed.tosafot.map(toComment),
    rishonim: parsed.rishonim.map(toComment),
    acharonim: parsed.acharonim.map(toComment),
    interplaySummary: parsed.interplaySummary,
  });
}
