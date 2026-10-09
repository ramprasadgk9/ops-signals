import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ClustersField } from './PluginApp';

// PluginApp's Prometheus query path imports @grafana/* (only loadable inside Grafana).
vi.mock('./grafanaPrometheus', () => ({}));
vi.mock('./prometheusFrameNormalizer', () => ({}));

function field(overrides: Partial<React.ComponentProps<typeof ClustersField>> = {}) {
  const props = { clusterOptions: ['eu', 'us'], clusterLabel: 'cluster', allClusters: true, setAllClusters: vi.fn(), selectedClusters: [], setSelectedClusters: vi.fn(), ...overrides };
  render(<ClustersField {...props} />);
  return props;
}

describe('ClustersField', () => {
  it('offers all clusters or a choice when the connection has several', () => {
    const props = field();

    expect(screen.getByText('Clusters')).toBeInTheDocument();
    expect(screen.getByLabelText('Clusters')).toBeDisabled();
    expect(screen.getByText('All clusters')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(props.setAllClusters).toHaveBeenCalledWith(false);
  });

  it('sends the clusters picked from the list', () => {
    const props = field({ allClusters: false });

    const list = screen.getByLabelText('Clusters') as HTMLSelectElement;
    list.options[1].selected = true;
    fireEvent.change(list);

    expect(props.setSelectedClusters).toHaveBeenCalledWith(['us']);
  });

  it('says so when there is one cluster, none, or no cluster label', () => {
    const { unmount } = render(<ClustersField clusterOptions={['staging']} clusterLabel="cluster" allClusters setAllClusters={vi.fn()} selectedClusters={[]} setSelectedClusters={vi.fn()} />);
    expect(screen.getByText('staging')).toBeInTheDocument();
    expect(screen.getByText(/The only cluster on this connection/)).toBeInTheDocument();
    unmount();

    const second = render(<ClustersField clusterOptions={[]} clusterLabel="cluster" allClusters setAllClusters={vi.fn()} selectedClusters={[]} setSelectedClusters={vi.fn()} />);
    expect(screen.getByText('No clusters')).toBeInTheDocument();
    expect(screen.getByText(/has no "cluster" label/)).toBeInTheDocument();
    second.unmount();

    render(<ClustersField clusterOptions={[]} clusterLabel={null} allClusters setAllClusters={vi.fn()} selectedClusters={[]} setSelectedClusters={vi.fn()} />);
    expect(screen.getByText(/Turned off for this connection/)).toBeInTheDocument();
  });

  it("keeps a saved schedule's clusters visible when the connection no longer has them", () => {
    field({ clusterOptions: ['us'], allClusters: false, selectedClusters: ['eu'] });

    expect(screen.getByRole('option', { name: 'eu (not on this connection now)' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'us' })).toBeInTheDocument();
  });
});
