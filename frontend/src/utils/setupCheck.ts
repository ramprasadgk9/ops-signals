// The Setup check (GET /api/setup/check): shared by the web UI's Setup check page and the plugin's
// Configuration page, which each render it their own way.

export type SetupCheckStatus = 'ok' | 'fail' | 'warn' | 'off';
export type SetupCheckGroup = 'required' | 'recommended' | 'optional';
export type SetupCheckAction = 'test_connection' | 'run_analysis' | 'send_test_alert';

export interface SetupCheck {
  id: string;
  group: SetupCheckGroup;
  status: SetupCheckStatus;
  title: string;
  detail: string;
  tried?: string | null;
  cause?: string | null;
  fix?: string[];
  snippet?: string | null;
  docs?: string | null;
  action?: SetupCheckAction | string | null;
  connection_id?: string | null;
}

export interface SetupCheckResult {
  generated_at: string;
  version: string;
  checks: SetupCheck[];
}

export const SETUP_GROUPS: { id: SetupCheckGroup; title: string; hint: string }[] = [
  { id: 'required', title: 'Needed to start', hint: "Ops Signals can't analyze anything until these are green" },
  { id: 'recommended', title: 'Recommended', hint: 'do these before your team uses it' },
  { id: 'optional', title: 'Optional', hint: 'add when you need them' },
];

const REPO_DOCS = 'https://github.com/ramprasadgk9/ops-signals/blob/main/';

export function setupDocsUrl(path: string): string {
  return `${REPO_DOCS}${path.replace(/^\/+/, '')}`;
}

export function checksIn(result: SetupCheckResult, group: SetupCheckGroup): SetupCheck[] {
  return result.checks.filter((check) => check.group === group);
}

/** Whether a check has steps to show behind "How to fix". */
export function hasFixDetails(check: SetupCheck): boolean {
  return check.status !== 'ok' && Boolean(check.tried || check.cause || check.fix?.length || check.snippet);
}

export function setupSummary(result: SetupCheckResult) {
  const required = checksIn(result, 'required');
  return {
    requiredDone: required.filter((check) => check.status === 'ok').length,
    requiredTotal: required.length,
    requiredFailing: required.filter((check) => check.status === 'fail'),
    recommendedOpen: checksIn(result, 'recommended').filter((check) => check.status !== 'ok').length,
    optionalOff: checksIn(result, 'optional').filter((check) => check.status === 'off').length,
  };
}

/** The reminder shown above Overview, or null when everything needed works. */
export function setupBanner(result: SetupCheckResult): string | null {
  const summary = setupSummary(result);
  if (summary.requiredFailing.length === 0) return null;
  const names = summary.requiredFailing.map((check) => check.title).join(', ');
  return `Setup: ${summary.requiredDone} of ${summary.requiredTotal} done. Needs fixing: ${names}.`;
}

const REPORT_TAGS: Record<SetupCheckStatus, string> = { ok: '[ok]  ', fail: '[FAIL]', warn: '[warn]', off: '[--]  ' };

/** Plain text for a GitHub issue or a message to an admin. It carries titles and details only:
 * the backend already leaves secrets out of both. */
