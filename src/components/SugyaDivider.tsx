interface Props {
  number: number;
  topic: string;
  gist?: string;
  openingFormula?: string;
  onPrint?: () => void;
}

export function SugyaDivider({ number, topic, gist, openingFormula, onPrint }: Props) {
  return (
    <div
      style={{
        margin: "32px 0 16px",
        padding: "14px 18px",
        background:
          "linear-gradient(135deg, rgba(167,139,250,0.08), rgba(34,211,238,0.06))",
        border: "1px solid rgba(167,139,250,0.25)",
        borderLeft: "4px solid var(--raaya)",
        borderRadius: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 10,
          fontWeight: 800,
          color: "var(--raaya)",
          textTransform: "uppercase",
          letterSpacing: "0.12em",
          marginBottom: 4,
        }}
      >
        <span>
          Sugya {number}
          {openingFormula ? ` · opens with ` : ""}
          {openingFormula && (
            <span
              dir="rtl"
              lang="he"
              style={{
                fontFamily: '"Frank Ruhl Libre", serif',
                fontWeight: 500,
              }}
            >
              {openingFormula}
            </span>
          )}
        </span>
        {onPrint && (
          <button
            onClick={onPrint}
            className="no-print"
            title="Print this sugya"
            style={{
              background: "transparent",
              border: "1px solid var(--border)",
              color: "var(--soft)",
              cursor: "pointer",
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: 4,
              textTransform: "uppercase",
            }}
          >
            🖨 Print
          </button>
        )}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text)", marginBottom: gist ? 4 : 0 }}>
        {topic}
      </div>
      {gist && (
        <div style={{ fontSize: 13, color: "var(--soft)", lineHeight: 1.5 }}>
          {gist}
        </div>
      )}
    </div>
  );
}
