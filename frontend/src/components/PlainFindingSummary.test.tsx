import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PlainFindingSummary } from './PlainFindingSummary';
import type { FindingPlain } from '../types';

const stuck: FindingPlain = {
  kind: 'flatline',
  badge: 'gap',
  badge_label: 'Monitoring gap',
  headline: 'Active DB connections got stuck at 100 for 42 min',
  what: "From [[time:2026-10-26T14:06:00Z]] to [[time:2026-10-26T14:48:00Z]] it didn't change at all.",
  why: 'A stuck value often means the data source froze. Alerts on this metric may miss real problems.',
  check: 'Is the data source running and sending fresh values?',
  related: [],
};

const ai = {
  available: true,
  why: 'Active DB connections in payments stayed at exactly 100, which is often the pool limit.',
  check_extra: 'Whether 100 is the connection pool limit set for payments.',
  related_extra: null,
  model: 'qwen2.5:3b',
};

// Same as AppShell.test.tsx: Node's own localStorage global hides jsdom's.
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() { return items.size; },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => { items.delete(key); },
    setItem: (key: string, value: string) => { items.set(key, value); },
  };
}

describe('PlainFindingSummary with AI wording', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));
  afterEach(() => vi.unstubAllGlobals());

  it('shows the AI lines with a chip, names the model, and switches back to the template', () => {
    render(<PlainFindingSummary plain={stuck} summary="stored" ai={ai} />);

    const shown = screen.getByTestId('finding-plain');
    expect(shown).toHaveTextContent(ai.why);
    expect(shown).toHaveTextContent(`Is the data source running and sending fresh values? ${ai.check_extra}`);
    expect(screen.getAllByTestId('finding-plain-ai')).toHaveLength(2);
    expect(screen.getByTestId('finding-plain-ai-footer')).toHaveTextContent("Written by AI (qwen2.5:3b) from this finding's facts");

    fireEvent.click(screen.getByRole('button', { name: 'Show template wording' }));
    expect(shown).toHaveTextContent('A stuck value often means the data source froze.');
    expect(screen.queryByTestId('finding-plain-ai')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show AI wording' }));
    expect(shown).toHaveTextContent(ai.why);
  });

  it('shows the template while the lines are written', () => {
    render(<PlainFindingSummary plain={stuck} summary="stored" aiPending />);
    expect(screen.getByTestId('finding-plain')).toHaveTextContent('A stuck value often means the data source froze.');
    expect(screen.getByTestId('finding-plain-ai-pending')).toHaveTextContent('Writing for this finding...');
  });

  it('looks as before without AI', () => {
    render(<PlainFindingSummary plain={stuck} summary="stored" ai={{ available: false, reason: 'failed' }} />);
    expect(screen.queryByTestId('finding-plain-ai')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-plain-ai-footer')).not.toBeInTheDocument();
    expect(screen.queryByTestId('enable-ai-hint')).not.toBeInTheDocument();
  });

  it('offers how to turn AI on, with the steps in a dialog, until Not now', async () => {
    const { unmount } = render(<PlainFindingSummary plain={stuck} summary="stored" ai={{ available: false, reason: 'ai_off' }} showAiHint />);

    fireEvent.click(screen.getByRole('button', { name: 'How to turn it on' }));
    const dialog = screen.getByRole('dialog', { name: 'Turn on AI wording' });
    expect(dialog).toHaveTextContent('docker compose --profile ai up -d');
    expect(dialog).toHaveTextContent('OPS_SIGNALS_AI_ENABLED=1');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
    expect(screen.queryByTestId('enable-ai-hint')).not.toBeInTheDocument();
    unmount();

    render(<PlainFindingSummary plain={stuck} summary="stored" ai={{ available: false, reason: 'ai_off' }} showAiHint />);
    expect(screen.queryByTestId('enable-ai-hint')).not.toBeInTheDocument();
  });
});

describe('PlainFindingSummary with an alert on the metric', () => {
  it("shows the alert line, the team's words and a runbook link that opens in a new tab", () => {
    render(
      <PlainFindingSummary
        plain={{ ...stuck, alert: { name: 'PoolStuck', group: 'db', text: 'Checkout waits for a database connection.', runbook_url: 'https://wiki.example.com/pool', line: 'Still below the 120 alert line.', line_alert: 'PoolStuck' } }}
        summary="stored"
      />,
    );

    const shown = screen.getByTestId('finding-plain');
    expect(shown).toHaveTextContent('Alert line');
    expect(shown).toHaveTextContent('Still below the 120 alert line.');
    expect(shown).toHaveTextContent('Checkout waits for a database connection.');
    expect(shown).not.toHaveTextContent('A stuck value often means the data source froze.');
    const link = screen.getByTestId('finding-plain-link');
    expect(link).toHaveAttribute('href', 'https://wiki.example.com/pool');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(shown).toHaveTextContent('Open the runbook (from alert PoolStuck)');
  });
});
