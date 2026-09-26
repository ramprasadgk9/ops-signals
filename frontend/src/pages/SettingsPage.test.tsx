import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './SettingsPage';

describe('SettingsPage', () => {
  it('points data-source setup to the Integrations page', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Integrations' })).toHaveAttribute('href', '/integrations');
  });
});
