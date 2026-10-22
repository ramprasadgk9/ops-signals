import { describe, expect, it } from 'vitest';
import { metricScore, suggestMetrics } from './metricSuggest';

const stored = [
  'kafka_consumergroup_lag',
  'kafka_consumer_fetch_rate',
  'kafka_topic_messages_in_rate',
  'cpu_usage',
  'consumer_lag_seconds',
  'http_requests_total',
];

describe('suggestMetrics', () => {
  it('ranks whole-word matches above keywords inside a word', () => {
    expect(metricScore('consumer_lag_seconds', ['consumer', 'lag'])).toBe(4);
    expect(metricScore('kafka_consumergroup_lag', ['consumer', 'lag'])).toBe(3);
  });

  it('suggests the best fits, best first, and nothing that shares no keyword', () => {
    expect(suggestMetrics(['consumer', 'lag', 'backlog'], stored)).toEqual(['consumer_lag_seconds', 'kafka_consumergroup_lag', 'kafka_consumer_fetch_rate']);
    expect(suggestMetrics(['disk', 'write'], stored)).toEqual([]);
  });

  it('matches regardless of case and separators', () => {
    expect(suggestMetrics(['messages'], ['Kafka.Topic.Messages.In'])).toEqual(['Kafka.Topic.Messages.In']);
  });
});
