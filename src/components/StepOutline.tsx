import type { DafAnalysis, HebrewStepName } from "../lib/schema.js";

interface Props {
  analysis: DafAnalysis;
  activeStepNumber?: number;
  onJump: (stepNumber: number) => void;
}

const TYPE_COLORS: Record<HebrewStepName, string> = {
  מימרא: "#38bdf8",
  קשיא: "#fb7185",
  תירוץ: "#34d399",
  ראיה: "#a78bfa",
  דחיה: "#fb923c",
  שאלה: "#fbbf24",
  תשובה: "#22d3ee",
  מסקנא: "#e879f9",
};

export function StepOutline({ analysis, activeStepNumber, onJump }: Props) {
  const sugyot = analysis.sugyaBoundaries.length > 0 ? analysis.sugyaBoundaries : [];

  return (
    <aside
      style={{
        position: "sticky",
        top: 80,
        maxHeight: "calc(100vh - 110px)",
        overflowY: "auto",
        background: "var(--panel)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 12,
        fontSize: 12,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 800,
          color: "var(--accent)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 8,
          paddingBottom: 6,
          borderBottom: "1px solid var(--border-2)",
        }}
      >
        Outline · {analysis.steps.length} steps
      </div>

      {sugyot.length > 0
        ? sugyot.map((sugya, sugyaIdx) => {
            // Use firstStepNumber/lastStepNumber if they look valid; otherwise
            // fall back to proportional distribution across the sugyot. This
            // handles older JSONs where the per-amud renumbering left those
            // fields pointing at stale window-wide numbers.
            const totalSteps = analysis.steps.length;
            const stepNumbersInAmud = analysis.steps.map((s) => s.stepNumber);
            const minStep = Math.min(...stepNumbersInAmud);
            const maxStep = Math.max(...stepNumbersInAmud);
            const boundsValid =
              sugya.firstStepNumber !== undefined &&
              sugya.lastStepNumber !== undefined &&
              sugya.firstStepNumber >= minStep &&
              sugya.lastStepNumber <= maxStep;
            let stepsInSugya = boundsValid
              ? analysis.steps.filter(
                  (s) =>
                    s.stepNumber >= (sugya.firstStepNumber as number) &&
                    s.stepNumber <= (sugya.lastStepNumber as number),
                )
              : [];
            // Fallback: distribute steps proportionally to sugya line spans.
            if (stepsInSugya.length === 0) {
              const lineSpans = sugyot.map(
                (sg) => Math.max(1, sg.endLine - sg.startLine + 1),
              );
              const totalLines = lineSpans.reduce((a, b) => a + b, 0) || 1;
              const cumulative: number[] = [];
              let acc = 0;
              for (const span of lineSpans) {
                acc += span;
                cumulative.push(acc);
              }
              const startFrac =
                sugyaIdx === 0 ? 0 : cumulative[sugyaIdx - 1] / totalLines;
              const endFrac = cumulative[sugyaIdx] / totalLines;
              const startIdx = Math.floor(startFrac * totalSteps);
              const endIdx =
                sugyaIdx === sugyot.length - 1
                  ? totalSteps
                  : Math.floor(endFrac * totalSteps);
              stepsInSugya = analysis.steps.slice(startIdx, endIdx);
            }
            return (
              <div key={sugya.sugyaNumber} style={{ marginBottom: 12 }}>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--muted)",
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    marginBottom: 4,
                    paddingBottom: 2,
                    borderBottom: "1px dashed var(--border-2)",
                  }}
                  title={sugya.gist}
                >
                  Sugya {sugya.sugyaNumber}: {sugya.topic.slice(0, 38)}
                  {sugya.topic.length > 38 ? "…" : ""}
                </div>
                {stepsInSugya.map((s) => (
                  <StepRow
                    key={s.stepNumber}
                    stepNumber={s.stepNumber}
                    hebrewStepName={s.hebrewStepName}
                    title={s.title}
                    active={s.stepNumber === activeStepNumber}
                    onJump={onJump}
                  />
                ))}
              </div>
            );
          })
        : analysis.steps.map((s) => (
            <StepRow
              key={s.stepNumber}
              stepNumber={s.stepNumber}
              hebrewStepName={s.hebrewStepName}
              title={s.title}
              active={s.stepNumber === activeStepNumber}
              onJump={onJump}
            />
          ))}
    </aside>
  );
}

function StepRow({
  stepNumber,
  hebrewStepName,
  title,
  active,
  onJump,
}: {
  stepNumber: number;
  hebrewStepName: HebrewStepName;
  title: string;
  active: boolean;
  onJump: (n: number) => void;
}) {
  return (
    <button
      onClick={() => onJump(stepNumber)}
      style={{
        display: "flex",
        gap: 6,
        alignItems: "flex-start",
        padding: "4px 6px",
        width: "100%",
        textAlign: "left",
        border: "none",
        background: active ? "rgba(34,211,238,0.12)" : "transparent",
        borderRadius: 6,
        marginBottom: 1,
        color: active ? "var(--text)" : "var(--soft)",
        cursor: "pointer",
        fontSize: 11.5,
        lineHeight: 1.3,
        transition: "background 0.12s ease",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.background = "rgba(255,255,255,0.04)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.background = "transparent";
      }}
    >
      <span
        style={{
          flex: "0 0 4px",
          height: 14,
          marginTop: 2,
          borderRadius: 2,
          background: TYPE_COLORS[hebrewStepName] ?? "var(--muted)",
        }}
      />
      <span style={{ flex: "0 0 22px", color: "var(--muted)", fontWeight: 700 }}>
        {stepNumber}
      </span>
      <span style={{ flex: 1 }}>{title}</span>
    </button>
  );
}
