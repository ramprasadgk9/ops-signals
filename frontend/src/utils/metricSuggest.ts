// "Pick your metric": which of the user's stored metric names best fit a catalog signal, by the
// signal's keywords (config/behavior_patterns_catalog.yml). A whole word of the name counts more
// than a keyword buried inside one.

function words(metric: string): string[] {
  return metric.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

export function metricScore(metric: string, keywords: string[]): number {
  const nameWords = words(metric);
  const lower = metric.toLowerCase();
  return keywords.reduce((score, keyword) => {
    const key = keyword.toLowerCase();
    if (nameWords.includes(key)) return score + 2;
    return lower.includes(key) ? score + 1 : score;
  }, 0);
}

/** The best-fitting stored metric names, most keywords first, then the shorter name. */
export function suggestMetrics(keywords: string[], metrics: string[], limit = 3): string[] {
  return metrics
    .map((metric) => ({ metric, score: metricScore(metric, keywords) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.metric.length - b.metric.length || a.metric.localeCompare(b.metric))
    .slice(0, limit)
    .map((item) => item.metric);
}
