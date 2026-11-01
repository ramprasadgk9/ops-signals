import { useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Autocomplete, Box, Button, Chip, CircularProgress, Radio, Stack, TextField, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/queries';
import { WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import {
  formatValue,
  labChanges,
  overrideFileName,
  overrideSnippet,
  perServiceProblems,
  siteSnippet,
  type AnalyzerInUse,
} from '../../utils/analyzerSettings';
import { downloadText, type LabPassFailStatus } from './labConfig';
import { useAnalyzerInUse, type InUseComparison } from './labSettings';

type Props = {
  analyzerId: string;
  labName: string;
  /** The Lab's values in config/analyzers.yaml's shape, e.g. { implementation, finding_rules }. */
  values: Record<string, unknown>;
  passFailStatus: LabPassFailStatus;
  passFailReason: string;
  productionNote: string;
  /** Whether the Lab's last run made a finding; null before a run. */
  yourFound?: boolean | null;
  comparison?: InUseComparison;
};

type Target = 'team' | 'site';

function statusColor(status: LabPassFailStatus) {
  if (status === 'pass') return 'success';
  if (status === 'fail') return 'error';
  return 'default';
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

/** Why a correct paste could still change nothing: the analyzer doesn't run on its own. */
function wontRunText(analyzer: AnalyzerInUse): string | null {
  const name = analyzer.display_name;
  if (analyzer.run.status === 'only_if_chosen') {
    return `${name} doesn't run on its own in your setup, so these settings only matter once it's chosen: set selection_mode: all in config/analyzers.yaml, or list ${analyzer.analyzer_id} in selected_analyzers with selection_mode: manual_override.`;
  }
  if (analyzer.run.status === 'turned_off') return `${name} is turned off: ${analyzer.run.text} Turn it on with enabled: true in config/analyzers.yaml.`;
  if (analyzer.run.status === 'cant_run') return `${name} can't run: ${analyzer.run.text}`;
  return null;
}

/** "Use these values for real": only what the Lab changed from the values runs use, as a snippet for
 * a team's override file or for config/analyzers.yaml, already nested where the file reads it. */
export function AnalyzerLabConfigPanel({ analyzerId, labName, values, passFailStatus, passFailReason, productionNote, yourFound = null, comparison }: Props) {
  const { analyzer, isLoading, error } = useAnalyzerInUse(analyzerId);
  const servicesQuery = useQuery({ queryKey: ['services'], queryFn: api.services });
  const [target, setTarget] = useState<Target>('team');
  const [service, setService] = useState('');
  const [metric, setMetric] = useState('');
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  const changes = useMemo(() => labChanges(analyzer, values), [analyzer, values]);
  const teamProblems = perServiceProblems(changes);
  const effectiveTarget: Target = teamProblems.length ? 'site' : target;
  const snippet = effectiveTarget === 'team' ? overrideSnippet(analyzerId, changes, service, metric, reason) : siteSnippet(analyzerId, changes);
  const filename = effectiveTarget === 'team' ? overrideFileName(service, metric) : `${analyzerId}-analyzers.yaml`;
  const warning = analyzer ? wontRunText(analyzer) : null;

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack spacing={2} component="section" aria-label="Use these values for real">
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
          <Box>
            <Typography component="h2" sx={{ fontWeight: 900, fontSize: 20 }}>Use these values for real</Typography>
            <Typography sx={{ color: ui.muted }}>
              Copy the snippet into the file below. The next analysis run picks it up; nothing in {labName} is saved.
            </Typography>
          </Box>
          <Chip label={passFailStatus.toUpperCase()} color={statusColor(passFailStatus)} sx={{ fontWeight: 900, alignSelf: { xs: 'flex-start', md: 'center' } }} />
        </Stack>

        <Alert severity={passFailStatus === 'fail' ? 'warning' : 'info'}>{passFailReason}</Alert>
        {yourFound !== null && comparison ? (
          <Alert severity="info" icon={false} sx={{ border: `1px solid ${ui.border}`, bgcolor: 'transparent', color: ui.text }}>
            With your values: <strong>{yourFound ? 'a finding' : 'no finding'}</strong>.{' '}
            {comparison.running ? (
              <><CircularProgress size={12} sx={{ mx: 0.5 }} /> Running with the values runs use now…</>
            ) : comparison.error ? (
              <Box component="span" sx={{ color: ui.muted }}>Couldn't run with the values runs use now: {comparison.error}</Box>
            ) : comparison.found !== null ? (
              <>With the values runs use now: <strong>{comparison.found ? 'a finding' : 'no finding'}</strong>.</>
            ) : changes.length === 0 ? (
              <Box component="span" sx={{ color: ui.muted }}>These are the values runs use now.</Box>
            ) : null}
          </Alert>
        ) : null}
        <Alert severity="success">
          <strong>Use this in production when:</strong> {productionNote}
        </Alert>

        {isLoading ? <CircularProgress size={20} /> : null}
        {error ? <Alert severity="error">Couldn't read the settings in use, so there's no snippet: {error.message}</Alert> : null}

        {analyzer && changes.length === 0 ? (
          <Typography sx={{ color: ui.muted }}>Your values are the same as the values runs use now. Change a setting above to get a snippet.</Typography>
        ) : null}

        {analyzer && changes.length > 0 ? (
          <>
            <Box sx={{ border: `1px solid ${ui.border}`, borderRadius: 2, p: 1.5 }}>
              <Typography sx={{ fontWeight: 850, mb: 0.75 }}>
                You changed {changes.length} {changes.length === 1 ? 'setting' : 'settings'}
                <Typography component="span" sx={{ color: ui.muted, fontWeight: 500, fontSize: 13 }}> · only these go in the snippet; every other setting keeps its value</Typography>
              </Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {changes.map((change) => (
                  <Box key={change.path} component="code" sx={{ fontSize: 12.5, bgcolor: 'var(--os-surface-alt)', borderRadius: '4px', px: 0.75, py: 0.25 }}>
                    {change.path} <Box component="span" sx={{ textDecoration: 'line-through', color: ui.muted }}>{formatValue(change.from)}</Box> → <strong>{formatValue(change.to)}</strong>
                  </Box>
                ))}
              </Stack>
            </Box>

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 1.5 }} role="radiogroup" aria-label="Where to use these values">
              <TargetCard
                selected={effectiveTarget === 'team'}
                disabled={teamProblems.length > 0}
                onSelect={() => setTarget('team')}
                title="For one team's services"
                badge="Recommended"
                text="Other teams keep their settings. One team's right threshold is often another's noise."
              >
                {teamProblems.length ? (
                  <Typography sx={{ fontSize: 13, color: ui.muted }}>Not possible for these values: {teamProblems.join('; ')}.</Typography>
                ) : (
                  <Stack spacing={1}>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                      <Autocomplete
                        freeSolo
                        size="small"
                        options={servicesQuery.data ?? []}
                        inputValue={service}
                        onInputChange={(_, value) => setService(value)}
                        renderInput={(input) => <TextField {...input} label="Service" placeholder="payments-api" />}
                        sx={{ flex: 1 }}
                      />
                      <TextField size="small" label="Metric (optional)" value={metric} onChange={(event) => setMetric(event.target.value)} sx={{ flex: 1 }} />
                    </Stack>
                    <TextField size="small" label="Why these services need it" value={reason} onChange={(event) => setReason(event.target.value)} helperText="Shown on their findings next to the setting" />
                    <Typography sx={{ fontSize: 12.5, color: ui.muted }}>New file: <code>config/analyzer_overrides.d/{overrideFileName(service, metric)}</code></Typography>
                  </Stack>
                )}
              </TargetCard>
              <TargetCard
                selected={effectiveTarget === 'site'}
                onSelect={() => setTarget('site')}
                title="For every service"
                text="Changes the site-wide value in config/analyzers.yaml."
              >
                <Typography sx={{ fontSize: 12.5, color: ui.muted }}>
                  Paste under <code>analysis:</code> → <code>analyzers:</code>. If the file already has a <code>{analyzerId}:</code> block, add these keys to it.
                </Typography>
              </TargetCard>
            </Box>

            <Box component="pre" aria-label="Snippet" sx={{ m: 0, p: 2, borderRadius: 2, bgcolor: '#0f172a', color: '#e2e8f0', overflow: 'auto', fontSize: 13 }}>
              {snippet}
            </Box>

            {warning ? <Alert severity="warning">{warning}</Alert> : null}

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
              <Button startIcon={<ContentCopyRoundedIcon />} variant="contained" onClick={() => copyText(snippet).then(() => setMessage('Copied the snippet.'), () => setMessage("Couldn't copy: select the snippet and copy it."))} sx={{ textTransform: 'none', fontWeight: 800 }}>
                Copy snippet
              </Button>
              <Button startIcon={<DownloadRoundedIcon />} variant="outlined" onClick={() => downloadText(filename, snippet)} sx={{ textTransform: 'none', fontWeight: 800 }}>
                Download {filename}
              </Button>
              <Button
                component={RouterLink}
                to={effectiveTarget === 'team' && service ? `/analyzer-settings?service=${encodeURIComponent(service)}${metric ? `&metric=${encodeURIComponent(metric)}` : ''}` : `/analyzer-settings?analyzer=${analyzerId}`}
                sx={{ textTransform: 'none', fontWeight: 750 }}
              >
                Check afterwards on Settings in use →
              </Button>
            </Stack>
          </>
        ) : null}

        {message ? <Alert severity="success" onClose={() => setMessage(null)}>{message}</Alert> : null}
      </Stack>
    </WorkspacePanel>
  );
}

