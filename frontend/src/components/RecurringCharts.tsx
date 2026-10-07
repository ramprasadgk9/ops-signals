import React from 'react';
import { Box, Link, Stack, Tooltip, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { formatDateTime, relativeTime, ui } from '../standalone/theme';
import type { RecurringProblem } from '../types';

type RecurringCase = RecurringProblem['cases'][number];

// Status job, not identity: each dot is a case's state. Colours from the reserved status palette
// (good / warning) plus a neutral; never colour alone - the legend names each, the tooltip says it
// in words, and the "Show N cases" list is the table view. Yellow and grey sit below 3:1 on white,
// which that labelling covers.
export const OCCURRENCE_STATES = {
  open: { label: 'Still open', color: '#fab219' },
  verified: { label: 'Fixed, cause verified', color: '#0ca30c' },
  unverified: { label: 'Fixed, cause not verified', color: '#94a3b8' },
} as const;
type OccurrenceState = keyof typeof OCCURRENCE_STATES;

const RESOLVED = new Set(['resolved', 'closed', 'mitigated']);
const BAR_COLOR = ui.blue;
const DOT = 10;
const HIT = 24;
const DAY_MS = 86_400_000;

export function occurrenceState(item: RecurringCase): OccurrenceState {
  if (!RESOLVED.has(item.case_status)) return 'open';
  return item.rca_verified ? 'verified' : 'unverified';
}

/** Problems ranked by how often they happened: one bar each, count at the tip. Only worth drawing
 * for two or more problems; clicking a row jumps to that problem's card. */
export function ProblemRanking({ problems, days, onSelect }: { problems: RecurringProblem[]; days: number; onSelect: (centralCaseId: number) => void }) {
  if (problems.length < 2) return null;
  const most = Math.max(...problems.map((problem) => problem.occurrences));
  return (
    <Box sx={{ mb: 2 }} data-testid="problem-ranking">
      <Typography sx={{ fontSize: 12, color: ui.muted, mb: 0.75 }}>Times each problem happened in the last {days} days</Typography>
      <Stack spacing={0.75}>
        {problems.map((problem) => (
          <Tooltip
            key={problem.central_case_id}
            describeChild
            followCursor
            title={`${problem.occurrences} times · ${problem.services.join(', ')}${problem.last_seen ? ` · last ${relativeTime(problem.last_seen)}` : ''}${problem.open_cases ? ` · ${problem.open_cases} still open` : ''}`}
          >
            <Box
              component="button"
              type="button"
              onClick={() => onSelect(problem.central_case_id)}
              sx={{
                // Name beside its bar on wide screens, above it on a phone so names aren't cut short.
                display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(120px, 34%) 1fr' }, alignItems: 'center', columnGap: 1.5, rowGap: 0.25,
                width: '100%', minHeight: HIT, p: 0, border: 0, background: 'none', cursor: 'pointer', textAlign: 'left',
                '&:hover .bar, &:focus-visible .bar': { opacity: 0.85 },
                '&:focus-visible': { outline: `2px solid ${BAR_COLOR}`, outlineOffset: 2, borderRadius: '4px' },
              }}
            >
              <Typography sx={{ fontSize: 13, color: ui.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: { xs: 'normal', sm: 'nowrap' } }}>{problem.name}</Typography>
              <Stack direction="row" alignItems="center" spacing={0.75} sx={{ minWidth: 0 }}>
                <Box
                  className="bar"
                  sx={{ height: 14, width: `${(problem.occurrences / most) * 100}%`, minWidth: 4, bgcolor: BAR_COLOR, borderRadius: '0 4px 4px 0', flexShrink: 1 }}
                />
                <Typography sx={{ fontSize: 13, fontWeight: 700, color: ui.text, flexShrink: 0 }}>{problem.occurrences}</Typography>
              </Stack>
            </Box>
          </Tooltip>
        ))}
      </Stack>
    </Box>
  );
}

/** One dot per occurrence across the window, coloured by state, so a problem's rhythm - steady,
 * speeding up, still open - reads at a glance. Dots too close to tell apart stack upwards. Each
 * dot is a link to its case, with the details in its tooltip. */
export function OccurrenceTimeline({ cases, days, now = Date.now() }: { cases: RecurringCase[]; days: number; now?: number }) {
  const start = now - days * DAY_MS;
  const [track, width] = useWidth();
  // Dots closer than a dot's width (plus its ring) stack upwards; measured in pixels, so a phone
  // stacks what a wide screen can lay side by side.
  const minGap = width ? (DOT + 6) / width : 0.02;
  const placed = placeDots(
    cases.filter((item) => item.created_at).map((item) => ({ item, x: clamp((new Date(item.created_at!).getTime() - start) / (now - start)) })),
    minGap,
  );
  const rows = Math.max(1, ...placed.map((dot) => dot.row + 1));
  const height = rows * (DOT + 4) + HIT - DOT;
  const states = [...new Set(cases.map(occurrenceState))];

  return (
    <Box sx={{ mt: 1.25 }} data-testid="occurrence-timeline">
      <Box ref={track} sx={{ position: 'relative', height, mx: `${HIT / 2}px` }} role="list" aria-label={`${cases.length} occurrences over the last ${days} days`}>
        <Box sx={{ position: 'absolute', left: 0, right: 0, bottom: HIT / 2, height: '1px', bgcolor: ui.border }} />
        {placed.map(({ item, x, row }) => {
          const state = OCCURRENCE_STATES[occurrenceState(item)];
          return (
            <Tooltip
              key={item.case_id}
              describeChild
              title={
                <Box>
                  <Typography sx={{ fontSize: 12, fontWeight: 700 }}>{item.title}</Typography>
                  <Typography sx={{ fontSize: 12 }}>{[formatDateTime(item.created_at), item.service, state.label, item.origin === 'imported' ? 'imported' : null].filter(Boolean).join(' · ')}</Typography>
                </Box>
              }
            >
              <Link
                component={RouterLink}
                to={`/cases/${item.case_id}`}
                role="listitem"
                aria-label={`${item.title}, ${formatDateTime(item.created_at)}, ${state.label}`}
                sx={{
                  position: 'absolute', left: `${x * 100}%`, bottom: row * (DOT + 4),
                  width: HIT, height: HIT, ml: `${-HIT / 2}px`, display: 'grid', placeItems: 'center', borderRadius: '50%',
                  '&:focus-visible': { outline: `2px solid ${BAR_COLOR}` },
                }}
              >
                <Box sx={{ width: DOT, height: DOT, borderRadius: '50%', bgcolor: state.color, boxShadow: (theme) => `0 0 0 2px ${theme.palette.background.paper}` }} />
              </Link>
            </Tooltip>
          );
        })}
      </Box>
      <Stack direction="row" justifyContent="space-between" sx={{ fontSize: 11, color: ui.muted, mt: 0.25 }}>
        <span>{days} days ago</span>
        <span>today</span>
      </Stack>
      <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }} data-testid="occurrence-legend">
        {(Object.keys(OCCURRENCE_STATES) as OccurrenceState[]).filter((key) => states.includes(key)).map((key) => (
          <Stack key={key} direction="row" spacing={0.5} alignItems="center">
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: OCCURRENCE_STATES[key].color }} />
            <Typography sx={{ fontSize: 12, color: ui.muted }}>{OCCURRENCE_STATES[key].label}</Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

const clamp = (value: number) => Math.min(1, Math.max(0, value));

/** Earliest first; a dot closer than minGap to the last dot in a row goes up a row (at most 4). */
function placeDots<T extends { x: number }>(dots: T[], minGap: number): (T & { row: number })[] {
  const lastInRow: number[] = [];
  return [...dots]
    .sort((a, b) => a.x - b.x)
    .map((dot) => {
      let row = lastInRow.findIndex((last) => dot.x - last >= minGap);
      if (row === -1) row = lastInRow.length < 4 ? lastInRow.length : lastInRow.length - 1;
      lastInRow[row] = dot.x;
      return { ...dot, row };
    });
}

function useWidth(): [React.RefObject<HTMLDivElement>, number] {
  const ref = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}
