import { useMemo } from "react";
import type { LibraryIndex, LibraryIndexEntry } from "../lib/library.js";

interface Props {
  library: LibraryIndex;
  current: LibraryIndexEntry | null;
  onSelect: (file: string) => void;
}

export function DafPicker({ library, current, onSelect }: Props) {
  const dapim = library.entries.filter((e) => !e.file.includes(".demo."));
  const idx = current ? dapim.findIndex((e) => e.file === current.file) : -1;

  const prev = idx > 0 ? dapim[idx - 1] : null;
  const next = idx >= 0 && idx < dapim.length - 1 ? dapim[idx + 1] : null;

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
      }}
    >
      <button
        className="action"
        disabled={!prev}
        onClick={() => prev && onSelect(prev.file)}
        style={{
          opacity: prev ? 1 : 0.3,
          cursor: prev ? "pointer" : "not-allowed",
        }}
      >
        ← Prev{prev ? `: ${prev.masechet.replaceAll("_", " ")} ${prev.daf}${prev.amud}` : ""}
      </button>
      <div style={{ flex: 1, textAlign: "center" }}>
        {current ? (
          <>
            <div style={{ fontSize: 18, fontWeight: 800 }}>
              {current.masechet.replaceAll("_", " ")} {current.daf}
              {current.amud}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>
              {dapim.length > 0 && idx >= 0 && `${idx + 1} of ${dapim.length} in library`}
            </div>
          </>
        ) : (
          <div style={{ color: "var(--muted)" }}>Pick a daf from the Library →</div>
        )}
      </div>
      <button
        className="action primary"
        disabled={!next}
        onClick={() => next && onSelect(next.file)}
        style={{
          opacity: next ? 1 : 0.3,
          cursor: next ? "pointer" : "not-allowed",
        }}
      >
        Next{next ? `: ${next.masechet.replaceAll("_", " ")} ${next.daf}${next.amud}` : ""} →
      </button>
    </div>
  );
}
