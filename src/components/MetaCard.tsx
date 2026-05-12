import type { DafAnalysis } from "../lib/schema.js";

export function MetaCard({ analysis }: { analysis: DafAnalysis }) {
  return (
    <section className="card meta-card">
      <h2>{analysis.mainTopic}</h2>
      <p>{analysis.overview}</p>
      <p className="sub" style={{ marginTop: 8, fontSize: 12 }}>
        {analysis.ref} • {analysis.steps.length} steps •{" "}
        {analysis.sugyaBoundaries.length} sugyot • pipeline v
        {analysis.pipelineVersion}
      </p>
    </section>
  );
}
