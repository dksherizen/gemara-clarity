import { writeFile, mkdir, unlink } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { LLMRouter } from "../src/lib/llm/router.js";
import type { PipelinePass, Provider } from "../src/lib/llm/types.js";
import { runFullPipeline } from "../src/lib/pipeline/orchestrator.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const PROGRESS_PATH = join(ROOT, "public", "data", "progress.json");

interface Progress {
  active: boolean;
  ref: string;
  startedAt: string;
  elapsedSec: number;
  lastUpdateAt: string;
  log: Array<{ ts: number; msg: string }>;
}

async function writeProgress(p: Progress): Promise<void> {
  try {
    await writeFile(PROGRESS_PATH, JSON.stringify(p, null, 2), "utf8");
  } catch {
    /* non-fatal */
  }
}

function parseArgs(): {
  masechet: string;
  daf: number;
  amud: "a" | "b";
  out: string;
  meforshim: boolean;
} {
  const args = process.argv.slice(2);
  const get = (flag: string, fallback?: string) => {
    const i = args.indexOf(flag);
    if (i === -1) return fallback;
    return args[i + 1];
  };
  const masechet = get("--masechet") ?? get("-m") ?? "Berakhot";
  const daf = parseInt(get("--daf") ?? get("-d") ?? "2", 10);
  const amud = (get("--amud") ?? get("-a") ?? "a") as "a" | "b";
  const out =
    get("--out") ??
    get("-o") ??
    join(ROOT, "public", "data", `${masechet}_${daf}${amud}.json`);
  const meforshim = !args.includes("--no-meforshim");
  return { masechet, daf, amud, out, meforshim };
}

function passOverridesFromEnv(): Partial<Record<PipelinePass, Provider>> {
  const map: Partial<Record<PipelinePass, Provider>> = {};
  const passes: PipelinePass[] = [
    "segmentation",
    "structure",
    "phrasemap",
    "meforshim",
    "teaching",
    "validate",
  ];
  for (const p of passes) {
    const v = process.env[`PASS_${p.toUpperCase()}_PROVIDER`];
    if (v) map[p] = v as Provider;
  }
  return map;
}

async function main() {
  const { masechet, daf, amud, out, meforshim } = parseArgs();

  const router = new LLMRouter({
    anthropicKey: process.env.ANTHROPIC_API_KEY,
    openaiKey: process.env.OPENAI_API_KEY,
    googleKey: process.env.GOOGLE_API_KEY,
    anthropicModel: process.env.ANTHROPIC_MODEL,
    openaiModel: process.env.OPENAI_MODEL,
    googleModel: process.env.GOOGLE_MODEL,
    lmstudioBaseURL: process.env.LMSTUDIO_BASE_URL,
    lmstudioModel: process.env.LMSTUDIO_MODEL,
    passProviders: passOverridesFromEnv(),
  });

  const available = router.availableProviders();
  if (available.length === 0) {
    console.error(
      "No LLM providers configured. Set at least one of:\n" +
        "  ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, or LMSTUDIO_BASE_URL\n" +
        "in the environment (or in .env loaded via `node --env-file .env`).",
    );
    process.exit(1);
  }
  console.log(`Providers available: ${available.join(", ")}`);
  console.log(`Target: ${masechet} ${daf}${amud}`);
  console.log(`Output: ${out}`);
  console.log(`Meforshim: ${meforshim ? "ON" : "OFF"}`);
  console.log("");

  const started = Date.now();
  const ref = `${masechet} ${daf}${amud}`;
  const logBuffer: Array<{ ts: number; msg: string }> = [];

  await mkdir(dirname(PROGRESS_PATH), { recursive: true });
  await writeProgress({
    active: true,
    ref,
    startedAt: new Date(started).toISOString(),
    elapsedSec: 0,
    lastUpdateAt: new Date().toISOString(),
    log: [{ ts: 0, msg: "Pipeline started…" }],
  });

  let analysis;
  try {
    analysis = await runFullPipeline(router, {
      masechet,
      daf,
      amud,
      enableMeforshim: meforshim,
      onProgress: (msg) => {
        const ts = (Date.now() - started) / 1000;
        console.log(`[${elapsed(started)}] ${msg}`);
        logBuffer.push({ ts, msg });
        if (logBuffer.length > 200) logBuffer.shift();
        void writeProgress({
          active: true,
          ref,
          startedAt: new Date(started).toISOString(),
          elapsedSec: Math.round(ts),
          lastUpdateAt: new Date().toISOString(),
          log: logBuffer,
        });
      },
    });
  } catch (err) {
    await writeProgress({
      active: false,
      ref,
      startedAt: new Date(started).toISOString(),
      elapsedSec: Math.round((Date.now() - started) / 1000),
      lastUpdateAt: new Date().toISOString(),
      log: [
        ...logBuffer,
        { ts: (Date.now() - started) / 1000, msg: `FAILED: ${(err as Error).message.slice(0, 200)}` },
      ],
    });
    throw err;
  }

  await mkdir(dirname(out), { recursive: true });
  await writeFile(out, JSON.stringify(analysis, null, 2), "utf8");
  const cost = analysis.cost;
  console.log(
    `\nDone in ${elapsed(started)} — ${analysis.steps.length} steps, ${analysis.sugyaBoundaries.length} sugyot.`,
  );
  if (cost) {
    console.log(
      `Cost: $${cost.totalUSD.toFixed(3)} (${cost.totalInputTokens.toLocaleString()} in / ${cost.totalOutputTokens.toLocaleString()} out tokens)`,
    );
    console.log(
      `  by pass: ${Object.entries(cost.byPass)
        .map(([p, c]) => `${p}=$${c.toFixed(3)}`)
        .join(", ")}`,
    );
  }
  console.log(`Wrote ${out}`);
  await updateIndex(dirname(out));

  logBuffer.push({
    ts: (Date.now() - started) / 1000,
    msg: `Done — ${analysis.steps.length} steps, ${analysis.sugyaBoundaries.length} sugyot.`,
  });
  await writeProgress({
    active: false,
    ref,
    startedAt: new Date(started).toISOString(),
    elapsedSec: Math.round((Date.now() - started) / 1000),
    lastUpdateAt: new Date().toISOString(),
    log: logBuffer,
  });
}

async function updateIndex(dataDir: string): Promise<void> {
  const { readFile, readdir } = await import("node:fs/promises");
  const indexPath = join(dataDir, "index.json");
  const files = await readdir(dataDir);
  const entries: Array<Record<string, unknown>> = [];
  for (const f of files.sort()) {
    if (!f.endsWith(".json") || f === "index.json") continue;
    try {
      const a = JSON.parse(await readFile(join(dataDir, f), "utf8"));
      entries.push({
        ref: a.ref,
        masechet: a.masechet,
        daf: a.daf,
        amud: a.amud,
        mainTopic: a.mainTopic,
        generatedAt: a.generatedAt,
        file: f,
      });
    } catch {
      /* skip malformed */
    }
  }
  await writeFile(
    indexPath,
    JSON.stringify({ generatedAt: new Date().toISOString(), entries }, null, 2),
    "utf8",
  );
  console.log(`Updated library index (${entries.length} entries).`);
}

function elapsed(start: number): string {
  const ms = Date.now() - start;
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

main().catch((err) => {
  console.error("\n[FATAL]", err);
  process.exit(1);
});
