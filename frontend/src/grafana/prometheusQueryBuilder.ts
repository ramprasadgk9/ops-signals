export type MetricMode = 'metric' | 'promql';

export type PrometheusQueryTarget = {
  metric: string;
  mode: MetricMode;
  service: string;
  serviceLabel: string;
};

const labelNamePattern = /^[a-zA-Z_][a-zA-Z0-9_]*$/;

export function escapePrometheusLabelValue(value: string) {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
}

export function buildServiceMatcher(serviceLabel: string, service: string) {
  if (!labelNamePattern.test(serviceLabel)) {
    throw new Error(`Invalid service label: ${serviceLabel}`);
  }
  return `${serviceLabel}="${escapePrometheusLabelValue(service)}"`;
}

export function validatePromQL(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error('Metric or PromQL expression is required.');
  }
  if (/[;\n\r]/.test(trimmed)) {
    throw new Error('PromQL must be a single expression.');
  }
  return trimmed;
}

export function buildMetricQuery(target: PrometheusQueryTarget) {
  const metricOrExpression = validatePromQL(target.metric);
  const matcher = buildServiceMatcher(target.serviceLabel || 'service', target.service);

  if (target.mode === 'promql') {
    if (metricOrExpression.includes('$service')) {
      return metricOrExpression.replace(/\$service\b/g, escapePrometheusLabelValue(target.service));
    }
    return metricOrExpression;
  }

  if (!labelNamePattern.test(metricOrExpression)) {
    throw new Error('Metric mode requires a raw Prometheus metric name. Switch to PromQL expression for complex queries.');
  }

  return `${metricOrExpression}{${matcher}}`;
}

