import { z } from "zod";
import type { LLMRouter } from "../llm/index.js";
import { KeyTermSchema, type Step } from "../schema.js";

const PolishedStepSchema = z.object({
  stepNumber: z.number().int(),
  title: z.string(),
  whatsHappening: z.string(),
  deeperAnalysis: z.string(),
  keyTerms: z.array(KeyTermSchema),
  whatToRemember: z.string().optional(),
  confusionAlert: z.string().optional(),
  whyThisMatters: z.string().optional(),
});

const ResponseSchema = z.object({ steps: z.array(PolishedStepSchema) });

const SYSTEM = `You are polishing the teaching layer of an existing Gemara analysis. You will receive an array of steps; for each, return a tightened version that follows these strict rules:

1. whatsHappening: STRICT MAX 2 plain-English sentences. State exactly what the Gemara is doing right now. If it's a setup/transition line, say so explicitly. No vague paraphrasing.
2. deeperAnalysis: STRICT MAX 3 short sentences. Explain the logic clearly. State exactly what changed, what is being challenged, or what new information is added.
3. keyTerms: keep only NEW or uniquely important terms for this step. ADD FULL NIKUD (vowels) to every Hebrew/Aramaic term, even if the input lacks them. Aim for 3-6 terms per step. NEVER repeat terms that appeared in earlier steps (the input list is in stepNumber order — track what you've already emitted).
4. whatToRemember: KEEP only if it captures a genuine takeaway from a major section conclusion. Otherwise DROP it (set to empty string or omit). Never put filler here.
5. confusionAlert: KEEP only if there is a real, classic trap a beginner would fall into. Otherwise DROP. Be hyper-conservative.
6. whyThisMatters: KEEP only if there is genuine lasting halachic or conceptual significance. Otherwise DROP.
7. title: clean English phrase. NO tags like "ALT", "Alternative", קשיא, דחיה in the title.

HEBREW SCRIPT INLINE: In all English fields, write Talmudic/halachic technical terms, sage names, masechtot names, and concept names in HEBREW SCRIPT (e.g. "עדים זוממין", "קל וחומר", "רבי יהושע בן לוי", "כהונה", "משנה", "גמרא") — NOT transliteration.

Return strict JSON: { steps: [{stepNumber, title, whatsHappening, deeperAnalysis, keyTerms, whatToRemember?, confusionAlert?, whyThisMatters?}, ...] }`;

function compactStepInput(step: Step) {
  return {
    stepNumber: step.stepNumber,
    hebrewStepName: step.hebrewStepName,
    title: step.title,
    whatsHappening: step.whatsHappening,
    deeperAnalysis: step.deeperAnalysis,
    keyTerms: step.keyTerms,
    whatToRemember: step.whatToRemember,
    confusionAlert: step.confusionAlert,
    whyThisMatters: step.whyThisMatters,
  };
}

export async function polishTeachingLayer(
  router: LLMRouter,
  steps: Step[],
  batchSize = 8,
): Promise<Step[]> {
  if (steps.length === 0) return steps;
  const adapter = router.for("teaching");
  const polished: Step[] = [];
  for (let i = 0; i < steps.length; i += batchSize) {
    const batch = steps.slice(i, i + batchSize);
    const priorTerms = polished
      .flatMap((s) => s.keyTerms.map((t) => t.term))
      .slice(-40);
    try {
      const user = `Steps already polished (do NOT repeat their keyTerms — these are the recent ones):
${priorTerms.length ? priorTerms.join(", ") : "(none yet — this is the first batch)"}

Steps to polish in this batch:
${JSON.stringify(batch.map(compactStepInput), null, 2)}

Return polished JSON.`;
      const result = await adapter.callJSON<z.infer<typeof ResponseSchema>>({
        system: SYSTEM,
        user,
        maxTokens: 8000,
        temperature: 0.1,
      });
      const parsed = ResponseSchema.parse(result.data);
      const byNumber = new Map(parsed.steps.map((p) => [p.stepNumber, p]));
      for (const original of batch) {
        const p = byNumber.get(original.stepNumber);
        if (!p) {
          polished.push(original);
          continue;
        }
        polished.push({
          ...original,
          title: p.title || original.title,
          whatsHappening: p.whatsHappening || original.whatsHappening,
          deeperAnalysis: p.deeperAnalysis || original.deeperAnalysis,
          keyTerms: p.keyTerms.length ? p.keyTerms : original.keyTerms,
          whatToRemember: nonEmpty(p.whatToRemember),
          confusionAlert: nonEmpty(p.confusionAlert),
          whyThisMatters: nonEmpty(p.whyThisMatters),
        });
      }
    } catch (err) {
      console.warn(
        `[teaching] batch starting at step ${batch[0].stepNumber} failed; keeping originals: ${(err as Error).message}`,
      );
      polished.push(...batch);
    }
  }
  return polished;
}

function nonEmpty(s: string | undefined): string | undefined {
  if (!s) return undefined;
  const t = s.trim();
  if (!t) return undefined;
  if (/^(n\/?a|none|skip)$/i.test(t)) return undefined;
  return t;
}
