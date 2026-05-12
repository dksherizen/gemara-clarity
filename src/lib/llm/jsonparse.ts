export function extractJSON<T = unknown>(text: string): T {
  if (!text) throw new Error("Empty LLM response.");
  let s = text.trim();
  if (s.startsWith("```")) {
    s = s.replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/i, "").trim();
  }
  const first = s.indexOf("{");
  const lastClose = s.lastIndexOf("}");
  if (first >= 0 && lastClose > first) {
    s = s.slice(first, lastClose + 1);
  }
  try {
    return JSON.parse(s) as T;
  } catch (err) {
    const repaired = repairCommonIssues(s);
    return JSON.parse(repaired) as T;
  }
}

function repairCommonIssues(s: string): string {
  return s
    .replace(/,\s*([}\]])/g, "$1")
    .replace(/“|”/g, '"')
    .replace(/‘|’/g, "'");
}
