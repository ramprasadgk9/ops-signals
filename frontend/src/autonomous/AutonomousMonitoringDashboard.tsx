import './AutonomousMonitoringDashboard.css';
import React from 'react';
import type { AutonomousDashboardData } from './dashboardModel';
import type { AutonomousQuestionAnswer, FindingsWindow } from '../api/queries';
import type { Finding } from '../types';

export type AutonomousDashboardContext = {
  environment?: string | null;
  datasource?: string | null;
  policy?: string | null;
  timeWindow?: string | null;
  sourceLabel?: string | null;
};

type Props = {
  data: AutonomousDashboardData;
  context: AutonomousDashboardContext;
  state?: 'idle' | 'loading' | 'error' | 'ready';
  error?: string | null;
  onRetry?: () => void;
  isLoading?: boolean;
  askOps?: {
    question: string;
    answer: AutonomousQuestionAnswer | null;
    isLoading: boolean;
    error?: string | null;
    onQuestionChange: (question: string) => void;
    onAsk: (question?: string) => void;
  };
  findingsLookup?: {
    window: FindingsWindow;
    query: string;
    service: string;
    metricName: string;
    findings: Finding[];
    isLoading: boolean;
    error?: string | null;
    onWindowChange: (window: FindingsWindow) => void;
    onQueryChange: (query: string) => void;
    onServiceChange: (service: string) => void;
    onMetricNameChange: (metricName: string) => void;
    onSearch: () => void;
    onAskAboutFinding: (finding: Finding) => void;
  };
};

function fmt(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : 'Not available';
}

function fmtScore(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : 'n/a';
}

