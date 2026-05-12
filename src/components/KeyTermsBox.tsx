import type { KeyTerm } from "../lib/schema.js";

export function KeyTermsBox({ terms }: { terms: KeyTerm[] }) {
  if (!terms.length) return null;
  return (
    <div className="key-terms-box">
      <span className="teaching-label">Key Terms</span>
      <div className="key-terms-grid">
        {terms.map((t, i) => (
          <div key={i} className="term-item">
            <span className="term-heb" dir="rtl" lang="he">
              {t.term}
            </span>
            <span className="term-eng">{t.meaning}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
