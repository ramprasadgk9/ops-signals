import React, { useEffect, useState } from 'react';
import type { CoverageReport, CoverageStatus, MemoryStatsResponse, RecurringProblem, RecurringProblemsResponse } from '../types';
import { getMemoryStats, getMonitoringCoverage, getRecurringProblems } from './backendClient';
import { styles } from './plainUi';
import { caseToRecordCauseOn, recurringNextStep, type NextStepTone } from '../utils/recurringNextStep';

// Recurring problems in the Grafana plugin's own styling: problems that keep coming back, which
// imported past incidents monitoring caught, and one line on what is in memory. Same endpoints and
// wording as the web UI's RecurringProblemsPage, RecurringProblemsPanel and CoveragePanel. Case titles open the case
// through `onOpenCase`, in the investigation drawer the parent owns.

type Load<T> = { status: 'loading' } | { status: 'error' } | { status: 'ready'; data: T };

function useLoad<T>(load: () => Promise<T>, deps: React.DependencyList): Load<T> {
  const [state, setState] = useState<Load<T>>({ status: 'loading' });
  useEffect(() => {
    let active = true;
    setState({ status: 'loading' });
    load()
      .then((data) => { if (active) setState({ status: 'ready', data }); })
      .catch(() => { if (active) setState({ status: 'error' }); });
    return () => { active = false; };
  }, deps);
  return state;
}

const PANEL: React.CSSProperties = { ...styles.stack, gap: 12, border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 14 };
const BOX: React.CSSProperties = { border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12 };
const LINK_BUTTON: React.CSSProperties = { border: 0, background: 'transparent', color: '#5794f2', padding: 0, cursor: 'pointer', fontWeight: 600, textAlign: 'left' };
const PICKED: React.CSSProperties = { background: '#5794f2', color: '#fff', border: '1px solid #5794f2' };
const RESOLVED = new Set(['resolved', 'closed', 'mitigated']);

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
}

function Choices<T extends string | number>({ options, value, onChange, label }: { options: Array<{ id: T; label: string }>; value: T; onChange: (value: T) => void; label: string }) {
  return (
    <div role="group" aria-label={label} style={{ ...styles.row, gap: 6 }}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
          style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: 'pointer', ...(value === option.id ? PICKED : {}) }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Tile({ value, label, tone }: { value: number; label: string; tone?: string }) {
  return (
    <div style={{ ...BOX, minWidth: 0 }}>
      <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1, color: tone }}>{value}</div>
      <div style={{ ...styles.muted, fontSize: 12 }}>{label}</div>
    </div>
  );
}

function CaseButton({ caseId, title, onOpenCase }: { caseId: number; title: string; onOpenCase: (caseId: number) => void }) {
  return <button type="button" style={LINK_BUTTON} onClick={() => onOpenCase(caseId)}>{title}</button>;
}

export function PluginOperationalMemory({ backendUrl, onOpenCase }: { backendUrl: string; onOpenCase: (caseId: number) => void }) {
  return (
    <section data-testid="plugin-operational-memory" style={{ ...styles.stack, gap: 12 }}>
      <div>
        <strong style={{ fontSize: 16 }}>Recurring problems</strong>
        <div style={{ ...styles.helperText, marginTop: 2 }}>
          Problems that keep coming back. Fix these for good instead of firefighting them again.
        </div>
      </div>
      <MemoryStats backendUrl={backendUrl} />
      <RecurringProblems backendUrl={backendUrl} onOpenCase={onOpenCase} />
      <MonitoringCoverage backendUrl={backendUrl} onOpenCase={onOpenCase} />
    </section>
  );
}

function MemoryStats({ backendUrl }: { backendUrl: string }) {
  const state = useLoad<MemoryStatsResponse>(() => getMemoryStats(backendUrl), [backendUrl]);
  if (state.status === 'loading') return <div style={styles.muted}>Loading memory status...</div>;
  if (state.status === 'error') return <div style={styles.muted}>Memory status could not be loaded. Check the backend connection.</div>;
  const stats = state.data;
  const availability = !stats.enabled ? 'Memory is turned off on this backend.' : stats.status === 'healthy' ? null : `Memory is ${stats.status}: search and publishing may not work until it recovers.`;
  if (availability) return <div data-testid="plugin-memory-stats" style={styles.alert}>{availability}</div>;
  // One line, naming only the counts that need attention.
  const trouble = stats.stale_cases + stats.error_cases;
  const parts = [
    `${stats.indexed_cases} past ${stats.indexed_cases === 1 ? 'case' : 'cases'} published`,
    stats.not_indexed_cases ? `${stats.not_indexed_cases} not published` : null,
    stats.stale_cases ? `${stats.stale_cases} changed since publishing` : null,
    stats.error_cases ? `${stats.error_cases} failed to publish` : null,
    trouble ? null : 'all up to date',
  ].filter(Boolean);
  return (
    <div data-testid="plugin-memory-stats" style={{ fontSize: 13 }}>
      <span style={{ color: trouble ? '#ffb357' : '#3fcf8e', fontWeight: 700 }}>{trouble ? '⚠' : '✓'}</span> {parts.join(' · ')}
    </div>
  );
}

