import { readFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { fetchDafText } from "../src/lib/sefaria/index.js";
import type { DafAnalysis, Step } from "../src/lib/schema.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

// The original app's Firestore-cached JSON format (loose typing on purpose —
// we just need to derive metrics, not validate the schema).
interface OriginalAnalysis {
  mainTopic?: string;
  overview?: string;
  steps?: Array<{
    stepNumber: number;
    hebrewStepName: string;
    title: string;
    keyTerms?: Array<{ term: string }>;
    phrases?: Array<{ aramaic: string; english: string; notes?: string }>;
    whatsHappening?: string;
    deeperAnalysis?: string;
    macroPhase?: string;
    classificationConfidence?: string;
  }>;
}

interface Metrics {
  label: string;
  totalSteps: number;
  stepTypeCounts: Record<string, number>;
  totalPhrases: number;
  avgPhrasesPerStep: number;
  totalKeyTerms: number;
  uniqueKeyTerms: number;
  redundantKeyTerms: number;
  termsWithNikud: number;
  termsWithoutNikud: number;
  avgWhatsHappeningChars: number;
  avgDeeperAnalysisChars: number;
  totalAramaicChars: number;
  sourceCoverageRatio: number;
  stepsWithMeforshim: number;
  totalMeforshim: number;
  hasSugyaBoundaries: boolean;
  lowConfidenceSteps: number;
}

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

function coverageRatio(sourceLines: string[], generated: string): number {
  const src = normalizeForCoverage(sourceLines.join(" "));
  const gen = normalizeForCoverage(generated);
  if (src.length === 0) return 1;
  let gi = 0;
  let matched = 0;
  const lookahead = 16;
  for (let i = 0; i < src.length; i++) {
    for (let j = gi; j < Math.min(gi + lookahead, gen.length); j++) {
      if (src[i] === gen[j]) {
        matched++;
        gi = j + 1;
        break;
      }
    }
  }
  return matched / src.length;
}

const NIKUD_RX = /[֑-ׇ]/;

function hasNikud(s: string): boolean {
  return NIKUD_RX.test(s);
}

function metricsFromSteps(
  label: string,
  steps: Array<{
    hebrewStepName: string;
    keyTerms?: Array<{ term: string }>;
    phrases?: Array<{ aramaic: string }>;
    whatsHappening?: string;
    deeperAnalysis?: string;
    meforshim?: Step["meforshim"];
    classificationConfidence?: string;
  }>,
  hasSugyaBoundaries: boolean,
  sourceLines: string[],
): Metrics {
  const stepTypeCounts: Record<string, number> = {};
  let totalPhrases = 0;
  let totalKeyTerms = 0;
  const termsSeen = new Set<string>();
  let redundant = 0;
  let withNikud = 0;
  let withoutNikud = 0;
  let totalWhats = 0;
  let totalDeep = 0;
  let allAramaic = "";
  let stepsWithMef = 0;
  let totalMef = 0;
  let lowConf = 0;

  for (const step of steps) {
    stepTypeCounts[step.hebrewStepName] =
      (stepTypeCounts[step.hebrewStepName] || 0) + 1;
    const phrases = step.phrases ?? [];
    totalPhrases += phrases.length;
    for (const p of phrases) allAramaic += " " + (p.aramaic || "");
    for (const t of step.keyTerms ?? []) {
      totalKeyTerms++;
      const norm = t.term.replace(/[֑-ׇ]/g, "").trim();
      if (termsSeen.has(norm)) redundant++;
      termsSeen.add(norm);
      if (hasNikud(t.term)) withNikud++;
      else withoutNikud++;
    }
    if (step.whatsHappening) totalWhats += step.whatsHappening.length;
    if (step.deeperAnalysis) totalDeep += step.deeperAnalysis.length;
    if (step.meforshim) {
      const mef = step.meforshim;
      const count =
        mef.rashi.length +
        mef.tosafot.length +
        mef.rishonim.length +
        mef.acharonim.length;
      if (count > 0) {
        stepsWithMef++;
        totalMef += count;
      }
    }
    if (
      step.classificationConfidence &&
      step.classificationConfidence !== "High"
    ) {
      lowConf++;
    }
  }

  const n = steps.length || 1;
  return {
    label,
    totalSteps: steps.length,
    stepTypeCounts,
    totalPhrases,
    avgPhrasesPerStep: totalPhrases / n,
    totalKeyTerms,
    uniqueKeyTerms: termsSeen.size,
    redundantKeyTerms: redundant,
    termsWithNikud: withNikud,
    termsWithoutNikud: withoutNikud,
    avgWhatsHappeningChars: totalWhats / n,
    avgDeeperAnalysisChars: totalDeep / n,
    totalAramaicChars: allAramaic.length,
    sourceCoverageRatio: coverageRatio(sourceLines, allAramaic),
    stepsWithMeforshim: stepsWithMef,
    totalMeforshim: totalMef,
    hasSugyaBoundaries,
    lowConfidenceSteps: lowConf,
  };
}

function formatRow(label: string, a: string, b: string, hint?: string): string {
  return `  ${label.padEnd(28)} ${a.padStart(12)} ${b.padStart(12)}${hint ? "   " + hint : ""}`;
}

function compare(orig: Metrics, neu: Metrics): string {
  const lines: string[] = [];
  lines.push(`\n=== A/B comparison ===`);
  lines.push(`  ${"".padEnd(28)} ${"ORIGINAL".padStart(12)} ${"NEW".padStart(12)}`);
  lines.push(formatRow("steps", String(orig.totalSteps), String(neu.totalSteps)));
  lines.push(
    formatRow(
      "sugya boundaries",
      orig.hasSugyaBoundaries ? "yes" : "no",
      neu.hasSugyaBoundaries ? "yes" : "no",
      neu.hasSugyaBoundaries && !orig.hasSugyaBoundaries ? "★ new" : "",
    ),
  );
  lines.push(
    formatRow(
      "phrases (total)",
      String(orig.totalPhrases),
      String(neu.totalPhrases),
    ),
  );
  lines.push(
    formatRow(
      "phrases / step",
      orig.avgPhrasesPerStep.toFixed(2),
      neu.avgPhrasesPerStep.toFixed(2),
    ),
  );
  lines.push(
    formatRow(
      "source coverage",
      (orig.sourceCoverageRatio * 100).toFixed(1) + "%",
      (neu.sourceCoverageRatio * 100).toFixed(1) + "%",
      neu.sourceCoverageRatio > orig.sourceCoverageRatio + 0.02 ? "★ better" : "",
    ),
  );
  lines.push(
    formatRow(
      "key terms (total)",
      String(orig.totalKeyTerms),
      String(neu.totalKeyTerms),
    ),
  );
  lines.push(
    formatRow(
      "unique key terms",
      String(orig.uniqueKeyTerms),
      String(neu.uniqueKeyTerms),
    ),
  );
  lines.push(
    formatRow(
      "redundant key terms",
      String(orig.redundantKeyTerms),
      String(neu.redundantKeyTerms),
      neu.redundantKeyTerms < orig.redundantKeyTerms ? "★ better" : "",
    ),
  );
  lines.push(
    formatRow(
      "terms WITH nikud",
      String(orig.termsWithNikud),
      String(neu.termsWithNikud),
    ),
  );
  lines.push(
    formatRow(
      "terms WITHOUT nikud",
      String(orig.termsWithoutNikud),
      String(neu.termsWithoutNikud),
      neu.termsWithoutNikud < orig.termsWithoutNikud ? "★ better" : "",
    ),
  );
  lines.push(
    formatRow(
      "avg whatsHappening chars",
      orig.avgWhatsHappeningChars.toFixed(0),
      neu.avgWhatsHappeningChars.toFixed(0),
      neu.avgWhatsHappeningChars < 250 && orig.avgWhatsHappeningChars > 250
        ? "★ tighter"
        : "",
    ),
  );
  lines.push(
    formatRow(
      "avg deeperAnalysis chars",
      orig.avgDeeperAnalysisChars.toFixed(0),
      neu.avgDeeperAnalysisChars.toFixed(0),
      neu.avgDeeperAnalysisChars < 400 && orig.avgDeeperAnalysisChars > 400
        ? "★ tighter"
        : "",
    ),
  );
  lines.push(
    formatRow(
      "low-confidence steps",
      String(orig.lowConfidenceSteps),
      String(neu.lowConfidenceSteps),
    ),
  );
  lines.push(
    formatRow(
      "steps with meforshim",
      String(orig.stepsWithMeforshim),
      String(neu.stepsWithMeforshim),
      neu.stepsWithMeforshim > 0 && orig.stepsWithMeforshim === 0
        ? "★ NEW capability"
        : "",
    ),
  );
  lines.push(
    formatRow(
      "meforshim comments (total)",
      String(orig.totalMeforshim),
      String(neu.totalMeforshim),
    ),
  );

  lines.push(`\n  Step-type distribution:`);
  const types = new Set([
    ...Object.keys(orig.stepTypeCounts),
    ...Object.keys(neu.stepTypeCounts),
  ]);
  for (const t of types) {
    lines.push(
      formatRow(
        `  ${t}`,
        String(orig.stepTypeCounts[t] || 0),
        String(neu.stepTypeCounts[t] || 0),
      ),
    );
  }

  return lines.join("\n");
}

function parseArgs() {
  const a = process.argv.slice(2);
  const get = (flag: string, fb?: string) => {
    const i = a.indexOf(flag);
    if (i === -1) return fb;
    return a[i + 1];
  };
  return {
    original: get("--original") ?? get("-o"),
    next: get("--next") ?? get("-n"),
    masechet: get("--masechet") ?? get("-m"),
    daf: get("--daf") ?? get("-d"),
    amud: (get("--amud") ?? "a") as "a" | "b",
  };
}

async function main() {
  const a = parseArgs();
  if (!a.original || !a.next) {
    console.error(
      "Usage: tsx scripts/compare-vs-original.ts --original <path-to-old.json> --next <path-to-new.json> -m Berakhot -d 2 -a a",
    );
    process.exit(2);
  }
  const origRaw = JSON.parse(await readFile(a.original, "utf8")) as
    | OriginalAnalysis
    | { analysis: OriginalAnalysis };
  const orig =
    "analysis" in origRaw && origRaw.analysis
      ? origRaw.analysis
      : (origRaw as OriginalAnalysis);
  const neu = JSON.parse(await readFile(a.next, "utf8")) as DafAnalysis;

  const masechet = a.masechet ?? neu.masechet;
  const daf = a.daf ? parseInt(a.daf, 10) : neu.daf;
  const amud = (a.amud ?? neu.amud) as "a" | "b";
  const source = await fetchDafText(masechet, daf, amud);

  const origMetrics = metricsFromSteps(
    "original",
    (orig.steps ?? []) as any,
    false,
    source.hebrew,
  );
  const neuMetrics = metricsFromSteps(
    "new",
    neu.steps as any,
    neu.sugyaBoundaries.length > 1,
    source.hebrew,
  );

  console.log(`Comparing ${masechet} ${daf}${amud}`);
  console.log(`Original: ${a.original}`);
  console.log(`New:      ${a.next}`);
  console.log(compare(origMetrics, neuMetrics));
}

main().catch((err) => {
  console.error("\n[FATAL]", err);
  process.exit(1);
});
