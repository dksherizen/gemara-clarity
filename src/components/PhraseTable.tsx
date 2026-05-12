import type { Phrase } from "../lib/schema.js";

interface Props {
  phrases: Phrase[];
  showTranslation: boolean;
}

export function PhraseTable({ phrases, showTranslation }: Props) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {showTranslation && <th>English</th>}
            <th>Hebrew / Aramaic</th>
          </tr>
        </thead>
        <tbody>
          {phrases.map((p) => (
            <tr key={p.phraseNumber}>
              {showTranslation && (
                <td>
                  {p.english}
                  {p.notes && <div className="phrase-note">{p.notes}</div>}
                </td>
              )}
              <td className="rtl" dir="rtl" lang="he">
                {p.aramaic}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
