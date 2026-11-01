import { Fragment, useState } from 'react';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded';
import KeyboardArrowDownRoundedIcon from '@mui/icons-material/KeyboardArrowDownRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { PageHeader, WorkspacePanel } from '../standalone/components';
import { ui } from '../standalone/theme';
import {
  OVERRIDES_DOC_URL,
  RUN_ORDER,
  RUN_STATUS,
  atAGlance,
  formatValue,
  selectionSentence,
  sourceText,
  type AnalyzerInUse,
  type AnalyzerSetting,
  type RunStatus,
  type SettingsLayer,
} from '../utils/analyzerSettings';

// The Lab for each analyzer that has one (components/AppShell.tsx).
const LAB_FOR: Record<string, string> = {
  anomaly_zscore: '/experiments/zscore-anomaly-lab',
  pyod_outlier: '/experiments/pyod-outlier-lab',
  prophet: '/experiments/prophet-forecast-lab',
  baseline_shift: '/experiments/ruptures-change-point-lab',
  stumpy: '/experiments/stumpy-motif-lab',
  trend: '/experiments/trend-lab',
};

// Tint backgrounds with ink text from the theme's tokens, so each chip stays readable in dark mode.
const TONES = {
  green: { bg: 'var(--os-tint-green, #ecfdf5)', fg: 'var(--os-ink-green, #166534)' },
  blue: { bg: 'var(--os-tint-blue, #eff6ff)', fg: 'var(--os-ink-blue, #1d4ed8)' },
  amber: { bg: 'var(--os-tint-amber, #fffbeb)', fg: 'var(--os-ink-amber, #92400e)' },
  red: { bg: 'var(--os-tint-rose, #fff1f2)', fg: 'var(--os-ink-red, #b91c1c)' },
  grey: { bg: 'var(--os-surface-alt, #f8fafc)', fg: ui.muted },
};

