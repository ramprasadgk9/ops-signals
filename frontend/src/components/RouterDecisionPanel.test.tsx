import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RouterDecisionPanel } from './RouterDecisionPanel';
import { api } from '../api/queries';
import type { Me } from '../hooks/useWebPermissions';
import type { AnalyzerExecution, CsvAnalyzerRoutingDecision } from '../types';

vi.mock('../api/queries', () => ({ api: { me: vi.fn() } }));

const decisions: CsvAnalyzerRoutingDecision[] = [
  { analyzer_id: 'ruptures', display_name: 'Ruptures', recommendation: 'RECOMMENDED', final_score: 1, parameters_tested: { detected_profiles: ['baseline_shift', 'spike'] } },
  { analyzer_id: 'kats', display_name: 'Kats', recommendation: 'RECOMMENDED', final_score: 0.82 },
  { analyzer_id: 'stumpy', display_name: 'STUMPY', recommendation: 'NOT_RECOMMENDED', final_score: 0.42, routing_reason: 'Profiles did not match.' },
  { analyzer_id: 'prophet', display_name: 'Prophet', recommendation: 'REJECTED', final_score: 0 },
];
const executions: AnalyzerExecution[] = [
  { router_analyzer_id: 'ruptures', execution_status: 'completed', run_reason: 'router_pick', in_finding: true, execution_reason: 'Picked by the router for this series.' },
  { router_analyzer_id: 'kats', execution_status: 'skipped', run_reason: 'not_built_in' },
  { router_analyzer_id: 'stumpy', execution_status: 'completed', run_reason: 'always_run', in_finding: false, execution_reason: 'Runs on every series.', description: 'Finds a stretch that looks unlike the rest of the series.' },
  { router_analyzer_id: 'prophet', execution_status: 'skipped', run_reason: 'library_missing', missing_library: 'prophet' },
];

function renderPanel(role: Me['role'] | 'none') {
  const me: Me =
    role === 'none'
      ? { signed_in: false, name: null, role: null, via: 'none', groups: [], granted_by: null, mode: 'off', problem: null }
      : { signed_in: true, name: 'Sam', role, via: 'proxy', groups: [], granted_by: null, mode: 'proxy', problem: null };
  vi.mocked(api.me).mockResolvedValue(me);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterDecisionPanel decisions={decisions} executions={executions} executedAnalyzers={['ruptures', 'stumpy']} findingCount={1} />
    </QueryClientProvider>,
  );
}

// Same in-memory stand-in the AppShell tests use: Node's own localStorage global lacks clear().
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() { return items.size; },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => { items.delete(key); },
    setItem: (key: string, value: string) => { items.set(key, value); },
  };
}

beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));

describe('RouterDecisionPanel', () => {
  it('leads with what ran and why', () => {
    renderPanel('none');

    expect(screen.getByText('2', { selector: 'strong' }).parentElement).toHaveTextContent('2 ran');
    const ruptures = screen.getByTestId('ran-analyzer-ruptures');
    expect(within(ruptures).getByText('Router pick')).toBeInTheDocument();
    expect(within(ruptures).getByText('In the finding')).toBeInTheDocument();
    const stumpy = screen.getByTestId('ran-analyzer-stumpy');
    expect(within(stumpy).getByText('Runs on every series')).toBeInTheDocument();
    expect(within(stumpy).getByText('Runs on every series.')).toBeInTheDocument();
    expect(within(stumpy).queryByText('Profiles did not match.')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ran-analyzer-kats')).not.toBeInTheDocument();
  });

  it('explains what an analyzer does from a tip next to its name', async () => {
    renderPanel('none');

    const stumpy = screen.getByTestId('ran-analyzer-stumpy');
    fireEvent.click(within(stumpy).getByRole('button', { name: 'What STUMPY does' }));

    expect(await screen.findByRole('tooltip')).toHaveTextContent('Finds a stretch that looks unlike the rest of the series.');
    expect(within(screen.getByTestId('ran-analyzer-ruptures')).queryByRole('button', { name: /What Ruptures does/ })).not.toBeInTheDocument();
  });

  it('folds the scoring and keeps catalog-only analyzers apart', () => {
    renderPanel('none');

    expect(screen.queryByTestId('router-score-ruptures')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /How the router scored this series/ }));

    expect(screen.getByTestId('router-rating-stumpy')).toHaveTextContent('Not recommended');
    expect(screen.getByTestId('router-score-stumpy')).toHaveTextContent('Ran (every series)');
    expect(screen.getByTestId('router-score-prophet')).toHaveTextContent('Library not installed');
    expect(screen.queryByTestId('router-score-kats')).not.toBeInTheDocument();
    expect(screen.getByTestId('router-not-built-in-kats')).toHaveTextContent('Kats');
  });

  it('shows the install hint when nobody is signed in, as everything else is unlocked then', async () => {
    renderPanel('none');
    expect(await screen.findByTestId('missing-library-prophet')).toBeInTheDocument();
  });

  it('shows admins how to install a missing library', async () => {
    renderPanel('Admin');

    const hint = await screen.findByTestId('missing-library-prophet');
    fireEvent.click(within(hint).getByRole('button', { name: 'Show how to install' }));
    expect(within(hint).getByText('pip install prophet')).toBeInTheDocument();

    fireEvent.click(within(hint).getByRole('button', { name: "Don't show again" }));
    expect(screen.queryByTestId('missing-library-prophet')).not.toBeInTheDocument();
  });

  it('hides the install hint from viewers', async () => {
    renderPanel('Viewer');

    await screen.findByTestId('ran-analyzer-ruptures');
    await vi.waitFor(() => expect(api.me).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId('missing-library-prophet')).not.toBeInTheDocument();
  });
});
