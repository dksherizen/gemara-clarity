import { z } from "zod";
import type { LLMRouter } from "../llm/index.js";
import { PhraseSchema, type Phrase, type Step } from "../schema.js";

const ResponseSchema = z.object({ phrases: z.array(PhraseSchema).min(1) });

const SYSTEM = `You are mapping a chunk of Talmudic Aramaic/Hebrew to English phrase-by-phrase.

Rules:
- The full Aramaic text must be preserved EXACTLY in the phrase array, in the original order, with NO missing or added words.
- Target 3-8 Aramaic words per phrase. Flex shorter or longer ONLY when grammar demands it (a complete clause).
- Avoid isolated one-word phrases unless semantically necessary.
- Avoid oversized sentence-level phrases.
- English: plain, fluent translation that's helpful for an English-speaking learner. Keep beginner-friendly.
- notes (OPTIONAL): only when an Aramaic idiom, technical term, or grammatical structure genuinely needs clarification. Skip when unnecessary.

Return strict JSON: { phrases: [{phraseNumber, aramaic, english, notes?}, ...] }`;

function normalizeForCoverage(s: string): string[] {
  return s
    .replace(/<[^>]*>?/gm, " ")
    .replace(/[a-zA-Z]/g, "")
    .replace(/[֑-ׇ]/g, "")
    .replace(/[.,;:!?\-'"()\[\]{}״׳]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
}

function coverageRatio(source: string, generatedJoined: string): number {
  const src = normalizeForCoverage(source);
  const gen = normalizeForCoverage(generatedJoined);
  if (src.length === 0) return 1;
  let gi = 0;
  const lookahead = 12;
  let matched = 0;
  for (let i = 0; i < src.length; i++) {
    let found = false;
    for (let j = gi; j < Math.min(gi + lookahead, gen.length); j++) {
      if (src[i] === gen[j]) {
        found = true;
        gi = j + 1;
        break;
      }
    }
    if (found) matched++;
  }
  return matched / src.length;
}

export async function mapPhrasesForStep(
  router: LLMRouter,
  stepAramaic: string,
  stepEnglishHint: string,
  maxAttempts = 2,
): Promise<{ phrases: Phrase[]; coverage: number; modelUsed: string }> {
  const adapter = router.for("phrasemap");
  let attempt = 0;
  let lastError = "";
  while (attempt < maxAttempts) {
    attempt++;
    const user = `Aramaic/Hebrew text to map:
${stepAramaic}

Reference English (Sefaria translation, for guidance only):
${stepEnglishHint}

Produce the phrase-by-phrase mapping per the rules. The Aramaic in your phrases array, when concatenated, MUST equal the source above with no missing or added words.${
      attempt > 1
        ? `\n\nPREVIOUS ATTEMPT FAILED: ${lastError}. Ensure full source coverage this time.`
        : ""
    }`;

    const result = await adapter.callJSON<z.infer<typeof ResponseSchema>>({
      system: SYSTEM,
      user,
      maxTokens: 6000,
      temperature: 0.1,
    });
    const parsed = ResponseSchema.parse(result.data);
    const phrases = parsed.phrases.map((p, i) => ({
      ...p,
      phraseNumber: i + 1,
    }));
    const generatedJoined = phrases.map((p) => p.aramaic).join(" ");
    const coverage = coverageRatio(stepAramaic, generatedJoined);
    if (coverage >= 0.85) {
      return {
        phrases,
        coverage,
        modelUsed: `${adapter.provider}/${adapter.model}`,
      };
    }
    lastError = `Coverage was ${(coverage * 100).toFixed(1)}% — too many source words missing.`;
  }
  throw new Error(`phrasemap failed: ${lastError}`);
}

export async function attachPhrasesToSteps(
  router: LLMRouter,
  daf: { hebrew: string[]; english: string[] },
  steps: Step[],
  stepLineRanges: { startLine: number; endLine: number }[],
): Promise<Step[]> {
  const out: Step[] = [];
  for (let i = 0; i < steps.length; i++) {
    const { startLine, endLine } = stepLineRanges[i];
    const aramaicChunk = daf.hebrew.slice(startLine - 1, endLine).join(" ");
    const englishChunk = daf.english.slice(startLine - 1, endLine).join(" ");
    if (!aramaicChunk.trim()) {
      out.push(steps[i]);
      continue;
    }
    try {
      const { phrases } = await mapPhrasesForStep(
        router,
        aramaicChunk,
        englishChunk,
      );
      out.push({ ...steps[i], phrases });
    } catch (err) {
      console.warn(
        `[phrasemap] step ${steps[i].stepNumber} fell back to whole-chunk single phrase: ${(err as Error).message}`,
      );
      out.push({
        ...steps[i],
        phrases: [
          {
            phraseNumber: 1,
            aramaic: aramaicChunk,
            english: englishChunk || "[translation unavailable]",
          },
        ],
      });
    }
  }
  return out;
}
