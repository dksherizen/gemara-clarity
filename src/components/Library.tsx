import type { LibraryIndex } from "../lib/library.js";

interface LibraryProps {
  library: LibraryIndex;
  onSelect: (file: string) => void;
}

export function Library({ library, onSelect }: LibraryProps) {
  return (
    <section className="card library-panel">
      <h2 style={{ margin: 0, fontSize: 22 }}>Library</h2>
      <p className="sub">{library.entries.length} dapim available</p>
      <div className="library-grid" style={{ flexDirection: "column", alignItems: "stretch" }}>
        {library.entries.map((e) => {
          const isDemo = e.file.includes(".demo.");
          return (
            <button
              key={e.file}
              className="pill action library-btn"
              onClick={() => onSelect(e.file)}
              style={{
                textAlign: "left",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: 4,
                width: "100%",
                alignItems: "flex-start",
                background: isDemo
                  ? "rgba(251,191,36,0.06)"
                  : "rgba(34,211,238,0.06)",
                borderColor: isDemo
                  ? "rgba(251,191,36,0.3)"
                  : undefined,
              }}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <strong style={{ fontSize: 15 }}>
                  {e.masechet.replaceAll("_", " ")} {e.daf}
                  {e.amud}
                </strong>
                {isDemo && (
                  <span
                    style={{
                      fontSize: 9,
                      letterSpacing: 0.5,
                      padding: "2px 6px",
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
                  fontSize: 12,
                  fontWeight: 400,
                  color: "var(--muted)",
                  lineHeight: 1.4,
                }}
              >
                {e.mainTopic.length > 110
                  ? e.mainTopic.slice(0, 110) + "…"
                  : e.mainTopic}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
