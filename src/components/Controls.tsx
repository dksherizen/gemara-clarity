export interface ControlState {
  showLibrary: boolean;
  showTranslation: boolean;
  showColors: boolean;
  showLogic: boolean;
  showTerms: boolean;
  showNotes: boolean;
  showMeforshim: boolean;
  showHeader: boolean;
  darkMode: boolean;
  controlsHidden: boolean;
}

interface ControlsProps {
  controls: ControlState;
  setControls: (next: ControlState) => void;
}

export function Controls({ controls, setControls }: ControlsProps) {
  const toggle = (key: keyof ControlState) =>
    setControls({ ...controls, [key]: !controls[key] });

  function Pill({
    field,
    label,
  }: {
    field: keyof ControlState;
    label: string;
  }) {
    return (
      <button
        className={`pill ${controls[field] ? "active" : ""}`}
        onClick={() => toggle(field)}
      >
        {label}
      </button>
    );
  }

  return (
    <div className="controls-shell card">
      <div className="control-row" style={{ justifyContent: "center" }}>
        <Pill field="showLibrary" label="Library" />
        <Pill field="showTranslation" label="English" />
        <Pill field="showColors" label="Colors" />
        <Pill field="showLogic" label="Logic" />
        <Pill field="showTerms" label="Terms" />
        <Pill field="showNotes" label="Notes" />
        <Pill field="showMeforshim" label="Meforshim" />
        <Pill field="showHeader" label="Header" />
        <Pill field="darkMode" label="Dark" />
        <button
          className="tiny-btn"
          onClick={() => setControls({ ...controls, controlsHidden: true })}
        >
          Hide controls
        </button>
        <button
          className="action primary"
          onClick={() => window.print()}
          title="Print / export to PDF"
        >
          Print / PDF
        </button>
      </div>
    </div>
  );
}
