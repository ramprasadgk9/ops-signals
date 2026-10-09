import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createCaseFromBehavior } from './backendClient';
import { PluginBehaviorFindings, type PluginBehaviorFindingRow } from './PluginBehaviorFindings';

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
});
