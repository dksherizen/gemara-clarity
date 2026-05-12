import { segmentSugyot } from "./1-segmentation.js";
import { structureSugya, skeletonToStep } from "./2-structure.js";
import { attachPhrasesToSteps } from "./3-phrasemap.js";
import { enrichStepsWithMeforshim } from "./4-meforshim.js";
import { polishTeachingLayer } from "./5-teaching.js";
import { reviewAnalysis, applyAutomaticFixes } from "./6-validate.js";
import { fetchDafText } from "../sefaria/index.js";
import type { LLMRouter } from "../llm/index.js";
import type { DafAnalysis, Step } from "../schema.js";

export const PIPELINE_VERSION = "0.3.0";

export interface OrchestratorOptions {
  masechet: string;
  daf: number;
  amud: "a" | "b";
  enableMeforshim?: boolean;
  enableTeachingPolish?: boolean;
  enableValidation?: boolean;
  meforshimExtraSeforim?: string[];
  onProgress?: (msg: string) => void;
}

export async function runFullPipeline(
  router: LLMRouter,
  opts: OrchestratorOptions,
): Promise<DafAnalysis> {
  const log = opts.onProgress ?? (() => {});
  const modelsUsed: Record<string, string> = {};
  router.resetUsage();

  log(`Fetching ${opts.masechet} ${opts.daf}${opts.amud} from Sefaria…`);
  const daf = await fetchDafText(opts.masechet, opts.daf, opts.amud);

  log(`Pass 1/6: segmenting ${daf.hebrew.length} lines into sugyot…`);
  const seg = await segmentSugyot(router, daf);
  modelsUsed.segmentation = seg.modelUsed;
  log(`  → ${seg.sugyot.length} sugyot identified.`);

  log(`Pass 2/6: building structural skeleton for each sugya…`);
  const allSteps: Step[] = [];
  const stepLineRanges: { startLine: number; endLine: number }[] = [];
  let nextStepNumber = 1;
  const sugyotWithSteps = [...seg.sugyot];
  for (let si = 0; si < sugyotWithSteps.length; si++) {
    const sugya = sugyotWithSteps[si];
    log(`  · sugya ${sugya.sugyaNumber} (${sugya.topic})`);
    const structured = await structureSugya(router, daf, sugya, nextStepNumber);
    if (!modelsUsed.structure) modelsUsed.structure = structured.modelUsed;
    const firstStepInSugya = nextStepNumber;
    // Auto-repair overlapping/non-contiguous line ranges.
    // The model often returns identical ranges across logically-distinct steps
    // (e.g. a ראיה + a מימרא covering the same Aramaic). Force contiguity.
    const sugyaLineCount = sugya.endLine - sugya.startLine + 1;
    const repairedSkeletons = structured.skeletons.map((s, idx, arr) => {
      const prevEnd = idx === 0 ? 0 : arr[idx - 1].endLineInSugya;
      const start = Math.min(
        sugyaLineCount,
        Math.max(prevEnd + 1, s.startLineInSugya, 1),
      );
      let end = Math.max(s.endLineInSugya, start);
      // Last step in sugya must end at the sugya's last line.
      if (idx === arr.length - 1) end = sugyaLineCount;
      end = Math.min(end, sugyaLineCount);
      // If we'd skip lines, extend backward.
      const repairedStart = Math.min(start, end);
      arr[idx] = { ...s, startLineInSugya: repairedStart, endLineInSugya: end };
      return arr[idx];
    });
    // Drop any step whose range collapsed to empty (start > sugyaLineCount).
    const validSkeletons = repairedSkeletons.filter(
      (s) => s.startLineInSugya <= s.endLineInSugya &&
        s.startLineInSugya <= sugyaLineCount,
    );
    for (const skeleton of validSkeletons) {
      allSteps.push(skeletonToStep(skeleton));
      stepLineRanges.push({
        startLine: sugya.startLine + skeleton.startLineInSugya - 1,
        endLine: sugya.startLine + skeleton.endLineInSugya - 1,
      });
      nextStepNumber = skeleton.stepNumber + 1;
    }
    sugyotWithSteps[si] = {
      ...sugya,
      firstStepNumber: firstStepInSugya,
      lastStepNumber: nextStepNumber - 1,
    };
  }
  log(`  → ${allSteps.length} total steps across daf.`);

  log(`Pass 3/6: phrase-by-phrase mapping for each step…`);
  const withPhrases = await attachPhrasesToSteps(
    router,
    daf,
    allSteps,
    stepLineRanges,
  );
  modelsUsed.phrasemap = router.for("phrasemap").provider + "/" + router.for("phrasemap").model;

  let workingSteps = withPhrases;
  if (opts.enableMeforshim !== false) {
    log(`Pass 4/6: meforshim grounding (Rashi / Tosafot / Rishonim)…`);
    workingSteps = await enrichStepsWithMeforshim(
      router,
      daf,
      workingSteps,
      stepLineRanges.map((r) => r.startLine),
      { extraSeforim: opts.meforshimExtraSeforim },
    );
    modelsUsed.meforshim = router.for("meforshim").provider + "/" + router.for("meforshim").model;
  } else {
    log(`Pass 4/6 skipped (meforshim disabled).`);
  }

  if (opts.enableTeachingPolish !== false) {
    log(`Pass 5/6: teaching-layer polish (length, nikud, dedupe terms)…`);
    workingSteps = await polishTeachingLayer(router, workingSteps);
    modelsUsed.teaching = router.for("teaching").provider + "/" + router.for("teaching").model;
  } else {
    log(`Pass 5/6 skipped (teaching polish disabled).`);
  }

  const cost = {
    totalUSD: router.totalCost(),
    totalInputTokens: router.usage.reduce((s, u) => s + u.inputTokens, 0),
    totalOutputTokens: router.usage.reduce((s, u) => s + u.outputTokens, 0),
    byPass: router.costByPass(),
  };
  const draft: DafAnalysis = {
    ref: daf.ref,
    masechet: opts.masechet,
    daf: opts.daf,
    amud: opts.amud,
    mainTopic: seg.mainTopic,
    overview: seg.overview,
    sugyaBoundaries: sugyotWithSteps,
    steps: workingSteps,
    pipelineVersion: PIPELINE_VERSION,
    generatedAt: new Date().toISOString(),
    modelsUsed,
    cost,
  };

  if (opts.enableValidation !== false) {
    log(`Pass 6/6: validation re-read (cross-model audit)…`);
    try {
      const review = await reviewAnalysis(router, daf, draft);
      modelsUsed.validate = router.for("validate").provider + "/" + router.for("validate").model;
      const { patched, applied, skipped } = applyAutomaticFixes(draft, review);
      log(
        `  → overall: ${review.overallAssessment} | ${review.issues.length} issues | ${applied.length} auto-patched | ${skipped.length} reported`,
      );
      return {
        ...patched,
        modelsUsed,
      } as DafAnalysis & { review?: typeof review };
    } catch (err) {
      log(`  ⚠ validation pass failed: ${(err as Error).message}`);
      return draft;
    }
  }

  log(`Pass 6/6 skipped (validation disabled).`);
  return draft;
}
