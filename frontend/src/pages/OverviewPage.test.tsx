import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from './OverviewPage';
import { api } from '../api/queries';
import type { BehaviorFinding, Finding, IngestionStatus, OperationalCase } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    metricUsage: vi.fn().mockResolvedValue({ snapshot: null, items: [] }),
    findings: vi.fn(),
    cases: vi.fn(),
    behaviorFindings: vi.fn(),
    overviewSummary: vi.fn(),
    memoryStats: vi.fn(),
    autonomousPolicyRuns: vi.fn(),
    ingestionStatus: vi.fn(),
    setupSummary: vi.fn().mockResolvedValue({ generated_at: '2026-10-19T00:00:00Z', version: 'test', checks: [] }),
    alerts: vi.fn(),
    runCsvUpload: vi.fn(),
    sendTestAlert: vi.fn(),
  },
}));

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const emptySummary = {
  generated_at: '2026-07-26T00:00:00Z',
  window: '24h' as const,
  active_findings: 0,
  open_cases: 0,
  behavior_changes: 0,
  impacted_services: 0,
  memory_items: 0,
  severity_trend: [],
  category_breakdown: [],
};

const healthyMemory = {
  generated_at: '2026-07-26T00:00:00Z',
  enabled: true,
  status: 'healthy',
  indexed_cases: 0,
  not_indexed_cases: 0,
  stale_cases: 0,
  error_cases: 0,
  total_cases: 0,
  source: 'ops_operational_cases.memory_status',
};

const autonomousRun = {
  policy_run_id: 'run-1',
  id: 'run-1',
  status: 'completed',
  trigger: 'run_once',
  policy_id: null,
  started_at: '2026-07-26T00:00:00Z',
  completed_at: '2026-07-26T00:01:00Z',
  metrics_discovered: 4,
  metrics_selected: 1,
  jobs_planned: 1,
  jobs_completed: 1,
  jobs_skipped: 3,
  jobs_failed: 0,
  findings_created: 2,
};

