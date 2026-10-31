import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WhatsWhat } from './WhatsWhat';

async function open(page: Parameters<typeof WhatsWhat>[0]['page']) {
  render(<p>Subtitle.<WhatsWhat page={page} /></p>);
  fireEvent.click(screen.getByRole('button', { name: "What's what?" }));
  return screen.findByRole('dialog', { name: "What's what?" });
}

describe("What's what?", () => {
  it('shows the chain with this page highlighted, its words and the full glossary', async () => {
    const dialog = await open('findings');

    const steps = within(within(dialog).getByRole('list', { name: 'From signal to memory' })).getAllByRole('listitem');
    expect(steps.map((step) => step.querySelector('p')?.textContent)).toEqual(['Signal', 'Finding', 'Case', 'Memory']);
    expect(steps[1]).toHaveAttribute('aria-current', 'page');
    expect(steps[1]).toHaveTextContent('A symptom: this metric changed, with the evidence. Not a diagnosis.');
    expect(steps[1]).toHaveTextContent('This page');
    expect(steps[2]).not.toHaveAttribute('aria-current');

    expect(within(dialog).getAllByRole('term').map((term) => term.textContent)).toEqual(['Evidence badge', 'Needs attention', 'Was this real?', 'Seen before', 'Finding vs alert']);
    expect(within(dialog).getByRole('link', { name: /full glossary/i })).toHaveAttribute('href', expect.stringMatching(/docs\/glossary\.md$/));
  });

  it('lists the words of the page it is on', async () => {
    const dialog = await open('cases');

    expect(within(dialog).getByText('Finding vs case')).toBeInTheDocument();
    expect(within(dialog).getByText(/Many findings never become cases/)).toBeInTheDocument();
    expect(within(dialog).getAllByRole('listitem')[2]).toHaveAttribute('aria-current', 'page');
  });

  it('closes', async () => {
    const dialog = await open('recurring');

    fireEvent.click(within(dialog).getByText('Close'));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
