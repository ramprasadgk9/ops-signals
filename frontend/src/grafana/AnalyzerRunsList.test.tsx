import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalyzerRunsList } from './PanelPreview';
import { PermissionsProvider, type GrafanaRole } from './permissions';
import type { GrafanaAnalysisResult } from './contracts';

const result = {
  runId: 'run-1',
  status: 'complete',
  datasource: 'Prometheus',
  service: 'checkout',
  metric: 'cpu_usage',
  from: '',
  to: '',
  summary: '',
  signals: [],
  findings: [{ id: 1, title: 'Shift', summary: '', category: 'baseline_shift', health_status: 'warning', importance_score: 0.8, investigation_priority: 1, signal_ids: ['s1'] }],
  behaviorFindings: [],
  timeseries: [],
  analysisRuns: [],
  analyzerRouting: [
    { analyzer_id: 'ruptures', display_name: 'Ruptures', eligible: true, recommendation: 'RECOMMENDED', final_score: 1, reasons: [], warnings: [] },
    { analyzer_id: 'kats', display_name: 'Kats', eligible: true, recommendation: 'RECOMMENDED', final_score: 0.82, reasons: [], warnings: [] },
    { analyzer_id: 'stumpy', display_name: 'STUMPY', eligible: true, recommendation: 'NOT_RECOMMENDED', final_score: 0.42, reasons: ['Profiles did not match.'], warnings: [] },
    { analyzer_id: 'prophet', display_name: 'Prophet', eligible: false, recommendation: 'REJECTED', final_score: 0, reasons: [], warnings: [] },
  ],
  executedAnalyzers: ['ruptures', 'stumpy'],
  analyzerExecutions: [
    { router_analyzer_id: 'ruptures', execution_status: 'completed', run_reason: 'router_pick', in_finding: true, execution_reason: 'Picked by the router for this series.' },
    { router_analyzer_id: 'kats', execution_status: 'skipped', run_reason: 'not_built_in' },
    { router_analyzer_id: 'stumpy', execution_status: 'completed', run_reason: 'always_run', in_finding: false, execution_reason: 'Runs on every series.' },
    { router_analyzer_id: 'prophet', execution_status: 'skipped', run_reason: 'library_missing', missing_library: 'prophet' },
  ],
} as GrafanaAnalysisResult;

function renderList(role: GrafanaRole | null, overrides: Partial<GrafanaAnalysisResult> = {}) {
  render(
    <PermissionsProvider role={role}>
      <AnalyzerRunsList result={{ ...result, ...overrides }} />
    </PermissionsProvider>,
  );
}

describe('plugin AnalyzerRunsList', () => {
  it('shows what ran with its reason, not the router rating', () => {
    renderList(null);

    expect(screen.getByText(/2 analyzers ran/)).toBeInTheDocument();
    const stumpy = screen.getByTestId('ran-analyzer-stumpy');
    expect(within(stumpy).getByText('Runs on every series')).toBeInTheDocument();
    expect(within(stumpy).queryByText(/Profiles did not match/)).not.toBeInTheDocument();
    expect(within(screen.getByTestId('ran-analyzer-ruptures')).getByText('In the finding')).toBeInTheDocument();
  });

  it('folds the rest and lists catalog-only analyzers separately', () => {
    renderList(null);

    fireEvent.click(screen.getByRole('button', { name: 'How the router scored this series' }));
    expect(screen.getByTestId('router-score-prophet')).toHaveTextContent('Library not installed');
    expect(screen.queryByTestId('router-score-kats')).not.toBeInTheDocument();
    expect(screen.getByTestId('router-not-built-in')).toHaveTextContent('Kats');
  });

  it('shows the install hint to admins only', () => {
    renderList('Admin');
    expect(screen.getByTestId('missing-library-prophet')).toHaveTextContent('pip install prophet');
  });

  it('hides the install hint from viewers', () => {
    renderList('Viewer');
    expect(screen.queryByTestId('missing-library-prophet')).not.toBeInTheDocument();
  });

  it('still names what ran for runs saved without per-analyzer records', () => {
    renderList(null, { analyzerExecutions: [] });
    expect(screen.getByText(/2 analyzers ran/)).toBeInTheDocument();
    expect(screen.getByText('Ruptures, Stumpy')).toBeInTheDocument();
  });
});
