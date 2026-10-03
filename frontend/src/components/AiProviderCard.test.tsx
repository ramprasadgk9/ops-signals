import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AiProviderCard } from './AiProviderCard';
import { api } from '../api/queries';
import type { AIStatus } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    aiStatus: vi.fn(),
    testAiConnection: vi.fn(),
  },
}));

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AiProviderCard />
    </QueryClientProvider>
  );
}

const active: AIStatus = {
  enabled: true,
  provider: 'openai_compatible',
  model: 'qwen2.5-7b',
  endpoint: 'http://vllm:8000/v1',
  api_key_set: true,
  active: true,
  issue: null,
};

describe('AiProviderCard', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('says AI is off by default and how to turn it on, without a test button', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue({ ...active, enabled: false, active: false, provider: 'ollama' });

    renderCard();

    expect(await screen.findByText('Off')).toBeInTheDocument();
    expect(screen.getByText(/everything works without it/i)).toBeInTheDocument();
    expect(screen.getByText(/OPS_SIGNALS_AI_ENABLED=1/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /test connection/i })).not.toBeInTheDocument();
  });

  it('shows the active provider, model and endpoint', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(active);

    renderCard();

    expect(await screen.findByText('In use')).toBeInTheDocument();
    expect(screen.getByText('OpenAI-compatible')).toBeInTheDocument();
    expect(screen.getByText('qwen2.5-7b')).toBeInTheDocument();
    expect(screen.getByText('http://vllm:8000/v1')).toBeInTheDocument();
    expect(screen.getByText('Set')).toBeInTheDocument();
  });

  it('explains why configured AI is not in use', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue({ ...active, active: false, model: null, issue: 'The openai_compatible provider needs model (OPS_SIGNALS_OPENAI_MODEL).' });

    renderCard();

    expect(await screen.findByText('Not in use')).toBeInTheDocument();
    expect(screen.getByText(/needs model/)).toBeInTheDocument();
  });

  it('runs a connection test and shows the reply', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(active);
    vi.mocked(api.testAiConnection).mockResolvedValue({ ok: true, provider: 'openai_compatible', model: 'qwen2.5-7b', latency_ms: 812.4, reply: 'ok', error: null });

    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: /test connection/i }));

    expect(await screen.findByText(/Connected to qwen2.5-7b in 812 ms/)).toBeInTheDocument();
    expect(api.testAiConnection).toHaveBeenCalledTimes(1);
  });

  it('shows the provider error when the connection test fails', async () => {
    vi.mocked(api.aiStatus).mockResolvedValue(active);
    vi.mocked(api.testAiConnection).mockResolvedValue({ ok: false, provider: 'openai_compatible', model: 'qwen2.5-7b', latency_ms: null, reply: null, error: 'HTTP 401: Incorrect API key provided' });

    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: /test connection/i }));

    expect(await screen.findByText(/Incorrect API key provided/)).toBeInTheDocument();
  });
});
