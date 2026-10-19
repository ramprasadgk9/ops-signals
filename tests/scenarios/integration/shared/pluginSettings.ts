import type { APIRequestContext } from '@playwright/test';
import { expect } from '@playwright/test';
import { env } from './env';

const PLUGIN_ID = 'breezypoppy3596-opssignals-app';

/** The local stack's provisioned setting (grafana/provisioning/plugins): through Grafana. */
export const THROUGH_GRAFANA = { backendUrl: 'http://host.docker.internal:8002', connectMode: 'grafana' };
/** The browser calls the backend itself, picking it from the local addresses. */
export const DIRECT = { backendUrl: '', connectMode: 'direct' };

/** Saves the plugin's connection settings as a Grafana admin. They last until Grafana restarts and
 * provisioning applies THROUGH_GRAFANA again, so a test that changes them puts them back. */
export async function setPluginConnection(request: APIRequestContext, jsonData: Record<string, string>): Promise<void> {
  const response = await request.post(`${env.grafanaBaseUrl}/api/plugins/${PLUGIN_ID}/settings`, {
    headers: { Authorization: `Basic ${Buffer.from(`${env.grafanaUser}:${env.grafanaPassword}`).toString('base64')}` },
    data: { enabled: true, pinned: true, jsonData },
  });
  expect(response.ok(), `saving plugin settings failed: ${response.status()}`).toBe(true);
}
