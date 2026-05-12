import { useEffect, useState } from "react";

interface ProgressData {
  active: boolean;
  ref: string;
  startedAt: string;
  elapsedSec: number;
  lastUpdateAt: string;
  log: Array<{ ts: number; msg: string }>;
}

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m${String(s).padStart(2, "0")}s`;
}

function detectPass(msg: string): { pass?: number; label?: string } {
  const m = msg.match(/^Pass\s+(\d+)\/\d+:\s*(.*)$/);
  if (m) return { pass: parseInt(m[1], 10), label: m[2] };
  return {};
}

export function PipelineProgress() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [secondsSinceUpdate, setSecondsSinceUpdate] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await fetch("/data/progress.json?t=" + Date.now(), {
          cache: "no-cache",
        });
        if (r.ok && !cancelled) {
          const d = (await r.json()) as ProgressData;
          setData(d);
          if (d.lastUpdateAt) {
            setSecondsSinceUpdate(
              Math.round((Date.now() - new Date(d.lastUpdateAt).getTime()) / 1000),
            );
          }
        }
      } catch {
        /* progress.json missing is fine */
      }
    }
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!data) return null;
  // Hide if the run finished more than 30 seconds ago.
  const finishedLongAgo = !data.active && secondsSinceUpdate > 30;
  if (finishedLongAgo) return null;

  const currentPass = [...data.log].reverse().find((l) => detectPass(l.msg).pass);
  const passInfo = currentPass ? detectPass(currentPass.msg) : {};
  const recentMsg = data.log[data.log.length - 1]?.msg ?? "Starting…";

  const passes = [
    { n: 1, name: "Segmentation" },
    { n: 2, name: "Structure" },
    { n: 3, name: "Phrase map" },
    { n: 4, name: "Meforshim" },
    { n: 5, name: "Teaching" },
    { n: 6, name: "Validate" },
  ];

  return (
    <section
      className="card"
      style={{
        padding: "16px 18px",
        marginBottom: 12,
        borderColor: data.active ? "var(--accent)" : "var(--border)",
        background: data.active
          ? "linear-gradient(90deg, rgba(34,211,238,0.06), var(--panel))"
          : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: data.active ? "var(--accent)" : "var(--terutz)",
            boxShadow: data.active ? "0 0 8px var(--accent)" : "none",
            animation: data.active ? "pulse 1.4s ease-in-out infinite" : "none",
          }}
        />
        <strong style={{ fontSize: 14, letterSpacing: 0.5 }}>
          {data.active ? "PIPELINE RUNNING" : "PIPELINE DONE"}
        </strong>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          {data.ref} · {formatElapsed(data.elapsedSec)} elapsed
        </span>
        <span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: 11 }}>
          last update {secondsSinceUpdate}s ago
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, 1fr)",
          gap: 6,
          marginBottom: 12,
        }}
      >
        {passes.map((p) => {
          const isCurrent = passInfo.pass === p.n;
          const isDone = (passInfo.pass ?? 0) > p.n || !data.active;
          return (
            <div
              key={p.n}
              style={{
                padding: "8px 10px",
                borderRadius: 8,
                background: isCurrent
                  ? "rgba(34,211,238,0.12)"
                  : isDone
                  ? "rgba(52,211,153,0.08)"
                  : "rgba(255,255,255,0.02)",
                border: `1px solid ${
                  isCurrent
                    ? "rgba(34,211,238,0.4)"
                    : isDone
                    ? "rgba(52,211,153,0.3)"
                    : "var(--border-2)"
                }`,
                textAlign: "center",
                fontSize: 11,
                fontWeight: 700,
                color: isCurrent
                  ? "var(--accent)"
                  : isDone
                  ? "var(--terutz)"
                  : "var(--muted)",
              }}
            >
              <div style={{ fontSize: 10, opacity: 0.7 }}>PASS {p.n}</div>
              <div>{p.name}</div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          fontSize: 12,
          color: "var(--soft)",
          fontFamily: "ui-monospace, Menlo, monospace",
          background: "rgba(0,0,0,0.15)",
          padding: 10,
          borderRadius: 8,
          maxHeight: 160,
          overflowY: "auto",
        }}
      >
        {data.log.slice(-10).map((l, i) => (
          <div key={i} style={{ marginBottom: 2 }}>
            <span style={{ color: "var(--muted)", marginRight: 8 }}>
              [{formatElapsed(l.ts)}]
            </span>
            {l.msg}
          </div>
        ))}
      </div>

      {data.active && (
        <p style={{ fontSize: 11, color: "var(--muted)", margin: "8px 0 0" }}>
          Most recent: {recentMsg}
        </p>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%      { opacity: 0.5; transform: scale(1.4); }
        }
      `}</style>
    </section>
  );
}
