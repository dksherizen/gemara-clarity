import { useState } from "react";
import type {
  DafAnalysis,
  HebrewStepName,
  Step,
  SugyaBoundary,
} from "../lib/schema.js";

const TYPE_VAR: Record<HebrewStepName, string> = {
  מימרא: "--mimra",
  קשיא: "--kashya",
  תירוץ: "--terutz",
  ראיה: "--raaya",
  דחיה: "--dechiya",
  שאלה: "--sheelah",
  תשובה: "--teshuvah",
  מסקנא: "--maskana",
};

interface Props {
  analysis: DafAnalysis;
  sugya: SugyaBoundary;
}

function stepsForSugya(analysis: DafAnalysis, sugya: SugyaBoundary): Step[] {
  const total = analysis.steps.length;
  if (
    sugya.firstStepNumber !== undefined &&
    sugya.lastStepNumber !== undefined
  ) {
    const inRange = analysis.steps.filter(
      (s) =>
        s.stepNumber >= sugya.firstStepNumber! &&
        s.stepNumber <= sugya.lastStepNumber!,
    );
    if (inRange.length) return inRange;
  }
  // Proportional fallback by line span.
  const sugyot = analysis.sugyaBoundaries;
  const idx = sugyot.findIndex((sg) => sg.sugyaNumber === sugya.sugyaNumber);
  if (idx < 0) return analysis.steps;
  const spans = sugyot.map((sg) => Math.max(1, sg.endLine - sg.startLine + 1));
  const totalLines = spans.reduce((a, b) => a + b, 0) || 1;
  let acc = 0;
  const cumulative = spans.map((s) => (acc += s) / totalLines);
  const startFrac = idx === 0 ? 0 : cumulative[idx - 1];
  const endFrac = cumulative[idx];
  const startIdx = Math.floor(startFrac * total);
  const endIdx = idx === sugyot.length - 1 ? total : Math.floor(endFrac * total);
  return analysis.steps.slice(startIdx, endIdx);
}

function computeDepths(steps: Step[]): number[] {
  let d = 0;
  return steps.map((s) => {
    if (s.branchRole === "opens_new_branch") d += 1;
    else if (s.branchRole === "returns_to_previous_branch") d = Math.max(0, d - 1);
    else if (s.branchRole === "conclusion_of_branch") d = 0;
    return d;
  });
}

export function ArgumentFlow({ analysis, sugya }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const steps = stepsForSugya(analysis, sugya);
  if (steps.length < 2) return null;
  const depths = computeDepths(steps);

  return (
    <div className="arg-flow">
      <div className="arg-flow-head">
        <span className="arg-flow-label">
          Argument flow · {steps.length} steps
        </span>
        <button
          className="arg-flow-toggle"
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? "show" : "hide"}
        </button>
      </div>
      {!collapsed && (
        <ol className="arg-tree">
          {steps.map((s, i) => {
            const colorVar = TYPE_VAR[s.hebrewStepName];
            return (
              <li
                key={s.stepNumber}
                className="arg-node"
                style={{ ["--depth" as any]: depths[i] }}
                data-role={s.branchRole || ""}
              >
                <span
                  className="arg-bar"
                  style={{ background: `var(${colorVar})` }}
                />
                <span className="arg-num">#{s.stepNumber}</span>
                <span
                  className="arg-type"
                  style={{ color: `var(${colorVar})` }}
                >
                  {s.hebrewStepName}
                </span>
                <span className="arg-title" title={s.title}>
                  {s.title}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