const IS_PATTERN = /[*?[]/;

export function RunStatusChip({ status }: { status: RunStatus }) {
  const { label, tone } = RUN_STATUS[status];
  return <Chip size="small" label={label} sx={{ bgcolor: TONES[tone].bg, color: TONES[tone].fg, fontWeight: 800 }} />;
}

export function AnalyzerSettingsPage() {
  const [params, setParams] = useSearchParams();
  const provider = params.get('provider') === 'otel' ? 'otel' : 'prometheus';
  const service = params.get('service') ?? '';
  const metric = params.get('metric') ?? '';
  const [metricDraft, setMetricDraft] = useState(metric);
  // Off at first: with nothing changed, the filter would hide every setting.
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [open, setOpen] = useState<string | null>(params.get('analyzer'));
  const [helpOpen, setHelpOpen] = useState(false);

  const settingsQuery = useQuery({
    queryKey: ['analyzer-settings', provider, service, metric],
    queryFn: () => api.analyzerSettings({ provider, service, metric }),
  });
  const servicesQuery = useQuery({ queryKey: ['services'], queryFn: api.services });
  // The chosen service's own metrics, so the Metric box offers real names.
  const metricsQuery = useQuery({ queryKey: ['service-metrics', service], queryFn: () => api.metrics(service), enabled: Boolean(service && !IS_PATTERN.test(service)) });
  const data = settingsQuery.data;
  const scoped = Boolean(service || metric);
  const serviceOptions = Array.from(new Set([...(data?.scopes ?? []).map((scope) => scope.service).filter((name): name is string => Boolean(name && !IS_PATTERN.test(name))), ...(servicesQuery.data ?? [])]));
  const metricOptions = Array.from(new Set([
    ...(data?.scopes ?? []).filter((scope) => !service || scope.service === service).map((scope) => scope.metric).filter((name): name is string => Boolean(name && !IS_PATTERN.test(name))),
    ...(service ? metricsQuery.data ?? [] : []),
  ]));
  const glance = data ? atAGlance(data) : null;

  const update = (next: Record<string, string>) => {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value) merged.set(key, value);
      else merged.delete(key);
    }
    setParams(merged, { replace: true });
  };

  return (
    <Stack spacing={3}>
      <PageHeader
        title="Analyzer settings in use"
        subtitle="What every analysis run uses right now, and which file each value comes from. This page only shows settings. To change one, edit the file it names."
        action={
          <Button variant="outlined" startIcon={<HelpOutlineRoundedIcon />} onClick={() => setHelpOpen(true)} sx={{ textTransform: 'none', fontWeight: 750 }}>
            How settings work
          </Button>
        }
      />
      <HowSettingsWork open={helpOpen} onClose={() => setHelpOpen(false)} />

      {settingsQuery.isLoading ? <CircularProgress size={24} /> : null}
      {settingsQuery.error ? <Alert severity="error">Couldn't read the analyzer settings: {(settingsQuery.error as Error).message}</Alert> : null}

      {data && glance ? (
        <>
          <Box component="section" aria-label="At a glance" sx={{ border: `1px solid ${ui.border}`, borderLeft: `4px solid var(--os-ink-brand, #0f766e)`, borderRadius: '10px', p: 2, bgcolor: ui.surface }}>
            <Typography sx={{ fontWeight: 850, fontSize: 15, mb: 0.5 }}>
              At a glance{scoped ? ` · ${[service, metric].filter(Boolean).join(' · ')}` : ''} · {data.provider_label}
            </Typography>
            <Typography sx={{ fontSize: 14 }}>{glance.customized}</Typography>
            <Typography sx={{ fontSize: 14 }}>{glance.runs}</Typography>
            <Typography sx={{ fontSize: 14, color: ui.muted }}>
              <strong>Labs are a sandbox:</strong> nothing tried there changes these settings. Each Lab's <em>Use these values for real</em> gives the snippet to paste.
            </Typography>
            {glance.problems ? <Typography sx={{ fontSize: 14, color: 'var(--os-ink-amber, #92400e)', fontWeight: 700, mt: 0.5 }}>{glance.problems}</Typography> : null}
          </Box>

          <Box component="ol" aria-label="Where a setting comes from" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(4, 1fr) 0.9fr' }, gap: 1.25, m: 0, p: 0, listStyle: 'none' }}>
            {data.layers.map((layer, index) => <LayerCard key={layer.key} layer={layer} index={index + 1} scoped={scoped} />)}
            <Box component="li" sx={{ border: `1.5px dashed ${ui.border}`, borderRadius: '10px', p: 1.5, color: ui.muted }}>
              <Typography sx={{ fontWeight: 800, fontSize: 14, color: ui.text }}>Labs</Typography>
              <Typography sx={{ fontSize: 13 }}>A sandbox. Runs never use what you try there.</Typography>
            </Box>
          </Box>

          {data.layers.flatMap((layer) => layer.errors ?? []).map((error) => (
            <Alert key={error.file} severity="warning">
              <strong>{error.file} is skipped</strong>, so none of its settings apply: {error.message}
            </Alert>
          ))}

          <Alert severity="info" icon={false} sx={{ bgcolor: 'var(--os-surface-alt)', color: ui.text, border: `1px solid ${ui.border}` }}>
            <strong>How a run picks analyzers: </strong>
            {selectionSentence(data.selection)}{' '}
            <Typography component="span" sx={{ color: ui.muted, fontSize: 13 }}>
              (selection_mode: {data.selection.mode}, min_score: {data.selection.min_score}, max_analyzers: {data.selection.max_analyzers}
              {data.selection.max_analyzers_source ? ` from ${sourceText(data.selection.max_analyzers_source)}` : ' in analyzers.yaml'})
            </Typography>
          </Alert>
        </>
      ) : null}

      <WorkspacePanel sx={{ p: 2.5 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', md: 'center' }} sx={{ mb: 2 }}>
          <TextField select size="small" label="Data source" value={provider} onChange={(event) => update({ provider: event.target.value === 'otel' ? 'otel' : '' })} sx={{ minWidth: 170 }}>
            <MenuItem value="prometheus">Prometheus</MenuItem>
            <MenuItem value="otel">OTLP</MenuItem>
          </TextField>
          <Autocomplete
            freeSolo
            size="small"
            options={serviceOptions}
            value={service || null}
            onChange={(_, value) => update({ service: value ?? '' })}
            renderInput={(input) => <TextField {...input} label="Service" placeholder="Every service (site-wide)" />}
            sx={{ minWidth: 260 }}
          />
          <Autocomplete
            freeSolo
            size="small"
            options={metricOptions}
            inputValue={metricDraft}
            onInputChange={(_, value) => setMetricDraft(value)}
            onChange={(_, value) => update({ metric: (value ?? '').trim() })}
            onBlur={() => { if (metricDraft.trim() !== metric) update({ metric: metricDraft.trim() }); }}
            renderInput={(input) => <TextField {...input} label="Metric" placeholder={service ? 'All metrics' : 'All metrics (pick a service for a list)'} />}
            sx={{ minWidth: 300 }}
          />
          <FormControlLabel control={<Checkbox checked={onlyChanged} onChange={(event) => setOnlyChanged(event.target.checked)} />} label="Only settings changed from default" />
        </Stack>
        {data && data.scopes.length && !scoped ? (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center" sx={{ mb: 2 }}>
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>Have their own settings:</Typography>
            {data.scopes.map((scope) => (
              <Chip
                key={scope.override_id}
                size="small"
                variant="outlined"
                label={[scope.service, scope.metric].filter(Boolean).join(' · ')}
                title={`${scope.file} → ${scope.override_id}: ${scope.reason}`}
                onClick={() => {
                  setMetricDraft(scope.metric && !IS_PATTERN.test(scope.metric) ? scope.metric : '');
                  setOnlyChanged(true);
                  update({ service: scope.service && !IS_PATTERN.test(scope.service) ? scope.service : '', metric: scope.metric && !IS_PATTERN.test(scope.metric) ? scope.metric : '' });
                }}
              />
            ))}
          </Stack>
        ) : null}
        {data && scoped && data.layers[3]?.applied?.length === 0 ? (
          <Alert severity="info" sx={{ mb: 2 }}>No team's file changes {[service, metric].filter(Boolean).join(' · ')}: it runs on the site-wide settings.</Alert>
        ) : null}

        {data ? (
          <Table size="small" aria-label="Analyzers">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: '32%' }}>Analyzer</TableCell>
                <TableCell sx={{ width: '32%' }}>Why</TableCell>
                <TableCell>Settings changed from default</TableCell>
                <TableCell padding="checkbox" />
              </TableRow>
            </TableHead>
            <TableBody>
              {RUN_ORDER.map((status) => {
                const group = data.analyzers.filter((analyzer) => analyzer.run.status === status);
                if (!group.length) return null;
                return (
                  <Fragment key={status}>
                    <TableRow>
                      <TableCell colSpan={4} sx={{ bgcolor: 'var(--os-surface-alt)', py: 0.75 }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <RunStatusChip status={status} />
                          <Typography component="h3" sx={{ fontSize: 13, fontWeight: 800 }}>{GROUP_TITLE[status]}</Typography>
                          <Typography sx={{ fontSize: 13, color: ui.muted }}>{group.length}</Typography>
                        </Stack>
                      </TableCell>
                    </TableRow>
                    {group.map((analyzer) => (
                      <AnalyzerRow
                        key={analyzer.analyzer_id}
                        analyzer={analyzer}
                        open={open === analyzer.analyzer_id || (scoped && onlyChanged && analyzer.changed_count > 0)}
                        onToggle={() => setOpen(open === analyzer.analyzer_id ? null : analyzer.analyzer_id)}
                        onlyChanged={onlyChanged}
                        onShowAll={() => setOnlyChanged(false)}
                        scoped={scoped}
                      />
                    ))}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        ) : null}
      </WorkspacePanel>
    </Stack>
  );
}

const GROUP_TITLE: Record<RunStatus, string> = {
  every_metric: 'Run on every metric',
  router: 'The router picks them when they suit a metric',
  only_if_chosen: "Don't run unless you choose them",
  cant_run: 'Turned on, but something they need is missing',
  turned_off: 'Switched off in your files',
};

function LayerCard({ layer, index, scoped }: { layer: SettingsLayer; index: number; scoped: boolean }) {
  const text: Record<SettingsLayer['key'], string> = {
    default: 'Shipped with Ops Signals.',
    site: 'Changes for every service.',
    provider: 'Changes for one kind of data source.',
    override: 'Changes for chosen services or metrics.',
  };
  let count: string;
  if (layer.key === 'default') count = `${layer.analyzers} analyzers`;
  else if (layer.key === 'override') count = scoped ? `${layer.applied?.length ?? 0} apply here` : `${layer.files} files · ${layer.overrides} overrides`;
  else if (layer.exists === false) count = 'No file';
  else count = `${layer.changed} ${layer.changed === 1 ? 'value' : 'values'} changed`;
  const highlight = layer.key === 'override' && (scoped ? Boolean(layer.applied?.length) : Boolean(layer.overrides));
  return (
    <Box component="li" sx={{ border: highlight ? `2px solid ${ui.blue}` : `1px solid ${ui.border}`, bgcolor: highlight ? 'var(--os-tint-blue, #eef2ff)' : 'transparent', borderRadius: '10px', p: 1.5 }}>
      <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{index} · {layer.title}</Typography>
      <Typography sx={{ fontSize: 13 }}>{text[layer.key]}</Typography>
      <Typography sx={{ fontFamily: 'monospace', fontSize: 12, color: ui.muted, mt: 0.75, wordBreak: 'break-all' }}>{layer.file}</Typography>
      <Typography sx={{ fontSize: 12, fontWeight: 800, mt: 0.5, color: highlight ? 'var(--os-ink-blue, #1d4ed8)' : ui.muted }}>{count}</Typography>
    </Box>
  );
}

function AnalyzerRow({ analyzer, open, onToggle, onlyChanged, onShowAll, scoped }: { analyzer: AnalyzerInUse; open: boolean; onToggle: () => void; onlyChanged: boolean; onShowAll: () => void; scoped: boolean }) {
  const [showIdle, setShowIdle] = useState(false);
  const shown = onlyChanged ? analyzer.settings.filter((setting) => setting.changed) : analyzer.settings;
  // Settings the analyzer reads (and keys it doesn't know, to catch typos) first; labels and
  // settings for another mode fold away.
  const settings = shown.filter((setting) => setting.use === 'used' || setting.use === 'unknown');
  const idle = shown.filter((setting) => setting.use === 'label' || setting.use === 'unused');
  const unknown = analyzer.settings.filter((setting) => setting.use === 'unknown').length;
  const overridden = analyzer.settings.filter((setting) => setting.source.layer === 'override').length;
  const lab = LAB_FOR[analyzer.analyzer_id];
  return (
    <Fragment>
      <TableRow hover onClick={onToggle} sx={{ cursor: 'pointer', '& > td': { borderBottom: open ? 'none' : undefined } }}>
        <TableCell>
          <Typography sx={{ fontWeight: 800, fontSize: 14 }}>
            {analyzer.display_name} <Box component="code" sx={{ fontSize: 12, color: ui.muted, ml: 0.5 }}>{analyzer.analyzer_id}</Box>
          </Typography>
          {analyzer.description ? <Typography sx={{ color: ui.muted, fontSize: 12.5 }}>{analyzer.description}</Typography> : null}
        </TableCell>
        <TableCell>
          {/* The status chip heads the group; the row says why. */}
          <Typography sx={{ color: ui.muted, fontSize: 12.5 }}>{analyzer.run.text}</Typography>
        </TableCell>
        <TableCell>
          {analyzer.changed_count === 0 ? (
            <Typography sx={{ color: ui.muted, fontSize: 13 }}>None</Typography>
          ) : (
            <Typography sx={{ fontSize: 13, fontWeight: 700, color: overridden ? 'var(--os-ink-blue, #1d4ed8)' : ui.text }}>
              {analyzer.changed_count} {analyzer.changed_count === 1 ? 'setting' : 'settings'}{overridden && scoped ? ', by a team’s file' : ''}
            </Typography>
          )}
          {unknown ? <Typography sx={{ fontSize: 12.5, fontWeight: 700, color: 'var(--os-ink-amber, #92400e)' }}>{unknown} not read: check spelling</Typography> : null}
        </TableCell>
        <TableCell padding="checkbox">
          <IconButton size="small" aria-label={open ? `Hide ${analyzer.display_name} settings` : `Show ${analyzer.display_name} settings`} aria-expanded={open}>
            <KeyboardArrowDownRoundedIcon sx={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 160ms ease' }} />
          </IconButton>
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow>
          <TableCell colSpan={4} sx={{ bgcolor: 'var(--os-surface-alt)', pt: 0 }}>
            {analyzer.run.note ? <Typography sx={{ fontSize: 13, color: ui.muted, pt: 1 }}>{analyzer.run.note}</Typography> : null}
            {analyzer.settings_note ? <Typography sx={{ fontSize: 13, fontWeight: 700, pt: 1 }}>{analyzer.settings_note}</Typography> : null}
            {settings.length || idle.length ? (
              <Table size="small" aria-label={`${analyzer.display_name} settings`} sx={{ bgcolor: ui.surface, border: `1px solid ${ui.border}`, borderRadius: '8px', mt: 1 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Setting</TableCell>
                    <TableCell>In use</TableCell>
                    <TableCell>Comes from</TableCell>
                    <TableCell>What it means</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {settings.map((setting) => <SettingRow key={setting.path} setting={setting} />)}
                  {idle.length ? (
                    <TableRow>
                      <TableCell colSpan={4} sx={{ py: 0.5 }}>
                        <Button size="small" onClick={() => setShowIdle(!showIdle)} aria-expanded={showIdle} sx={{ textTransform: 'none', fontWeight: 700 }}>
                          {showIdle ? 'Hide' : 'Show'} {idle.length} {idle.length === 1 ? 'setting' : 'settings'} the analyzer doesn't use
                        </Button>
                      </TableCell>
                    </TableRow>
                  ) : null}
                  {showIdle ? idle.map((setting) => <SettingRow key={setting.path} setting={setting} />) : null}
                </TableBody>
              </Table>
            ) : (
              <Typography sx={{ fontSize: 13, color: ui.muted, py: 1 }}>
                No settings changed from default.{' '}
                {onlyChanged && analyzer.settings.length ? (
                  <Button size="small" onClick={onShowAll} sx={{ textTransform: 'none', fontWeight: 700, p: 0, minWidth: 0, verticalAlign: 'baseline' }}>
                    Show all {analyzer.settings.length} {analyzer.settings.length === 1 ? 'setting' : 'settings'}
                  </Button>
                ) : null}
              </Typography>
            )}
            <Stack direction="row" spacing={1} sx={{ mt: 1.25, mb: 0.5 }}>
              {lab ? <Button size="small" variant="outlined" component={RouterLink} to={lab} sx={{ textTransform: 'none', fontWeight: 750 }}>Try it in the Lab</Button> : null}
            </Stack>
          </TableCell>
        </TableRow>
      ) : null}
    </Fragment>
  );
}

const USE_CHIP: Partial<Record<AnalyzerSetting['use'], { label: string; tone: keyof typeof TONES }>> = {
  label: { label: 'Label only', tone: 'grey' },
  unused: { label: 'Not used', tone: 'grey' },
  unknown: { label: 'Not read: check spelling', tone: 'amber' },
};

function SettingRow({ setting }: { setting: AnalyzerSetting }) {
  const chip = USE_CHIP[setting.use];
  const idle = setting.use === 'label' || setting.use === 'unused';
  return (
    <TableRow sx={idle ? { '& td': { color: ui.muted }, opacity: 0.85 } : undefined}>
      <TableCell>
        <Box component="code" sx={{ fontSize: 12.5 }}>{setting.path}</Box>
        {chip ? <Chip size="small" label={chip.label} sx={{ ml: 1, height: 20, fontSize: 11, fontWeight: 800, bgcolor: TONES[chip.tone].bg, color: TONES[chip.tone].fg }} /> : null}
      </TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>
        {setting.changed ? <Box component="span" sx={{ textDecoration: 'line-through', color: ui.muted, mr: 0.75, fontFamily: 'monospace' }}>{formatValue(setting.default)}</Box> : null}
        <Box component="span" sx={{ fontFamily: 'monospace', fontWeight: 800 }}>{formatValue(setting.value)}</Box>
      </TableCell>
      <TableCell>
        <Typography sx={{ fontSize: 13 }}>{sourceText(setting.source)}{setting.source.layer !== 'default' && !setting.changed ? ' (same as default)' : ''}</Typography>
        {setting.source.reason ? <Typography sx={{ fontSize: 12.5, color: ui.muted }}>"{setting.source.reason}"</Typography> : null}
      </TableCell>
      <TableCell>
        <Typography sx={{ fontSize: 13, color: ui.muted }}>{setting.meaning ?? ''}</Typography>
        {setting.use_note ? <Typography sx={{ fontSize: 12.5, fontWeight: 700, color: setting.use === 'unknown' ? 'var(--os-ink-amber, #92400e)' : ui.muted }}>{setting.use_note}</Typography> : null}
        {setting.per_service ? <Chip size="small" label="A team can change it" sx={{ mt: setting.meaning ? 0.5 : 0, height: 20, fontSize: 11 }} /> : null}
      </TableCell>
    </TableRow>
  );
}

/** "How settings work": the three questions people ask, and where a block goes in analyzers.yaml. */
export function HowSettingsWork({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth aria-labelledby="how-settings-work-title">
      <DialogTitle id="how-settings-work-title" sx={{ fontWeight: 850, pr: 6 }}>
        How analyzer settings work
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: 'absolute', right: 12, top: 12 }}>
          <CloseRoundedIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1.5} sx={{ fontSize: 14 }}>
          <Typography sx={{ fontSize: 14 }}>
            <strong>Which file do I edit?</strong> To change one team's services, add a file to <code>config/analyzer_overrides.d/</code>. To change every service, use <code>config/analyzers.yaml</code>. Don't edit the built-in defaults in <code>config/analyzer_registry.d/</code>.
          </Typography>
          <Typography sx={{ fontSize: 14 }}>
            <strong>I changed a Lab. Why didn't my findings change?</strong> Labs are a sandbox. Runs only read the files above. Each Lab's <em>Use these values for real</em> gives you the snippet to paste.
          </Typography>
          <Typography sx={{ fontSize: 14 }}>
            <strong>I changed a setting. Why did nothing happen?</strong> The analyzer may not run on that metric. Check <em>Does it run?</em> on this page. A team's file is read at the start of every run.
          </Typography>
          <Typography sx={{ fontSize: 14 }}>
            <strong>Where in analyzers.yaml?</strong> Under <code>analysis</code> → <code>analyzers</code>. List only the keys you change; every other setting keeps its value:
          </Typography>
          <Box component="pre" sx={{ m: 0, p: 2, borderRadius: 2, bgcolor: '#0f172a', color: '#e2e8f0', fontSize: 13 }}>
            {'analysis:\n  analyzers:\n    trend:                   # the analyzer id shown on this page\n      finding_rules:\n        min_slope_percent: 5   # only this changes'}
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 1.5, justifyContent: 'space-between' }}>
        <Button component="a" href={OVERRIDES_DOC_URL} target="_blank" rel="noopener noreferrer" endIcon={<OpenInNewRoundedIcon fontSize="small" />} sx={{ textTransform: 'none', fontWeight: 750 }}>
          Per-service settings guide
        </Button>
        <Button variant="outlined" onClick={onClose} sx={{ textTransform: 'none', fontWeight: 750 }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
