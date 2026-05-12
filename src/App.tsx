import { useEffect, useMemo, useState } from "react";
import type { DafAnalysis } from "./lib/schema.js";
import { loadAnalysis, loadLibraryIndex, type LibraryIndex } from "./lib/library.js";
import { Header } from "./components/Header.js";
import { Controls, type ControlState } from "./components/Controls.js";
import { Library } from "./components/Library.js";
import { MetaCard } from "./components/MetaCard.js";
import { StepCard } from "./components/StepCard.js";
import { SugyaDivider } from "./components/SugyaDivider.js";
import { PipelineProgress } from "./components/PipelineProgress.js";

const DEFAULT_CONTROLS: ControlState = {
  showLibrary: false,
  showTranslation: true,
  showColors: true,
  showLogic: false,
  showTerms: true,
  showNotes: true,
  showMeforshim: true,
  showHeader: true,
  darkMode: true,
  controlsHidden: false,
};

const STORAGE_KEY = "gemara-clarity-v2-ui";

function loadControls(): ControlState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CONTROLS;
    return { ...DEFAULT_CONTROLS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_CONTROLS;
  }
}

export function App() {
  const [controls, setControls] = useState<ControlState>(loadControls);
  const [library, setLibrary] = useState<LibraryIndex | null>(null);
  const [analysis, setAnalysis] = useState<DafAnalysis | null>(null);
  const [error, setError] = useState<string>("");
  const [status, setStatus] = useState<string>("Loading library…");

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(controls));
    document.body.classList.toggle("light", !controls.darkMode);
    document.body.classList.toggle("dark", controls.darkMode);
    document.body.classList.toggle("controls-hidden", controls.controlsHidden);
    document.body.classList.toggle("hide-logic", !controls.showLogic);
    document.body.classList.toggle("hide-terms", !controls.showTerms);
    document.body.classList.toggle("hide-notes", !controls.showNotes);
    document.body.classList.toggle("hide-header", !controls.showHeader);
    document.body.classList.toggle("hide-meforshim", !controls.showMeforshim);
  }, [controls]);

  useEffect(() => {
    let cancelled = false;
    loadLibraryIndex().then((idx) => {
      if (cancelled) return;
      setLibrary(idx);
      if (idx.entries.length === 0) {
        setStatus(
          "No analyses available yet. Run `node --env-file=.env --import tsx scripts/process-daf.ts -m Berakhot -d 2 -a a` to generate one.",
        );
        return;
      }
      setStatus("");
      // Auto-load: try entries in order until one succeeds (skips files that
      // are currently being rewritten by an active pipeline).
      const candidates = [
        ...idx.entries.filter((e) => !e.file.includes(".demo.")),
        ...idx.entries.filter((e) => e.file.includes(".demo.")),
      ];
      (async () => {
        for (const c of candidates) {
          try {
            const a = await loadAnalysis(c.file);
            if (cancelled) return;
            setAnalysis(a);
            setStatus("");
            return;
          } catch {
            // try next candidate
          }
        }
        if (!cancelled) {
          setStatus(
            "Waiting for the pipeline to finish writing a daf. Watch the progress panel above, or pick the Demo entry from the Library.",
          );
        }
      })();
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadFromLibrary(file: string) {
    setError("");
    setStatus(`Loading ${file}…`);
    try {
      const a = await loadAnalysis(file);
      setAnalysis(a);
      setStatus("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const stepsBySugya = useMemo(() => {
    if (!analysis) return [];
    const groups: Array<{
      sugyaNumber: number;
      topic: string;
      openingFormula?: string;
      steps: typeof analysis.steps;
    }> = [];
    for (const sugya of analysis.sugyaBoundaries) {
      const inSugya = analysis.steps.filter((s) => {
        if (
          sugya.firstStepNumber !== undefined &&
          sugya.lastStepNumber !== undefined
        ) {
          return (
            s.stepNumber >= sugya.firstStepNumber &&
            s.stepNumber <= sugya.lastStepNumber
          );
        }
        return false;
      });
      if (inSugya.length > 0) {
        groups.push({
          sugyaNumber: sugya.sugyaNumber,
          topic: sugya.topic,
          openingFormula: sugya.openingFormula,
          steps: inSugya,
        });
      }
    }
    if (groups.length === 0 && analysis.steps.length > 0) {
      return [
        {
          sugyaNumber: 1,
          topic: analysis.mainTopic,
          steps: analysis.steps,
        },
      ];
    }
    return groups;
  }, [analysis]);

  return (
    <>
      {controls.controlsHidden && (
        <button
          className="tiny-btn floating-show"
          onClick={() => setControls({ ...controls, controlsHidden: false })}
        >
          Show controls
        </button>
      )}
      <div className="app">
        <Header />
        <Controls controls={controls} setControls={setControls} />
        <PipelineProgress />
        {controls.showLibrary && library && (
          <Library library={library} onSelect={loadFromLibrary} />
        )}
        {status && <div className="status">{status}</div>}
        {error && <div className="error">{error}</div>}
        {analysis && (
          <>
            <MetaCard analysis={analysis} />
            <div className="step-list">
              {stepsBySugya.map((group) => (
                <div key={group.sugyaNumber}>
                  {stepsBySugya.length > 1 && (
                    <SugyaDivider
                      number={group.sugyaNumber}
                      topic={group.topic}
                      openingFormula={group.openingFormula}
                    />
                  )}
                  {group.steps.map((s) => (
                    <StepCard
                      key={s.stepNumber}
                      step={s}
                      showTranslation={controls.showTranslation}
                      showColors={controls.showColors}
                    />
                  ))}
                </div>
              ))}
            </div>
          </>
        )}
        {!analysis && !status && !error && (
          <section className="card empty-card">
            Choose a daf above to start learning.
          </section>
        )}
      </div>
    </>
  );
}
