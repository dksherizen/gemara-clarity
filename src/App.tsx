import { useEffect, useMemo, useRef, useState } from "react";
import type { DafAnalysis } from "./lib/schema.js";
import { loadAnalysis, loadLibraryIndex, type LibraryIndex, type LibraryIndexEntry } from "./lib/library.js";
import { Header } from "./components/Header.js";
import { Controls, type ControlState } from "./components/Controls.js";
// import { Library } from "./components/Library.js"; // replaced by QuickPicker
import { MetaCard } from "./components/MetaCard.js";
import { StepCard } from "./components/StepCard.js";
import { ArgumentFlow } from "./components/ArgumentFlow.js";
import { SearchPanel } from "./components/Search.js";
import { QuickPicker } from "./components/QuickPicker.js";
import { SugyaDivider } from "./components/SugyaDivider.js";
import { PipelineProgress } from "./components/PipelineProgress.js";
import { DafPicker } from "./components/DafPicker.js";
import { StepOutline } from "./components/StepOutline.js";

const DEFAULT_CONTROLS: ControlState = {
  showLibrary: true,
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
  const [currentEntry, setCurrentEntry] = useState<LibraryIndexEntry | null>(null);
  const [analysis, setAnalysis] = useState<DafAnalysis | null>(null);
  const [error, setError] = useState<string>("");
  const [status, setStatus] = useState<string>("Loading library…");
  const [activeStepNumber, setActiveStepNumber] = useState<number | undefined>(undefined);
  const stepRefs = useRef<Map<number, HTMLDivElement>>(new Map());

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
    loadLibraryIndex().then(async (idx) => {
      if (cancelled) return;
      setLibrary(idx);
      if (idx.entries.length === 0) {
        setStatus(
          "No analyses available yet. Run the CLI to generate one.",
        );
        return;
      }
      setStatus("");
      const candidates = [
        ...idx.entries.filter((e) => !e.file.includes(".demo.")),
        ...idx.entries.filter((e) => e.file.includes(".demo.")),
      ];
      for (const c of candidates) {
        try {
          const a = await loadAnalysis(c.file);
          if (cancelled) return;
          setAnalysis(a);
          setCurrentEntry(c);
          setStatus("");
          return;
        } catch {
          // try next
        }
      }
      if (!cancelled) setStatus("Pick a daf from the Library.");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function selectDaf(file: string) {
    if (!library) return;
    setError("");
    setActiveStepNumber(undefined);
    const entry = library.entries.find((e) => e.file === file);
    if (!entry) {
      setError(`Daf ${file} not in library.`);
      return;
    }
    setStatus(`Loading ${entry.masechet.replaceAll("_", " ")} ${entry.daf}${entry.amud}…`);
    try {
      const a = await loadAnalysis(file);
      setAnalysis(a);
      setCurrentEntry(entry);
      setStatus("");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(
        (err as Error).message.includes("404")
          ? "That daf is still being processed. Try another."
          : (err as Error).message,
      );
    }
  }

  function jumpToStep(n: number) {
    setActiveStepNumber(n);
    const el = stepRefs.current.get(n);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function registerStepRef(n: number, el: HTMLDivElement | null) {
    if (el) stepRefs.current.set(n, el);
    else stepRefs.current.delete(n);
  }

  const stepsBySugya = useMemo(() => {
    if (!analysis) return [];
    const groups: Array<{
      sugyaNumber: number;
      topic: string;
      gist: string;
      openingFormula?: string;
      steps: typeof analysis.steps;
    }> = [];
    for (const sugya of analysis.sugyaBoundaries) {
      const inSugya = analysis.steps.filter(
        (s) =>
          sugya.firstStepNumber !== undefined &&
          sugya.lastStepNumber !== undefined &&
          s.stepNumber >= sugya.firstStepNumber &&
          s.stepNumber <= sugya.lastStepNumber,
      );
      if (inSugya.length > 0) {
        groups.push({
          sugyaNumber: sugya.sugyaNumber,
          topic: sugya.topic,
          gist: sugya.gist,
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
          gist: analysis.overview,
          steps: analysis.steps,
        },
      ];
    }
    return groups;
  }, [analysis]);

  function printSingleSugya(sugyaNumber: number) {
    const groups = document.querySelectorAll<HTMLElement>("[data-sugya-group]");
    groups.forEach((g) => {
      const include = g.getAttribute("data-sugya-group") === String(sugyaNumber);
      g.querySelectorAll(".step-card").forEach((el) => {
        (el as HTMLElement).setAttribute("data-print-include", include ? "true" : "false");
      });
      const divider = g.querySelector('[class*="sugya-divider"]');
      if (divider) {
        divider.setAttribute("data-print-include", include ? "true" : "false");
      }
    });
    document.body.classList.add("print-single-sugya");
    window.print();
    setTimeout(() => {
      document.body.classList.remove("print-single-sugya");
      groups.forEach((g) =>
        g.querySelectorAll("[data-print-include]").forEach((el) =>
          el.removeAttribute("data-print-include"),
        ),
      );
    }, 500);
  }

  function printFullAmud() {
    window.print();
  }

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
      <div className="app" style={{ maxWidth: 1400 }}>
        <Header />
        <Controls controls={controls} setControls={setControls} />
        <PipelineProgress />

        {/* Library replaced by QuickPicker below. */}

        {library && library.entries.length > 1 && (
          <SearchPanel
            index={library}
            onJump={(file, stepNumber) => {
              const entry = library.entries.find((e) => e.file === file);
              if (entry) {
                selectDaf(entry.file);
                if (stepNumber !== undefined) {
                  // Defer scroll until the daf loads
                  setTimeout(() => {
                    const el = document.getElementById(`step-${stepNumber}`);
                    el?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }, 800);
                }
              }
            }}
          />
        )}

        {library && library.entries.length > 0 && (
          <QuickPicker
            library={library}
            current={currentEntry}
            onSelect={selectDaf}
          />
        )}

        {analysis && library && (
          <DafPicker library={library} current={currentEntry} onSelect={selectDaf} />
        )}

        {status && <div className="status">{status}</div>}
        {error && <div className="error">{error}</div>}

        {analysis && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "240px 1fr",
              gap: 16,
              alignItems: "start",
            }}
            className="daf-layout"
          >
            <StepOutline
              analysis={analysis}
              activeStepNumber={activeStepNumber}
              onJump={jumpToStep}
            />
            <div>
              <MetaCard analysis={analysis} />
              <div className="no-print" style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <button
                  onClick={printFullAmud}
                  style={{
                    background: "var(--panel)",
                    border: "1px solid var(--border)",
                    color: "var(--soft)",
                    cursor: "pointer",
                    fontSize: 12,
                    padding: "6px 12px",
                    borderRadius: 6,
                  }}
                >
                  🖨 Print this amud
                </button>
              </div>
              <div className="step-list">
                {stepsBySugya.map((group) => (
                  <div key={group.sugyaNumber} data-sugya-group={group.sugyaNumber}>
                    {stepsBySugya.length > 1 && (
                      <SugyaDivider
                        number={group.sugyaNumber}
                        topic={group.topic}
                        gist={group.gist}
                        openingFormula={group.openingFormula}
                        onPrint={() => printSingleSugya(group.sugyaNumber)}
                      />
                    )}
                    {(() => {
                      const sg = analysis.sugyaBoundaries.find(
                        (s) => s.sugyaNumber === group.sugyaNumber,
                      );
                      return sg ? <ArgumentFlow analysis={analysis} sugya={sg} /> : null;
                    })()}
                    {group.steps.map((s) => (
                      <div
                        key={s.stepNumber}
                        ref={(el) => registerStepRef(s.stepNumber, el)}
                        id={`step-${s.stepNumber}`}
                      >
                        <StepCard
                          step={s}
                          showTranslation={controls.showTranslation}
                          showColors={controls.showColors}
                          dafRef={analysis?.ref}
                        />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
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
