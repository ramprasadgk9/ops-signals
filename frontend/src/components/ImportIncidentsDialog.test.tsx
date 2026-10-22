import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ImportIncidentsDialog, buildImportForm, parsePairs, recallCheckLink } from './ImportIncidentsDialog';
import { api } from '../api/queries';
import type { CaseImportPreview } from '../types';

vi.mock('../api/queries', () => ({
  api: {
    caseImportProfiles: vi.fn(),
    caseImportTemplateUrl: (name: string) => `/api/case-imports/templates/${name}`,
    previewCaseImport: vi.fn(),
    runCaseImport: vi.fn(),
    undoCaseImport: vi.fn(),
  },
}));

const profiles = {
  profiles: [
    { id: 'jira-csv', label: 'Jira CSV export', kind: 'csv' as const, default_source: 'jira', checklist: ['Filter with JQL first.'] },
    { id: 'markdown', label: 'Markdown postmortems', kind: 'markdown' as const, default_source: 'markdown', checklist: ['One file per postmortem.'] },
  ],
  fields: ['source_id', 'title', 'root_cause'],
  required_fields: ['title', 'service', 'started_at', 'root_cause'],
  templates: ['incident-template.csv'],
};

const preview: CaseImportPreview = {
  file_profiles: { 'jira.csv': 'jira-csv' },
  warnings: [],
  counts: { new: 2, updated: 0, unchanged: 0, skipped: 1, duplicate_rows: 0 },
  redactions: 1,
  records: [
    { ref: 'jira.csv row 2', source: 'jira', source_id: 'OPS-412', title: 'Checkout 500s', service: 'Checkout', started_at: null, action: 'new', problems: [], redactions: 1, case_id: null },
    { ref: 'jira.csv row 3', source: 'jira', source_id: 'OPS-415', title: 'Login slow', service: 'Auth', started_at: null, action: 'new', problems: [], redactions: 0, case_id: null },
    { ref: 'jira.csv row 4', source: 'jira', source_id: 'OPS-420', title: 'No cause', service: 'Search', started_at: null, action: 'skipped', problems: ['missing root_cause'], redactions: 0, case_id: null },
  ],
};

function renderDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ImportIncidentsDialog open onClose={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ImportIncidentsDialog', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('walks source, upload, preview and import, sending aliases with the files', async () => {
    vi.mocked(api.caseImportProfiles).mockResolvedValue(profiles);
    vi.mocked(api.previewCaseImport).mockResolvedValue(preview);
    vi.mocked(api.runCaseImport).mockResolvedValue({
      ...preview,
      records: preview.records.map((record, index) => (record.action === 'new' ? { ...record, service: 'checkout-api', case_id: index + 1 } : record)),
      batch_id: 'b1',
      indexed: 2,
      index_failed: 0,
    });
    vi.mocked(api.undoCaseImport).mockResolvedValue({ batch_id: 'b1', deleted_cases: 2 });

    renderDialog();

    fireEvent.click(await screen.findByText('Jira CSV export'));
    expect(screen.getByText('Filter with JQL first.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /incident-template.csv/ })).toHaveAttribute('href', '/api/case-imports/templates/incident-template.csv');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    const file = new File(['Summary,Issue key\n'], 'jira.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('import-file-input'), { target: { files: [file] } });
    expect(screen.getByText('jira.csv')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(await screen.findByText('2 new')).toBeInTheDocument();
    expect(screen.getByText('1 values masked')).toBeInTheDocument();
    expect(screen.getByText(/1 incident has no root cause/)).toBeInTheDocument();
    expect(screen.getByText('OPS-420')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Service aliases'), { target: { value: 'Checkout = checkout-api' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import 2 cases' }));

    expect(await screen.findByText(/Imported 2 new and updated 0 cases/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Cases' })).toHaveAttribute('href', '/cases?origin=imported');
    expect(screen.getByRole('link', { name: 'OPS-412 · Checkout 500s' })).toHaveAttribute('href', '/cases/1');
    expect(screen.getByRole('link', { name: 'Try an alert' })).toHaveAttribute(
      'href',
      '/recurring-problems?service=checkout-api&message=Checkout+500s'
    );
    expect(screen.getByRole('link', { name: 'Open Integrations' })).toHaveAttribute('href', '/integrations');
    const form = vi.mocked(api.runCaseImport).mock.calls[0][0] as FormData;
    expect(JSON.parse(form.get('settings') as string)).toEqual({
      profile: 'jira-csv',
      service_aliases: { Checkout: 'checkout-api' },
      column_map: {},
    });
    expect((form.getAll('files')[0] as File).name).toBe('jira.csv');

    fireEvent.click(screen.getByRole('button', { name: /Undo this import/ }));
    expect(await screen.findByText(/Import undone/)).toBeInTheDocument();
    expect(api.undoCaseImport).toHaveBeenCalledWith('b1');
  });

  it('shows the server error when the preview is rejected', async () => {
    vi.mocked(api.caseImportProfiles).mockResolvedValue(profiles);
    vi.mocked(api.previewCaseImport).mockRejectedValue(new Error('unknown profile'));

    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    fireEvent.change(screen.getByTestId('import-file-input'), { target: { files: [new File(['x'], 'a.csv')] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(await screen.findByText('unknown profile')).toBeInTheDocument();
  });
});

describe('import form helpers', () => {
  it('parses "name = value" lines and ignores the rest', () => {
    expect(parsePairs('Checkout = checkout-api\nbad line\n = x\nAuth=auth-api')).toEqual({ Checkout: 'checkout-api', Auth: 'auth-api' });
  });

  it('builds multipart form data with every file and the settings JSON', () => {
    const form = buildImportForm([new File(['a'], 'a.md'), new File(['b'], 'b.csv')], { source: 'postmortems' });
    expect(form.getAll('files')).toHaveLength(2);
    expect(form.get('settings')).toBe('{"source":"postmortems"}');
  });
});

describe('recallCheckLink', () => {
  const record = (service: string, title: string, caseId: number | null) => ({
    ref: title, source: 'jira', source_id: null, title, service, started_at: null, action: 'new' as const, problems: [], redactions: 0, case_id: caseId,
  });

  it('picks the most common imported service and one of its titles', () => {
    const link = recallCheckLink([record('payments', 'Payments slow', 1), record('checkout', 'Checkout CPU', 2), record('checkout', 'Checkout errors', 3)]);
    expect(link).toEqual({ service: 'checkout', to: '/recurring-problems?service=checkout&message=Checkout+CPU' });
  });

  it('returns nothing when no case was written', () => {
    expect(recallCheckLink([record('checkout', 'Skipped one', null)])).toBeNull();
  });
});
