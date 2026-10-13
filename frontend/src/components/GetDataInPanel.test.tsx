import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { alertmanagerState, otlpState, prometheusState, SourceStatusStrip } from './GetDataInPanel';
import type { IngestionStatus } from '../types';

const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;

function status(sources: Partial<IngestionStatus['sources']> = {}): IngestionStatus {
  return {
    generated_at: new Date().toISOString(),
    has_any_data: true,
    sources: {
      otlp: { endpoint_path: '/api/otlp/v1/metrics', last_received_at: null },
      alertmanager: { endpoint_path: '/api/integrations/alertmanager', enabled: true, token_required: false, last_received_at: null, received_24h: 0 },
      prometheus: { configured: true, reachable: true },
      ...sources,
    },
  } as IngestionStatus;
}

function connection(id: string, reachable: boolean) {
  return { id, name: `Prometheus ${id}`, configured: true, url: `http://${id}:9090`, reachable };
}

describe('source states', () => {
  it('turns OTLP stale once a collector has gone quiet for minutes', () => {
    expect(otlpState(status({ otlp: { endpoint_path: '', last_received_at: ago(MINUTE) } }))).toBe('receiving');
    expect(otlpState(status({ otlp: { endpoint_path: '', last_received_at: ago(11 * HOUR) } }))).toBe('stale');
  });

  it('only turns Alertmanager stale after its default repeat interval', () => {
    const alertmanager = (last: string) => ({ endpoint_path: '', enabled: true, token_required: false, last_received_at: last, received_24h: 1 });
    expect(alertmanagerState(status({ alertmanager: alertmanager(ago(9 * MINUTE)) }))).toBe('receiving');
    expect(alertmanagerState(status({ alertmanager: alertmanager(ago(5 * HOUR)) }))).toBe('stale');
  });

  it('shows Prometheus as partial when one connection is down and another answers', () => {
    const partial = status({ prometheus: { configured: true, reachable: true, connections: [connection('local', false), connection('mimir', true)] } });
    expect(prometheusState(partial)).toBe('partial');
    expect(prometheusState(status({ prometheus: { configured: true, reachable: true, connections: [connection('mimir', true)] } }))).toBe('configured');
    expect(prometheusState(status({ prometheus: { configured: true, reachable: false, connections: [connection('local', false)] } }))).toBe('unreachable');

    render(<SourceStatusStrip status={partial} />);
    expect(screen.getByText('Prometheus · 1 of 2 unreachable')).toBeInTheDocument();
  });
});
