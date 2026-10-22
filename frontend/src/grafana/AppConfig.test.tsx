import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@grafana/runtime', () => ({ getBackendSrv: vi.fn() }));
vi.mock('./backendClient', () => ({
  getApiToken: () => '',
  setApiToken: vi.fn(),
  getSetupCheck: vi.fn().mockResolvedValue({ generated_at: '2026-10-19T00:00:00Z', version: 'test', checks: [] }),
  sendTestAlert: vi.fn(),
  testPrometheusConnection: vi.fn(),
}));
import { AppConfig } from './AppConfig';
import { getSetupCheck } from './backendClient';

const meta = (overrides = {}) => ({ id: 'ops-signals-app', enabled: true, pinned: true, jsonData: {}, ...overrides });
const PROXY = '/api/plugin-proxy/breezypoppy3596-opssignals-app/backend';

describe('AppConfig', () => {
  it('starts a new install on "Through Grafana" and saves the URL Grafana calls with the token encrypted', async () => {
    const save = vi.fn().mockResolvedValue({});
    const reload = vi.fn();
    render(<AppConfig plugin={{ meta: meta({ jsonData: { other: 'kept' } }) }} save={save} reload={reload} />);

    expect(screen.getByRole('radio', { name: /^Grafana/ })).toBeChecked();
    expect(screen.getByText('Backend URL, as this Grafana server reaches it')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Backend URL'), { target: { value: 'http://host.docker.internal:8002/' } });
    fireEvent.change(screen.getByLabelText('API token'), { target: { value: ' s3cret ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(save).toHaveBeenCalledWith('ops-signals-app', {
      enabled: true,
      pinned: true,
      jsonData: { other: 'kept', backendUrl: 'http://host.docker.internal:8002', connectMode: 'grafana', webUiUrl: '' },
      secureJsonData: { apiToken: 's3cret' },
    });
  });

  it('keeps an install saved before the choice existed on "Browser, directly"', async () => {
    const save = vi.fn().mockResolvedValue({});
    render(<AppConfig plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000' } }) }} save={save} reload={vi.fn()} />);

    expect(screen.getByRole('radio', { name: /^Browser, directly/ })).toBeChecked();
    expect(screen.getByLabelText('Backend URL')).toHaveValue('http://backend:8000');
    expect(screen.getByText(/so the browser may call it/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    // No token typed: nothing encrypted is sent, so Grafana keeps what it has.
    expect(save.mock.calls[0][1]).toEqual({ enabled: true, pinned: true, jsonData: { backendUrl: 'http://backend:8000', connectMode: 'direct', webUiUrl: '' } });
  });

  it('clears a saved backend URL with an empty value, not a missing key', async () => {
    const save = vi.fn().mockResolvedValue({});
    render(<AppConfig plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000', connectMode: 'direct' } }) }} save={save} reload={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Backend URL'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].jsonData).toEqual({ backendUrl: '', connectMode: 'direct', webUiUrl: '' });
  });

  it('shows a saved token only as Configured, and Reset removes it', async () => {
    const save = vi.fn().mockResolvedValue({});
    render(
      <AppConfig
        plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000', connectMode: 'grafana' }, secureJsonFields: { apiToken: true } }) }}
        save={save}
        reload={vi.fn()}
      />
    );

    expect(screen.getByLabelText('API token')).toHaveTextContent('● Configured');
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.getByLabelText('API token')).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].secureJsonData).toEqual({ apiToken: '' });
  });

  it('runs the Setup check through Grafana once that is saved', async () => {
    render(<AppConfig plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000', connectMode: 'grafana' } }) }} save={vi.fn()} />);

    await waitFor(() => expect(getSetupCheck).toHaveBeenCalledWith(PROXY));
    expect(await screen.findByText('backend:8000')).toBeInTheDocument();
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
    render(<AppConfig plugin={{ meta: meta({ enabled: false, pinned: false, jsonData: { connectMode: 'direct' } }) }} save={save} reload={reload} />);

    fireEvent.click(screen.getByRole('button', { name: 'Enable and save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied');
    expect(save).toHaveBeenCalledWith('ops-signals-app', { enabled: true, pinned: true, jsonData: { connectMode: 'direct', backendUrl: '', webUiUrl: '' } });
    expect(reload).not.toHaveBeenCalled();
  });

  it('saves the web UI address, and refuses one that is not a URL', async () => {
    const save = vi.fn().mockResolvedValue({});
    render(<AppConfig plugin={{ meta: meta({ jsonData: { backendUrl: 'http://backend:8000', connectMode: 'grafana' } }) }} save={save} reload={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Web UI address'), { target: { value: 'ops signals' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Enter the web UI address as an http:// or https:// URL.');
    expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Web UI address'), { target: { value: 'http://localhost:5174/' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].jsonData).toEqual({ backendUrl: 'http://backend:8000', connectMode: 'grafana', webUiUrl: 'http://localhost:5174' });
  });
});
