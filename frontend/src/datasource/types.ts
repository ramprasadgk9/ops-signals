import type { DataQuery, DataSourceJsonData } from '@grafana/data';

export type OpsSignalsDataSourceOptions = DataSourceJsonData & {
  url: string;
  defaultService?: string;
};

export type OpsSignalsQuery = DataQuery & {
  service: string;
  metric: string;
  from: string;
  to: string;
};
