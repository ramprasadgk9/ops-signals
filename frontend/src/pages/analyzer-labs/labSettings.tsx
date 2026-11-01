import { useCallback, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Box, Button, Stack, Tooltip, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/queries';
import { ui } from '../../standalone/theme';
import { formatValue, settingAt, sourceText, type AnalyzerInUse } from '../../utils/analyzerSettings';
import { RunStatusChip } from '../AnalyzerSettingsPage';

/** The site-wide settings Prometheus runs use for this analyzer: the same query (and cache) as the
 * Settings in use page's default view. */
export function useAnalyzerInUse(analyzerId: string) {
  const query = useQuery({
    queryKey: ['analyzer-settings', 'prometheus', '', ''],
    queryFn: () => api.analyzerSettings({ provider: 'prometheus' }),
    staleTime: 60_000,
  });
  return { analyzer: query.data?.analyzers?.find((item) => item.analyzer_id === analyzerId), isLoading: query.isLoading, error: query.error as Error | null };
}

/** At the top of every Lab: nothing here changes real runs, and what runs use now. */
export function LabSandboxBanner({ analyzerId, paths }: { analyzerId: string; paths: string[] }) {
  const { analyzer, error } = useAnalyzerInUse(analyzerId);
  const shown = paths.map((path) => settingAt(analyzer, path)).filter((setting) => setting !== undefined);
  const allDefault = shown.every((setting) => setting.source.layer === 'default' || !setting.changed);
  return (
    <Box role="note" aria-label="This Lab is a sandbox" sx={{ border: '1px solid #fcd34d', bgcolor: 'var(--os-tint-amber, #fffbeb)', borderRadius: '10px', p: 2 }}>
      <Typography sx={{ fontWeight: 850, color: 'var(--os-ink-amber, #92400e)', fontSize: 15 }}>
        This is a sandbox. Nothing you try here changes real analysis runs.
      </Typography>
      <Typography sx={{ fontSize: 14, mt: 0.5 }}>
        Runs use the settings in your config files. When a value here works better, <strong>Use these values for real</strong> at the bottom of this page gives you the snippet to paste.
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'flex-start', md: 'center' }} justifyContent="space-between" sx={{ mt: 1 }}>
        {analyzer ? (
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography sx={{ fontSize: 14, fontWeight: 800 }}>Runs use now:</Typography>
            {shown.map((setting) => (
              <Tooltip key={setting.path} title={`${setting.path} · ${sourceText(setting.source)}`} arrow>
                <Box component="code" sx={{ fontSize: 12.5, bgcolor: ui.surface, border: `1px solid ${ui.border}`, borderRadius: '4px', px: 0.75 }}>
                  {setting.path.split('.').pop()} {formatValue(setting.value)}
                </Box>
              </Tooltip>
            ))}
            <Typography sx={{ fontSize: 13, color: ui.muted }}>{allDefault ? 'built-in defaults' : 'from your config files'}, every service</Typography>
            {analyzer.run.status !== 'every_metric' && analyzer.run.status !== 'router' ? <RunStatusChip status={analyzer.run.status} /> : null}
          </Stack>
        ) : (
          <Typography sx={{ fontSize: 13, color: ui.muted }}>{error ? `Couldn't read the settings in use: ${error.message}` : 'Reading the settings in use…'}</Typography>
        )}
        <Button component={RouterLink} to={`/analyzer-settings?analyzer=${analyzerId}`} size="small" sx={{ textTransform: 'none', fontWeight: 750, flexShrink: 0 }}>
          See all settings in use →
        </Button>
      </Stack>
    </Box>
  );
}

/** Helper text under a Lab field: the value runs use, and Reset when the Lab's value differs. */
export function RunsUse({ analyzer, path, value, onReset }: { analyzer: AnalyzerInUse | undefined; path: string; value: unknown; onReset?: (value: unknown) => void }) {
  const setting = settingAt(analyzer, path);
  if (!setting) return null;
  const inUse = formatValue(setting.value);
  const same = typeof setting.value === 'number' || typeof value === 'number' ? Number(value) === Number(setting.value) : formatValue(value) === inUse;
  const where = setting.source.layer === 'default' || !setting.changed ? ' (default)' : '';
  if (same) return <Box component="span">Runs use {inUse}{where}</Box>;
  return (
    <Box component="span" sx={{ color: 'var(--os-ink-blue, #1d4ed8)', fontWeight: 700 }}>
      Changed · runs use {inUse}{where}
      {onReset ? (
        <Button size="small" onClick={() => onReset(setting.value)} sx={{ minWidth: 0, p: 0, ml: 0.75, textTransform: 'none', fontSize: 'inherit', verticalAlign: 'baseline' }}>
          Reset
        </Button>
      ) : null}
    </Box>
  );
}

export type InUseComparison = { running: boolean; found: boolean | null; error: string | null };

/** Runs the Lab's same data again without its overrides, so with the settings runs use now, to say
 * what today's settings would have found. The Lab run is a preview (nothing is saved). */
export function useInUseComparison() {
  const [state, setState] = useState<InUseComparison>({ running: false, found: null, error: null });
  const latest = useRef(0);
  const compare = useCallback((form: FormData) => {
    const id = ++latest.current;
    const copy = new FormData();
    form.forEach((value, key) => { if (key !== 'analyzer_overrides') copy.append(key, value); });
    setState({ running: true, found: null, error: null });
    api.runCsvValidation(copy).then(
      (result) => { if (id === latest.current) setState({ running: false, found: result.findings.length > 0, error: null }); },
      (err: unknown) => { if (id === latest.current) setState({ running: false, found: null, error: err instanceof Error ? err.message : 'Run failed' }); },
    );
  }, []);
  const reset = useCallback(() => { latest.current += 1; setState({ running: false, found: null, error: null }); }, []);
  return { comparison: state, compare, reset };
}
