import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AnalyzerSettingsPage } from './AnalyzerSettingsPage';
import { api } from '../api/queries';
import { SETTINGS } from '../utils/analyzerSettings.fixture';

vi.mock('../api/queries', () => ({
  api: { analyzerSettings: vi.fn(), services: vi.fn(), metrics: vi.fn() },
}));

function renderPage(path = '/analyzer-settings') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AnalyzerSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.clearAllMocks());

describe('AnalyzerSettingsPage', () => {
  it('shows where settings come from, how a run picks analyzers and whether each runs', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue(['checkout']);
    renderPage();

    const layers = await screen.findByRole('list', { name: 'Where a setting comes from' });
    expect(within(layers).getByText('1 value changed')).toBeInTheDocument();
    expect(within(layers).getByText('1 files · 1 overrides')).toBeInTheDocument();
    expect(within(layers).getByText('A sandbox. Runs never use what you try there.')).toBeInTheDocument();
    expect(screen.getByText(/runs up to 3 that score 0.80 or more/)).toBeInTheDocument();

    const table = screen.getByRole('table', { name: 'Analyzers' });
    expect(within(table).getByText('When it suits the metric')).toBeInTheDocument();
    expect(within(table).getByText('Only if you choose it')).toBeInTheDocument();
    expect(within(table).getByText("Can't run")).toBeInTheDocument();
    expect(within(table).getByText('2 settings')).toBeInTheDocument();
    expect(api.analyzerSettings).toHaveBeenCalledWith({ provider: 'prometheus', service: '', metric: '' });
  });

  it('answers at a glance what is customized, what runs, and which key nothing reads', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();
    const glance = await screen.findByRole('region', { name: 'At a glance' });
    expect(within(glance).getByText("Changed from the built-in defaults: 1 value in config/analyzers.yaml, 1 team's override for chosen services.")).toBeInTheDocument();
    expect(within(glance).getByText(/The router adds the ones that suit each metric from Trend Analysis\. Z-Score Anomaly runs only if you choose it\. Prophet can't run\./)).toBeInTheDocument();
    expect(within(glance).getByText(/probably a typo: trend: finding_rule.min_slope_percent/)).toBeInTheDocument();
    expect(within(glance).getByText('Labs are a sandbox:')).toBeInTheDocument();
  });

  it('groups analyzers by whether they run', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();
    const table = await screen.findByRole('table', { name: 'Analyzers' });
    const headings = within(table).getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent);
    expect(headings).toEqual(['The router picks them when they suit a metric', "Don't run unless you choose them", 'Turned on, but something they need is missing']);
  });

  it('opens an analyzer to show each value, its default and the file it comes from', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Show Trend Analysis settings' }));
    const settings = screen.getByRole('table', { name: 'Trend Analysis settings' });
    const slope = within(settings).getByText('finding_rules.min_slope_percent').closest('tr')!;
    expect(within(slope).getByText('10')).toHaveStyle({ textDecoration: 'line-through' });
    expect(within(slope).getByText('5')).toBeInTheDocument();
    expect(within(slope).getByText('config/analyzers.yaml')).toBeInTheDocument();
    expect(within(slope).getByText('A team can change it')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Try it in the Lab' })).toHaveAttribute('href', '/experiments/trend-lab');

    // A key Trend doesn't read is flagged; a label-only setting folds away until asked for.
    const typo = within(settings).getByText('finding_rule.min_slope_percent').closest('tr')!;
    expect(within(typo).getByText('Not read: check spelling')).toBeInTheDocument();
    expect(within(settings).queryByText('implementation.model')).not.toBeInTheDocument();
    fireEvent.click(within(settings).getByRole('button', { name: "Show 1 setting the analyzer doesn't use" }));
    const model = within(settings).getByText('implementation.model').closest('tr')!;
    expect(within(model).getByText('Label only')).toBeInTheDocument();
    expect(within(model).getByText("Shown in the finding's details only")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Only settings changed from default'));
    expect(within(settings).queryByText('implementation.model')).not.toBeInTheDocument();
  });

  it('offers the chosen service metrics in the Metric box, not browser history', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue({ ...SETTINGS, service: 'checkout' });
    vi.mocked(api.services).mockResolvedValue(['checkout']);
    vi.mocked(api.metrics).mockResolvedValue(['http_requests_total', 'process_cpu_seconds_total']);
    renderPage('/analyzer-settings?service=checkout');
    const box = await screen.findByRole('combobox', { name: 'Metric' });
    expect(box).toHaveAttribute('autocomplete', 'off');
    fireEvent.mouseDown(box);
    fireEvent.click(await screen.findByRole('option', { name: 'http_requests_total' }));
    expect(api.metrics).toHaveBeenCalledWith('checkout');
    expect(api.analyzerSettings).toHaveBeenLastCalledWith({ provider: 'prometheus', service: 'checkout', metric: 'http_requests_total' });
  });

  it("asks for a service's own settings and lists the services that have them", async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'payments-api · process_resident_memory_bytes' }));
    expect(api.analyzerSettings).toHaveBeenLastCalledWith({ provider: 'prometheus', service: 'payments-api', metric: 'process_resident_memory_bytes' });
  });

  it('says when no team file covers the chosen service', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue({ ...SETTINGS, service: 'checkout' });
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage('/analyzer-settings?service=checkout');
    expect(await screen.findByText("No team's file changes checkout: it runs on the site-wide settings.")).toBeInTheDocument();
    // Every setting stays listed: the changed-only filter starts off.
    expect(screen.getByLabelText('Only settings changed from default')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Show Z-Score Anomaly settings' }));
    expect(screen.getByRole('table', { name: 'Z-Score Anomaly settings' })).toHaveTextContent('finding_rules.min_abs_zscore');
  });

  it('offers every setting back when the changed-only filter leaves an analyzer empty', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();
    fireEvent.click(await screen.findByLabelText('Only settings changed from default'));
    fireEvent.click(screen.getByRole('button', { name: 'Show Z-Score Anomaly settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show all 1 setting' }));
    expect(screen.getByLabelText('Only settings changed from default')).not.toBeChecked();
    expect(screen.getByRole('table', { name: 'Z-Score Anomaly settings' })).toHaveTextContent('finding_rules.min_abs_zscore');
  });

  it('answers the three questions people ask in "How settings work"', async () => {
    vi.mocked(api.analyzerSettings).mockResolvedValue(SETTINGS);
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'How settings work' }));
    const dialog = await screen.findByRole('dialog', { name: 'How analyzer settings work' });
    expect(within(dialog).getByText('Which file do I edit?')).toBeInTheDocument();
    expect(within(dialog).getByText("I changed a Lab. Why didn't my findings change?")).toBeInTheDocument();
    expect(within(dialog).getByText('I changed a setting. Why did nothing happen?')).toBeInTheDocument();
  });

  it('reports a file the backend skipped', async () => {
    const layers = SETTINGS.layers.map((layer) => (layer.key === 'override' ? { ...layer, errors: [{ file: 'broken.yml', message: 'not valid YAML' }] } : layer));
    vi.mocked(api.analyzerSettings).mockResolvedValue({ ...SETTINGS, layers });
    vi.mocked(api.services).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('broken.yml is skipped')).toBeInTheDocument();
  });
});
