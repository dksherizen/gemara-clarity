import type { MeforshimBlock as MeforshimData, MeforeshComment } from "../lib/schema.js";

interface Props {
  data: MeforshimData;
}

function MeforeshItem({ comment }: { comment: MeforeshComment }) {
  return (
    <div className="mef-item">
      <div className="mef-source">
        {comment.source} <span style={{ opacity: 0.6 }}>· {comment.ref}</span>
      </div>
      <div className="mef-takeaway">{comment.takeaway}</div>
      {comment.hebrew && (
        <details>
          <summary>Verbatim text</summary>
          <div className="mef-verbatim" dir="rtl" lang="he">
            {comment.hebrew}
          </div>
          {comment.english && (
            <div style={{ marginTop: 6, color: "var(--soft)", fontSize: 13 }}>
              {comment.english}
            </div>
          )}
        </details>
      )}
    </div>
  );
}

function Group({
  label,
  items,
}: {
  label: string;
  items: MeforeshComment[];
}) {
  if (!items.length) return null;
  return (
    <div className="mef-group">
      <h4>{label}</h4>
      {items.map((c, i) => (
        <MeforeshItem key={i} comment={c} />
      ))}
    </div>
  );
}

export function MeforshimBlock({ data }: Props) {
  if (data.rashi.length === 0) return null;
  return (
    <div className="meforshim-block">
      <span className="mef-label">רש״י</span>
      {data.rashi.map((c, i) => (
        <MeforeshItem key={i} comment={c} />
      ))}
    </div>
  );
}
