import { writeFile, mkdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

// Convert Firestore REST API value representation to plain JSON
function unwrap(v: any): any {
  if (v === null || v === undefined) return v;
  if (typeof v !== "object") return v;
  if ("stringValue" in v) return v.stringValue;
  if ("integerValue" in v) return parseInt(v.integerValue, 10);
  if ("doubleValue" in v) return v.doubleValue;
  if ("booleanValue" in v) return v.booleanValue;
  if ("timestampValue" in v) return v.timestampValue;
  if ("nullValue" in v) return null;
  if ("arrayValue" in v) return (v.arrayValue.values || []).map(unwrap);
  if ("mapValue" in v) {
    const out: Record<string, any> = {};
    for (const [k, val] of Object.entries(v.mapValue.fields || {})) {
      out[k] = unwrap(val);
    }
    return out;
  }
  return v;
}

async function main() {
  const args = process.argv.slice(2);
  const get = (flag: string, fb?: string) => {
    const i = args.indexOf(flag);
    return i === -1 ? fb : args[i + 1];
  };
  const masechet = get("-m") ?? "Berakhot";
  const daf = get("-d") ?? "2";
  const amud = get("-a") ?? "a";

  const refId = `${masechet}_${daf}_${amud}`;
  const url = `https://firestore.googleapis.com/v1/projects/gemara-clarity/databases/(default)/documents/artifacts/gemara-clarity-public/public/data/gemara_cache_v5/${refId}`;

  console.log(`Fetching original analysis for ${masechet} ${daf}${amud}…`);
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Firestore returned ${r.status}: ${await r.text()}`);
  const raw = await r.json();

  // Firestore doc envelope: { name, fields: { analysis: {mapValue}, timestamp: {stringValue} } }
  const analysisField = raw.fields?.analysis;
  if (!analysisField) {
    throw new Error(`No 'analysis' field in document. Got: ${JSON.stringify(raw).slice(0, 300)}`);
  }
  const analysis = unwrap(analysisField);

  const outDir = join(ROOT, "data", "originals");
  await mkdir(outDir, { recursive: true });
  const out = join(outDir, `${masechet}_${daf}${amud}.json`);
  await writeFile(out, JSON.stringify(analysis, null, 2), "utf8");

  const stepCount = analysis?.steps?.length ?? 0;
  console.log(`Wrote ${out} (${stepCount} steps)`);
  if (analysis?.mainTopic) console.log(`  topic: ${analysis.mainTopic}`);
}

main().catch((err) => {
  console.error("[FATAL]", err);
  process.exit(1);
});