describe('OverviewPage integration resilience', () => {
  beforeEach(() => {
    // Tests that predate the ingestion status endpoint run against a failing one - which must
    // leave the Overview exactly as it was.
    vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('not mocked'));
    vi.mocked(api.alerts).mockRejectedValue(new Error('not mocked'));
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders authoritative overview summary values from the backend', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 1,
        service: 'checkout-api',
        metric_name: 'cpu_usage',
        title: 'CPU usage sustained high',
        summary: 'CPU high',
        category: 'behavior_change',
        health_status: 'critical',
        importance_score: 0.9,
        investigation_priority: 1,
        signal_ids: [],
        comparison_json: {},
        created_at: '2026-07-26T00:00:00Z',
      },
    ]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue({
      ...emptySummary,
      active_findings: 3,
      open_cases: 1,
      behavior_changes: 2,
      impacted_services: 2,
      memory_items: 1,
      severity_trend: [{ timestamp: '2026-07-26T00:00:00Z', critical: 1, high: 2, medium: 0, low: 0 }],
      category_breakdown: [{ category: 'behavior_change', count: 3 }],
    });
    vi.mocked(api.memoryStats).mockResolvedValue({ ...healthyMemory, indexed_cases: 1, total_cases: 1 });
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([autonomousRun]);

    renderOverview();

    expect(await screen.findByText('Active Findings')).toBeInTheDocument();
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Open Cases').length).toBeGreaterThan(0);
    expect(screen.getByText('Operational Summary')).toBeInTheDocument();
    expect(screen.getByText('Needs Attention')).toBeInTheDocument();
    expect(screen.getByText('CPU usage sustained high')).toBeInTheDocument();
    expect(screen.getByText('Autonomous Analysis')).toBeInTheDocument();
    expect(screen.getByText('checkout-api / cpu_usage')).toBeInTheDocument();
    expect(screen.getByText('Findings')).toBeInTheDocument();
    expect(screen.getByText('Generated')).toBeInTheDocument();
    expect(screen.getByText('Failed Jobs')).toBeInTheDocument();
    expect(screen.getByText('Execution errors')).toBeInTheDocument();
    expect(screen.getByText('Top Metric')).toBeInTheDocument();
    expect(screen.getByText('cpu_usage')).toBeInTheDocument();
    expect(screen.queryByText('Memory Items')).not.toBeInTheDocument();
    expect(screen.queryByText('Finding Severity Trend')).not.toBeInTheDocument();
  });

  it('only labels a "Needs Attention" row with a case when that exact finding was promoted, not just any finding sharing its metric name', async () => {
    // Regression test: a prior fallback matched a case to a finding by metric_name alone,
    // ignoring service - so an un-cased finding from one service showed up mislabeled with the
    // case ID of an unrelated, differently-serviced finding that happened to share a metric name.
    const cpuFindingFromCasedService: Finding = {
      id: 36,
      service: 'ruptures-lab',
      metric_name: 'cpu_usage',
      title: 'cpu_usage is trending in one direction.',
      summary: 'trend',
      category: 'behavior_change',
      health_status: 'significant',
      importance_score: 0.7,
      investigation_priority: 2,
      signal_ids: [],
      comparison_json: {},
      created_at: '2026-09-19T15:03:09Z',
    };
    const cpuFindingFromUncasedService: Finding = {
      ...cpuFindingFromCasedService,
      id: 41,
      service: 'test-otlp-service',
      created_at: '2026-09-22T16:24:25Z',
    };
    const caseForFirstFinding: OperationalCase = {
      id: 12,
      finding_id: 36,
      analysis_run_id: 'run-36',
      case_title: 'cpu_usage is trending in one direction.',
      case_status: 'open',
      finding_snapshot: cpuFindingFromCasedService,
      investigation_status: 'not_started',
      investigation_notes: [],
      root_cause_status: 'unknown',
      root_cause_verified: false,
      outcome_status: 'pending',
      memory_status: 'not_indexed',
      created_at: '2026-09-19T15:06:49Z',
      updated_at: '2026-09-19T15:06:49Z',
    };

    vi.mocked(api.findings).mockResolvedValue([cpuFindingFromUncasedService, cpuFindingFromCasedService]);
    vi.mocked(api.cases).mockResolvedValue([caseForFirstFinding]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('test-otlp-service / cpu_usage')).toBeInTheDocument();
    expect(screen.getByText('ruptures-lab / cpu_usage')).toBeInTheDocument();
    // The un-cased finding must show "No case" - not the other finding's "Case #12".
    expect(screen.getByText('No case')).toBeInTheDocument();
    expect(screen.getByText('Case #12')).toBeInTheDocument();
    expect(screen.getAllByText(/Case #12/)).toHaveLength(1);
  });

  it('renders empty states without fabricated trend points', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('No findings need attention in this window.')).toBeInTheDocument();
    expect(screen.getByText('No open cases returned by the API.')).toBeInTheDocument();
    expect(api.findings).toHaveBeenCalledWith(undefined, undefined, undefined, '24h');
  });

  it('keeps memory inventory off the executive overview', async () => {
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue({ ...healthyMemory, status: 'unhealthy', indexed_cases: 4 });
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('Operational Summary')).toBeInTheDocument();
    expect(screen.queryByText('Memory Items')).not.toBeInTheDocument();
    expect(screen.queryByText('Memory unavailable')).not.toBeInTheDocument();
  });

  it('keeps independent sections usable when the overview summary request fails', async () => {
    vi.mocked(api.findings).mockResolvedValue([
      {
        id: 1,
        service: 'checkout-api',
        metric_name: 'cpu_usage',
        title: 'CPU usage sustained high',
        summary: 'CPU high',
        category: 'resource',
        health_status: 'warning',
        importance_score: 0.8,
        investigation_priority: 2,
        signal_ids: [],
        comparison_json: {},
        created_at: '2026-07-26T00:00:00Z',
      },
    ]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([]);
    vi.mocked(api.overviewSummary).mockRejectedValue(new Error('malformed JSON'));
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findAllByText('Unavailable')).not.toHaveLength(0);
    expect(screen.getByText(/Findings unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Service impact unavailable/)).toBeInTheDocument();
    expect(screen.getByText('CPU usage sustained high')).toBeInTheDocument();
  });

  describe('data source onboarding', () => {
    const ingestion = (overrides: Partial<IngestionStatus> = {}): IngestionStatus => ({
      generated_at: '2026-07-26T00:00:00Z',
      has_any_data: false,
      sources: {
        otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: null },
        alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: false, token_required: false, last_received_at: null, received_24h: 0 },
        prometheus: { configured: false },
      },
      ...overrides,
    });

    function mockEmptyOverview() {
      vi.mocked(api.findings).mockResolvedValue([]);
      vi.mocked(api.cases).mockResolvedValue([]);
      vi.mocked(api.behaviorFindings).mockResolvedValue([]);
      vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
      vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
      vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);
    }

    it('counts the problems that need attention and says how many more are context', async () => {
      mockEmptyOverview();
      vi.mocked(api.overviewSummary).mockResolvedValue({ ...emptySummary, active_findings: 299, attention_findings: 57, context_findings: 242 });

      renderOverview();

      const tile = (await screen.findByText('Need Attention')).closest('a') as HTMLElement;
      expect(tile).toHaveTextContent('57');
      expect(tile).toHaveTextContent('+242 in context');
      expect(screen.queryByText('Active Findings')).not.toBeInTheDocument();
      expect(screen.getByText(/57 findings need attention, 242 more in context\./)).toBeInTheDocument();
    });

    it('lists only findings that need attention in the Needs Attention table', async () => {
      mockEmptyOverview();
      const base = { service: 'checkout-api', category: 'behavior_change', health_status: 'significant', importance_score: 0.7, investigation_priority: 2, signal_ids: [], comparison_json: {}, summary: '' };
      vi.mocked(api.findings).mockResolvedValue([
        { ...base, id: 1, metric_name: 'cpu_usage', title: 'cpu needs a look', trust: { tier: 'needs_attention' } },
        { ...base, id: 2, metric_name: 'disk_bytes', title: 'disk burst in context', trust: { tier: 'context' } },
      ] as never);

      renderOverview();

      expect(await screen.findByText('cpu needs a look')).toBeInTheDocument();
      expect(screen.queryByText('disk burst in context')).not.toBeInTheDocument();
    });

    it('shows the get-data-in panel and dashes instead of zero KPIs on a fresh install', async () => {
      mockEmptyOverview();
      vi.mocked(api.ingestionStatus).mockResolvedValue(ingestion());

      renderOverview();

      expect(await screen.findByText('Ops Signals hasn’t received any data yet')).toBeInTheDocument();
      expect(screen.getByText('Send metrics via OTLP')).toBeInTheDocument();
      expect(screen.getByText('Connect Alertmanager')).toBeInTheDocument();
      expect(screen.getByText(`${window.location.origin}/api/otlp/v1/metrics`)).toBeInTheDocument();
      expect(screen.getByText(`${window.location.origin}/api/integrations/alertmanager`)).toBeInTheDocument();
      expect(screen.getByText('Waiting for data')).toBeInTheDocument();
      expect(screen.getByText('Disabled')).toBeInTheDocument();
      // The one-off tile stays here, where a brand-new user needs it (Integrations only mentions it).
      expect(screen.getByText('Just exploring?')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Load demo data' })).toBeInTheDocument();
      // Enrichment is off, so there is nothing to test yet.
      expect(screen.queryByRole('button', { name: 'Send test alert' })).not.toBeInTheDocument();
      expect(screen.getByRole('status', { name: 'Data sources' })).toBeInTheDocument();
      expect(screen.getAllByText('—')).toHaveLength(4);
      expect(screen.queryByText('Healthy')).not.toBeInTheDocument();
      expect(screen.getByText(/Waiting for the first metrics or alerts/)).toBeInTheDocument();
      expect(screen.queryByText(/Automation healthy/)).not.toBeInTheDocument();
    });

    it('keeps the normal overview once any data exists, and shows live sources in the strip', async () => {
      mockEmptyOverview();
      vi.mocked(api.ingestionStatus).mockResolvedValue(
        ingestion({
          has_any_data: true,
          sources: {
            otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: new Date().toISOString() },
            alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: true, token_required: false, last_received_at: null, received_24h: 0 },
            prometheus: { configured: true },
          },
        })
      );

      renderOverview();

      expect(await screen.findByText(/OTLP · just now/)).toBeInTheDocument();
      expect(screen.queryByText('Ops Signals hasn’t received any data yet')).not.toBeInTheDocument();
      expect(screen.queryByText('—')).not.toBeInTheDocument();
      expect(screen.getByText('Healthy')).toBeInTheDocument();
    });

    it('keeps the panel and its result on screen after the first data lands, until closed', async () => {
      mockEmptyOverview();
      vi.mocked(api.ingestionStatus).mockResolvedValueOnce(ingestion()).mockResolvedValue(ingestion({ has_any_data: true }));
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('timestamp,metric_name,value\n', { status: 200 })));
      vi.mocked(api.runCsvUpload).mockResolvedValue({
        analysis_run_id: 'run-demo',
        file_name: 'demo-checkout-cpu.csv',
        provider: 'generic',
        source_type: 'csv',
        service: 'checkout',
        metric_name: 'cpu_usage',
        sample_count: 288,
        findings_count: 1,
      });

      renderOverview();
      fireEvent.click(await screen.findByRole('button', { name: 'Load demo data' }));

      expect(await screen.findByText('Data is arriving')).toBeInTheDocument();
      expect(screen.getByText(/Demo analysis complete for checkout \/ cpu_usage/)).toBeInTheDocument();
      expect(screen.queryByText('—')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      expect(screen.queryByText('Data is arriving')).not.toBeInTheDocument();
      vi.unstubAllGlobals();
    });

    it('offers no close button while nothing has arrived yet', async () => {
      mockEmptyOverview();
      vi.mocked(api.ingestionStatus).mockResolvedValue(ingestion());

      renderOverview();

      expect(await screen.findByText('Ops Signals hasn’t received any data yet')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    });

    it('renders the overview exactly as before when the status endpoint fails', async () => {
      mockEmptyOverview();
      vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('404'));

      renderOverview();

      expect(await screen.findByText('No findings need attention in this window.')).toBeInTheDocument();
      expect(screen.getByText('Healthy')).toBeInTheDocument();
      expect(screen.queryByText('Ops Signals hasn’t received any data yet')).not.toBeInTheDocument();
      expect(screen.queryByRole('status', { name: 'Data sources' })).not.toBeInTheDocument();
    });
  });

  describe('received alerts', () => {
    const finding: Finding = {
      id: 7,
      service: 'checkout-api',
      metric_name: 'latency_p95',
      title: 'Latency shift',
      summary: 'p95 up',
      category: 'behavior_change',
      health_status: 'critical',
      importance_score: 0.9,
      investigation_priority: 1,
      signal_ids: [],
      comparison_json: {},
      created_at: '2026-09-26T00:00:00Z',
    };
    const linkedAlert = {
      id: 1,
      source: 'alertmanager',
      alert_name: 'HighLatency',
      status: 'firing',
      service: 'checkout-api',
      severity: 'critical',
      summary: 'p95 above 300ms',
      starts_at: '2026-09-26T00:00:00Z',
      ends_at: null,
      received_at: new Date().toISOString(),
      labels: {},
      generator_url: null,
      analysis_status: null,
      recommendation: null,
      notify_status: null,
      finding_id: 7,
      case_id: null,
    };

    function mockOverviewWith(findings: Finding[]) {
      vi.mocked(api.findings).mockResolvedValue(findings);
      vi.mocked(api.cases).mockResolvedValue([]);
      vi.mocked(api.behaviorFindings).mockResolvedValue([]);
      vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
      vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
      vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);
    }

    it('badges a needs-attention finding with its linked alert and lists incoming alerts', async () => {
      mockOverviewWith([finding]);
      vi.mocked(api.alerts).mockResolvedValue([linkedAlert]);

      renderOverview();

      expect(await screen.findByText('Alert: HighLatency')).toBeInTheDocument();
      expect(screen.getByText('checkout-api / latency_p95')).toBeInTheDocument();
      expect(await screen.findByRole('region', { name: 'Incoming Alerts' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'All alerts →' })).toHaveAttribute('href', '/alerts');
    });

    it('adds nothing when no alerts have been received', async () => {
      mockOverviewWith([finding]);
      vi.mocked(api.alerts).mockResolvedValue([]);

      renderOverview();

      expect(await screen.findByText('checkout-api / latency_p95')).toBeInTheDocument();
      await waitFor(() => expect(api.alerts).toHaveBeenCalled());
      expect(screen.queryByText(/Alert: /)).not.toBeInTheDocument();
      expect(screen.queryByRole('region', { name: 'Incoming Alerts' })).not.toBeInTheDocument();
    });
  });
});

