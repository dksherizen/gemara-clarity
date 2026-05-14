import { useState } from "react";
import type { HebrewStepName, Step } from "../lib/schema.js";
import { HEBREW_STEP_NAMES, STEP_ENGLISH } from "../lib/schema.js";
import { PhraseTable } from "./PhraseTable.js";
import { KeyTermsBox } from "./KeyTermsBox.js";
import { MeforshimBlock } from "./MeforshimBlock.js";
import { LogicalBreakdown } from "./LogicalBreakdown.js";

interface Props {
  step: Step;
  showTranslation: boolean;
  showColors: boolean;
  dafRef?: string; // used for sending corrections back to the feedback server
}

const COLOR_CLASS: Record<HebrewStepName, string> = {
  מימרא: "step-mimra",
  קשיא: "step-kashya",
  תירוץ: "step-terutz",
  ראיה: "step-raaya",
  דחיה: "step-dechiya",
  שאלה: "step-sheelah",
  תשובה: "step-teshuvah",
  מסקנא: "step-maskana",
};

export function StepCard({ step, showTranslation, showColors, dafRef }: Props) {
  const [currentLabel, setCurrentLabel] = useState<HebrewStepName>(step.hebrewStepName);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  async function submitCorrection(newLabel: HebrewStepName) {
    if (!dafRef || newLabel === currentLabel) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      const r = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ref: dafRef,
          stepNumber: step.stepNumber,
          field: "hebrewStepName",
          oldValue: currentLabel,
          newValue: newLabel,
        }),
      });
      if (r.ok) setCurrentLabel(newLabel);
    } catch (e) {
      console.warn("feedback submit failed", e);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  const colorClass = showColors ? COLOR_CLASS[currentLabel] ?? "" : "";
  return (
    <section className={`card step-card ${colorClass}`}>
      <div className="step-head">
        <div className="accent-bar" />
        <div className="step-head-main">
          <div className="step-meta">
            <span className="badge step">#{step.stepNumber}</span>
            {editing ? (
              <select
                value={currentLabel}
                onChange={(e) => submitCorrection(e.target.value as HebrewStepName)}
                disabled={saving}
                onBlur={() => setEditing(false)}
                autoFocus
                style={{
                  fontSize: 13,
                  padding: "4px 8px",
                  borderRadius: 4,
                  background: "var(--panel)",
                  color: "var(--text)",
                  border: "1px solid var(--accent)",
                }}
              >
                {HEBREW_STEP_NAMES.map((n) => (
                  <option key={n} value={n}>
                    {n} · {STEP_ENGLISH[n]}
                  </option>
                ))}
              </select>
            ) : (
              <span
                className="badge logic"
                onClick={() => setEditing(true)}
                style={{ cursor: "pointer" }}
                title="click to suggest a correction"
              >
                {currentLabel} · {STEP_ENGLISH[currentLabel]}
              </span>
            )}
            {step.classificationConfidence &&
              step.classificationConfidence !== "High" && (
                <span className="badge subtle warning">
                  Conf: {step.classificationConfidence}
                </span>
              )}
            {step.alternativePossibleLabel && (
              <span className="badge subtle warning">
                Alt: {step.alternativePossibleLabel}
              </span>
            )}
          </div>
          <h2 className="step-title">{step.title}</h2>
          <p className="step-summary">{step.stepSummary}</p>
        </div>
      </div>

      <PhraseTable phrases={step.phrases} showTranslation={showTranslation} />

      {step.whatsHappening && (
        <div className="teaching-block">
          <span className="teaching-label">What's Happening</span>
          {step.whatsHappening}
        </div>
      )}
      {step.deeperAnalysis && (
        <div className="teaching-block">
          <span className="teaching-label">Deeper Analysis</span>
          {step.deeperAnalysis}
        </div>
      )}
      {step.whyThisMatters && (
        <div className="teaching-block">
          <span className="teaching-label">Why This Matters</span>
          {step.whyThisMatters}
        </div>
      )}

      <KeyTermsBox terms={step.keyTerms} />

      {step.whatToRemember && (
        <div className="remember-box">
          <strong>Remember</strong>
          {step.whatToRemember}
        </div>
      )}
      {step.confusionAlert && (
        <div className="alert-box">
          <strong>Common Confusion</strong>
          {step.confusionAlert}
        </div>
      )}

      {step.meforshim && <MeforshimBlock data={step.meforshim} />}

      <LogicalBreakdown step={step} />
    </section>
  );
}
