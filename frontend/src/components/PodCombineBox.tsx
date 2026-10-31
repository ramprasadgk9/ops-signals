import { Box, Button, MenuItem, Select, Stack, Typography } from '@mui/material';
import type { CombineChoice, PodSplit } from '../types';
import { COMBINE_ORDER, combineName } from '../utils/podCombine';

/** A pod choice: one of the ways to combine them, or `pod:<name>` for one pod alone. */
export type PodChoice = CombineChoice | `pod:${string}`;

export { combinedPhrase, combineName } from '../utils/podCombine';

function combineHelp(how: CombineChoice, label: string): string {
  if (how === 'sum') return 'The service total. For requests, bytes and connections.';
  if (how === 'avg') return `The typical ${label}. For CPU and memory use.`;
  if (how === 'max') return `The highest ${label} at each moment. For latency, errors and queues: one bad ${label} shows.`;
  return `The lowest ${label} at each moment. For health checks: one ${label} that is down shows.`;
}


/** The query a choice analyzes. */
export function podChoiceQuery(pods: PodSplit, choice: PodChoice): string {
  if (choice.startsWith('pod:')) return pods.one_queries[choice.slice(4)] ?? pods.queries[pods.suggested_combine];
  return pods.queries[choice as CombineChoice];
}

/** Values at each moment combined the way a choice does, for drawing the line Run Analysis will analyze. */
export function combineValues(values: number[], how: CombineChoice): number | null {
  if (!values.length) return null;
  if (how === 'sum') return values.reduce((total, value) => total + value, 0);
  if (how === 'avg') return values.reduce((total, value) => total + value, 0) / values.length;
  return how === 'max' ? Math.max(...values) : Math.min(...values);
}

/**
 * Shown when a preview returned one series per pod. Simple mode picks how Run Analysis reads them
 * (`onChoose`); Advanced mode keeps the user's query and offers buttons that replace it (`onUseQuery`).
 */
export function PodCombineBox({ pods, mode, choice, onChoose, onUseQuery }: {
  pods: PodSplit;
  mode: 'simple' | 'advanced';
  choice: PodChoice;
  onChoose: (choice: PodChoice) => void;
  onUseQuery: (query: string) => void;
}) {
  const { label, values, odd } = pods;
  const oneLabel = (name: string) => `Only ${name}`;
  const oddQuery = odd ? pods.one_queries[odd.value] : undefined;
  return (
    <Box data-testid="pod-combine-box" sx={{ border: '1px solid var(--os-tint-cyan-border)', bgcolor: 'var(--os-tint-cyan)', borderRadius: '8px', p: 1.6 }}>
      {mode === 'simple' ? (
        <>
          <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ md: 'center' }} spacing={1.2}>
            <Typography sx={{ fontWeight: 900, color: 'var(--os-text)' }}>{values.length} {label}s report this metric.</Typography>
            <Typography sx={{ color: 'var(--os-text)' }}>Analyze them as</Typography>
            <Select
              size="small"
              value={choice}
              onChange={(event) => onChoose(event.target.value as PodChoice)}
              inputProps={{ 'aria-label': `Analyze the ${label}s as` }}
              renderValue={(value) => (String(value).startsWith('pod:') ? oneLabel(String(value).slice(4)) : combineName(value as CombineChoice, label))}
              sx={{ minWidth: 230, bgcolor: 'var(--os-surface)', height: 40 }}
            >
              {COMBINE_ORDER.map((how) => (
                <MenuItem key={how} value={how} sx={{ display: 'block', whiteSpace: 'normal', maxWidth: 440 }}>
                  <Typography sx={{ fontWeight: 800, fontSize: 13 }}>{combineName(how, label)}{how === pods.suggested_combine ? ' (usual for this metric)' : ''}</Typography>
                  <Typography sx={{ fontSize: 12, color: 'var(--os-muted)' }}>{combineHelp(how, label)}</Typography>
                </MenuItem>
              ))}
              {values.filter((name) => pods.one_queries[name]).map((name) => (
                <MenuItem key={name} value={`pod:${name}`}>
                  <Typography sx={{ fontSize: 13, fontWeight: 700 }}>
                    {oneLabel(name)}{name === odd?.value ? <Box component="span" sx={{ ml: 1, color: 'var(--os-ink-red)', fontSize: 12 }}>behaving differently</Box> : null}
                  </Typography>
                </MenuItem>
              ))}
            </Select>
          </Stack>
          <Typography sx={{ mt: 0.8, fontSize: 12.5, color: 'var(--os-text-2)' }}>
            {choice.startsWith('pod:')
              ? `Run Analysis reads ${choice.slice(4)} alone.`
              : `${combineHelp(choice as CombineChoice, label)} ${choice === pods.suggested_combine ? 'Scheduled runs read this metric the same way.' : ''}`}
          </Typography>
        </>
      ) : (
        <>
          <Typography sx={{ fontWeight: 900, color: 'var(--os-text)' }}>This query returns {values.length} lines, one per {label}. Analysis needs one line.</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            {COMBINE_ORDER.map((how) => (
              <Button key={how} size="small" variant="outlined" onClick={() => onUseQuery(pods.queries[how])} sx={{ textTransform: 'none', fontWeight: 800, color: 'var(--os-ink-brand)', borderColor: 'var(--os-tint-cyan-border)', bgcolor: 'var(--os-surface)' }}>
                Combine: {combineName(how, label).toLowerCase()}
              </Button>
            ))}
          </Stack>
          <Typography sx={{ mt: 0.8, fontSize: 12, color: 'var(--os-text-2)' }}>
            Each button puts a new query in the box; you can edit it before running. The usual way for this metric is {combineName(pods.suggested_combine, label).toLowerCase()}.
          </Typography>
        </>
      )}
      {odd ? (
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={1.2} sx={{ mt: 1.2, p: 1.2, bgcolor: 'var(--os-surface)', borderRadius: '6px', borderLeft: '4px solid #ff4d57' }}>
          <Typography sx={{ fontSize: 13, color: 'var(--os-text)' }}>{odd.message}</Typography>
          {oddQuery ? (
            <Button
              size="small"
              variant="outlined"
              onClick={() => (mode === 'simple' ? onChoose(`pod:${odd.value}`) : onUseQuery(oddQuery))}
              sx={{ textTransform: 'none', fontWeight: 800, color: 'var(--os-ink-brand)', borderColor: 'var(--os-tint-cyan-border)', whiteSpace: 'nowrap', flexShrink: 0 }}
            >
              Analyze only {odd.value}
            </Button>
          ) : null}
        </Stack>
      ) : null}
    </Box>
  );
}
