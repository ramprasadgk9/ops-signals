import React from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  Step,
  StepLabel,
  Stepper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import HistoryRoundedIcon from '@mui/icons-material/HistoryRounded';
import { Link as RouterLink } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { Pill } from '../standalone/components';
import { ui } from '../standalone/theme';
import type { CaseImportPreview, CaseImportProfile, CaseImportRecord, CaseImportResult, CaseImportSettings } from '../types';

export const IMPORT_GUIDE_URL = 'https://github.com/ramprasadgk9/ops-signals/blob/main/docs/importing-incident-history.md';
const ACCEPTED_FILES = '.csv,.md,.markdown,.zip,.yaml,.yml';
const STEPS = ['Source', 'Upload', 'Preview and mapping', 'Import'];
const AUTO_PROFILE = 'auto';
const AUTO_CHECKLIST = [
  'Export resolved incidents that have a written root cause; skip ones without.',
  'Include an ID, title, service, start time and root cause for each incident.',
  'Service names should match the service label in your metrics, or add aliases in step 3.',
  'Remove customer names, emails and credentials. Obvious emails, tokens and IPs are masked on import.',
];
const PREVIEW_ROW_LIMIT = 200;

/** "Checkout = checkout-api" per line -> { Checkout: 'checkout-api' }. */
export function parsePairs(text: string): Record<string, string> {
  const pairs: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const index = line.indexOf('=');
    if (index <= 0) continue;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key && value) pairs[key] = value;
  }
  return pairs;
}

export function buildImportForm(files: File[], settings: CaseImportSettings) {
  const form = new FormData();
  files.forEach((file) => form.append('files', file));
  form.append('settings', JSON.stringify(settings));
  return form;
}

type Props = { open: boolean; onClose: () => void };

