import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { autonomousConfigureBlocker, autonomousSaveAction, ScopeChoice } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));

const READY = { selectedCategories: ['performance'], allServices: true, selectedServices: [], allNamespaces: true, selectedNamespaces: [] };

describe('autonomousConfigureBlocker', () => {
  it('lets a form with a category and all services and namespaces through', () => {
    expect(autonomousConfigureBlocker(READY)).toBe('');
  });

  it('asks for a category first', () => {
    expect(autonomousConfigureBlocker({ ...READY, selectedCategories: [] })).toBe('Pick at least one category to watch.');
  });

  it('asks for a picked service or namespace when "pick" has none', () => {
    expect(autonomousConfigureBlocker({ ...READY, allServices: false })).toBe('Pick at least one service, or choose All discovered.');
    expect(autonomousConfigureBlocker({ ...READY, allServices: false, selectedServices: ['checkout'] })).toBe('');
    expect(autonomousConfigureBlocker({ ...READY, allNamespaces: false })).toBe('Pick at least one namespace, or choose All namespaces.');
  });
});

describe('autonomousSaveAction', () => {
  it('offers no save for a new run-once setup: running once happens from the preview', () => {
    expect(autonomousSaveAction({ scheduleMode: 'run_once', scheduleMinutes: 30, editingPolicyName: null })).toBeNull();
  });

  it('saves a new setup as a schedule', () => {
    expect(autonomousSaveAction({ scheduleMode: 'scheduled', scheduleMinutes: 60, editingPolicyName: null })).toEqual({
      label: 'Save & schedule',
      hint: 'Preview first, or save now and it runs every 1h without you.',
    });
  });

  it('names the schedule being edited, and can drop its schedule', () => {
    expect(autonomousSaveAction({ scheduleMode: 'scheduled', scheduleMinutes: 30, editingPolicyName: 'Production coverage' })).toEqual({
      label: 'Save schedule',
      hint: 'Saving updates Production coverage; it runs every 30m.',
    });
    expect(autonomousSaveAction({ scheduleMode: 'run_once', scheduleMinutes: 30, editingPolicyName: 'Production coverage' })?.label).toBe('Save without schedule');
  });
});

function Harness({ initialAll = true, initialSelected = [] as string[], options = ['checkout', 'payments', 'cart'] }) {
  const [all, setAll] = useState(initialAll);
  const [selected, setSelected] = useState(initialSelected);
  return (
    <>
      <ScopeChoice
        title="Services"
        allLabel={`All discovered (${options.length})`}
        pickLabel="Pick services"
        all={all}
        setAll={setAll}
        options={options}
        selected={selected}
        setSelected={setSelected}
        emptyHint="No services found yet."
      />
      <output data-testid="state">{JSON.stringify({ all, selected })}</output>
    </>
  );
}

const state = () => JSON.parse(screen.getByTestId('state').textContent ?? '{}');

describe('ScopeChoice', () => {
  it('starts on All and shows no chip box until Pick is chosen', () => {
    render(<Harness />);

    expect(screen.getByRole('radio', { name: 'All discovered (3)' })).toBeChecked();
    expect(screen.queryByLabelText('Add services')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Pick services' }));
    expect(state().all).toBe(false);
    expect(screen.getByLabelText('Add services')).toBeInTheDocument();
  });

  it('adds a suggested value straight away and a typed one on Enter, once each', () => {
    render(<Harness initialAll={false} />);
    const input = screen.getByLabelText('Add services');

    fireEvent.change(input, { target: { value: 'payments' } });
    expect(state().selected).toEqual(['payments']);
    fireEvent.change(input, { target: { value: 'orders-api' } });
    expect(state().selected).toEqual(['payments']);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(state().selected).toEqual(['payments', 'orders-api']);
    fireEvent.change(input, { target: { value: 'orders-api' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(state().selected).toEqual(['payments', 'orders-api']);
  });

  it('removes a chip', () => {
    render(<Harness initialAll={false} initialSelected={['checkout', 'payments']} />);

    fireEvent.click(screen.getByRole('button', { name: 'Remove checkout' }));
    expect(state().selected).toEqual(['payments']);
  });

  it('says when nothing was found to pick from', () => {
    render(<Harness options={[]} />);

    expect(screen.getByText('No services found yet.')).toBeInTheDocument();
  });
});
