import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { HistoryPage } from '../pages/HistoryPage';
import { SettingsPage } from '../pages/SettingsPage';
import { CsvUploadPanel } from './CsvUploadPanel';
import { ThemeProviderWithMode } from '../theme/ThemeProviderWithMode';

vi.mock('../api/queries', () => ({
  api: {
    analysisRuns: vi.fn(),
    runCsvUpload: vi.fn(),
  },
}));

import { api } from '../api/queries';

function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProviderWithMode>
        <MemoryRouter>{ui}</MemoryRouter>
      </ThemeProviderWithMode>
    </QueryClientProvider>
  );
}

describe('HistoryPage', () => {
  it('renders empty state when there are no analysis runs', async () => {
    vi.mocked(api.analysisRuns).mockResolvedValue([]);
    renderWithProviders(<HistoryPage />);
    expect(await screen.findByText('No analysis history')).toBeInTheDocument();
    expect(screen.getByText('Analysis runs will appear here as you generate them.')).toBeInTheDocument();
  });

  it('renders historical questions and analysis runs', async () => {
    vi.mocked(api.analysisRuns).mockResolvedValue([
      {
        id: 'run-1',
        provider: 'generic',
        source_type: 'csv',
        service: 'checkout-service',
        metric_name: 'cpu_usage',
        start_time: '2026-07-01T00:00:00Z',
        end_time: '2026-07-01T02:00:00Z',
        sample_count: 24,
        status: 'completed',
        created_at: '2026-07-01T02:00:00Z',
      },
    ]);

    renderWithProviders(<HistoryPage />);

    expect(await screen.findByText('Analysis History')).toBeInTheDocument();
    expect(screen.getByText('Has this happened before?')).toBeInTheDocument();
    expect(screen.getByText('checkout-service')).toBeInTheDocument();
    expect(screen.getByText('cpu_usage')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Analyze Patterns' }));
    expect(await screen.findByText('Recurring Pattern Analysis')).toBeInTheDocument();
  });
});

describe('SettingsPage', () => {
  it('renders settings sections', () => {
    renderWithProviders(<SettingsPage />);
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByText('Analysis Configuration')).toBeInTheDocument();
    expect(screen.getByText('Display Preferences')).toBeInTheDocument();
    expect(screen.getByText('Provider Settings')).toBeInTheDocument();
  });
});

describe('CsvUploadPanel', () => {
  it('runs analysis after selecting a CSV file', async () => {
    vi.mocked(api.runCsvUpload).mockResolvedValue({
      analysis_run_id: 'run-upload-1',
      provider: 'prometheus',
      source_type: 'csv',
      service: 'checkout',
      metric_name: 'cpu_usage',
      sample_count: 24,
      findings_count: 1,
    });

    renderWithProviders(<CsvUploadPanel />);

    const file = new File(['timestamp,metric,value\n'], 'sample.csv', { type: 'text/csv' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByRole('button', { name: /Selected: sample.csv/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Run Analysis' }));

    await waitFor(() => {
      expect(api.runCsvUpload).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText(/Analysis run created: run-upload-1/)).toBeInTheDocument();
  });
});
