import { describe, expect, it } from 'vitest';
import { activeBackendUrl, backendOptionsFor, configuredBackendUrl, connectMode, defaultBackendUrl, grafanaProxyBase, isGrafanaProxyUrl, isValidBackendUrl, localBackendOptions } from './backendUrlSetting';

describe('backend URL setting', () => {
  it('falls back to the local Grafana stack backend when nothing is configured', () => {
    expect(defaultBackendUrl(undefined)).toBe('http://localhost:8002');
    expect(defaultBackendUrl({})).toBe('http://localhost:8002');
    expect(backendOptionsFor(undefined)).toEqual(localBackendOptions);
  });

  it('uses the configured backend, without a trailing slash, and lists it first', () => {
    const jsonData = { backendUrl: ' https://ops-signals.example.internal/ ' };
    expect(defaultBackendUrl(jsonData, 'http://localhost:8002')).toBe('https://ops-signals.example.internal');
    const options = backendOptionsFor(jsonData);
    expect(options[0]).toEqual({ label: 'Configured backend (https://ops-signals.example.internal)', value: 'https://ops-signals.example.internal' });
    expect(options).toHaveLength(localBackendOptions.length + 1);
  });

  it('does not list a configured local address twice', () => {
    const options = backendOptionsFor({ backendUrl: 'http://localhost:8001' });
    expect(options.filter((option) => option.value === 'http://localhost:8001')).toHaveLength(1);
    expect(options[0].label).toBe('Configured backend (http://localhost:8001)');
  });

  it('keeps a build default the picker would otherwise not show', () => {
    expect(defaultBackendUrl(undefined, 'http://backend:8000')).toBe('http://backend:8000');
    expect(backendOptionsFor(undefined, 'http://backend:8000')[0].value).toBe('http://backend:8000');
  });

  it('ignores a configured value that is not an http(s) URL', () => {
    expect(isValidBackendUrl('ops-signals:8000')).toBe(false);
    expect(isValidBackendUrl('javascript:alert(1)')).toBe(false);
    expect(configuredBackendUrl({ backendUrl: 'not a url' })).toBeUndefined();
    expect(defaultBackendUrl({ backendUrl: 'not a url' })).toBe('http://localhost:8002');
  });
});

describe('connect through Grafana', () => {
  it('uses the Grafana proxy only when chosen and a backend URL is saved', () => {
    expect(connectMode({ backendUrl: 'http://b:8000', connectMode: 'grafana' })).toBe('grafana');
    expect(connectMode({ backendUrl: '', connectMode: 'grafana' })).toBe('direct');
    expect(connectMode({ backendUrl: 'http://b:8000' })).toBe('direct');
    expect(activeBackendUrl({ backendUrl: 'http://b:8000', connectMode: 'grafana' })).toBe('/api/plugin-proxy/breezypoppy3596-opssignals-app/backend');
    expect(activeBackendUrl({ backendUrl: 'http://b:8000', connectMode: 'direct' })).toBe('http://b:8000');
  });

  it("follows Grafana's sub path", () => {
    Object.assign(window, { grafanaBootData: { settings: { appSubUrl: '/grafana/' } } });
    try {
      expect(grafanaProxyBase()).toBe('/grafana/api/plugin-proxy/breezypoppy3596-opssignals-app/backend');
      expect(isGrafanaProxyUrl(grafanaProxyBase())).toBe(true);
      expect(isGrafanaProxyUrl('http://localhost:8002')).toBe(false);
    } finally {
      delete (window as { grafanaBootData?: unknown }).grafanaBootData;
    }
  });
});
