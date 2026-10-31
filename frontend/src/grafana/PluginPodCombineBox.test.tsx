import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PluginPodCombineBox } from './PluginPodCombineBox';
import type { PodSplit } from '../types';

const QUERY = 'request_latency_p95{service="search-svc"}';
const pods: PodSplit = {
  label: 'pod',
  values: ['search-svc-2', 'search-svc-0', 'search-svc-1', 'search-svc-3'],
  suggested_combine: 'avg',
  queries: { max: `max by (service) (${QUERY})`, sum: `sum by (service) (${QUERY})`, avg: `avg by (service) (${QUERY})`, min: `min by (service) (${QUERY})` },
  one_queries: { 'search-svc-2': 'request_latency_p95{service="search-svc",pod="search-svc-2"}' },
  odd: { value: 'search-svc-2', message: 'search-svc-2 is behaving differently from the other 3 pods: it reaches 2,343 while the others stay near 92.' },
};

describe('PluginPodCombineBox', () => {
  it('offers the four ways to combine and puts the chosen query in the box', () => {
    const onUseQuery = vi.fn();
    render(<PluginPodCombineBox pods={pods} onUseQuery={onUseQuery} />);

    expect(screen.getByText('This query returns 4 lines, one per pod. Analysis needs one line.')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /^Combine: / }).map((button) => button.textContent)).toEqual([
      'Combine: highest pod', 'Combine: all pods added up', 'Combine: average pod', 'Combine: lowest pod',
    ]);
    expect(screen.getByText(/The usual way for this metric is average pod\./)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Combine: average pod' }));
    expect(onUseQuery).toHaveBeenCalledWith(`avg by (service) (${QUERY})`);
  });

  it('names the odd pod and offers it alone for a plain selector', () => {
    const onUseQuery = vi.fn();
    render(<PluginPodCombineBox pods={pods} onUseQuery={onUseQuery} />);

    expect(screen.getByText(pods.odd!.message)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Analyze only search-svc-2' }));
    expect(onUseQuery).toHaveBeenCalledWith('request_latency_p95{service="search-svc",pod="search-svc-2"}');
  });

  it('has no one-pod button for hand-written PromQL, and no odd pod with labels only', () => {
    render(<PluginPodCombineBox pods={{ ...pods, one_queries: {} }} onUseQuery={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Analyze only/ })).toBeNull();

    render(<PluginPodCombineBox pods={{ ...pods, odd: null }} onUseQuery={vi.fn()} />);
    expect(screen.getAllByText(/behaving differently/)).toHaveLength(1);
  });
});