export function setupReport(result: SetupCheckResult): string {
  const lines = [`Ops Signals setup check · ${result.generated_at.slice(0, 16).replace('T', ' ')} UTC`, `version ${result.version}`, ''];
  for (const group of SETUP_GROUPS) {
    const checks = checksIn(result, group.id);
    if (!checks.length) continue;
    lines.push(`${group.title}:`);
    for (const check of checks) {
      lines.push(`${REPORT_TAGS[check.status]} ${check.title}${check.status === 'ok' ? '' : `: ${check.detail}`}`);
    }
    lines.push('');
  }
  return lines.join('\n').trimEnd();
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** What to show when the check itself can't be fetched: the backend is the problem. */
export function unreachableSetupResult(error: unknown, backendLabel: string): SetupCheckResult {
  const message = error instanceof Error ? error.message : String(error);
  // The web UI's ApiError carries the status; the plugin's client puts it in the message.
  const carried = (error as { status?: unknown } | null)?.status;
  const status = typeof carried === 'number' ? carried : Number(/Request failed: (\d{3})/.exec(message)?.[1] ?? 0);
  const check: SetupCheck =
    status === 401
      ? {
          id: 'backend',
          group: 'required',
          status: 'fail',
          title: 'Backend',
          detail: 'The backend needs an API token, and this request had none or the wrong one.',
          cause: 'OPS_SIGNALS_API_TOKEN is set on the backend.',
          fix: ['Enter the token in the API token field (Grafana plugin), or set OPS_SIGNALS_API_TOKEN on the web container.', 'Then check again.'],
          docs: 'docs/security-model.md',
        }
      : status === 404
        ? {
            id: 'backend',
            group: 'required',
            status: 'fail',
            title: 'Backend',
            detail: `${capitalize(backendLabel)} answered, but has no setup check. It may be an older Ops Signals or not Ops Signals at all.`,
            fix: ['Check the backend URL points at Ops Signals.', 'Upgrade the backend if it is older than this page.'],
          }
        : {
            id: 'backend',
            group: 'required',
            status: 'fail',
            title: 'Backend',
            detail: status ? `${capitalize(backendLabel)} answered with an error (${status}).` : `Can't reach ${backendLabel}.`,
            tried: message,
            cause: status ? 'The backend is up but failing; its log has the details.' : 'The backend is down, the URL is wrong, or the browser is blocked from calling it (CORS).',
            fix: status
              ? ['Look in the backend log for the error.', 'Then check again.']
              : [
                  'Check the backend is running and the URL is right.',
                  "If the browser calls it directly (the Grafana plugin), add this site's address to OPS_SIGNALS_CORS_ORIGINS on the backend.",
                  'Then check again.',
                ],
            docs: 'docs/security-model.md',
          };
  return { generated_at: new Date().toISOString(), version: 'unknown', checks: [check] };
}

/** One line for a row's own Test button (POST /api/prometheus/test-connection). */
export function connectionTestText(result: { available: boolean; latency_ms?: number | null; message: string }): string {
  return result.available ? `Connected in ${result.latency_ms ?? '?'} ms` : `Still failing: ${result.message}`;
}

export type SetupChipTone = 'ok' | 'warn' | 'fail' | 'off' | 'pending';
export type SetupChip = { id: 'backend' | 'metrics' | 'memory'; label: string; tone: SetupChipTone; title: string };

const METRIC_CHECK = /^(connection:|otlp$|metrics$|connections$)/;

/** The app header's status chips, from the Setup check: null while it runs, unreachable when it failed. */
export function setupChips(result: SetupCheckResult | null, unreachable = false): SetupChip[] {
  if (unreachable) {
    return [{ id: 'backend', label: 'Backend unreachable', tone: 'fail', title: result?.checks[0]?.detail ?? "The backend can't be reached." }];
  }
  if (!result) return [{ id: 'backend', label: 'Checking backend…', tone: 'pending', title: 'Running the Setup check' }];

  const chips: SetupChip[] = [{ id: 'backend', label: 'Backend connected', tone: 'ok', title: `Ops Signals ${result.version}` }];
  const metrics = result.checks.filter((check) => check.group === 'required' && METRIC_CHECK.test(check.id));
  const failing = metrics.filter((check) => check.status !== 'ok');
  if (metrics.length) {
    chips.push(
      failing.length
        ? { id: 'metrics', label: `Metrics: ${failing.length} failing`, tone: 'fail', title: failing.map((check) => `${check.title}: ${check.detail}`).join('\n') }
        : { id: 'metrics', label: 'Metrics ready', tone: 'ok', title: metrics.map((check) => check.title).join('\n') }
    );
  }
  const memory = result.checks.find((check) => check.id === 'memory');
  if (memory) {
    const memoryLabel = { ok: 'Case memory on', warn: 'Case memory starting', fail: 'Case memory down', off: 'Case memory off' }[memory.status];
    chips.push({ id: 'memory', label: memoryLabel, tone: memory.status, title: memory.detail });
  }
  return chips;
}
