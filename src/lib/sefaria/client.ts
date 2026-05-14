import type { DafSourceText } from "../schema.js";

const SEFARIA_BASE = "https://www.sefaria.org/api";

export interface SefariaLink {
  ref: string;
  anchorRef: string;
  anchorRefExpanded: string[];
  sourceRef: string;
  sourceHeRef: string;
  category: string;
  type: string;
  indexTitle: string;
  collectiveTitle: { en: string; he: string };
  sourceHasEn: boolean;
  compDate?: [number, number];
}

export interface SefariaTextResponse {
  ref: string;
  heRef: string;
  text: string | string[] | string[][];
  he: string | string[] | string[][];
  versions?: unknown[];
  isComplex?: boolean;
}

export interface MeforeshLink {
  collectiveTitle: string;
  hebrewTitle: string;
  anchorRef: string;
  sourceRef: string;
  category: string;
  hasEnglish: boolean;
  compositionYear?: number;
}

export interface MeforeshWithText extends MeforeshLink {
  hebrew: string;
  english: string;
}

// Rashi + Tosafot — required for Bavli, especially Bava Metzia where Tosafot
// is foundational. Override per-call with options.extraSeforim.
const CORE_MEFORSHIM = new Set([
  "Rashi",
  "Tosafot",
]);

function flattenStrings(value: SefariaTextResponse["text"]): string[] {
  if (!value) return [];
  if (typeof value === "string") return [value];
  return value.flatMap(flattenStrings as (v: string | string[]) => string[]);
}

function stripHtml(s: string): string {
  return s
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`Sefaria ${r.status} ${r.statusText} for ${url}`);
  return (await r.json()) as T;
}

export async function fetchDafText(
  masechet: string,
  daf: number,
  amud: "a" | "b",
): Promise<DafSourceText> {
  const ref = `${masechet}.${daf}${amud}`;
  const url = `${SEFARIA_BASE}/texts/${encodeURIComponent(ref)}?context=0&commentary=0`;
  const data = await getJSON<SefariaTextResponse>(url);
  const hebrew = flattenStrings(data.he).map(stripHtml).filter(Boolean);
  const english = flattenStrings(data.text).map(stripHtml).filter(Boolean);
  if (!hebrew.length) throw new Error(`No source text returned for ${ref}`);
  return {
    ref: data.ref ?? ref,
    masechet,
    daf,
    amud,
    hebrew,
    english,
  };
}

export async function fetchLinksForDaf(
  masechet: string,
  daf: number,
  amud: "a" | "b",
): Promise<SefariaLink[]> {
  const ref = `${masechet}.${daf}${amud}`;
  const url = `${SEFARIA_BASE}/links/${encodeURIComponent(ref)}?with_text=0`;
  const raw = await getJSON<Array<Record<string, unknown>>>(url);
  return raw.map((row) => ({
    ref: String(row.ref ?? ""),
    anchorRef: String(row.anchorRef ?? ""),
    anchorRefExpanded: (row.anchorRefExpanded as string[]) ?? [],
    sourceRef: String(row.sourceRef ?? ""),
    sourceHeRef: String(row.sourceHeRef ?? ""),
    category: String(row.category ?? ""),
    type: String(row.type ?? ""),
    indexTitle: String(row.index_title ?? ""),
    collectiveTitle: (row.collectiveTitle as { en: string; he: string }) ?? {
      en: "",
      he: "",
    },
    sourceHasEn: Boolean(row.sourceHasEn),
    compDate: row.compDate as [number, number] | undefined,
  }));
}

export function filterMeforshim(
  links: SefariaLink[],
  options: { extraSeforim?: string[]; categoriesToInclude?: string[] } = {},
): MeforeshLink[] {
  const allowed = new Set([...CORE_MEFORSHIM, ...(options.extraSeforim ?? [])]);
  const cats = new Set(options.categoriesToInclude ?? ["Commentary"]);
  return links
    .filter((l) => cats.has(l.category) && allowed.has(l.collectiveTitle.en))
    .map((l) => ({
      collectiveTitle: l.collectiveTitle.en,
      hebrewTitle: l.collectiveTitle.he,
      anchorRef: l.anchorRef,
      sourceRef: l.sourceRef,
      category: l.category,
      hasEnglish: l.sourceHasEn,
      compositionYear: l.compDate?.[0],
    }));
}

export async function fetchCommentaryText(
  sourceRef: string,
): Promise<{ hebrew: string; english: string }> {
  const url = `${SEFARIA_BASE}/texts/${encodeURIComponent(
    sourceRef,
  )}?context=0&commentary=0`;
  const data = await getJSON<SefariaTextResponse>(url);
  const hebrew = flattenStrings(data.he).map(stripHtml).join(" ").trim();
  const english = flattenStrings(data.text).map(stripHtml).join(" ").trim();
  return { hebrew, english };
}

export async function fetchMeforshimByAnchor(
  masechet: string,
  daf: number,
  amud: "a" | "b",
  options?: { extraSeforim?: string[]; concurrency?: number },
): Promise<Map<string, MeforeshWithText[]>> {
  const links = await fetchLinksForDaf(masechet, daf, amud);
  const meforshim = filterMeforshim(links, options);
  const concurrency = options?.concurrency ?? 6;
  const results: MeforeshWithText[] = [];
  let i = 0;
  async function worker() {
    while (i < meforshim.length) {
      const idx = i++;
      const m = meforshim[idx];
      try {
        const txt = await fetchCommentaryText(m.sourceRef);
        results.push({ ...m, hebrew: txt.hebrew, english: txt.english });
      } catch (err) {
        results.push({ ...m, hebrew: "", english: "" });
      }
    }
  }
  await Promise.all(
    Array(Math.min(concurrency, meforshim.length)).fill(0).map(worker),
  );

  const byAnchor = new Map<string, MeforeshWithText[]>();
  for (const m of results) {
    if (!byAnchor.has(m.anchorRef)) byAnchor.set(m.anchorRef, []);
    byAnchor.get(m.anchorRef)!.push(m);
  }
  return byAnchor;
}