describe('OverviewPage combined patterns', () => {
  beforeEach(() => {
    vi.mocked(api.ingestionStatus).mockRejectedValue(new Error('not mocked'));
    vi.mocked(api.alerts).mockRejectedValue(new Error('not mocked'));
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('lists a combined pattern first in Needs Attention, marked with its metric count', async () => {
    const pattern = {
      id: 3,
      behavior_id: 'pool_exhaustion:1:run-1',
      definition_id: 'pool_exhaustion',
      definition_version: 1,
      title: 'Database connection pool exhaustion',
      summary: 'Pool filling up.',
      category: 'resource_constraint',
      severity: 'critical',
      service: 'checkout-api',
      analysis_run_id: 'run-1',
      input_metrics_json: { db_wait: 'db_connection_wait_seconds', db_pool: 'db_connections_active' },
      facts_json: {},
      evidence_json: [],
      matched_conditions_json: [],
      confidence: 1,
      correlation_json: {},
      case_id: null,
      occurrence_count: 1,
      last_seen_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
    } satisfies BehaviorFinding;
    vi.mocked(api.findings).mockResolvedValue([]);
    vi.mocked(api.cases).mockResolvedValue([]);
    vi.mocked(api.behaviorFindings).mockResolvedValue([pattern]);
    vi.mocked(api.overviewSummary).mockResolvedValue(emptySummary);
    vi.mocked(api.memoryStats).mockResolvedValue(healthyMemory);
    vi.mocked(api.autonomousPolicyRuns).mockResolvedValue([]);

    renderOverview();

    expect(await screen.findByText('checkout-api / 2 metrics')).toBeInTheDocument();
    expect(screen.getByText('Combined pattern')).toBeInTheDocument();
    expect(screen.getByText('Database connection pool exhaustion')).toBeInTheDocument();
    expect(screen.queryByText('No findings need attention in this window.')).not.toBeInTheDocument();
  });
});
