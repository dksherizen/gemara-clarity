import { useMemo, useState } from "react";
import type { LibraryIndex } from "../lib/library.js";

interface LibraryProps {
  library: LibraryIndex;
  onSelect: (file: string) => void;
  currentFile?: string;
}

export function Library({ library, onSelect, currentFile }: LibraryProps) {
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const filtered = library.entries.filter((e) => {
      if (!query.trim()) return true;
      const q = query.toLowerCase();
      return (
        e.ref.toLowerCase().includes(q) ||
        e.masechet.toLowerCase().includes(q) ||
        (e.mainTopic ?? "").toLowerCase().includes(q)
      );
    });
    const groups = new Map<string, typeof library.entries>();
    for (const e of filtered) {
      const key = e.masechet || "Other";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(e);
    }
    for (const arr of groups.values()) {
      arr.sort((a, b) => {
        if ((a.daf ?? 0) !== (b.daf ?? 0)) return (a.daf ?? 0) - (b.daf ?? 0);
        return (a.amud || "").localeCompare(b.amud || "");
      });
    }
    return groups;
  }, [library.entries, query]);

  const totalShown = useMemo(
    () => Array.from(grouped.values()).reduce((s, a) => s + a.length, 0),
    [grouped],
  );

  return (
    <section className="card library-panel" style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 22, flex: 1 }}>Library</h2>
        <input
          type="search"
          placeholder="Search masechet, daf, topic…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="compact-input"
          style={{
            flex: 2,
            maxWidth: 360,
            height: 32,
            fontSize: 13,
          }}
        />
        <span className="sub" style={{ fontSize: 12 }}>
          {totalShown} of {library.entries.length}
        </span>
      </div>

      <div style={{ maxHeight: 380, overflowY: "auto", paddingRight: 6 }}>
        {[...grouped.entries()].map(([masechet, entries]) => (
          <div key={masechet} style={{ marginBottom: 12 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 800,
                color: "var(--accent)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                marginBottom: 6,
                paddingBottom: 4,
                borderBottom: "1px solid var(--border-2)",
              }}
            >
              {masechet.replaceAll("_", " ")}  ·  {entries.length} {entries.length === 1 ? "daf" : "dapim"}
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                gap: 6,
              }}
            >
              {entries.map((e) => {
                const isDemo = e.file.includes(".demo.");
                const isCurrent = currentFile === e.file;
                return (
                  <button
                    key={e.file}
                    className="pill action library-btn"
                    onClick={() => onSelect(e.file)}
                    style={{
                      textAlign: "left",
                      padding: "8px 12px",
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                      alignItems: "flex-start",
                      background: isCurrent
                        ? "rgba(34,211,238,0.18)"
                        : isDemo
                        ? "rgba(251,191,36,0.06)"
                        : "rgba(34,211,238,0.04)",
                      borderColor: isCurrent
                        ? "var(--accent)"
                        : isDemo
                        ? "rgba(251,191,36,0.3)"
                        : undefined,
                    }}
                  >
                    <span style={{ fontSize: 14, fontWeight: 700, display: "flex", gap: 6, alignItems: "center" }}>
                      {e.daf}
                      {e.amud}
                      {isDemo && (
                        <span
                          style={{
                            fontSize: 9,
                            padding: "1px 5px",
                            background: "rgba(251,191,36,0.15)",
                            color: "#fbbf24",
                            borderRadius: 4,
                            fontWeight: 800,
                          }}
                        >
                          DEMO
                        </span>
                      )}
                    </span>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 400,
                        color: "var(--muted)",
                        lineHeight: 1.35,
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical" as const,
                        overflow: "hidden",
                      }}
                    >
                      {e.mainTopic || "(no topic)"}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
