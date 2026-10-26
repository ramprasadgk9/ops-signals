import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getSetupCheck, testPrometheusConnection } from './backendClient';
import { PluginSetupBanner, SetupCheckPanel, SetupChips } from './SetupCheckPanel';
import type { SetupCheckResult } from '../utils/setupCheck';

vi.mock('./backendClient', () => ({
  getSetupCheck: vi.fn(),
  sendTestAlert: vi.fn(),
  testPrometheusConnection: vi.fn(),
}));

const RESULT: SetupCheckResult = {
  generated_at: '2026-10-19T14:02:31Z',
  version: '0.5.0',
  checks: [
    { id: 'backend', group: 'required', status: 'ok', title: 'Backend', detail: 'Answering' },
    {
      id: 'connection:default',
      group: 'required',
      status: 'fail',
      title: 'Metrics: default',
      detail: "Can't reach localhost.",
      tried: 'GET http://localhost:9090/api/v1/status/buildinfo\n-> 503 Prometheus connection failed',
      cause: 'localhost is the backend\'s own machine.',
      fix: ['Use the Prometheus service name.'],
      action: 'test_connection',
      connection_id: 'default',
    },
    { id: 'login', group: 'recommended', status: 'warn', title: 'Login', detail: 'Open.', fix: ['Create a token.'], snippet: 'OPS_SIGNALS_API_TOKEN=x' },
    {
      id: 'analyzer_overrides', group: 'optional', status: 'ok', title: 'Per-service analyzer settings',
      detail: '1 override in 1 file in use: payments-team.yml', action: 'how_to_set', docs: 'docs/configuration.md',
      fix: ['checkout-team.yml skipped: a value is out of range. Its services run on the default settings.', 'Copy the example file.'],
      snippet: 'overrides:\n  payments_memory_trend: {}',
    },
  ],
};

describe('SetupCheckPanel', () => {
  afterEach(() => vi.clearAllMocks());

  it('checks the given backend and shows the groups', async () => {
    vi.mocked(getSetupCheck).mockResolvedValue(RESULT);
    render(<SetupCheckPanel backendUrl="http://localhost:8002" />);

    const needed = await screen.findByRole('region', { name: 'Needed to start' });
    expect(within(needed).getByText('Metrics: default')).toBeInTheDocument();
    expect(getSetupCheck).toHaveBeenCalledWith('http://localhost:8002');
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByText('localhost:8002')).toBeInTheDocument();
  });

  it('opens the fix and tests the connection again', async () => {
    vi.mocked(getSetupCheck).mockResolvedValue(RESULT);
    vi.mocked(testPrometheusConnection).mockResolvedValue({ available: false, message: 'Prometheus connection failed' } as never);
    render(<SetupCheckPanel backendUrl="http://localhost:8002" />);

    fireEvent.click(await screen.findByRole('button', { name: 'How to fix: Metrics: default' }));
    expect(screen.getByText(/503 Prometheus connection failed/)).toBeInTheDocument();
    expect(screen.getByText('Use the Prometheus service name.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Test Metrics: default' }));
    expect(await screen.findByText('Still failing: Prometheus connection failed')).toBeInTheDocument();
    expect(testPrometheusConnection).toHaveBeenCalledWith('http://localhost:8002', 'default');
  });

  it('shows an unreachable backend as a failed Backend check with the CORS hint', async () => {
    vi.mocked(getSetupCheck).mockRejectedValue(new TypeError('Failed to fetch'));
    render(<SetupCheckPanel backendUrl="https://ops.example.com" />);

    expect(await screen.findByText("Can't reach ops.example.com.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'How to fix: Backend' }));
    expect(screen.getByText(/OPS_SIGNALS_CORS_ORIGINS/)).toBeInTheDocument();
  });
});

describe('PluginSetupBanner', () => {
  it('links to the Configuration page while something needed is broken', () => {
    render(<PluginSetupBanner result={RESULT} unreachable={false} />);

    expect(screen.getByText('Setup: 1 of 2 done. Needs fixing: Metrics: default.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Setup check' })).toHaveAttribute('href', '/plugins/breezypoppy3596-opssignals-app?page=configuration');
  });

  it('tells a viewer to ask an admin instead of linking to a page they cannot open', () => {
    Object.assign(window, { grafanaBootData: { user: { orgRole: 'Viewer', isGrafanaAdmin: false } } });
    try {
      render(<PluginSetupBanner result={RESULT} unreachable={false} />);
      expect(screen.getByText('Ask a Grafana admin to open Ops Signals → Configuration.')).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Open Setup check' })).not.toBeInTheDocument();
    } finally {
      delete (window as { grafanaBootData?: unknown }).grafanaBootData;
    }
  });

  it('stays hidden when the backend is unreachable (the Backend chip says so) or nothing is broken', () => {
    const { container, rerender } = render(<PluginSetupBanner result={RESULT} unreachable />);
    expect(container).toBeEmptyDOMElement();
    rerender(<PluginSetupBanner result={{ ...RESULT, checks: RESULT.checks.slice(0, 1) }} unreachable={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('SetupChips', () => {
  it('shows what the check found, with the details on hover', () => {
    render(<SetupChips result={RESULT} unreachable={false} />);

    expect(screen.getByText('● Backend connected')).toBeInTheDocument();
    expect(screen.getByText('● Metrics: 1 failing')).toHaveAttribute('title', "Metrics: default: Can't reach localhost.");
  });
});

describe('SetupCheckPanel per-service analyzer settings', () => {
  afterEach(() => vi.clearAllMocks());

  it('offers "How to set" on the row even when it is ok', async () => {
    vi.mocked(getSetupCheck).mockResolvedValue(RESULT);
    render(<SetupCheckPanel backendUrl="http://localhost:8002" />);

    fireEvent.click(await screen.findByRole('button', { name: 'How to set: Per-service analyzer settings' }));

    expect(screen.getByText('Copy the example file.')).toBeInTheDocument();
  });
});