function TargetCard({ selected, disabled = false, onSelect, title, badge, text, children }: { selected: boolean; disabled?: boolean; onSelect: () => void; title: string; badge?: string; text: string; children: React.ReactNode }) {
  return (
    <Box
      onClick={disabled ? undefined : onSelect}
      sx={{
        border: selected ? `2px solid ${ui.blue}` : `1px solid ${ui.border}`,
        bgcolor: selected ? 'var(--os-tint-blue, #eef2ff)' : 'transparent',
        borderRadius: '10px',
        p: 1.5,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.7 : 1,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={0.5}>
        <Radio size="small" checked={selected} disabled={disabled} onChange={onSelect} inputProps={{ 'aria-label': title }} sx={{ p: 0.5 }} />
        <Typography sx={{ fontWeight: 850 }}>{title}</Typography>
        {badge ? <Chip size="small" label={badge} sx={{ height: 20, fontSize: 11, fontWeight: 800, color: 'var(--os-ink-blue, #1d4ed8)', bgcolor: 'var(--os-tint-blue, #eef2ff)' }} /> : null}
      </Stack>
      <Typography sx={{ fontSize: 13, color: ui.muted, my: 0.75 }}>{text}</Typography>
      <Box onClick={(event) => event.stopPropagation()}>{children}</Box>
    </Box>
  );
}
