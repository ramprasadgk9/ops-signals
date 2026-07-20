import {
  DataSourceApi,
  FieldType,
  MutableDataFrame,
  type DataQueryRequest,
  type DataQueryResponse,
  type DataSourceInstanceSettings,
} from '@grafana/data';
import type { OpsSignalsDataSourceOptions, OpsSignalsQuery } from './types';
import { runBackendAnalysis } from '../grafana/backendClient';

export class OpsSignalsDataSourceApi extends DataSourceApi<OpsSignalsQuery, OpsSignalsDataSourceOptions> {
  private readonly settings: DataSourceInstanceSettings<OpsSignalsDataSourceOptions>;

  constructor(instanceSettings: DataSourceInstanceSettings<OpsSignalsDataSourceOptions>) {
    super(instanceSettings);
    this.settings = instanceSettings;
  }

  async query(options: DataQueryRequest<OpsSignalsQuery>): Promise<DataQueryResponse> {
    const target = options.targets[0] ?? { refId: 'A', service: '', metric: '', from: '', to: '' };
    const result = await runBackendAnalysis(this.settings.jsonData.url || 'http://localhost:8000', {
      datasource: this.settings.name || 'Prometheus',
      service: target.service,
      metric: target.metric,
      from: target.from,
      to: target.to,
    });

    const frame = new MutableDataFrame({
      name: 'ops-signals-analysis',
      fields: [
        { name: 'time', type: FieldType.time, values: [Date.now()] },
        { name: 'signals', type: FieldType.number, values: [result.signals.length] },
        { name: 'findings', type: FieldType.number, values: [result.findings.length] },
        { name: 'behaviorFindings', type: FieldType.number, values: [result.behaviorFindings.length] },
        { name: 'summary', type: FieldType.string, values: [result.summary] },
        { name: 'runId', type: FieldType.string, values: [result.runId] },
      ],
    });

    return { data: [frame] };
  }

  async testDatasource() {
    return {
      status: 'success',
      message: 'Ops Signals datasource is ready.',
      title: 'Ops Signals',
    };
  }
}