function fmtDate(value?: string | null) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'n/a';
  return date.toLocaleString(undefined, { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function cls(value?: string | null) {
  return (value || '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
}

function Stat({ value, label, detail, tone }: { value: number | null | string; label: string; detail: string; tone?: string }) {
  return (
    <div className="auto-stat">
      <div className="auto-stat-value" style={tone ? { color: tone } : undefined}>{typeof value === 'number' ? value.toLocaleString() : value}</div>
      <div className="auto-stat-label">{label}</div>
      <div className="auto-stat-detail">{detail}</div>
    </div>
  );
}

function Panel({ title, span, children }: { title: string; span: 4 | 5 | 6 | 7 | 12; children: React.ReactNode }) {
  return (
    <section className={`auto-panel auto-span-${span}`}>
      <h3 className="auto-panel-title">{title}</h3>
      {children}
    </section>
  );
}

const suggestedQuestions = [
  'Summarize this autonomous run',
  'What changed in this run?',
  'What should I investigate first?',
  'Which metrics were skipped?',
  'Which findings are new in the last 24h?',
];

function evidenceCount(answer: AutonomousQuestionAnswer | null, key: string) {
  const value = answer?.evidence?.[key];
  return Array.isArray(value) ? value.length : 0;
}

function AskOpsPanel({ askOps }: { askOps: NonNullable<Props['askOps']> }) {
  return (
    <div className="auto-ask">
      <p className="auto-helper">Ask about the current autonomous run. Answers are grounded in stored runs, jobs, findings, and cases.</p>
      <div className="auto-prompt-grid">
        {suggestedQuestions.map((question) => (
          <button type="button" className="auto-prompt" key={question} onClick={() => askOps.onAsk(question)} disabled={askOps.isLoading}>
            {question}
          </button>
        ))}
      </div>
      <div className="auto-input-row">
        <input
          className="auto-input"
          value={askOps.question}
          onChange={(event) => askOps.onQuestionChange(event.target.value)}
          placeholder="Ask: what changed in checkout in the last 24h?"
        />
        <button type="button" className="auto-primary-button" onClick={() => askOps.onAsk()} disabled={askOps.isLoading || !askOps.question.trim()}>
          {askOps.isLoading ? 'Asking...' : 'Ask'}
        </button>
      </div>
      {askOps.error ? <div className="auto-inline-error">{askOps.error}</div> : null}
      {askOps.answer ? (
        <div className="auto-answer">
          <div className="auto-answer-head">
            <div>
              <div className="auto-row-title">{askOps.answer.headline}</div>
              <div className="auto-row-meta">
                Priority {askOps.answer.priority} · confidence {(askOps.answer.confidence * 100).toFixed(0)}%
                {' · '}
                {askOps.answer.ai_synthesis_used ? 'AI-generated' : 'Evidence summary (no AI)'}
              </div>
            </div>
            <div className="auto-evidence-chips" aria-label="Answer evidence">
              <span>{evidenceCount(askOps.answer, 'finding_ids')} findings</span>
              <span>{evidenceCount(askOps.answer, 'job_ids')} jobs</span>
              <span>{evidenceCount(askOps.answer, 'case_ids')} cases</span>
            </div>
          </div>
          <p>{askOps.answer.answer}</p>
          <ul className="auto-answer-list">
            {askOps.answer.key_points.map((point) => <li key={point}>{point}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function FindingsLookupPanel({ findingsLookup }: { findingsLookup: NonNullable<Props['findingsLookup']> }) {
  return (
    <div className="auto-lookup">
      <p className="auto-helper">Search stored findings by time, service, metric, or text. Useful for demoing what landed in Postgres.</p>
      <div className="auto-form-grid">
        <label>
          Window
          <select className="auto-input" value={findingsLookup.window} onChange={(event) => findingsLookup.onWindowChange(event.target.value as FindingsWindow)}>
            <option value="1h">Last 1 hour</option>
            <option value="6h">Last 6 hours</option>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
          </select>
        </label>
        <label>
          Search text
          <input className="auto-input" value={findingsLookup.query} onChange={(event) => findingsLookup.onQueryChange(event.target.value)} placeholder="baseline, spike, checkout" />
        </label>
        <label>
          Service
          <input className="auto-input" value={findingsLookup.service} onChange={(event) => findingsLookup.onServiceChange(event.target.value)} placeholder="optional" />
        </label>
        <label>
          Metric
          <input className="auto-input" value={findingsLookup.metricName} onChange={(event) => findingsLookup.onMetricNameChange(event.target.value)} placeholder="optional" />
        </label>
      </div>
      <button type="button" className="auto-primary-button" onClick={findingsLookup.onSearch} disabled={findingsLookup.isLoading}>
        {findingsLookup.isLoading ? 'Searching...' : 'Find recent findings'}
      </button>
      {findingsLookup.error ? <div className="auto-inline-error">{findingsLookup.error}</div> : null}
      <div className="auto-list auto-lookup-results">
        {findingsLookup.findings.length ? findingsLookup.findings.map((finding) => (
          <div className="auto-list-row" key={finding.id}>
            <div>
              <div className="auto-row-title">{finding.service} / {finding.metric_name}</div>
              <div className="auto-row-meta">{finding.title}</div>
              <div className="auto-row-meta">Importance {fmtScore(finding.importance_score)} · {finding.category} · {fmtDate(finding.created_at)}</div>
            </div>
            <button type="button" className="auto-action" onClick={() => findingsLookup.onAskAboutFinding(finding)}>Ask</button>
          </div>
        )) : <div className="auto-empty">No findings matched the selected filters.</div>}
      </div>
    </div>
  );
}

export function AutonomousMonitoringDashboard({ data, context, state, isLoading = false, error, onRetry, askOps, findingsLookup }: Props) {
  const totalDistribution = data.behaviorDistribution.reduce((sum, item) => sum + item.count, 0);
  const displayState = state ?? (isLoading ? 'loading' : 'ready');

  const header = (
    <div className="auto-header">
      <div>
        <div className="auto-kicker">Overview › Autonomous Monitoring</div>
        <h2 className="auto-title">Autonomous Monitoring Overview</h2>
        <p className="auto-subtitle">Across autonomous analysis runs, see what changed, what matters, and what to investigate first.</p>
      </div>
      <div className="auto-context" aria-label="Autonomous monitoring context">
        <span className="auto-chip">Source: {context.sourceLabel || context.datasource || 'Prometheus'}</span>
        <span className="auto-chip">Policy: {context.policy || 'Current monitoring policy'}</span>
        <span className="auto-chip">Time window: {context.timeWindow || 'Last 24 hours'}</span>
        {context.environment ? <span className="auto-chip">Environment: {context.environment}</span> : null}
      </div>
    </div>
  );

  if (displayState === 'idle') {
    return (
      <div className="autonomous-dashboard">
        {header}
        <section className="auto-state-panel">
          <h3 className="auto-state-title">No autonomous analysis has been completed yet.</h3>
          <p className="auto-state-copy">Run an autonomous analysis to discover:</p>
          <div className="auto-state-list">
            <span>Metrics selected</span>
            <span>Findings</span>
            <span>Behavior distribution</span>
            <span>Execution history</span>
            <span>Cases</span>
          </div>
          <p className="auto-state-copy">The dashboard will be populated after the first completed run.</p>
        </section>
      </div>
    );
  }

  if (displayState === 'loading') {
    return (
      <div className="autonomous-dashboard">
        {header}
        <section className="auto-state-panel" aria-live="polite">
          <h3 className="auto-state-title">Running Autonomous Analysis...</h3>
          <div className="auto-progress-list">
            <span>Discovering metrics</span>
            <span>Building metric plan</span>
            <span>Executing analysis jobs</span>
            <span>Aggregating findings</span>
            <span>Loading dashboard...</span>
          </div>
        </section>
      </div>
    );
  }

  if (displayState === 'error') {
    return (
      <div className="autonomous-dashboard">
        {header}
        <section className="auto-state-panel" role="alert">
          <h3 className="auto-state-title">Autonomous summary unavailable.</h3>
          <p className="auto-state-copy">{error && error !== 'Autonomous summary unavailable.' ? error : 'Refresh the backend connection and try again.'}</p>
          {onRetry ? (
            <button type="button" className="auto-state-action" onClick={onRetry}>
              Retry
            </button>
          ) : null}
        </section>
      </div>
    );
  }

  return (
    <div className="autonomous-dashboard">
      {header}

      {error ? <div className="auto-empty" role="alert">Some autonomous summary data could not be refreshed.</div> : null}

      <div className="auto-grid">
        <Panel title="Discovery & Selection" span={7}>
          <div className="auto-stat-grid">
            <Stat value={fmt(data.summary.metricsDiscovered)} label="Metrics discovered" detail="From autonomous policy data" tone="var(--auto-green)" />
            <Stat value={fmt(data.summary.candidatesSelected)} label="Metrics selected" detail="By monitoring policy" tone="var(--auto-green)" />
            <Stat value={data.summary.findingsGenerated} label="Findings" detail="Generated" tone="var(--auto-orange)" />
            <Stat value={data.summary.casesOpen} label="Cases" detail="Created / open" tone="var(--auto-purple)" />
          </div>
        </Panel>

        <Panel title="Execution Summary" span={5}>
          <div className="auto-stat-grid compact">
            <Stat value={fmt(data.summary.executed)} label="Executed" detail="Metrics" tone="var(--auto-blue)" />
            <Stat value={fmt(data.summary.skipped)} label="Skipped" detail="By policy / filters" tone="var(--auto-orange)" />
            <Stat value={fmt(data.summary.failed)} label="Failed" detail="Errors" tone="var(--auto-red)" />
          </div>
        </Panel>

        <Panel title="Top Findings by Importance" span={7}>
          {data.topFindings.length ? (
            <table className="auto-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Severity</th>
                  <th>Service</th>
                  <th>Metric</th>
                  <th>Behavior</th>
                  <th>Importance</th>
                  <th>First observed</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {data.topFindings.map((finding) => (
                  <tr key={`${finding.rank}-${finding.service}-${finding.metric}`}>
                    <td>{finding.rank}</td>
                    <td><span className={`auto-pill ${cls(finding.severity)}`}>{finding.severity}</span></td>
                    <td>{finding.service}</td>
                    <td><a className="auto-link" href={finding.href}>{finding.metric}</a></td>
                    <td>{finding.behavior}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span>{fmtScore(finding.importance)}</span>
                        <span className="auto-bar"><span className="auto-bar-fill" style={{ width: `${Math.max(0, Math.min(1, finding.importance)) * 100}%` }} /></span>
                      </div>
                    </td>
                    <td>{fmtDate(finding.firstObserved)}</td>
                    <td><a className="auto-action" href={finding.href}>Open</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="auto-empty">No findings returned for the selected window.</div>}
        </Panel>

        <Panel title="Behavior Distribution" span={5}>
          {data.behaviorDistribution.length ? (
            <div className="auto-distribution">
              <div className="auto-donut" data-total={`${totalDistribution}\n`} aria-label={`${totalDistribution} total findings`} />
              <div className="auto-list">
                {data.behaviorDistribution.map((item) => (
                  <div className="auto-list-row" key={item.label}>
                    <div className="auto-row-title">{item.label}</div>
                    <div>{item.count}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : <div className="auto-empty">No finding categories available.</div>}
        </Panel>

        <Panel title={data.selection.title} span={4}>
          <div className="auto-selection">
            <div className="auto-funnel">
              <div className="auto-funnel-step">{fmt(data.selection.discovered)} discovered</div>
              <div className="auto-funnel-step">{fmt(data.selection.selected)} selected</div>
              <div className="auto-funnel-step">{fmt(data.selection.excluded)} excluded</div>
            </div>
            <div>
              <div className="auto-row-title">{data.selection.selectedLabel}</div>
              <div className="auto-row-meta">Statistical candidate screening is not enabled yet.</div>
              <div className="auto-stat" style={{ marginTop: 12 }}>
                <div className="auto-stat-value" style={{ color: 'var(--auto-green)' }}>
                  {data.selection.reductionPercent === null ? 'Not available' : `${data.selection.reductionPercent.toFixed(1)}%`}
                </div>
                <div className="auto-stat-label">Reduction</div>
                <div className="auto-stat-detail">Compared to discovered metrics</div>
              </div>
            </div>
          </div>
          <div className="auto-empty" style={{ marginTop: 12 }}>Selection reasons: Screening not enabled</div>
        </Panel>

        <Panel title="Execution History" span={4}>
          {data.executionRows.length ? (
            <div className="auto-list">
              {data.executionRows.map((row) => (
                <div className="auto-list-row" key={row.id}>
                  <div>
                    <div className="auto-row-title">{row.scope}</div>
                    <div className="auto-row-meta">{row.metrics}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span className={`auto-pill ${cls(row.status)}`}>{row.status}</span>
                    <div className="auto-row-meta">{fmtDate(row.completed)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="auto-empty">No autonomous executions returned yet.</div>}
        </Panel>

        <Panel title="Recent Cases" span={4}>
          {data.recentCases.length ? (
            <div className="auto-list">
              {data.recentCases.map((caseItem) => (
                <a className="auto-list-row auto-link" href={caseItem.href} key={caseItem.id}>
                  <div>
                    <div className="auto-row-title">{caseItem.title}</div>
                    <div className="auto-row-meta">{caseItem.status} · {caseItem.meta}</div>
                  </div>
                  <div className="auto-row-meta">{fmtDate(caseItem.updatedAt)}</div>
                </a>
              ))}
            </div>
          ) : <div className="auto-empty">No cases returned yet.</div>}
        </Panel>

        {askOps ? (
          <Panel title="Ask Ops Signals" span={6}>
            <AskOpsPanel askOps={askOps} />
          </Panel>
        ) : null}

        {findingsLookup ? (
          <Panel title="Find Recent Findings" span={6}>
            <FindingsLookupPanel findingsLookup={findingsLookup} />
          </Panel>
        ) : null}
      </div>
    </div>
  );
}
