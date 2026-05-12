import { useState } from "react";
import type { Step } from "../lib/schema.js";

interface Props {
  step: Step;
}

function titleCase(s: string): string {
  return s.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function LogicalBreakdown({ step }: Props) {
  const [open, setOpen] = useState(true);

  const conditionals: Array<{ label: string; value: string }> = [];
  if (step.kashyaTarget) conditionals.push({ label: "Attacking", value: step.kashyaTarget });
  if (step.kashyaAttackLogic) conditionals.push({ label: "The Problem", value: step.kashyaAttackLogic });
  if (step.terutzResolutionType)
    conditionals.push({ label: "How it's resolved", value: titleCase(step.terutzResolutionType) });
  if (step.terutzHavaAmina)
    conditionals.push({ label: "Initial Assumption (Hava Amina)", value: step.terutzHavaAmina });
  if (step.terutzMaskana)
    conditionals.push({ label: "Conclusion (Maskana)", value: step.terutzMaskana });
  if (step.sheelahInformationSought)
    conditionals.push({ label: "Question asks", value: step.sheelahInformationSought });
  if (step.teshuvahAnswerProvided)
    conditionals.push({ label: "The Answer", value: step.teshuvahAnswerProvided });
  if (step.raayaObject) conditionals.push({ label: "Trying to prove", value: step.raayaObject });
  if (step.raayaSupportSource)
    conditionals.push({ label: "Evidence", value: step.raayaSupportSource });
  if (step.dechiyaRejectionScope)
    conditionals.push({ label: "Rejecting the", value: titleCase(step.dechiyaRejectionScope) });
  if (step.dechiyaFlawIdentified)
    conditionals.push({ label: "Why it fails", value: step.dechiyaFlawIdentified });
  if (step.mimraCoreRuling) conditionals.push({ label: "The Law", value: step.mimraCoreRuling });
  if (step.maskanaFinalTakeaway)
    conditionals.push({ label: "Bottom Line", value: step.maskanaFinalTakeaway });

  const macroPhase = step.macroPhase ? titleCase(step.macroPhase) : "Continuing Sugya";
  const branchRole = step.branchRole ? titleCase(step.branchRole) : "Continues Current Line";
  const scope = step.scopeOfStep ? titleCase(step.scopeOfStep) : "General Logic";
  const dependsOn = step.dependsOnStepNumbers?.length
    ? step.dependsOnStepNumbers.join(", ")
    : "None";

  return (
    <>
      <button className="logic-toggle-btn" onClick={() => setOpen(!open)}>
        <span>Logical Breakdown</span>
        <span style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .2s" }}>
          ▾
        </span>
      </button>
      <div className={`logic-details ${open ? "show" : ""}`}>
        {conditionals.length > 0 ? (
          <div className="logic-conditionals">
            {conditionals.map((c, i) => (
              <div key={i} className="cond-box">
                <strong>{c.label}:</strong> {c.value}
              </div>
            ))}
          </div>
        ) : (
          <div className="logic-item" style={{ paddingBottom: 8, color: "var(--muted)" }}>
            <em>No conditional argumentative logic required for this step.</em>
          </div>
        )}
        <details className="advanced-meta" open>
          <summary
            style={{
              fontSize: 10,
              color: "var(--muted)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              fontWeight: 600,
              outline: "none",
            }}
          >
            Sugya Architecture
          </summary>
          <div className="logic-grid" style={{ fontSize: 11, marginTop: 10 }}>
            <div className="logic-item">
              <strong>Phase</strong>
              {macroPhase}
            </div>
            <div className="logic-item">
              <strong>Branch</strong>
              {branchRole}
            </div>
            <div className="logic-item">
              <strong>Scope</strong>
              {scope}
            </div>
            <div className="logic-item">
              <strong>Depends On</strong>
              {dependsOn}
            </div>
          </div>
          {step.relationToPreviousStep && (
            <div className="logic-item" style={{ marginTop: 6, fontSize: 11 }}>
              <strong>Relation to Previous:</strong> {step.relationToPreviousStep}
            </div>
          )}
        </details>
      </div>
    </>
  );
}
