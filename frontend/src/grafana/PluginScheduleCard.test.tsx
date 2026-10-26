import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutonomousPolicy } from './contracts';
import { LOCK_REASONS, PermissionsProvider } from './permissions';
import { PluginScheduleCard } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));

const SCHEDULE = {
  id: 'policy-1',
  name: 'Checkout services, hourly',
  datasource: 'prometheus',
  backend: 'grafana-plugin',
  scope: { environment: 'production', services: [], namespaces: [], all_services: true, all_namespaces: true, service_label: 'service', namespace_label: 'namespace', environment_label: 'env' },
  monitoring_selection: { categories: ['performance'] },
  execution: { interval: '1m', analysis_window: '6h', max_metrics_per_run: 200, max_parallel_jobs: 20 },
  enabled: true,
  schedule_minutes: 60,
  next_run_at: null,
  last_run_status: 'completed',
  consecutive_failures: 0,
  created_at: null,
  updated_at: null,
  created_by: 'priya',
  edited_by: 'sam',
} as AutonomousPolicy;

describe('PluginScheduleCard', () => {
  it("shows a Viewer the schedule and who owns it, with no buttons (the Autonomous tab's read-only view)", () => {
    render(
      <PermissionsProvider role="Viewer">
        <PluginScheduleCard policy={SCHEDULE} connections={[]} readOnly />
      </PermissionsProvider>
    );
    expect(screen.getByRole('heading', { name: 'Checkout services, hourly' })).toBeInTheDocument();
    expect(screen.getByText(/Owner priya · last edited by sam/)).toBeInTheDocument();
    expect(screen.getByText(LOCK_REASONS.schedule)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('gives an Editor Edit and Pause, with no lock note', () => {
    render(
      <PermissionsProvider role="Editor">
        <PluginScheduleCard policy={SCHEDULE} connections={[]} />
      </PermissionsProvider>
    );
    expect(screen.getByRole('button', { name: 'Edit' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Pause' })).toBeEnabled();
    expect(screen.queryByText(LOCK_REASONS.schedule)).not.toBeInTheDocument();
  });
});
