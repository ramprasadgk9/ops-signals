import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AddAnalyzerPage } from './AddAnalyzerPage';
import { getJson, postJson } from '../../api/client';

vi.mock('../../api/client', () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
  deleteJson: vi.fn(),
}));

function renderPage() {
  vi.mocked(getJson).mockImplementation(async (url: string) => (url.includes('/readiness/') ? {} : []) as never);
  vi.mocked(postJson).mockImplementation(async (_url: string, body: unknown) => {
    const config = (body as { config: { analyzer_id: string } }).config;
    return { id: 1, analyzer_id: config.analyzer_id, display_name: '', status: 'routing_tested', config, readiness: null, promoted_at: null } as never;
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AddAnalyzerPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

function openApiPath() {
  fireEvent.click(screen.getByRole('button', { name: 'Add Analyzer' }));
  fireEvent.click(screen.getByRole('button', { name: /I have a hosted API or model/i }));
  return screen.getByRole('presentation');
}

describe('AddAnalyzerPage - hosted API or model', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('presents the API path as working, not coming soon', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Add Analyzer' }));

    const apiChoice = screen.getByRole('button', { name: /I have a hosted API or model/i });
    expect(apiChoice).toHaveTextContent(/sends each metric window/i);
    expect(apiChoice).not.toHaveTextContent(/not runnable/i);
  });

  it('asks for the service URLs and a key variable instead of a Python library', () => {
    renderPage();
    const drawer = openApiPath();

    expect(within(drawer).getByLabelText('Analyze URL')).toBeInTheDocument();
    expect(within(drawer).getByLabelText('Health Check URL')).toBeInTheDocument();
    expect(within(drawer).getByLabelText('API key environment variable (optional)')).toBeInTheDocument();
    expect(within(drawer).queryByLabelText('Library')).not.toBeInTheDocument();
    expect(within(drawer).queryByLabelText('Python Import Name')).not.toBeInTheDocument();
    expect(within(drawer).queryByText(/aren't wired up/i)).not.toBeInTheDocument();
    expect(within(drawer).getByText(/docs\/http-analyzer-contract.md/)).toBeInTheDocument();
  });

  it('saves the service settings with the draft', async () => {
    renderPage();
    const drawer = openApiPath();

    fireEvent.change(within(drawer).getByLabelText('Analyze URL'), { target: { value: 'http://toto:8080/analyze' } });
    fireEvent.change(within(drawer).getByLabelText('API key environment variable (optional)'), { target: { value: 'TOTO_KEY' } });
    fireEvent.click(within(drawer).getByRole('button', { name: /Save Draft/i }));

    await waitFor(() => expect(postJson).toHaveBeenCalledWith(
      '/api/analyzer-labs/drafts',
      expect.objectContaining({
        config: expect.objectContaining({
          library: 'http',
          runtime_params: expect.objectContaining({
            external_runtime: { type: 'external_http', analyze_url: 'http://toto:8080/analyze', api_key_env: 'TOTO_KEY' },
          }),
        }),
      })
    ));
  });
});

describe('AddAnalyzerPage - walkthrough video', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('plays the recorded walkthrough from the Setup Flow card', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /Watch how/i }));

    const dialog = screen.getByRole('dialog', { name: 'How to add an analyzer' });
    const video = within(dialog).getByLabelText('Add analyzer walkthrough video');
    expect(video).toHaveAttribute('src', `${import.meta.env.BASE_URL}walkthroughs/add-analyzer.webm`);
  });

  it('goes straight to the add form from the video', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /Watch how/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Try it now' }));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'How to add an analyzer' })).not.toBeInTheDocument());
    expect(screen.getByText('What are you adding?')).toBeInTheDocument();
  });
});
