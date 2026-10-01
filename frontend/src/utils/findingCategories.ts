// Plain-language meaning of each finding category. The category is chosen by the backend from the
// kinds of signals behind a finding (intelligence/finding_aggregator.py: FindingAggregator._category),
// in this order of precedence - so these descriptions must stay in step with that logic.

type CategoryInfo = {
  label: string;
  /** One short line, for a legend or a label. */
  short: string;
  /** What it means and what to check first, for a tooltip. */
  detail: string;
};

const CATEGORIES: Record<string, CategoryInfo> = {
  data_quality: {
    label: 'Data Quality',
    short: 'The metric stopped reporting or froze at one value',
    detail:
      'The problem is with the data itself: the metric stopped sending points (a gap), or got stuck at the same value. ' +
      'Check the exporter, scrape target or pipeline before trusting other findings on this metric.',
  },
  behavior_change: {
    label: 'Behavior Change',
    short: 'The metric moved to a new normal level, or is steadily trending',
    detail:
      'The metric settled at a new level and stayed there (for example after a deploy or config change), ' +
      'or has been climbing or falling steadily. Look at what changed around the time it started.',
  },
  unusual_activity: {
    label: 'Unusual Activity',
    short: 'Short spikes or dips that don’t fit the usual pattern',
    detail:
      'Brief stretches where the metric jumped or dropped well outside its normal range, then came back. ' +
      'Check whether they line up with traffic bursts, batch jobs or short incidents.',
  },
  operational_insight: {
    label: 'Operational Insight',
    short: 'A pattern worth knowing, such as a forecast',
    detail: 'Not a problem by itself, but useful context about how the metric behaves, such as a forecast or a recurring pattern.',
  },
};

function fallbackLabel(category: string): string {
  return category
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function categoryLabel(category?: string | null): string {
  if (!category) return 'Insight';
  return CATEGORIES[category]?.label ?? fallbackLabel(category);
}

export function categoryShortDescription(category?: string | null): string | null {
  return category ? CATEGORIES[category]?.short ?? null : null;
}

export function categoryDetail(category?: string | null): string | null {
  return category ? CATEGORIES[category]?.detail ?? null : null;
}
