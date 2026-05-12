interface Props {
  number: number;
  topic: string;
  openingFormula?: string;
}

export function SugyaDivider({ number, topic, openingFormula }: Props) {
  return (
    <div className="sugya-divider">
      <div className="line" />
      <div className="label">
        Sugya {number} · {topic}
        {openingFormula ? ` · ${openingFormula}` : ""}
      </div>
      <div className="line" />
    </div>
  );
}
