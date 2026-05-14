import { readFile } from "node:fs/promises";
import { DafAnalysisSchema, HEBREW_STEP_NAMES } from "../src/lib/schema.js";
import { fetchDafText } from "../src/lib/sefaria/index.js";

interface QualityIssue {
  severity: "critical" | "warning" | "nit";
  category: string;
  detail: string;
  stepNumber?: number;
}

interface QualityReport {
  file: string;
  ref: string;
  pass: boolean;
  score: number;
  metrics: Record<string, number | string>;
  issues: QualityIssue[];
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

function coverageRatio(source: string, generated: string): number {
  const src = normalizeForCoverage(source);
  const gen = normalizeForCoverage(generated);
  if (src.length === 0) return 1;
  let gi = 0;
  let matched = 0;
  const lookahead = 20;
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

export async function checkDaf(filePath: string): Promise<QualityReport> {
  const raw = await readFile(filePath, "utf8");
  const data = JSON.parse(raw);
  const issues: QualityIssue[] = [];

  // 1. Schema validation
  const result = DafAnalysisSchema.safeParse(data);
  if (!result.success) {
    issues.push({
      severity: "critical",
      category: "schema",
      detail: `Schema validation failed: ${result.error.issues.slice(0, 3).map((i) => `${i.path.join(".")}: ${i.message}`).join("; ")}`,
    });
  }

  const a = data;
  const steps = a.steps ?? [];

  // 2. Basic structure
  if (steps.length === 0) {
    issues.push({ severity: "critical", category: "structure", detail: "Zero steps in daf" });
  }
  if (!a.mainTopic || a.mainTopic.length < 10) {
    issues.push({ severity: "warning", category: "structure", detail: "mainTopic missing or too short" });
  }
  if (!a.overview || a.overview.length < 30) {
    issues.push({ severity: "warning", category: "structure", detail: "overview missing or too short" });
  }
  if (!a.sugyaBoundaries || a.sugyaBoundaries.length === 0) {
    issues.push({ severity: "warning", category: "structure", detail: "No sugya boundaries" });
  }

  // 3. Step-level checks
  const allTerms = new Set<string>();
  let termsWithoutNikud = 0;
  let stepsWithoutPhrases = 0;
  let stepsWithoutTitle = 0;
  let stepsWithInvalidName = 0;
  let stepsWithMeforshim = 0;
  let totalRashi = 0;
  let totalAramaicText = "";

  for (const s of steps) {
    if (!s.title || s.title.length < 3) stepsWithoutTitle++;
    if (!HEBREW_STEP_NAMES.includes(s.hebrewStepName)) stepsWithInvalidName++;
    if (!s.phrases || s.phrases.length === 0) stepsWithoutPhrases++;
    for (const p of s.phrases ?? []) totalAramaicText += " " + (p.aramaic ?? "");
    for (const t of s.keyTerms ?? []) {
      allTerms.add((t.term ?? "").replace(/[֑-ׇ]/g, ""));
      if (!NIKUD_RX.test(t.term ?? "")) termsWithoutNikud++;
    }
    if (s.meforshim) {
      const mef = s.meforshim;
      const count =
        (mef.rashi?.length ?? 0) +
        (mef.tosafot?.length ?? 0) +
        (mef.rishonim?.length ?? 0) +
        (mef.acharonim?.length ?? 0);
      if (count > 0) stepsWithMeforshim++;
      totalRashi += mef.rashi?.length ?? 0;
    }
  }

  if (stepsWithInvalidName > 0)
    issues.push({ severity: "critical", category: "classification", detail: `${stepsWithInvalidName} step(s) have invalid hebrewStepName` });
  if (stepsWithoutPhrases > 0)
    issues.push({ severity: "critical", category: "coverage", detail: `${stepsWithoutPhrases} step(s) have no phrases` });
  if (stepsWithoutTitle > 0)
    issues.push({ severity: "warning", category: "structure", detail: `${stepsWithoutTitle} step(s) have missing/short title` });
  if (termsWithoutNikud > 0)
    issues.push({ severity: "warning", category: "nikud", detail: `${termsWithoutNikud} key term(s) missing nikud` });

  // 4. Source coverage from Sefaria
  let coverage = 0;
  let sourceLineCount = 0;
  try {
    const src = await fetchDafText(a.masechet, a.daf, a.amud);
    sourceLineCount = src.hebrew.length;
    coverage = coverageRatio(src.hebrew.join(" "), totalAramaicText);
    if (coverage < 0.85) {
      issues.push({
        severity: "critical",
        category: "coverage",
        detail: `Source coverage only ${(coverage * 100).toFixed(1)}% — missing significant source text`,
      });
    } else if (coverage < 0.95) {
      issues.push({
        severity: "warning",
        category: "coverage",
        detail: `Source coverage ${(coverage * 100).toFixed(1)}% — slightly under 95% target`,
      });
    }
  } catch (e) {
    issues.push({ severity: "warning", category: "verification", detail: `Could not fetch Sefaria source: ${(e as Error).message}` });
  }

  // 5. Sugya boundary sanity
  for (const sugya of a.sugyaBoundaries ?? []) {
    if (sugya.startLine > sugya.endLine) {
      issues.push({
        severity: "warning",
        category: "boundaries",
        detail: `Sugya ${sugya.sugyaNumber} has startLine > endLine`,
      });
    }
    if (sourceLineCount > 0 && sugya.endLine > sourceLineCount) {
      issues.push({
        severity: "warning",
        category: "boundaries",
        detail: `Sugya ${sugya.sugyaNumber} endLine (${sugya.endLine}) exceeds source line count (${sourceLineCount})`,
      });
    }
  }

  // 6. Final score: 100 minus penalty per issue
  let score = 100;
  for (const i of issues) {
    if (i.severity === "critical") score -= 25;
    else if (i.severity === "warning") score -= 7;
    else score -= 2;
  }
  score = Math.max(0, score);

  return {
    file: filePath,
    ref: a.ref ?? "?",
    pass: !issues.some((i) => i.severity === "critical"),
    score,
    metrics: {
      steps: steps.length,
      sugyot: (a.sugyaBoundaries ?? []).length,
      uniqueKeyTerms: allTerms.size,
      termsWithoutNikud,
      stepsWithMeforshim,
      totalRashi,
      sourceCoverage: `${(coverage * 100).toFixed(1)}%`,
    },
    issues,
  };
}

async function main() {
  const files = process.argv.slice(2);
  if (files.length === 0) {
    console.error("Usage: tsx scripts/quality-check.ts <path-to-daf.json> [more.json ...]");
    process.exit(2);
  }
  let allPass = true;
  for (const f of files) {
    const r = await checkDaf(f);
    console.log(`\n=== ${r.ref} (${r.file}) ===`);
    console.log(`Pass: ${r.pass ? "✅" : "❌"}  Score: ${r.score}/100`);
    console.log(`Metrics:`, r.metrics);
    if (r.issues.length > 0) {
      console.log(`Issues (${r.issues.length}):`);
      for (const i of r.issues) {
        const icon = i.severity === "critical" ? "🔴" : i.severity === "warning" ? "🟡" : "⚪";
        console.log(`  ${icon} [${i.category}] ${i.detail}`);
      }
    }
    if (!r.pass) allPass = false;
  }
  process.exit(allPass ? 0 : 1);
}

main().catch((e) => {
  console.error("[FATAL]", e);
  process.exit(2);
});
