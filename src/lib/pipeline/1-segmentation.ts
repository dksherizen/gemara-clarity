import { z } from "zod";
import { SugyaBoundarySchema, type SugyaBoundary } from "../schema.js";
import type { LLMRouter } from "../llm/index.js";
import type { DafSourceText } from "../schema.js";

const ResultSchema = z.object({
  mainTopic: z.string(),
  overview: z.string(),
  sugyot: z.array(SugyaBoundarySchema),
});

export interface SegmentationResult {
  mainTopic: string;
  overview: string;
  sugyot: SugyaBoundary[];
  modelUsed: string;
}

const SYSTEM = `You are an expert in classical Talmudic structure. Given the FULL Hebrew/Aramaic text of one amud of Gemara, your job is to:

1. Identify the main topic of the amud in plain English.
2. Write a 2-3 sentence overview describing the flow of the amud.
3. Segment the amud into its natural sugyot (discrete topical/argumentative units).

A "sugya" is a self-contained argumentative or topical unit. Do NOT cut by arbitrary line count. A sugya may be:
- A Mishnah + its accompanying Gemara analysis (treat as one sugya)
- A single discussion launched by an opening question (e.g. תנו רבנן, איתמר, איבעיא להו, מנא הני מילי) and ending when the discussion clearly concludes or pivots to a new topic
- A perek transition (Hadran + new perek opening) is the END of one sugya and START of another — never combined

For each sugya, return:
- sugyaNumber: 1-indexed
- startLine: the 1-indexed line number (from the input) where the sugya BEGINS
- endLine: the 1-indexed line number where the sugya ENDS (inclusive)
- topic: a short English phrase (under 10 words) naming the sugya
- gist: a one-sentence English description of what is debated/established
- openingFormula: the literal Aramaic words that open the sugya (e.g. "תנו רבנן", "אמר רבי יוחנן", "תנן התם"), if any

Coverage requirements:
- Every input line MUST belong to exactly one sugya. No line may be skipped, no line may belong to two sugyot.
- The first sugya MUST start at line 1. The last sugya MUST end at the final line.
- Sugyot must be contiguous: sugya N+1 starts at sugya N's endLine + 1.

Return ONLY valid JSON, no commentary, no markdown.`;

function buildUserPrompt(daf: DafSourceText): string {
  const numbered = daf.hebrew
    .map((line, i) => `[${i + 1}] ${line}`)
    .join("\n");
  return `Daf reference: ${daf.ref}\n\nSource text (numbered lines):\n${numbered}\n\nSegment this amud into its natural sugyot following the rules above. Return JSON with shape: { mainTopic, overview, sugyot: [{sugyaNumber, startLine, endLine, topic, gist, openingFormula}] }`;
}

function validateCoverage(
  sugyot: SugyaBoundary[],
  totalLines: number,
): SugyaBoundary[] {
  const sorted = [...sugyot].sort((a, b) => a.startLine - b.startLine);
  if (sorted.length === 0) {
    return [
      {
        sugyaNumber: 1,
        startLine: 1,
        endLine: totalLines,
        topic: "Full amud",
        gist: "Segmentation failed; treating whole amud as one sugya.",
      },
    ];
  }

  const repaired: SugyaBoundary[] = [];
  let expectedStart = 1;
  for (let i = 0; i < sorted.length; i++) {
    const s = sorted[i];
    let start = Math.max(expectedStart, s.startLine);
    let end = Math.min(totalLines, s.endLine);
    if (i === sorted.length - 1) end = totalLines;
    if (end < start) end = start;
    repaired.push({
      ...s,
      sugyaNumber: i + 1,
      startLine: start,
      endLine: end,
    });
    expectedStart = end + 1;
  }
  if (repaired[repaired.length - 1].endLine < totalLines) {
    repaired[repaired.length - 1].endLine = totalLines;
  }
  return repaired;
}

export async function segmentSugyot(
  router: LLMRouter,
  daf: DafSourceText,
): Promise<SegmentationResult> {
  const adapter = router.for("segmentation");
  const totalLines = daf.hebrew.length;

  const result = await adapter.callJSON<z.infer<typeof ResultSchema>>({
    system: SYSTEM,
    user: buildUserPrompt(daf),
    maxTokens: 6000,
    temperature: 0.1,
  });

  let parsed;
  try {
    parsed = ResultSchema.parse(result.data);
  } catch (zodErr) {
    console.error(
      `[segmentation] schema parse failed. Raw text (first 1500 chars):\n${result.raw.slice(0, 1500)}\n\nParsed data keys: ${
        result.data && typeof result.data === "object"
          ? Object.keys(result.data as object).join(", ")
          : "(not an object)"
      }`,
    );
    throw zodErr;
  }
  const sugyot = validateCoverage(parsed.sugyot, totalLines);

  return {
    mainTopic: parsed.mainTopic,
    overview: parsed.overview,
    sugyot,
    modelUsed: `${adapter.provider}/${adapter.model}`,
  };
}
