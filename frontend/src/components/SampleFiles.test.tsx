import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/queries';
import type { SampleFile } from '../types';
import { SampleFiles } from './SampleFiles';

vi.mock('../api/queries', () => ({ api: { sampleFiles: vi.fn() } }));

const SAMPLES: SampleFile[] = [
  {
    id: 'sudden-jump', file: 'sudden-jump.csv', title: 'A sudden jump that stays', description: 'CPU steps up and stays there.',
    service: 'sample-inventory', metric: 'cpu_usage', interval: '5m', rows: 120,
    preview: ['timestamp,metric_name,value,service,env', '2026-07-30T00:00:00Z,cpu_usage,0.8242,sample-inventory,demo'],
  },
  {
    id: 'slow-climb', file: 'slow-climb.csv', title: 'Memory creeping up', description: 'Memory rises every hour.',
    service: 'sample-search', metric: 'memory_usage', interval: '5m', rows: 120,
    preview: ['timestamp,metric_name,value,service,env', '2026-07-30T00:00:00Z,memory_usage,512,sample-search,demo'],
  },
];

function renderWith(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.mocked(api.sampleFiles).mockResolvedValue(SAMPLES);
});

describe('SampleFiles', () => {
  it('lets anyone download a sample and see its first rows and columns', async () => {
    renderWith(<SampleFiles />);
    const box = await screen.findByTestId('sample-files');
    expect(box).toHaveTextContent('Sample files');
    // Outside the demo there is nothing to analyze in one click: upload the file below instead.
    expect(within(box).queryByRole('button', { name: 'Analyze it' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Download sudden-jump.csv' })).toHaveAttribute('href', '/api/samples/sudden-jump.csv');
    expect(screen.getByRole('link', { name: 'Download sudden-jump.csv' })).toHaveAttribute('download', 'sudden-jump.csv');
    expect(screen.getByTestId('sample-preview')).toHaveTextContent('2026-07-30T00:00:00Z,cpu_usage,0.8242');
    expect(box).toHaveTextContent('120 rows, one every 5m');
    expect(box).toHaveTextContent('timestampneeded · ISO time, UTC');
    expect(box).toHaveTextContent('metric_nameoptional · or type it in Metric');

    // Picking another sample shows its rows.
    fireEvent.click(screen.getByTestId('sample-slow-climb'));
    expect(screen.getByTestId('sample-preview')).toHaveTextContent('memory_usage,512');
    expect(screen.getByTestId('sample-slow-climb')).toHaveAttribute('data-selected', 'true');
  });

  it('in the demo, analyzes a sample in one click', async () => {
    const onAnalyze = vi.fn();
    renderWith(<SampleFiles onAnalyze={onAnalyze} note="Everyone shares this demo." />);
    const card = await screen.findByTestId('sample-slow-climb');
    expect(screen.getByTestId('sample-files')).toHaveTextContent('Try a sample file');
    expect(screen.getByTestId('sample-files')).toHaveTextContent('Everyone shares this demo.');
    fireEvent.click(within(card).getByRole('button', { name: 'Analyze it' }));
    expect(onAnalyze).toHaveBeenCalledWith(SAMPLES[1]);
    expect(screen.getByTestId('sample-preview')).toHaveTextContent('memory_usage');
  });

  it('shows nothing when there are no samples', async () => {
    vi.mocked(api.sampleFiles).mockResolvedValue([]);
    const { container } = renderWith(<SampleFiles />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