export function ImportIncidentsDialog({ open, onClose }: Props) {
  const queryClient = useQueryClient();
  const profilesQuery = useQuery({ queryKey: ['case-import-profiles'], queryFn: () => api.caseImportProfiles(), enabled: open });
  const [step, setStep] = React.useState(0);
  const [profile, setProfile] = React.useState(AUTO_PROFILE);
  const [files, setFiles] = React.useState<File[]>([]);
  const [aliasesText, setAliasesText] = React.useState('');
  const [columnsText, setColumnsText] = React.useState('');
  const [source, setSource] = React.useState('');
  const [preview, setPreview] = React.useState<CaseImportPreview | null>(null);
  const [result, setResult] = React.useState<CaseImportResult | null>(null);

  const settings: CaseImportSettings = {
    ...(profile !== AUTO_PROFILE ? { profile } : {}),
    ...(source.trim() ? { source: source.trim() } : {}),
    service_aliases: parsePairs(aliasesText),
    column_map: parsePairs(columnsText),
  };

  const previewMutation = useMutation({
    mutationFn: () => api.previewCaseImport(buildImportForm(files, settings)),
    onSuccess: (data) => {
      setPreview(data);
      setStep(2);
    },
  });
  const importMutation = useMutation({
    mutationFn: () => api.runCaseImport(buildImportForm(files, settings)),
    onSuccess: (data) => {
      setResult(data);
      void queryClient.invalidateQueries();
    },
  });
  const undoMutation = useMutation({
    mutationFn: (batchId: string) => api.undoCaseImport(batchId),
    onSuccess: () => void queryClient.invalidateQueries(),
  });

  const close = () => {
    setStep(0);
    setFiles([]);
    setPreview(null);
    setResult(null);
    previewMutation.reset();
    importMutation.reset();
    undoMutation.reset();
    onClose();
  };

  const profiles = profilesQuery.data?.profiles ?? [];
  const selectedProfile = profiles.find((item) => item.id === profile);
  const writes = preview ? preview.counts.new + preview.counts.updated : 0;

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="md" aria-labelledby="import-incidents-title">
      <DialogTitle id="import-incidents-title" sx={{ fontWeight: 900 }}>Import past incidents</DialogTitle>
      <DialogContent dividers>
        <Stepper activeStep={step} alternativeLabel sx={{ mb: 3 }}>
          {STEPS.map((label) => (
            <Step key={label}><StepLabel>{label}</StepLabel></Step>
          ))}
        </Stepper>

        {step === 0 ? (
          <SourceStep
            profiles={profiles}
            loading={profilesQuery.isLoading}
            error={profilesQuery.error}
            profile={profile}
            onProfile={setProfile}
            checklist={selectedProfile?.checklist ?? AUTO_CHECKLIST}
            templates={profilesQuery.data?.templates ?? []}
          />
        ) : null}

        {step === 1 ? <UploadStep files={files} onFiles={setFiles} /> : null}

        {step === 2 && preview ? (
          <Stack spacing={2}>
            <PreviewSummary preview={preview} />
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
              <TextField
                label="Service aliases"
                placeholder={'Checkout = checkout-api\nPayments = payments-worker'}
                helperText="One per line: name in the export = service label in your metrics"
                multiline
                minRows={3}
                fullWidth
                value={aliasesText}
                onChange={(event) => setAliasesText(event.target.value)}
              />
              <TextField
                label="Column overrides"
                placeholder={'root_cause = Custom field (Why it happened)'}
                helperText={`One per line: case field = column header. Fields: ${(profilesQuery.data?.fields ?? []).join(', ')}`}
                multiline
                minRows={3}
                fullWidth
                value={columnsText}
                onChange={(event) => setColumnsText(event.target.value)}
              />
            </Stack>
            <Stack direction="row" spacing={2} alignItems="center">
              <TextField size="small" label="Source label (optional)" value={source} onChange={(event) => setSource(event.target.value)} />
              <Button variant="outlined" onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending} sx={{ textTransform: 'none', fontWeight: 800 }}>
                Re-check with these settings
              </Button>
            </Stack>
            <PreviewTable preview={preview} />
          </Stack>
        ) : null}

        {step === 3 && preview ? (
          <Stack spacing={2}>
            {!result ? (
              <Typography>
                Ready to write <b>{preview.counts.new}</b> new and <b>{preview.counts.updated}</b> updated cases.{' '}
                {preview.counts.unchanged} unchanged, {preview.counts.skipped} skipped and {preview.counts.duplicate_rows} duplicate rows
                will be left alone. Imported cases are marked as imported and indexed into operational memory.
              </Typography>
            ) : (
              <ImportDone
                result={result}
                undone={undoMutation.isSuccess}
                undoing={undoMutation.isPending}
                onUndo={() => undoMutation.mutate(result.batch_id)}
                onNavigate={close}
              />
            )}
            {importMutation.isPending ? (
              <Stack direction="row" spacing={1.5} alignItems="center">
                <CircularProgress size={20} />
                <Typography>Importing and indexing. Large imports can take a minute while each case is embedded.</Typography>
              </Stack>
            ) : null}
          </Stack>
        ) : null}

        {previewMutation.error || importMutation.error || undoMutation.error ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {(previewMutation.error ?? importMutation.error ?? undoMutation.error)?.message}
          </Alert>
        ) : null}
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Link href={IMPORT_GUIDE_URL} target="_blank" rel="noreferrer" sx={{ mr: 'auto', fontWeight: 700 }}>
          Full guide
        </Link>
        <Button onClick={close} sx={{ textTransform: 'none' }}>{result ? 'Close' : 'Cancel'}</Button>
        {step > 0 && !result ? (
          <Button onClick={() => setStep(step - 1)} sx={{ textTransform: 'none' }}>Back</Button>
        ) : null}
        {step === 0 ? (
          <Button variant="contained" onClick={() => setStep(1)} sx={{ textTransform: 'none', fontWeight: 800 }}>Next</Button>
        ) : null}
        {step === 1 ? (
          <Button
            variant="contained"
            disabled={!files.length || previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
            sx={{ textTransform: 'none', fontWeight: 800 }}
          >
            {previewMutation.isPending ? 'Checking...' : 'Preview'}
          </Button>
        ) : null}
        {step === 2 ? (
          <Button variant="contained" onClick={() => setStep(3)} sx={{ textTransform: 'none', fontWeight: 800 }}>Next</Button>
        ) : null}
        {step === 3 && !result ? (
          <Button
            variant="contained"
            disabled={!writes || importMutation.isPending}
            onClick={() => importMutation.mutate()}
            sx={{ textTransform: 'none', fontWeight: 800 }}
          >
            Import {writes} cases
          </Button>
        ) : null}
      </DialogActions>
    </Dialog>
  );
}

