import { useEffect, useMemo, useState } from "react";
import type { DafAnalysis } from "../lib/schema.js";
import { loadAnalysis, type LibraryIndex } from "../lib/library.js";

interface Props {
  index: LibraryIndex;
  onJump: (file: string, stepNumber?: number) => void;
}

interface Hit {
  ref: string;
  file: string;
  stepNumber?: number;
  snippet: string;
  field: string;
  score: number;
}

// Cache fetched analyses so we don't re-fetch the whole library on every search.
const ANALYSIS_CACHE = new Map<string, DafAnalysis>();

function snippetAround(text: string, query: string, ctx = 50): string {
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const idx = lower.indexOf(q);
  if (idx < 0) return text.slice(0, 120);
  const start = Math.max(0, idx - ctx);
  const end = Math.min(text.length, idx + q.length + ctx);
  return (start > 0 ? "…" : "") + text.slice(start, end) + (end < text.length ? "…" : "");
}

async function loadAll(index: LibraryIndex, onProgress?: (n: number, total: number) => void): Promise<DafAnalysis[]> {
  const all: DafAnalysis[] = [];
  for (let i = 0; i < index.entries.length; i++) {
    const e = index.entries[i];
    let a = ANALYSIS_CACHE.get(e.file);
    if (!a) {
      try {
        a = await loadAnalysis(e.file);
        ANALYSIS_CACHE.set(e.file, a);
      } catch {
        continue;
      }
    }
    all.push(a);
    onProgress?.(i + 1, index.entries.length);
  }
  return all;
}

function searchAll(analyses: DafAnalysis[], query: string, max = 50): Hit[] {
  const q = query.trim();
  if (!q) return [];
  const qLower = q.toLowerCase();
  const hits: Hit[] = [];
  for (const a of analyses) {
    // mainTopic / overview
    if (a.mainTopic && a.mainTopic.toLowerCase().includes(qLower)) {
      hits.push({
        ref: a.ref,
        file: `${a.masechet}_${a.daf}${a.amud}.json`,
        snippet: snippetAround(a.mainTopic, q),
        field: "mainTopic",
        score: 10,
      });
    }
    for (const s of a.steps) {
      const fields: [string, string | undefined][] = [
        ["title", s.title],
        ["summary", s.stepSummary],
        ["whatsHappening", s.whatsHappening],
        ["deeperAnalysis", s.deeperAnalysis],
      ];
      for (const [field, val] of fields) {
        if (val && val.toLowerCase().includes(qLower)) {
          hits.push({
            ref: a.ref,
            file: `${a.masechet}_${a.daf}${a.amud}.json`,
            stepNumber: s.stepNumber,
            snippet: snippetAround(val, q),
            field,
            score: field === "title" ? 8 : 5,
          });
        }
      }
      // KeyTerms
      for (const kt of s.keyTerms || []) {
        if (
          (kt.term && kt.term.includes(q)) ||
          (kt.meaning && kt.meaning.toLowerCase().includes(qLower))
        ) {
          hits.push({
            ref: a.ref,
            file: `${a.masechet}_${a.daf}${a.amud}.json`,
            stepNumber: s.stepNumber,
            snippet: `${kt.term} — ${kt.meaning}`,
            field: "keyTerm",
            score: 7,
          });
        }
      }
      // Phrases (Aramaic + English)
      for (const p of s.phrases || []) {
        if (p.aramaic && p.aramaic.includes(q)) {
          hits.push({
            ref: a.ref,
            file: `${a.masechet}_${a.daf}${a.amud}.json`,
            stepNumber: s.stepNumber,
            snippet: snippetAround(p.aramaic, q),
            field: "phrase (aramaic)",
            score: 6,
          });
        }
        if (p.english && p.english.toLowerCase().includes(qLower)) {
          hits.push({
            ref: a.ref,
            file: `${a.masechet}_${a.daf}${a.amud}.json`,
            stepNumber: s.stepNumber,
            snippet: snippetAround(p.english, q),
            field: "phrase (english)",
            score: 4,
          });
        }
      }
      // Meforshim takeaways
      if (s.meforshim) {
        const all = [
          ...(s.meforshim.rashi || []),
          ...(s.meforshim.tosafot || []),
          ...(s.meforshim.rishonim || []),
          ...(s.meforshim.acharonim || []),
        ];
        for (const m of all) {
          if (m.takeaway && m.takeaway.toLowerCase().includes(qLower)) {
            hits.push({
              ref: a.ref,
              file: `${a.masechet}_${a.daf}${a.amud}.json`,
              stepNumber: s.stepNumber,
              snippet: `${m.source}: ${snippetAround(m.takeaway, q)}`,
              field: "meforesh",
              score: 6,
            });
          }
        }
      }
    }
  }
  hits.sort((a, b) => b.score - a.score);
  return hits.slice(0, max);
}

export function SearchPanel({ index, onJump }: Props) {
  const [query, setQuery] = useState("");
  const [analyses, setAnalyses] = useState<DafAnalysis[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadedN, setLoadedN] = useState(0);

  // Load all once when search becomes used.
  async function ensureLoaded() {
    if (analyses.length >= index.entries.length || loading) return;
    setLoading(true);
    setLoadedN(0);
    try {
      const all = await loadAll(index, (n) => setLoadedN(n));
      setAnalyses(all);
    } finally {
      setLoading(false);
    }
  }

  const hits = useMemo(() => searchAll(analyses, query, 80), [analyses, query]);

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 14,
        marginBottom: 16,
        background: "var(--panel)",
      }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <input
          type="search"
          placeholder="Search across all built dapim… (e.g. חזקה, kal vchomer, מציאה)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={ensureLoaded}
          style={{
            flex: 1,
            background: "var(--panel-2)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 14,
          }}
        />
        <span style={{ fontSize: 11, color: "var(--muted)" }}>
          {loading ? `loading ${loadedN}/${index.entries.length}…` :
            analyses.length ? `${analyses.length} dapim indexed` : "click to load"}
        </span>
      </div>
      {hits.length > 0 && (
        <div style={{ marginTop: 12, maxHeight: 360, overflowY: "auto" }}>
          {hits.map((h, i) => (
            <button
              key={i}
              onClick={() => onJump(h.file, h.stepNumber)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "transparent",
                border: "none",
                borderBottom: "1px solid var(--border-2)",
                padding: "8px 4px",
                color: "var(--text)",
                cursor: "pointer",
                fontSize: 13,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.04)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <div style={{ color: "var(--accent)", fontWeight: 600 }}>
                {h.ref}
                {h.stepNumber ? ` · step #${h.stepNumber}` : ""}
                <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 8, fontSize: 11 }}>
                  ({h.field})
                </span>
              </div>
              <div style={{ color: "var(--soft)", marginTop: 2 }}>{h.snippet}</div>
            </button>
          ))}
        </div>
      )}
      {query && hits.length === 0 && analyses.length > 0 && !loading && (
        <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 12 }}>
          No matches in {analyses.length} dapim.
        </div>
      )}
    </div>
  );
}
