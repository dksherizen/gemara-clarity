import { useMemo } from "react";
import type { LibraryIndex, LibraryIndexEntry } from "../lib/library.js";

// Canonical Shas order — full list of masechtos.
const SHAS_ORDER: Array<[string, number]> = [
  ["Berakhot", 64],
  ["Shabbat", 157],
  ["Eruvin", 105],
  ["Pesachim", 121],
  ["Yoma", 88],
  ["Sukkah", 56],
  ["Beitzah", 40],
  ["Rosh_Hashanah", 35],
  ["Taanit", 31],
  ["Megillah", 32],
  ["Moed_Katan", 29],
  ["Chagigah", 27],
  ["Yevamot", 122],
  ["Ketubot", 112],
  ["Nedarim", 91],
  ["Nazir", 66],
  ["Sotah", 49],
  ["Gittin", 90],
  ["Kiddushin", 82],
  ["Bava_Kamma", 119],
  ["Bava_Metzia", 119],
  ["Bava_Batra", 176],
  ["Sanhedrin", 113],
  ["Makkot", 24],
  ["Shevuot", 49],
  ["Avodah_Zarah", 76],
  ["Horayot", 14],
  ["Zevachim", 120],
  ["Menachot", 110],
  ["Chullin", 141],
  ["Bekhorot", 61],
  ["Arakhin", 34],
  ["Temurah", 34],
  ["Keritot", 28],
  ["Meilah", 22],
  ["Tamid", 33],
  ["Niddah", 73],
];

interface Props {
  library: LibraryIndex;
  current: LibraryIndexEntry | null;
  onSelect: (file: string) => void;
}

export function QuickPicker({ library, current, onSelect }: Props) {
  // Index: masechet -> { dapim available, by-amud sets }
  const availability = useMemo(() => {
    const map = new Map<string, Map<number, Set<string>>>();
    for (const e of library.entries) {
      if (!map.has(e.masechet)) map.set(e.masechet, new Map());
      const dafMap = map.get(e.masechet)!;
      if (!dafMap.has(e.daf)) dafMap.set(e.daf, new Set());
      dafMap.get(e.daf)!.add(e.amud);
    }
    return map;
  }, [library.entries]);

  const masechet = current?.masechet || "Bava_Metzia";
  const daf = current?.daf ?? 2;
  const amud = current?.amud ?? "a";

  const masechetDafMap = availability.get(masechet) || new Map();
  const dapimAvailable = [...masechetDafMap.keys()].sort((a, b) => a - b);
  const amudimAvailableForCurrentDaf = masechetDafMap.get(daf) || new Set();

  // For the daf-number dropdown, show ALL dapim of the masechet (so user can
  // see scope), with available ones rendered normally and missing ones greyed.
  const allDapim = useMemo(() => {
    const total = SHAS_ORDER.find(([m]) => m === masechet)?.[1] ?? 64;
    const arr: number[] = [];
    for (let i = 2; i <= total; i++) arr.push(i);
    return arr;
  }, [masechet]);

  function findEntry(m: string, d: number, a: string): LibraryIndexEntry | null {
    return (
      library.entries.find((e) => e.masechet === m && e.daf === d && e.amud === a) ||
      null
    );
  }

  function onMasechetChange(m: string) {
    // Jump to first available daf in this masechet (a-side preferred).
    const dafMap = availability.get(m);
    if (!dafMap || dafMap.size === 0) return;
    const firstDaf = [...dafMap.keys()].sort((a, b) => a - b)[0];
    const sides = dafMap.get(firstDaf)!;
    const firstAmud = sides.has("a") ? "a" : "b";
    const entry = findEntry(m, firstDaf, firstAmud);
    if (entry) onSelect(entry.file);
  }

  function onDafChange(d: number) {
    // Stay on same amud if available; otherwise switch to the side that is.
    const sides = masechetDafMap.get(d) || new Set();
    const targetAmud = sides.has(amud) ? amud : sides.has("a") ? "a" : "b";
    if (!sides.has(targetAmud)) return;
    const entry = findEntry(masechet, d, targetAmud);
    if (entry) onSelect(entry.file);
  }

  function onAmudClick(a: "a" | "b") {
    if (!amudimAvailableForCurrentDaf.has(a)) return;
    const entry = findEntry(masechet, daf, a);
    if (entry) onSelect(entry.file);
  }

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        padding: "8px 12px",
        background: "var(--panel-2)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        marginBottom: 12,
        flexWrap: "wrap",
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 800,
          color: "var(--accent)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          paddingRight: 4,
        }}
      >
        Quick pick
      </span>

      <select
        value={masechet}
        onChange={(e) => onMasechetChange(e.target.value)}
        style={{
          background: "var(--panel)",
          color: "var(--text)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 13,
          cursor: "pointer",
        }}
      >
        {SHAS_ORDER.map(([m]) => {
          const hasData = availability.has(m);
          return (
            <option
              key={m}
              value={m}
              disabled={!hasData}
              style={{ color: hasData ? "inherit" : "#888" }}
            >
              {m.replaceAll("_", " ")}
              {!hasData ? " (empty)" : ""}
            </option>
          );
        })}
      </select>

      <select
        value={daf}
        onChange={(e) => onDafChange(parseInt(e.target.value, 10))}
        style={{
          background: "var(--panel)",
          color: "var(--text)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 13,
          cursor: "pointer",
          minWidth: 72,
        }}
      >
        {allDapim.map((d) => {
          const sides = masechetDafMap.get(d);
          const hasAny = sides && sides.size > 0;
          return (
            <option
              key={d}
              value={d}
              disabled={!hasAny}
              style={{ color: hasAny ? "inherit" : "#888" }}
            >
              {d}
              {!hasAny ? "" : sides.size === 2 ? "" : ` (${[...sides][0]} only)`}
            </option>
          );
        })}
      </select>

      <div style={{ display: "flex", gap: 4 }}>
        {(["a", "b"] as const).map((a) => {
          const available = amudimAvailableForCurrentDaf.has(a);
          const isActive = amud === a;
          return (
            <button
              key={a}
              onClick={() => onAmudClick(a)}
              disabled={!available}
              className={`pill ${isActive ? "active" : ""}`}
              style={{
                cursor: available ? "pointer" : "not-allowed",
                opacity: available ? 1 : 0.35,
                minWidth: 36,
                padding: "6px 12px",
                fontSize: 14,
                fontWeight: 700,
              }}
              title={available ? `View ${daf}${a}` : `${daf}${a} not yet generated`}
            >
              {a}
            </button>
          );
        })}
      </div>
    </div>
  );
}