const PROBLEM_WINDOWS = [30, 90, 180, 365].map((days) => ({ id: days, label: `${days} days` }));
const GROUPINGS: Array<{ id: 'symptom' | 'cause'; label: string }> = [
  { id: 'symptom', label: 'By symptom' },
  { id: 'cause', label: 'By cause' },
];
// Verified causes come first; the rest stay one click away.
const CAUSES_SHOWN = 2;

function RecurringProblems({ backendUrl, onOpenCase }: { backendUrl: string; onOpenCase: (caseId: number) => void }) {
  const [days, setDays] = useState(90);
  const [groupBy, setGroupBy] = useState<'symptom' | 'cause'>('symptom');
  const state = useLoad<RecurringProblemsResponse>(() => getRecurringProblems(backendUrl, days, groupBy), [backendUrl, days, groupBy]);
  const data = state.status === 'ready' ? state.data : null;

  return (
    <div data-testid="plugin-recurring-problems" style={PANEL}>
      <div style={styles.rowBetween}>
        <Choices label="Group by" options={GROUPINGS} value={groupBy} onChange={setGroupBy} />
        <Choices label="Window" options={PROBLEM_WINDOWS} value={days} onChange={setDays} />
      </div>
      {state.status === 'loading' ? <div style={styles.muted}>Grouping past cases...</div> : null}
      {state.status === 'error' ? <div style={styles.muted}>Recurring problems could not be loaded.</div> : null}
      {data && !data.available ? <div style={styles.muted}>{data.reason}</div> : null}
      {data?.available && !data.problems.length ? (
        <div style={styles.muted}>No problem happened {data.min_occurrences} or more times in the last {data.window_days} days ({data.cases_considered} cases compared).</div>
      ) : null}
      {data?.available && data.problems.length ? (
        <>
          {data.problems.map((problem) => <ProblemCard key={problem.central_case_id} problem={problem} days={data.window_days} groupBy={data.group_by} onOpenCase={onOpenCase} />)}
          <div style={styles.helperText}>
            {data.cases_considered} {data.group_by === 'cause' ? 'cases with a recorded cause' : 'cases'} from the last {data.window_days} days compared
            {data.sampled ? ' (a sample of them)' : ''}. Every case in a group is at least{' '}
            {Math.round(data.group_similarity * 100)}% like its central case in {data.group_by === 'cause' ? 'cause and fix' : 'symptom'}.
          </div>
        </>
      ) : null}
    </div>
  );
}

const NEXT_STEP_TONES: Record<NextStepTone, string> = { fix: '#3fcf8e', mixed: '#5794f2', verify: '#ffb357', record: '#ffb357' };

