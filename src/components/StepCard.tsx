import type { HebrewStepName, Step } from "../lib/schema.js";
import { STEP_ENGLISH } from "../lib/schema.js";
import { PhraseTable } from "./PhraseTable.js";
import { KeyTermsBox } from "./KeyTermsBox.js";
import { MeforshimBlock } from "./MeforshimBlock.js";
import { LogicalBreakdown } from "./LogicalBreakdown.js";

interface Props {
  step: Step;
  showTranslation: boolean;
  showColors: boolean;
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

export function StepCard({ step, showTranslation, showColors }: Props) {
  const colorClass = showColors ? COLOR_CLASS[step.hebrewStepName] ?? "" : "";
  return (
    <section className={`card step-card ${colorClass}`}>
      <div className="step-head">
        <div className="accent-bar" />
        <div className="step-head-main">
          <div className="step-meta">
            <span className="badge step">#{step.stepNumber}</span>
            <span className="badge logic">
              {step.hebrewStepName} · {STEP_ENGLISH[step.hebrewStepName]}
            </span>
            {step.triggerLanguage && (
              <span className="badge subtle">Trigger: {step.triggerLanguage}</span>
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
