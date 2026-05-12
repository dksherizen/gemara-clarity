import { writeFile, readFile, mkdir, access } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { LLMRouter } from "../src/lib/llm/router.js";
import type { PipelinePass, Provider } from "../src/lib/llm/types.js";
import { runFullPipeline } from "../src/lib/pipeline/orchestrator.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

const MASECHTOT: Record<string, number> = {
  Berakhot: 64,
  Shabbat: 157,
  Eruvin: 105,
  Pesachim: 121,
  Yoma: 88,
  Sukkah: 56,
  Beitzah: 40,
  Rosh_Hashanah: 35,
  Taanit: 31,
  Megillah: 32,
  Moed_Katan: 29,
  Chagigah: 27,
  Yevamot: 122,
  Ketubot: 112,
  Nedarim: 91,
  Nazir: 66,
  Sotah: 49,
  Gittin: 90,
  Kiddushin: 82,
  Bava_Kamma: 119,
  Bava_Metzia: 119,
  Bava_Batra: 176,
  Sanhedrin: 113,
  Makkot: 24,
  Shevuot: 49,
  Avodah_Zarah: 76,
  Horayot: 14,
  Zevachim: 120,
  Menachot: 110,
  Chullin: 141,
  Bekhorot: 61,
  Arakhin: 34,
  Temurah: 34,
  Keritot: 28,
  Meilah: 22,
  Tamid: 33,
  Niddah: 73,
};

interface Args {
  masechet: string;
  startDaf: number;
  endDaf?: number;
  startAmud: "a" | "b";
  meforshim: boolean;
  delayMs: number;
  retry: number;
  budgetUSD?: number;
}

function parseArgs(): Args {
  const args = process.argv.slice(2);
  const get = (flag: string, fallback?: string) => {
    const i = args.indexOf(flag);
    if (i === -1) return fallback;
    return args[i + 1];
  };
  const masechet = get("--masechet") ?? get("-m") ?? "Berakhot";
  if (!MASECHTOT[masechet]) {
    throw new Error(
      `Unknown masechet '${masechet}'. Valid: ${Object.keys(MASECHTOT).join(", ")}`,
    );
  }
  return {
    masechet,
    startDaf: parseInt(get("--from") ?? get("--start") ?? "2", 10),
    endDaf: get("--to") ? parseInt(get("--to")!, 10) : undefined,
    startAmud: (get("--start-amud") ?? "a") as "a" | "b",
    meforshim: !args.includes("--no-meforshim"),
    delayMs: parseInt(get("--delay") ?? "0", 10),
    retry: parseInt(get("--retry") ?? "1", 10),
  };
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

async function fileExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

async function updateIndex(dataDir: string): Promise<void> {
  const indexPath = join(dataDir, "index.json");
  const entries: Array<{
    ref: string;
    masechet: string;
    daf: number;
    amud: "a" | "b";
    mainTopic: string;
    generatedAt: string;
    file: string;
  }> = [];

  for (const [masechet, max] of Object.entries(MASECHTOT)) {
    for (let d = 2; d <= max; d++) {
      for (const amud of ["a", "b"] as const) {
        const file = `${masechet}_${d}${amud}.json`;
        const fp = join(dataDir, file);
        if (!(await fileExists(fp))) continue;
        try {
          const raw = await readFile(fp, "utf8");
          const a = JSON.parse(raw);
          entries.push({
            ref: a.ref,
            masechet: a.masechet,
            daf: a.daf,
            amud: a.amud,
            mainTopic: a.mainTopic,
            generatedAt: a.generatedAt,
            file,
          });
        } catch {
          /* skip malformed */
        }
      }
    }
  }

  entries.sort((a, b) => {
    if (a.masechet !== b.masechet) return a.masechet.localeCompare(b.masechet);
    if (a.daf !== b.daf) return a.daf - b.daf;
    return a.amud.localeCompare(b.amud);
  });

  await writeFile(
    indexPath,
    JSON.stringify({ generatedAt: new Date().toISOString(), entries }, null, 2),
    "utf8",
  );
}

async function processOne(
  router: LLMRouter,
  masechet: string,
  daf: number,
  amud: "a" | "b",
  dataDir: string,
  meforshim: boolean,
  retry: number,
): Promise<"ok" | "skipped" | "failed"> {
  const file = `${masechet}_${daf}${amud}.json`;
  const out = join(dataDir, file);
  if (await fileExists(out)) {
    console.log(`  · skipping ${masechet} ${daf}${amud} (already exists)`);
    return "skipped";
  }
  for (let attempt = 1; attempt <= retry; attempt++) {
    try {
      const started = Date.now();
      console.log(`  · processing ${masechet} ${daf}${amud} (attempt ${attempt}/${retry})…`);
      const analysis = await runFullPipeline(router, {
        masechet,
        daf,
        amud,
        enableMeforshim: meforshim,
        onProgress: () => {},
      });
      await writeFile(out, JSON.stringify(analysis, null, 2), "utf8");
      const secs = Math.round((Date.now() - started) / 1000);
      console.log(
        `    → ok (${secs}s, ${analysis.steps.length} steps, ${analysis.sugyaBoundaries.length} sugyot)`,
      );
      return "ok";
    } catch (err) {
      console.warn(
        `    ⚠ attempt ${attempt} failed: ${(err as Error).message.slice(0, 200)}`,
      );
      if (attempt === retry) return "failed";
    }
  }
  return "failed";
}

async function sleep(ms: number) {
  if (ms <= 0) return;
  return new Promise<void>((r) => setTimeout(r, ms));
}

async function main() {
  const a = parseArgs();
  const max = MASECHTOT[a.masechet];
  const endDaf = a.endDaf ?? max;

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

  if (router.availableProviders().length === 0) {
    console.error("No LLM providers configured. See .env.example.");
    process.exit(1);
  }

  const dataDir = join(ROOT, "public", "data");
  await mkdir(dataDir, { recursive: true });

  console.log(
    `Batching ${a.masechet} from daf ${a.startDaf}${a.startAmud} to daf ${endDaf}b`,
  );
  console.log(`Providers: ${router.availableProviders().join(", ")}`);
  console.log(`Meforshim: ${a.meforshim ? "ON" : "OFF"}`);
  console.log("");

  let ok = 0, skipped = 0, failed = 0;
  const overallStarted = Date.now();
  for (let d = a.startDaf; d <= endDaf; d++) {
    const amudim: ("a" | "b")[] =
      d === a.startDaf && a.startAmud === "b" ? ["b"] : ["a", "b"];
    for (const amud of amudim) {
      const res = await processOne(
        router,
        a.masechet,
        d,
        amud,
        dataDir,
        a.meforshim,
        a.retry,
      );
      if (res === "ok") ok++;
      else if (res === "skipped") skipped++;
      else failed++;
      await updateIndex(dataDir);
      await sleep(a.delayMs);
    }
  }
  const mins = Math.round((Date.now() - overallStarted) / 60000);
  console.log(`\nDone in ${mins}m. ok=${ok} skipped=${skipped} failed=${failed}`);
}

main().catch((err) => {
  console.error("\n[FATAL]", err);
  process.exit(1);
});
