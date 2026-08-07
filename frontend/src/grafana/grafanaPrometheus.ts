import { LoadingState, dateTime } from '@grafana/data';
import { getDataSourceSrv } from '@grafana/runtime';
import type { GrafanaTimeRange } from './grafanaTimeRange';

export type PrometheusDatasourceRef = {
  uid: string;
  name: string;
  type: string;
};

type QueryResult = {
  data?: unknown[];
  state?: LoadingState;
  error?: unknown;
};

function datasourceSrv() {
  return getDataSourceSrv() as unknown as {
    getList?: (filters?: Record<string, unknown>) => Array<{ uid?: string; name?: string; type?: string }>;
    get: (uid: string) => Promise<any>;
  };
}

export function listPrometheusDatasources(): PrometheusDatasourceRef[] {
  const list = datasourceSrv().getList?.({ type: 'prometheus' }) ?? [];
  return list
    .filter((item) => item.type === 'prometheus' && item.uid && item.name)
    .map((item) => ({ uid: String(item.uid), name: String(item.name), type: String(item.type) }));
}

async function metricFindQuery(datasourceUid: string, query: string) {
  const datasource = await datasourceSrv().get(datasourceUid);
  if (typeof datasource.metricFindQuery !== 'function') return [];
  const response = await datasource.metricFindQuery(query);
  return Array.isArray(response) ? response.map((item) => String(item.text ?? item.value ?? item)).filter(Boolean) : [];
}

export async function discoverServiceValues(datasourceUid: string, serviceLabel: string) {
  return metricFindQuery(datasourceUid, `label_values({__name__=~".+"}, ${serviceLabel})`);
}

export async function discoverLabelValues(datasourceUid: string, labelName: string) {
  return metricFindQuery(datasourceUid, `label_values({__name__=~".+"}, ${labelName})`);
}

export async function discoverMetricNames(datasourceUid: string) {
  return metricFindQuery(datasourceUid, 'label_values(__name__)');
}

export async function queryPrometheusDatasource({
  datasourceUid,
  promql,
  range,
  intervalMs,
}: {
  datasourceUid: string;
  promql: string;
  range: GrafanaTimeRange;
  intervalMs: number;
}): Promise<unknown[]> {
  const datasource = await datasourceSrv().get(datasourceUid);
  const from = dateTime(range.from);
  const to = dateTime(range.to);
  const request = {
    requestId: `ops-signals-${Date.now()}`,
    interval: `${Math.max(Math.round(intervalMs / 1000), 1)}s`,
    intervalMs,
    maxDataPoints: 1000,
    range: {
      from,
      to,
      raw: {
        from: from.toISOString(),
        to: to.toISOString(),
      },
    },
    scopedVars: {},
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    targets: [
      {
        refId: 'A',
        expr: promql,
        format: 'time_series',
        datasource: { uid: datasourceUid, type: 'prometheus' },
      },
    ],
  };

  return new Promise((resolve, reject) => {
    const subscription = datasource.query(request).subscribe({
      next: (result: QueryResult) => {
        if (result.error) {
          reject(result.error);
          subscription.unsubscribe();
          return;
        }
        if (result.state === LoadingState.Done || result.data) {
          resolve(result.data ?? []);
          subscription.unsubscribe();
        }
      },
      error: reject,
      complete: () => resolve([]),
    });
  });
}
