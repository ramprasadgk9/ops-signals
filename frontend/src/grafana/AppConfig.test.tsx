import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@grafana/runtime', () => ({ getBackendSrv: vi.fn() }));
import { AppConfig } from './AppConfig';

const meta = (overrides = {}) => ({ id: 'ops-signals-app', enabled: true, pinned: true, jsonData: {}, ...overrides });

describe('AppConfig', () => {
  it('saves the backend URL into the app settings and reloads', async () => {
    const save = vi.fn().mockResolvedValue({});
    const reload = vi.fn();
    render(<AppConfig plugin={{ meta: meta({ jsonData: { other: 'kept' } }) }} save={save} reload={reload} />);

    fireEvent.change(screen.getByLabelText('Backend URL'), { target: { value: 'https://ops-signals.example.internal/' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(save).toHaveBeenCalledWith('ops-signals-app', {
      enabled: true,
      pinned: true,
      jsonData: { other: 'kept', backendUrl: 'https://ops-signals.example.internal' },
    });
  });

  it('clears a saved backend URL with an empty value, not a missing key', async () => {
    const save = vi.fn().mockResolvedValue({});
    render(<AppConfig plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000' } }) }} save={save} reload={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Backend URL'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(JSON.parse(JSON.stringify(save.mock.calls[0][1])).jsonData).toEqual({ backendUrl: '' });
  });

  it('shows the saved backend URL', () => {
    render(<AppConfig plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000' } }) }} save={vi.fn()} />);
    expect(screen.getByLabelText('Backend URL')).toHaveValue('http://backend:8000');
  });

  it('blocks saving a value that is not an http(s) URL', () => {
    const save = vi.fn();
    render(<AppConfig plugin={{ meta: meta() }} save={save} />);

    fireEvent.change(screen.getByLabelText('Backend URL'), { target: { value: 'ops-signals:8000' } });

    expect(screen.getByRole('alert')).toHaveTextContent('Enter an http:// or https:// URL.');
    expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled();
  });

  it('enables a disabled plugin on save and reports a failed save', async () => {
    const save = vi.fn().mockRejectedValue(new Error('Permission denied'));
    const reload = vi.fn();
    render(<AppConfig plugin={{ meta: meta({ enabled: false, pinned: false }) }} save={save} reload={reload} />);

    fireEvent.click(screen.getByRole('button', { name: 'Enable and save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied');
    expect(save).toHaveBeenCalledWith('ops-signals-app', { enabled: true, pinned: true, jsonData: { backendUrl: '' } });
    expect(reload).not.toHaveBeenCalled();
  });
});
