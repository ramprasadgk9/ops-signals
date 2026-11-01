import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AnalyzerLabConfigPanel } from './AnalyzerLabConfigPanel';
import { LabSandboxBanner, RunsUse } from './labSettings';
import { api } from '../../api/queries';
import { SETTINGS } from '../../utils/analyzerSettings.fixture';

vi.mock('../../api/queries', () => ({
  api: { analyzerSettings: vi.fn(), services: vi.fn() },
}));

function renderWith(node: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function panel(values: Record<string, unknown>, extra: Partial<React.ComponentProps<typeof AnalyzerLabConfigPanel>> = {}) {
  return (
    <AnalyzerLabConfigPanel
      analyzerId="trend"
      labName="Trend Lab"
      values={values}
      passFailStatus="unknown"
      passFailReason="Run the analyzer to mark this lab run pass or fail."
      productionNote="the metric moves steadily."
      {...extra}
    />
  );
}

afterEach(() => vi.clearAllMocks());

describe('Use these values for real', () => {
  it('has no snippet while the Lab values are the ones runs use', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderWith(panel({ implementation: { model: 'OLS' }, finding_rules: { min_slope_percent: 5 } }));
    expect(await screen.findByText('Your values are the same as the values runs use now. Change a setting above to get a snippet.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Snippet')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Save YAML Suggestion/ })).not.toBeInTheDocument();
  });

  it("offers a team's file first, then the site-wide block, with only the changed key", async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue(['payments-api']);
    renderWith(panel({ implementation: { model: 'OLS' }, finding_rules: { min_slope_percent: 8 } }));

    expect(await screen.findByText('You changed 1 setting')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Service'), { target: { value: 'payments-api' } });
    const snippet = screen.getByLabelText('Snippet');
    expect(snippet.textContent).toContain('overrides:');
    expect(snippet.textContent).toContain('service: payments-api');
    expect(snippet.textContent).toContain('min_slope_percent: 8');
    expect(snippet.textContent).not.toContain('model');
    expect(screen.getByRole('button', { name: 'Download payments-api.yml' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: 'For every service' }));
    expect(screen.getByLabelText('Snippet').textContent).toBe('analysis:\n  analyzers:\n    trend:\n      finding_rules:\n        min_slope_percent: 8\n');
  });

  it("falls back to every service when a team's file can't hold the change", async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderWith(panel({ implementation: { model: 'RLM' } }));
    expect(await screen.findByText(/Not possible for these values: implementation.model can only be changed for every service/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'For every service' })).toBeChecked();
    expect(screen.getByLabelText('Snippet').textContent).toContain('model: RLM');
  });

  it("warns when the analyzer doesn't run on its own", async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderWith(panel({ finding_rules: { min_abs_zscore: 4 } }, { analyzerId: 'anomaly_zscore', labName: 'Z-Score Anomaly Lab' }));
    expect(await screen.findByText(/Z-Score Anomaly doesn't run on its own in your setup/)).toBeInTheDocument();
  });

  it('compares the last run with what the values in use found', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderWith(panel({ finding_rules: { min_slope_percent: 8 } }, { yourFound: true, comparison: { running: false, found: false, error: null } }));
    const region = await screen.findByRole('region', { name: 'Use these values for real' });
    expect(within(region).getByText(/With your values:/).textContent).toBe('With your values: a finding. With the values runs use now: no finding.');
  });
});

describe('Lab sandbox banner and field notes', () => {
  it('says the Lab is a sandbox and shows the values runs use', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    renderWith(<LabSandboxBanner analyzerId="anomaly_zscore" paths={['finding_rules.min_abs_zscore']} />);
    const banner = screen.getByRole('note', { name: 'This Lab is a sandbox' });
    expect(within(banner).getByText('This is a sandbox. Nothing you try here changes real analysis runs.')).toBeInTheDocument();
    expect(await within(banner).findByText('min_abs_zscore 3')).toBeInTheDocument();
    expect(within(banner).getByText('Only if you choose it')).toBeInTheDocument();
    expect(within(banner).getByRole('link', { name: 'See all settings in use →' })).toHaveAttribute('href', '/analyzer-settings?analyzer=anomaly_zscore');
  });

  it('notes the value in use under a field, and resets a changed one', () => {
    const analyzer = SETTINGS.analyzers[0];
    const onReset = vi.fn();
    const { rerender } = render(<RunsUse analyzer={analyzer} path="implementation.model" value="OLS" />);
    expect(screen.getByText('Runs use OLS (default)')).toBeInTheDocument();
    rerender(<RunsUse analyzer={analyzer} path="finding_rules.min_slope_percent" value={8} onReset={onReset} />);
    expect(screen.getByText(/Changed · runs use 5/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(onReset).toHaveBeenCalledWith(5);
  });
});
