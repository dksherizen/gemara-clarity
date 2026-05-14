import type { MeforshimBlock as MeforshimData, MeforeshComment } from "../lib/schema.js";

interface Props {
  data: MeforshimData;
}

function MeforeshItem({ comment }: { comment: MeforeshComment }) {
  const hasPhrases = comment.phrases && comment.phrases.length > 0;
  return (
    <div className="mef-item">
      <div className="mef-source">
        {comment.source} <span style={{ opacity: 0.6 }}>· {comment.ref}</span>
      </div>
      <div className="mef-takeaway">{comment.takeaway}</div>
      {(comment.hebrew || hasPhrases) && (
        <details>
          <summary>Verbatim text</summary>
          {hasPhrases ? (
            <div className="table-wrap" style={{ marginTop: 6 }}>
              <table style={{ fontSize: 13 }}>
                <thead>
                  <tr>
                    <th>English</th>
                    <th>Hebrew</th>
                  </tr>
                </thead>
                <tbody>
                  {comment.phrases!.map((p) => (
                    <tr key={p.phraseNumber}>
                      <td style={{ color: "var(--soft)" }}>
                        {p.english}
                        {p.notes && (
                          <div className="phrase-note">{p.notes}</div>
                        )}
                      </td>
                      <td className="rtl" dir="rtl" lang="he">
                        {p.aramaic}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <>
              <div className="mef-verbatim" dir="rtl" lang="he">
                {comment.hebrew}
              </div>
              {comment.english && (
                <div style={{ marginTop: 6, color: "var(--soft)", fontSize: 13 }}>
                  {comment.english}
                </div>
              )}
            </>
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
  const total =
    data.rashi.length +
    data.tosafot.length +
    data.rishonim.length +
    data.acharonim.length;
  if (total === 0) return null;
  return (
    <div className="meforshim-block">
      <span className="mef-label">Meforshim</span>
      {data.rashi.length > 0 && (
        <div className="mef-group">
          <h4>רש״י</h4>
          {data.rashi.map((c, i) => (
            <MeforeshItem key={`r-${i}`} comment={c} />
          ))}
        </div>
      )}
      {data.tosafot.length > 0 && (
        <div className="mef-group">
          <h4>תוספות</h4>
          {data.tosafot.map((c, i) => (
            <MeforeshItem key={`t-${i}`} comment={c} />
          ))}
        </div>
      )}
      {data.rishonim.length > 0 && (
        <div className="mef-group">
          <h4>Rishonim</h4>
          {data.rishonim.map((c, i) => (
            <MeforeshItem key={`ri-${i}`} comment={c} />
          ))}
        </div>
      )}
      {data.interplaySummary && (
        <div className="mef-interplay">
          <strong>Interplay:</strong> {data.interplaySummary}
        </div>
      )}
    </div>
  );
}
