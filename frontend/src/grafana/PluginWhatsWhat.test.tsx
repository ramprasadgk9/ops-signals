import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PluginWhatsWhat } from './PluginWhatsWhat';

describe("Plugin What's what?", () => {
  it('shows the chain, the Overview words and the full glossary, and closes on Escape', () => {
    render(<p>Current run result.<PluginWhatsWhat page="overview" /></p>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: "What's what?" }));

    const dialog = screen.getByRole('dialog', { name: "What's what?" });
    const steps = within(within(dialog).getByRole('list', { name: 'From signal to memory' })).getAllByRole('listitem');
    expect(steps).toHaveLength(4);
    // The Overview holds every step, so none is highlighted.
    expect(steps.filter((step) => step.getAttribute('aria-current'))).toHaveLength(0);
    expect(within(dialog).getAllByRole('term').map((term) => term.textContent)).toEqual(['Finding vs case', 'Evidence badge', 'Combined pattern', 'Seen before', "Fix didn't hold"]);
    expect(within(dialog).getByRole('link', { name: /full glossary/i })).toHaveAttribute('href', expect.stringMatching(/docs\/glossary\.md$/));

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes from its Close button', () => {
    render(<PluginWhatsWhat page="findings" />);
    fireEvent.click(screen.getByRole('button', { name: "What's what?" }));

    fireEvent.click(within(screen.getByRole('dialog')).getByText('Close'));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