function NextStep({ problem, groupBy, onOpenCase }: { problem: RecurringProblem; groupBy: 'symptom' | 'cause'; onOpenCase: (caseId: number) => void }) {
  const step = recurringNextStep(problem, groupBy);
  const tone = NEXT_STEP_TONES[step.tone];
  return (
    <div data-testid="plugin-recurring-next-step" style={{ borderLeft: `3px solid ${tone}`, paddingLeft: 10, fontSize: 13 }}>
      <b style={{ color: tone }}>{step.title}</b> {step.detail}
      {step.tone === 'record' || step.tone === 'verify' ? (
        <div>
          <button type="button" style={LINK_BUTTON} onClick={() => onOpenCase(caseToRecordCauseOn(problem))}>
            {step.tone === 'record' ? 'Add a cause' : 'Confirm a cause'}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ProblemCard({ problem, days, groupBy, onOpenCase }: { problem: RecurringProblem; days: number; groupBy: 'symptom' | 'cause'; onOpenCase: (caseId: number) => void }) {
  const [showCases, setShowCases] = useState(false);
  const [showAllCauses, setShowAllCauses] = useState(false);
  const hiddenCauses = Math.max(problem.causes.length - CAUSES_SHOWN, 0);
  const causes = showAllCauses ? problem.causes : problem.causes.slice(0, CAUSES_SHOWN);
  return (
    <div data-testid="plugin-recurring-problem" style={{ ...BOX, ...styles.stack, gap: 6 }}>
      <div style={{ ...styles.row, gap: 8 }}>
        <strong>{problem.name}</strong>
        <span style={{ ...styles.chip, color: '#ffb357', borderColor: '#ffb35766' }}>{problem.occurrences} times in {days} days</span>
        {problem.named_by === 'ai' ? <span style={styles.chip}>AI-named</span> : null}
      </div>
      <div style={styles.helperText}>
        {[
          problem.services.join(', '),
          problem.last_seen ? `last ${formatDate(problem.last_seen)}` : null,
          problem.first_seen ? `first ${formatDate(problem.first_seen)}` : null,
          `${problem.verified_root_causes} verified ${problem.verified_root_causes === 1 ? 'cause' : 'causes'}`,
          problem.open_cases ? `${problem.open_cases} still open` : null,
        ].filter(Boolean).join(' · ')}
      </div>
      {problem.causes.length ? (
        <div style={{ ...styles.stack, gap: 4 }}>
          {causes.map((cause) => (
            <div key={cause.case_id} style={{ fontSize: 13 }}>
              <b>Cause{cause.verified ? ' (verified)' : ''}:</b> {cause.root_cause}
              {cause.fix ? <> — <b>Fix:</b> {cause.fix}</> : null}
            </div>
          ))}
          {hiddenCauses ? (
            <button type="button" style={LINK_BUTTON} onClick={() => setShowAllCauses(!showAllCauses)}>
              {showAllCauses ? 'Show fewer causes' : `Show ${hiddenCauses} more ${hiddenCauses === 1 ? 'cause' : 'causes'}`}
            </button>
          ) : null}
        </div>
      ) : null}
      <NextStep problem={problem} groupBy={groupBy} onOpenCase={onOpenCase} />
      <button type="button" style={LINK_BUTTON} onClick={() => setShowCases(!showCases)}>
        {showCases ? 'Hide' : 'Show'} {problem.occurrences} cases
      </button>
      {showCases ? problem.cases.map((item) => (
        <div key={item.case_id} style={{ fontSize: 13 }}>
          <CaseButton caseId={item.case_id} title={item.title} onOpenCase={onOpenCase} />
          <span style={styles.muted}>
            {' · '}
            {[
              item.service,
              formatDate(item.created_at) || null,
              !RESOLVED.has(item.case_status) ? 'Still open' : item.rca_verified ? 'Fixed, cause verified' : 'Fixed, cause not verified',
              item.origin === 'imported' ? 'imported' : null,
            ].filter(Boolean).join(' · ')}
          </span>
        </div>
      )) : null}
    </div>
  );
}

const COVERAGE_STATUSES: Record<Exclude<CoverageStatus, 'unknown'>, { label: string; tone: string; hint: string }> = {
  detected: { label: 'Detected', tone: '#3fcf8e', hint: 'A finding that reads like it was raised while it happened' },
  flagged_other: { label: 'Flagged something else', tone: 'rgba(204, 204, 220, 0.72)', hint: 'Something was flagged then, but nothing like this incident' },
  missed: { label: 'Missed', tone: '#f2495c', hint: 'The service was analysed and nothing was flagged: a detection gap' },
  not_watched: { label: 'Not watched', tone: '#ffb357', hint: 'Nothing analysed the service then: a coverage gap' },
};
const COVERAGE_ORDER = ['detected', 'flagged_other', 'missed', 'not_watched'] as const;
const GAPS = new Set<CoverageStatus>(['missed', 'not_watched', 'flagged_other', 'unknown']);
const COVERAGE_WINDOWS = [
  { id: 90, label: '90 days' },
  { id: 365, label: '1 year' },
  { id: 3650, label: 'All' },
];

function MonitoringCoverage({ backendUrl, onOpenCase }: { backendUrl: string; onOpenCase: (caseId: number) => void }) {
  const [days, setDays] = useState(365);
  const [showDetected, setShowDetected] = useState(false);
  const state = useLoad<CoverageReport>(() => getMonitoringCoverage(backendUrl, days), [backendUrl, days]);
  const data = state.status === 'ready' ? state.data : null;
  const gaps = data?.incidents.filter((incident) => GAPS.has(incident.status)) ?? [];
  const detected = data?.incidents.filter((incident) => incident.status === 'detected') ?? [];

  if (data?.available && !data.incidents.length) {
    return (
      <div data-testid="plugin-monitoring-coverage" style={{ ...PANEL, ...styles.rowBetween, borderStyle: 'dashed' }}>
        <div style={{ fontSize: 13 }}>
          <strong>Did your monitoring catch past incidents?</strong> <span style={styles.muted}>{data.reason}</span>
        </div>
        <Choices label="Coverage window" options={COVERAGE_WINDOWS} value={days} onChange={setDays} />
      </div>
    );
  }

  return (
    <div data-testid="plugin-monitoring-coverage" style={PANEL}>
      <div style={styles.rowBetween}>
        <div>
          <strong>Monitoring coverage</strong>
          <div style={{ ...styles.helperText, marginTop: 2 }}>Your imported past incidents, checked against what Ops Signals analysed and flagged while each one happened.</div>
        </div>
        <Choices label="Coverage window" options={COVERAGE_WINDOWS} value={days} onChange={setDays} />
      </div>
      {state.status === 'loading' ? <div style={styles.muted}>Checking past incidents...</div> : null}
      {state.status === 'error' ? <div style={styles.muted}>Coverage could not be loaded.</div> : null}
      {data && !data.available ? <div style={styles.muted}>{data.reason}</div> : null}
      {data?.available && data.incidents.length ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
            {COVERAGE_ORDER.map((status) => (
              <div key={status} title={COVERAGE_STATUSES[status].hint}>
                <Tile value={data.counts[status] ?? 0} label={COVERAGE_STATUSES[status].label} tone={COVERAGE_STATUSES[status].tone} />
              </div>
            ))}
          </div>
          {data.counts.unknown ? <div style={styles.helperText}>{data.counts.unknown} more can't be checked: the postmortem has no service or start time.</div> : null}
          {gaps.length ? (
            <div style={{ ...styles.stack, gap: 8 }}>
              <strong style={{ fontSize: 13 }}>What monitoring missed</strong>
              {gaps.map((incident) => <IncidentRow key={incident.case_id} incident={incident} onOpenCase={onOpenCase} />)}
            </div>
          ) : (
            <div style={styles.muted}>Every checkable incident in this window was detected while it happened.</div>
          )}
          {detected.length ? (
            <div style={{ ...styles.stack, gap: 8 }}>
              <button type="button" style={LINK_BUTTON} onClick={() => setShowDetected(!showDetected)}>
                {showDetected ? 'Hide' : 'Show'} {detected.length} detected {detected.length === 1 ? 'incident' : 'incidents'}
              </button>
              {showDetected ? detected.map((incident) => <IncidentRow key={incident.case_id} incident={incident} onOpenCase={onOpenCase} />) : null}
            </div>
          ) : null}
          <div style={styles.helperText}>
            {data.incidents_considered} imported {data.incidents_considered === 1 ? 'incident' : 'incidents'} checked. "Detected" means a finding on the same service, raised while
            the incident happened, reads at least 60% like the postmortem's symptom; anything less is shown as flagged something else.
          </div>
        </>
      ) : null}
    </div>
  );
}

function IncidentRow({ incident, onOpenCase }: { incident: CoverageReport['incidents'][number]; onOpenCase: (caseId: number) => void }) {
  const status = incident.status === 'unknown' ? null : COVERAGE_STATUSES[incident.status];
  return (
    <div data-testid="plugin-coverage-incident" style={{ ...BOX, ...styles.stack, gap: 4 }}>
      <div style={{ ...styles.row, gap: 8 }}>
        <span style={{ ...styles.chip, color: status?.tone, borderColor: status ? `${status.tone}66` : undefined }}>{incident.label}</span>
        <CaseButton caseId={incident.case_id} title={incident.title} onOpenCase={onOpenCase} />
      </div>
      <div style={styles.helperText}>{[incident.service, formatDate(incident.started_at) || null].filter(Boolean).join(' · ')}</div>
      <div style={{ fontSize: 13 }}>{incident.explanation}</div>
      {incident.evidence.length && incident.status !== 'detected' ? (
        <div style={{ ...styles.muted, fontSize: 13 }}>Flagged then: {incident.evidence.map((item) => `${item.title} (${Math.round(item.similarity * 100)}%)`).join('; ')}</div>
      ) : null}
      {incident.seen_elsewhere_case_id ? (
        <button type="button" style={LINK_BUTTON} onClick={() => onOpenCase(incident.seen_elsewhere_case_id as number)}>Open the latest detected case like it</button>
      ) : null}
    </div>
  );
}