function SourceStep({
  profiles,
  loading,
  error,
  profile,
  onProfile,
  checklist,
  templates,
}: {
  profiles: CaseImportProfile[];
  loading: boolean;
  error: Error | null;
  profile: string;
  onProfile: (value: string) => void;
  checklist: string[];
  templates: string[];
}) {
  if (loading) return <CircularProgress size={24} />;
  if (error) return <Alert severity="error">Import options could not be loaded: {error.message}</Alert>;
  const options = [{ id: AUTO_PROFILE, label: 'Detect from the files' }, ...profiles];
  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography sx={{ fontWeight: 800, mb: 1 }}>Where are the incidents from?</Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {options.map((option) => (
            <Chip
              key={option.id}
              label={option.label}
              onClick={() => onProfile(option.id)}
              color={profile === option.id ? 'primary' : 'default'}
              variant={profile === option.id ? 'filled' : 'outlined'}
              sx={{ fontWeight: 800 }}
            />
          ))}
        </Stack>
      </Box>
      <Box sx={{ p: 2, border: `1px solid ${ui.border}`, borderRadius: '8px', bgcolor: 'var(--os-surface-alt)' }}>
        <Typography sx={{ fontWeight: 800, mb: 1 }}>Before you export</Typography>
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
          {checklist.map((item) => (
            <Typography component="li" key={item} sx={{ fontSize: 14, mb: 0.5 }}>{item}</Typography>
          ))}
        </Box>
      </Box>
      {templates.length ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
          <Typography sx={{ fontSize: 14, color: ui.muted }}>Templates:</Typography>
          {templates.map((name) => (
            <Button
              key={name}
              size="small"
              href={api.caseImportTemplateUrl(name)}
              download={name}
              startIcon={<DownloadRoundedIcon />}
              sx={{ textTransform: 'none' }}
            >
              {name}
            </Button>
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}

function UploadStep({ files, onFiles }: { files: File[]; onFiles: (files: File[]) => void }) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const incoming = Array.from(list);
    onFiles([...files.filter((file) => !incoming.some((item) => item.name === file.name)), ...incoming]);
  };
  return (
    <Stack spacing={2}>
      <Box
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
        sx={{
          py: 5,
          textAlign: 'center',
          border: `2px dashed ${dragging ? ui.blue : ui.border}`,
          borderRadius: '8px',
          bgcolor: dragging ? 'var(--os-tint-blue)' : 'var(--os-surface-alt)',
        }}
      >
        <UploadFileRoundedIcon sx={{ fontSize: 40, color: ui.muted }} />
        <Typography sx={{ fontWeight: 800, mt: 1 }}>Drop exports here</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 14 }}>CSV, Markdown or a .zip of them, plus an optional ops-signals-import.yaml</Typography>
        <Button variant="outlined" onClick={() => inputRef.current?.click()} sx={{ mt: 2, textTransform: 'none', fontWeight: 800 }}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={ACCEPTED_FILES}
          data-testid="import-file-input"
          onChange={(event) => addFiles(event.target.files)}
        />
      </Box>
      {files.length ? (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {files.map((file) => (
            <Chip key={file.name} label={file.name} onDelete={() => onFiles(files.filter((item) => item !== file))} />
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}

function PreviewSummary({ preview }: { preview: CaseImportPreview }) {
  const { counts } = preview;
  const missingRootCause = preview.records.filter((record) => record.problems.includes('missing root_cause')).length;
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip color="success" label={`${counts.new} new`} />
        <Chip color="info" label={`${counts.updated} updated`} />
        <Chip label={`${counts.unchanged} unchanged`} />
        <Chip color={counts.skipped ? 'warning' : 'default'} label={`${counts.skipped} skipped`} />
        <Chip label={`${counts.duplicate_rows} duplicate rows`} />
        {preview.redactions ? <Chip variant="outlined" label={`${preview.redactions} values masked`} /> : null}
      </Stack>
      <Typography sx={{ fontSize: 14, color: ui.muted }}>
        {Object.entries(preview.file_profiles).map(([name, profileId]) => `${name}: ${profileId}`).join(' · ')}
      </Typography>
      {missingRootCause ? (
        <Alert severity="warning">
          {missingRootCause === 1 ? '1 incident has' : `${missingRootCause} incidents have`} no root cause and will be skipped. Add a root cause column, or map it under Column overrides.{' '}
          <Link href={`${IMPORT_GUIDE_URL}#which-incidents-to-include`} target="_blank" rel="noreferrer">Why</Link>
        </Alert>
      ) : null}
      {preview.warnings.map((warning) => (
        <Alert key={warning} severity="info">{warning}</Alert>
      ))}
    </Stack>
  );
}

function PreviewTable({ preview }: { preview: CaseImportPreview }) {
  const rows = preview.records.slice(0, PREVIEW_ROW_LIMIT);
  return (
    <Box sx={{ maxHeight: 320, overflow: 'auto', border: `1px solid ${ui.border}`, borderRadius: '8px' }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Action</TableCell>
            <TableCell>ID</TableCell>
            <TableCell>Title</TableCell>
            <TableCell>Service</TableCell>
            <TableCell>Problems</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((record) => (
            <TableRow key={`${record.ref}-${record.source_id}`}>
              <TableCell><Pill label={record.action} /></TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{record.source_id ?? '--'}</TableCell>
              <TableCell>{record.title || <Typography component="span" color="text.secondary">{record.ref}</Typography>}</TableCell>
              <TableCell>{record.service || '--'}</TableCell>
              <TableCell sx={{ color: ui.red }}>{record.problems.join(', ')}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {preview.records.length > rows.length ? (
        <Typography sx={{ p: 1.5, fontSize: 13, color: ui.muted }}>Showing the first {rows.length} of {preview.records.length} records.</Typography>
      ) : null}
    </Box>
  );
}

/** Builds the "check recall" link: the alert preview pre-filled with the service most of the
 * import is about and one imported title as the alert message. */
export function recallCheckLink(records: CaseImportRecord[]) {
  const written = records.filter((record) => record.case_id && record.service);
  if (!written.length) return null;
  const counts = new Map<string, number>();
  written.forEach((record) => counts.set(record.service, (counts.get(record.service) ?? 0) + 1));
  const service = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
  const example = written.find((record) => record.service === service)!;
  const params = new URLSearchParams({ service, message: example.title });
  return { service, to: `/operational-memory?${params.toString()}` };
}

function ImportDone({
  result,
  undone,
  undoing,
  onUndo,
  onNavigate,
}: {
  result: CaseImportResult;
  undone: boolean;
  undoing: boolean;
  onUndo: () => void;
  onNavigate: () => void;
}) {
  if (undone) return <Alert severity="info">Import undone. The cases it created were removed from Cases and from memory.</Alert>;
  const written = result.records.filter((record) => record.case_id && (record.action === 'new' || record.action === 'updated'));
  const recall = recallCheckLink(written);
  const memoryOn = result.indexed > 0;
  return (
    <Stack spacing={2}>
      <Alert severity="success">
        Imported {result.counts.new} new and updated {result.counts.updated} cases. {result.indexed} indexed into memory
        {result.index_failed ? `, ${result.index_failed} failed to index (retry from the case page)` : ''}.
      </Alert>
      {!memoryOn && written.length ? (
        <Alert severity="warning">Memory is not enabled, so similar-case search will not find these cases until they are indexed.</Alert>
      ) : null}

      <Box sx={{ p: 2, border: `1px solid ${ui.border}`, borderRadius: '8px' }} data-testid="import-next-steps">
        <Typography sx={{ fontWeight: 900, mb: 1.5 }}>What next</Typography>
        <Stack spacing={1.75}>
          <NextStep
            title="See the imported cases"
            body="They are on the Cases page as resolved cases with an Imported badge."
            action={<Button component={RouterLink} to="/cases?origin=imported" onClick={onNavigate} size="small" variant="contained" sx={{ textTransform: 'none', fontWeight: 800 }}>Open Cases</Button>}
          >
            {written.length ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                {written.slice(0, 5).map((record) => (
                  <Chip
                    key={record.case_id}
                    size="small"
                    clickable
                    component={RouterLink}
                    to={`/cases/${record.case_id}`}
                    onClick={onNavigate}
                    label={record.source_id && !record.source_id.startsWith('fp-') ? `${record.source_id} · ${record.title}` : record.title}
                    sx={{ maxWidth: 320 }}
                  />
                ))}
                {written.length > 5 ? <Typography sx={{ fontSize: 13, color: ui.muted, alignSelf: 'center' }}>and {written.length - 5} more</Typography> : null}
              </Stack>
            ) : null}
          </NextStep>
          {recall && memoryOn ? (
            <NextStep
              title="Check that alerts recall them"
              body={`Opens the Alert Context Preview filled in for ${recall.service}. Run it and the imported incidents should show up under similar cases.`}
              action={<Button component={RouterLink} to={recall.to} onClick={onNavigate} size="small" variant="outlined" sx={{ textTransform: 'none', fontWeight: 800 }}>Try an alert</Button>}
            />
          ) : null}
          {memoryOn ? (
            <NextStep
              title="Ask about past incidents"
              body={'Ask Ops Signals questions like "have we seen high CPU on checkout before?"'}
              action={<Button component={RouterLink} to="/assistant" onClick={onNavigate} size="small" variant="outlined" sx={{ textTransform: 'none', fontWeight: 800 }}>Ask Ops Signals</Button>}
            />
          ) : null}
          <NextStep
            title="Manage imports"
            body="Integrations lists every import with its counts. Undo is there too, and re-importing an updated export only changes what changed."
            action={<Button component={RouterLink} to="/integrations" onClick={onNavigate} size="small" variant="outlined" sx={{ textTransform: 'none', fontWeight: 800 }}>Open Integrations</Button>}
          />
        </Stack>
      </Box>

      <Box>
        <Button startIcon={<HistoryRoundedIcon />} onClick={onUndo} disabled={undoing} color="warning" sx={{ textTransform: 'none', fontWeight: 800 }}>
          Undo this import
        </Button>
      </Box>
    </Stack>
  );
}

function NextStep({ title, body, action, children }: { title: string; body: string; action: React.ReactNode; children?: React.ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{title}</Typography>
        <Typography sx={{ color: ui.muted, fontSize: 13 }}>{body}</Typography>
        {children}
      </Box>
      <Box sx={{ flexShrink: 0 }}>{action}</Box>
    </Stack>
  );
}
