import type { DafAnalysis } from "./schema.js";

export interface LibraryIndexEntry {
  ref: string;
  masechet: string;
  daf: number;
  amud: "a" | "b";
  mainTopic: string;
  generatedAt: string;
  file: string;
}

export interface LibraryIndex {
  generatedAt: string;
  entries: LibraryIndexEntry[];
}

export async function loadLibraryIndex(): Promise<LibraryIndex> {
  try {
    const r = await fetch("/data/index.json", { cache: "no-cache" });
    if (!r.ok) return { generatedAt: new Date().toISOString(), entries: [] };
    return (await r.json()) as LibraryIndex;
  } catch {
    return { generatedAt: new Date().toISOString(), entries: [] };
  }
}

export async function loadAnalysis(file: string): Promise<DafAnalysis> {
  const r = await fetch(`/data/${file}`, { cache: "no-cache" });
  if (!r.ok) throw new Error(`Failed to load /data/${file}: ${r.status}`);
  return (await r.json()) as DafAnalysis;
}
