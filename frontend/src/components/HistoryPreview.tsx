import { useState } from 'react';
import { Alert, Autocomplete, Box, Button, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import HistoryRoundedIcon from '@mui/icons-material/HistoryRounded';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/queries';
import { formatDateTime, ui } from '../standalone/theme';
import type { BehaviorDefinitionDraft, HistoryPreview as HistoryPreviewResult, HistoryRun } from '../types';

// Passes the palette checks (lightness band, chroma, contrast) on both the light and dark surface.
const LINE = '#0d9488';
const LOOK_BACKS = [
  { hours: 24, label: 'Last 24 hours' },
  { hours: 72, label: 'Last 3 days' },
  { hours: 168, label: 'Last 7 days' },
];

const time = (value: string | null | undefined) => (value ? Date.parse(value) : Number.NaN);

/**
 * Chart rows with a break wherever no data was stored: the points are averages per slice of the
 * look-back, and only slices with data come back, so a straight line across a gap would draw
 * values that never existed.
 */
export function withGaps(points: Array<[string, number]>, since: number, until: number, buckets = 240): Array<{ at: number; value: number | null }> {
  const slice = (until - since) / buckets;
  const rows: Array<{ at: number; value: number | null }> = [];
  points.forEach(([at, value], index) => {
    const now = time(at);
    if (index > 0 && now - rows[rows.length - 1].at > slice * 1.5) rows.push({ at: rows[rows.length - 1].at + slice, value: null });
    rows.push({ at: now, value });
  });
  return rows;
}

/** In plain words, why one run did not match. */
export function runReason(run: HistoryRun): string {
  if (run.matched) return 'Matched';
  // No signal means its analyzers saw no change - or did not run on that metric at all.
  if (run.missing_inputs.length) return `No signal for ${run.missing_inputs.join(', ')}: no change, or its analyzers did not run`;
  return run.blocked_by[0] ?? 'Did not match';
}

function Verdict({ result, lookBack }: { result: HistoryPreviewResult; lookBack: string }) {
  if (result.verdict === 'fired') {
    return (
      <Alert severity="success">
        Would have fired in {result.runs_matched} of {result.runs_checked} runs of {result.service} ({lookBack.toLowerCase()}).
      </Alert>
    );
  }
  if (result.verdict === 'never') {
    return (
      <Alert severity="warning">
        Never matched in {result.runs_checked} runs of {result.service}. Most often stopped by: <strong>{result.reason}</strong>.
      </Alert>
    );
  }
  if (result.verdict === 'cant_check') {
    return (
      <Alert severity="info">
        Can't tell yet: {result.reason} in any run. Either that metric never changed, or its analyzers did not run on it — if it
        did change, list another analyzer for the input, route one to that metric, or pick another metric.
      </Alert>
    );
  }
  return <Alert severity="info">No analysis runs of {result.service} in the {lookBack.toLowerCase()}.</Alert>;
}

/** One small line chart per input metric (different scales, so never one shared axis), runs that matched shaded. */
function MetricCharts({ result }: { result: HistoryPreviewResult }) {
  const domain: [number, number] = [time(result.since), Date.now()];
  const matched = result.runs.filter((run) => run.matched && run.start && run.end);
  return (
    <Stack spacing={1.5}>
      {result.series.map((series) => (
        <Box key={series.alias}>
          <Typography sx={{ fontSize: 13, fontWeight: 800 }}>
            {series.alias} · <Box component="span" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>{series.metric_name}</Box>
          </Typography>
          {series.points.length ? (
            <Box sx={{ height: 96 }} role="img" aria-label={`${series.metric_name} over the look-back${matched.length ? ', with the runs that matched shaded' : ''}`}>
              <ResponsiveContainer>
                <LineChart data={withGaps(series.points, domain[0], domain[1])} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="at" type="number" domain={domain} scale="time" tickFormatter={(value: number) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} tick={{ fontSize: 11, fill: 'var(--os-muted)' }} stroke="var(--os-border)" minTickGap={48} />
                  <YAxis width={48} tick={{ fontSize: 11, fill: 'var(--os-muted)' }} stroke="var(--os-border)" tickCount={3} />
                  {matched.map((run) => (
                    <ReferenceArea key={run.analysis_run_id} x1={time(run.start)} x2={time(run.end)} fill={LINE} fillOpacity={0.18} ifOverflow="hidden" />
                  ))}
                  <Tooltip
                    labelFormatter={(value: number) => formatDateTime(new Date(value).toISOString())}
                    formatter={(value: number) => [value.toLocaleString(undefined, { maximumFractionDigits: 3 }), series.metric_name]}
                    contentStyle={{ background: 'var(--os-surface)', border: '1px solid var(--os-border)', color: 'var(--os-text)', fontSize: 12 }}
                  />
                  <Line type="linear" dataKey="value" stroke={LINE} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </Box>
          ) : (
            <Typography sx={{ fontSize: 13, color: ui.muted }}>No stored points for this metric on {result.service} in the look-back.</Typography>
          )}
        </Box>
      ))}
      {matched.length ? <Typography sx={{ fontSize: 12, color: ui.muted }}>Shaded: when the runs that matched saw the change. Gaps: no data stored.</Typography> : null}
      {result.series_truncated ? <Typography sx={{ fontSize: 12, color: ui.muted }}>Lines show the newest 20,000 stored points only.</Typography> : null}
    </Stack>
  );
}

/**
 * "See it on my data": what this draft would have said on each recent analysis run of one service,
 * and why it did or did not match. Nothing is saved.
 */
export function HistoryPreview({ draft, blockedReason }: {
  draft: BehaviorDefinitionDraft;
  /** Why the preview can't run yet; the builder already shows it next to Test Pattern. */
  blockedReason?: string | null;
}) {
  // Services of recent runs; any other service can be typed in.
  const servicesQuery = useQuery({ queryKey: ['behavior-history-services'], queryFn: api.behaviorHistoryServices, retry: false });
  const [service, setService] = useState('');
  const [hours, setHours] = useState(168);
  const previewMutation = useMutation({ mutationFn: () => api.behaviorHistoryPreview(draft, service, hours) });
  const lookBack = LOOK_BACKS.find((item) => item.hours === hours)?.label ?? `${hours} hours`;
  const result = previewMutation.data;

  return (
    <Box component="section" aria-labelledby="history-preview-heading" sx={{ mt: 3, pt: 2.5, borderTop: `1px solid ${ui.border}` }}>
      <Typography id="history-preview-heading" sx={{ fontWeight: 900, fontSize: 16 }}>See it on my data</Typography>
      <Typography sx={{ color: ui.muted, fontSize: 13, mb: 1.5 }}>
        Tries this pattern on every recent analysis run of one service, as the real check would have, and says why each run did or did not match.
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
        <Autocomplete
          freeSolo
          options={servicesQuery.data ?? []}
          inputValue={service}
          onInputChange={(_event, value) => setService(value.trim())}
          sx={{ minWidth: 240 }}
          renderInput={(params) => <TextField {...params} size="small" label="Service" />}
        />
        <TextField select size="small" label="Look back" value={hours} onChange={(event) => setHours(Number(event.target.value))} sx={{ minWidth: 160 }}>
          {LOOK_BACKS.map((item) => <MenuItem key={item.hours} value={item.hours}>{item.label}</MenuItem>)}
        </TextField>
        <Button
          startIcon={<HistoryRoundedIcon />}
          variant="outlined"
          onClick={() => previewMutation.mutate()}
          disabled={!service || Boolean(blockedReason) || previewMutation.isPending}
          title={blockedReason ?? undefined}
          sx={{ textTransform: 'none', fontWeight: 850 }}
        >
          {previewMutation.isPending ? 'Checking…' : 'See it on my data'}
        </Button>
      </Stack>
      {previewMutation.isError ? (
        <Alert severity="error" sx={{ mt: 2 }}>{previewMutation.error instanceof Error ? previewMutation.error.message : 'The preview failed.'}</Alert>
      ) : null}

      {result ? (
        <Stack spacing={2} sx={{ mt: 2 }}>
          <Verdict result={result} lookBack={lookBack} />
          {result.runs_checked ? (
            <>
              <Box>
                <Typography sx={{ fontSize: 13, fontWeight: 800, mb: 0.5 }}>Each input, on its own</Typography>
                {result.inputs.map((input) => (
                  <Typography key={input.alias} sx={{ fontSize: 13 }}>
                    {input.alias} (<Box component="span" sx={{ fontFamily: 'monospace' }}>{input.metric_name}</Box>): signals in {input.runs_with_signals} of {result.runs_checked} runs
                  </Typography>
                ))}
                {result.runs_judged ? (
                  result.conditions.map((condition) => (
                    <Typography key={`${condition.group}-${condition.fact}`} sx={{ fontSize: 13 }}>
                      {condition.fact} {condition.operator} {String(condition.value)}: passed in {condition.passed_runs} of {result.runs_judged} runs it could be checked in
                    </Typography>
                  ))
                ) : null}
              </Box>
              <MetricCharts result={result} />
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small" aria-label="Runs checked">
                  <TableHead><TableRow><TableCell>Run</TableCell><TableCell>When</TableCell><TableCell>Result</TableCell></TableRow></TableHead>
                  <TableBody>
                    {result.runs.slice(0, 20).map((run) => (
                      <TableRow key={run.analysis_run_id}>
                        <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{run.analysis_run_id.slice(0, 12)}</TableCell>
                        <TableCell>{formatDateTime(run.at)}</TableCell>
                        <TableCell sx={{ color: run.matched ? ui.green : 'inherit', fontWeight: run.matched ? 800 : 400 }}>{runReason(run)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {result.runs.length > 20 ? <Typography sx={{ fontSize: 12, color: ui.muted, mt: 0.5 }}>Newest 20 of {result.runs.length} runs shown.</Typography> : null}
              </Box>
            </>
          ) : null}
        </Stack>
      ) : null}
    </Box>
  );
}
