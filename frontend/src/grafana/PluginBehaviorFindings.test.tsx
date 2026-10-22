import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createCaseFromBehavior } from './backendClient';
import { PluginBehaviorFindings, type PluginBehaviorFindingRow } from './PluginBehaviorFindings';
import { WebUiContext } from './webUiLink';

vi.mock('./backendClient', () => ({ createCaseFromBehavior: vi.fn() }));
const createCase = vi.mocked(createCaseFromBehavior);

function row(overrides: Partial<PluginBehaviorFindingRow> = {}): PluginBehaviorFindingRow {
  return { id: 5, title: 'Memory leak driving restarts', summary: 'Heap grew until the pod restarted.', severity: 'critical', confidence: 0.82, service: 'checkout', case_id: null, ...overrides };
}

describe('PluginBehaviorFindings', () => {
  beforeEach(() => {
    createCase.mockReset();
  });

  it('creates a case from a behavior finding and opens it', async () => {
    createCase.mockResolvedValue({ case_id: 31, behavior_finding_id: 5, case_status: 'open', memory_status: 'not_indexed' });
    const onOpenCase = vi.fn();
    render(<PluginBehaviorFindings backendUrl="http://backend" findings={[row()]} onOpenCase={onOpenCase} />);

    expect(screen.getByTestId('plugin-behavior-finding')).toHaveTextContent('checkout · Confidence 82%');
    fireEvent.click(screen.getByRole('button', { name: 'Create Case' }));

    expect(await screen.findByRole('button', { name: 'Open Case' })).toBeInTheDocument();
    expect(createCase).toHaveBeenCalledWith('http://backend', 5);
    expect(onOpenCase).toHaveBeenCalledWith(31);
    expect(screen.getByTestId('plugin-behavior-finding')).toHaveTextContent('Case #31');
  });

  it('opens the existing case instead of creating another', () => {
    const onOpenCase = vi.fn();
    render(<PluginBehaviorFindings backendUrl="http://backend" findings={[row({ case_id: 12 })]} onOpenCase={onOpenCase} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open Case' }));

    expect(onOpenCase).toHaveBeenCalledWith(12);
    expect(createCase).not.toHaveBeenCalled();
  });

  it('says when the case could not be created', async () => {
    createCase.mockRejectedValue(new Error('down'));
    render(<PluginBehaviorFindings backendUrl="http://backend" findings={[row()]} onOpenCase={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Create Case' }));

    expect(await screen.findByText(/Could not create a case for "Memory leak driving restarts"/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create Case' })).toBeEnabled();
  });

  it('renders nothing without behavior findings', () => {
    const { container } = render(<PluginBehaviorFindings backendUrl="http://backend" findings={[]} onOpenCase={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows what the match saw: each metric with its change, the timing and the rule', () => {
    render(
      <PluginBehaviorFindings
        backendUrl="http://backend"
        onOpenCase={vi.fn()}
        findings={[row({
          title: 'Consumer falling behind', definition_id: 'consumer_falling_behind', definition_version: 1,
          input_metrics_json: { lag: 'kafka_consumergroup_lag', produced: 'kafka_topic_messages_in_rate' },
          facts_json: {
            lag: { trend: { present: true, direction: 'upward', change_percent: 235.4 } },
            produced: { trend: { present: true, direction: 'upward', change_percent: 91.8 } },
          },
          matched_conditions_json: [{ passed: true }, { passed: true }],
          correlation_json: { matched: true, overlap_minutes: 235 },
          occurrence_count: 1,
        })]}
      />
    );
    const card = screen.getByTestId('plugin-behavior-finding');
    expect(card).toHaveTextContent('2 metrics combined');
    expect(screen.getAllByTestId('plugin-behavior-metric').map((metric) => metric.textContent)).toEqual([
      '● kafka_consumergroup_lagSlowly rising +235%',
      '● kafka_topic_messages_in_rateSlowly rising +92%',
    ]);
    expect(card).toHaveTextContent('Both at the same time · 235 min');
    expect(card).toHaveTextContent('2 of 2 conditions passed');
    expect(card).toHaveTextContent('Seen once');
    expect(card).toHaveTextContent('checkout · Confidence 82% · rule consumer_falling_behind v1');
    // No web UI address set: no links to it.
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('links to the web UI when its address is set', () => {
    const lastSeen = new Date(Date.now() - 2 * 3600_000).toISOString();
    render(
      <WebUiContext.Provider value="http://ops.example">
        <PluginBehaviorFindings backendUrl="http://backend" findings={[row({ last_seen_at: lastSeen })]} onOpenCase={vi.fn()} />
      </WebUiContext.Provider>
    );
    expect(screen.getByRole('link', { name: 'Manage patterns in Ops Signals ↗' })).toHaveAttribute('href', 'http://ops.example/behavior-intelligence?tab=patterns');
    expect(screen.getByRole('link', { name: 'Open in Ops Signals ↗' })).toHaveAttribute('href', 'http://ops.example/findings?window=6h&pattern=5');
  });
});
