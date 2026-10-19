import { describe, expect, it } from 'vitest';
import { hasFixDetails, setupBanner, setupChips, setupDocsUrl, setupReport, setupSummary, unreachableSetupResult, type SetupCheckResult } from './setupCheck';

const RESULT: SetupCheckResult = {
  generated_at: '2026-10-19T14:02:31Z',
  version: '0.5.0',
  checks: [
    { id: 'backend', group: 'required', status: 'ok', title: 'Backend', detail: 'Answering' },
    { id: 'database', group: 'required', status: 'ok', title: 'Database', detail: 'Connected' },
    { id: 'connection:mimir-eu', group: 'required', status: 'fail', title: 'Metrics: mimir-eu', detail: 'Login rejected (401).', fix: ['Get a token.'] },
    { id: 'login', group: 'recommended', status: 'warn', title: 'Login', detail: 'Open.', snippet: 'OPS_SIGNALS_API_TOKEN=...' },
    { id: 'risky_switches', group: 'recommended', status: 'ok', title: 'Risky switches', detail: 'Off.' },
    { id: 'alerts', group: 'optional', status: 'off', title: 'Alerts receiver', detail: 'Off.', docs: 'docs/alert-enrichment.md' },
    { id: 'ai', group: 'optional', status: 'off', title: 'AI assistant', detail: 'Off.' },
  ],
};

describe('setupSummary', () => {
  it('counts what is done, what is worth doing and what is not set up', () => {
    const summary = setupSummary(RESULT);
    expect([summary.requiredDone, summary.requiredTotal, summary.recommendedOpen, summary.optionalOff]).toEqual([2, 3, 1, 2]);
    expect(summary.requiredFailing.map((check) => check.title)).toEqual(['Metrics: mimir-eu']);
  });
});

describe('setupBanner', () => {
  it('names what needs fixing', () => {
    expect(setupBanner(RESULT)).toBe('Setup: 2 of 3 done. Needs fixing: Metrics: mimir-eu.');
  });

  it('is silent when everything needed works, even with recommended steps left', () => {
    const fixed = { ...RESULT, checks: RESULT.checks.map((check) => (check.group === 'required' ? { ...check, status: 'ok' as const } : check)) };
    expect(setupBanner(fixed)).toBeNull();
  });
});

describe('setupReport', () => {
  it('lists every check by group, with details only where something is wrong', () => {
    expect(setupReport(RESULT)).toBe(
      [
        'Ops Signals setup check · 2026-10-19 14:02 UTC',
        'version 0.5.0',
        '',
        'Needed to start:',
        '[ok]   Backend',
        '[ok]   Database',
        '[FAIL] Metrics: mimir-eu: Login rejected (401).',
        '',
        'Recommended:',
        '[warn] Login: Open.',
        '[ok]   Risky switches',
        '',
        'Optional:',
        '[--]   Alerts receiver: Off.',
        '[--]   AI assistant: Off.',
      ].join('\n')
    );
  });
});

describe('hasFixDetails', () => {
  it('offers "How to fix" only for a check that is not ok and has steps', () => {
    expect(hasFixDetails(RESULT.checks[2])).toBe(true);
    expect(hasFixDetails(RESULT.checks[3])).toBe(true);
    expect(hasFixDetails(RESULT.checks[5])).toBe(false);
    expect(hasFixDetails({ ...RESULT.checks[2], status: 'ok' })).toBe(false);
  });
});

describe('unreachableSetupResult', () => {
  it('turns a network failure into a failed Backend check that mentions CORS', () => {
    const [check] = unreachableSetupResult(new TypeError('Failed to fetch'), 'localhost:8000').checks;
    expect(check).toMatchObject({ id: 'backend', group: 'required', status: 'fail', detail: "Can't reach localhost:8000.", tried: 'Failed to fetch' });
    expect(check.fix?.join(' ')).toContain('OPS_SIGNALS_CORS_ORIGINS');
  });

  it('asks for the API token on a 401, from either client', () => {
    expect(unreachableSetupResult(new Error('Request failed: 401 - Missing bearer token'), 'b').checks[0].detail).toContain('needs an API token');
    expect(unreachableSetupResult(Object.assign(new Error('Unauthorized'), { status: 401 }), 'b').checks[0].detail).toContain('needs an API token');
  });

  it('says an older backend has no setup check on a 404', () => {
    expect(unreachableSetupResult(Object.assign(new Error('Not Found'), { status: 404 }), 'localhost:8000').checks[0].detail).toContain('Localhost:8000 answered, but has no setup check');
  });
});

it('links docs to the repository', () => {
  expect(setupDocsUrl('docs/security-model.md')).toBe('https://github.com/ramprasadgk9/ops-signals/blob/main/docs/security-model.md');
});

describe('setupChips', () => {
  it('says checking while the check runs, and unreachable when it failed', () => {
    expect(setupChips(null).map((chip) => [chip.label, chip.tone])).toEqual([['Checking backend…', 'pending']]);
    expect(setupChips(unreachableSetupResult(new TypeError('Failed to fetch'), 'localhost:8002'), true)).toEqual([
      { id: 'backend', label: 'Backend unreachable', tone: 'fail', title: "Can't reach localhost:8002." },
    ]);
  });

  it('turns the metrics and memory checks into chips', () => {
    const chips = setupChips({
      ...RESULT,
      checks: [...RESULT.checks, { id: 'memory', group: 'required', status: 'ok', title: 'Memory search', detail: 'Connected' }],
    });
    expect(chips.map((chip) => [chip.label, chip.tone])).toEqual([
      ['Backend connected', 'ok'],
      ['Metrics: 1 failing', 'fail'],
      ['Case memory on', 'ok'],
    ]);
    expect(chips[1].title).toBe('Metrics: mimir-eu: Login rejected (401).');
  });

  it('shows metrics ready and memory off when that is the case', () => {
    const chips = setupChips({
      ...RESULT,
      checks: [
        { id: 'connection:default', group: 'required', status: 'ok', title: 'Metrics: default', detail: 'Answered' },
        { id: 'memory', group: 'optional', status: 'off', title: 'Memory search', detail: 'Off.' },
      ],
    });
    expect(chips.map((chip) => [chip.label, chip.tone])).toEqual([
      ['Backend connected', 'ok'],
      ['Metrics ready', 'ok'],
      ['Case memory off', 'off'],
    ]);
  });
});
