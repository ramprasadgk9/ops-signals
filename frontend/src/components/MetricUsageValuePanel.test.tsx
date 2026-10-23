import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MetricUsageValuePanel, formatMoney } from './MetricUsageValuePanel';
import type { MetricUsageItem, MetricUsageSnapshot } from '../types';

const snapshot = (overrides: Partial<MetricUsageSnapshot> = {}): MetricUsageSnapshot => ({
  id: 's', trigger: 'schedule', status: 'completed', created_at: '2026-10-08T12:00:00Z', duration_ms: 50, error: null,
  metrics_total: 299, watched: 8, blind_spots: 7, unwatched: 284, missing: 0, watched_percent: 2.7,
  series_total: 10000, series_unwatched: 5200, sources: {}, ...overrides,
});

const blind = (metric: string, problems: number): MetricUsageItem => ({
  metric, status: 'blind_spot', connections: ['default'], usages: [], via_recording_rules: [],
  problem_findings: problems, latest_finding_id: 1, analyzed: true, series: 10,
});

describe('MetricUsageValuePanel', () => {
  it('leads with series and adds the cost at the configured rate as an estimate', () => {
    render(
      <MetricUsageValuePanel
        snapshot={snapshot()}
        cost={{ per_1k_series_month: 0.5, currency: 'USD', unwatched_monthly: 2.6, total_monthly: 5 }}
        blindSpots={[]}
        history={[]}
      />
    );
    const tile = screen.getByTestId('value-storage');
    expect(tile).toHaveTextContent('5,200 series');
    expect(tile).toHaveTextContent('on metrics no dashboard or alert uses');
    expect(tile).toHaveTextContent('52% of all 10,000. Some may still matter: add those to Grafana, drop the rest.');
    expect(tile).toHaveTextContent(`About ${formatMoney(2.6, 'USD')} / month at your rate`);
    expect(screen.getAllByLabelText(/How this is worked out: .*5,200 series ÷ 1,000 ×/)).toHaveLength(1);
  });

  it('shows no money until a rate is set', () => {
    render(<MetricUsageValuePanel snapshot={snapshot()} cost={null} blindSpots={[]} history={[]} />);
    const tile = screen.getByTestId('value-storage');
    expect(tile).toHaveTextContent('5,200 series');
    expect(tile).not.toHaveTextContent('$');
    expect(screen.getAllByLabelText(/Set OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES to also see an estimated monthly cost/)).toHaveLength(1);
  });

  it('links to the metrics when the page can open them', () => {
    const onReview = vi.fn();
    render(<MetricUsageValuePanel snapshot={snapshot()} cost={null} blindSpots={[]} history={[]} onReviewUnused={onReview} />);
    fireEvent.click(screen.getByRole('button', { name: 'See these metrics →' }));
    expect(onReview).toHaveBeenCalled();
  });

  it('says when series could not be counted', () => {
    render(<MetricUsageValuePanel snapshot={snapshot({ series_total: null, series_unwatched: null })} cost={null} blindSpots={[]} history={[]} />);
    expect(screen.getByTestId('value-storage')).toHaveTextContent("Series couldn't be counted");
  });

  it('adds up the problems on blind spots', () => {
    render(<MetricUsageValuePanel snapshot={snapshot()} cost={null} blindSpots={[blind('a', 28), blind('b', 26)]} history={[]} />);
    expect(screen.getByTestId('value-unseen')).toHaveTextContent('54 problemsnobody would have seenOn 2 metrics with no dashboard or alert');
  });

  it('compares the oldest kept check with the latest', () => {
    const history = [
      snapshot({ id: 'new', watched_percent: 10.5, blind_spots: 2, created_at: '2026-10-08T12:00:00Z' }),
      snapshot({ id: 'failed', status: 'failed', watched_percent: null, blind_spots: 0 }),
      snapshot({ id: 'old', watched_percent: 2.7, blind_spots: 7, created_at: '2026-10-01T12:00:00Z' }),
    ];
    render(<MetricUsageValuePanel snapshot={snapshot()} cost={null} blindSpots={[]} history={history} />);
    const tile = screen.getByTestId('value-trend');
    expect(tile).toHaveTextContent('2.7% → 10.5%');
    expect(tile).toHaveTextContent('Blind spots 7 → 2 ✓');
  });

  it('waits for a second check before showing a trend', () => {
    render(<MetricUsageValuePanel snapshot={snapshot()} cost={null} blindSpots={[]} history={[snapshot()]} />);
    expect(screen.getByTestId('value-trend')).toHaveTextContent('after the next check');
  });

  it('falls back to the plain code for a currency the browser does not know', () => {
    expect(formatMoney(12.5, 'credits')).toBe('12.5 credits');
  });
});
