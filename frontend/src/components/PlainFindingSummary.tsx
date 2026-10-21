import { useState } from 'react';
import { Box, Button, Chip, Stack, Tooltip, Typography } from '@mui/material';
import type { FindingPlain } from '../types';
import { plainLines, plainTimes, plainTone, type PlainTone } from '../utils/findingPlain';

// A finding in plain words: what changed, why it matters and what to check, with the stored
// summary kept under "Technical details". Wording comes from config/finding_templates.yaml.

const CHIP_COLOR: Record<PlainTone, 'error' | 'success' | 'warning' | 'default'> = {
  bad: 'error',
  good: 'success',
  gap: 'warning',
  neutral: 'default',
};

export function PlainBadge({ plain }: { plain: FindingPlain }) {
  const tone = plainTone(plain.badge);
  return (
    <Stack direction="row" spacing={0.75} sx={{ alignSelf: 'flex-start' }}>
      <Chip
        label={plain.badge_label}
        color={CHIP_COLOR[tone]}
        size="small"
        variant={tone === 'neutral' ? 'outlined' : 'filled'}
        data-testid="finding-plain-badge"
        sx={{ fontWeight: 700 }}
      />
      {plain.service_importance_label ? (
        <Chip
          label={plain.service_importance_label}
          size="small"
          variant="outlined"
          color={plain.service_importance === 'critical' ? 'warning' : 'default'}
          data-testid="finding-plain-importance"
        />
      ) : null}
    </Stack>
  );
}

export function PlainFindingSummary({
  plain,
  summary,
  signal,
  onOpenFinding,
}: {
  plain: FindingPlain;
  /** The finding's stored summary, shown under Technical details. */
  summary: string;
  /** The finding's strongest signal in analyzer words (utils/findingPlain leadSignalText), also under Technical details. */
  signal?: string | null;
  onOpenFinding?: (findingId: number) => void;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const lines = plainLines(plain);
  return (
    <Stack spacing={1.25} data-testid="finding-plain">
      <Typography variant="body2" sx={{ color: 'text.primary' }} data-testid="finding-plain-what">
        {plainTimes(plain.what)}
      </Typography>
      {lines.length ? (
        <Box
          component="dl"
          sx={{
            m: 0,
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '110px minmax(0, 1fr)' },
            columnGap: 1.5,
            rowGap: { xs: 0.25, sm: 0.75 },
            borderTop: 1,
            borderColor: 'divider',
            pt: 1,
          }}
        >
          {lines.map((line, index) => (
            <Box key={`${line.label}-${index}`} sx={{ display: 'contents' }}>
              <Typography component="dt" variant="caption" color="text.secondary" sx={{ fontWeight: 700, pt: '2px', mt: { xs: index ? 0.75 : 0, sm: 0 } }}>
                {line.hint ? (
                  <Tooltip title={line.hint} enterTouchDelay={0}>
                    <Box component="span" tabIndex={0} data-testid="finding-plain-hint" sx={{ cursor: 'help', borderBottom: '1px dotted', borderColor: 'text.secondary' }}>
                      {line.label}
                    </Box>
                  </Tooltip>
                ) : (
                  line.label
                )}
              </Typography>
              <Typography component="dd" variant="body2" sx={{ m: 0, minWidth: 0 }}>
                {line.text}
                {line.findingId && onOpenFinding ? (
                  <Button size="small" onClick={() => onOpenFinding(line.findingId as number)} sx={{ textTransform: 'none', ml: 0.5, py: 0, minWidth: 0 }}>
                    Open #{line.findingId}
                  </Button>
                ) : null}
              </Typography>
            </Box>
          ))}
        </Box>
      ) : null}
      <Box>
        <Button
          size="small"
          onClick={() => setShowDetails((value) => !value)}
          aria-expanded={showDetails}
          sx={{ textTransform: 'none', px: 0, minWidth: 0 }}
        >
          {showDetails ? '▾' : '▸'} Technical details
        </Button>
        {showDetails ? (
          <Stack spacing={0.75} sx={{ mt: 0.5 }} data-testid="finding-plain-details">
            <Typography variant="body2" color="text.secondary" sx={{ fontSize: 13 }}>
              {summary}
            </Typography>
            {signal ? (
              <Typography variant="body2" color="text.secondary" sx={{ fontSize: 13 }} data-testid="finding-plain-signal">
                <strong>Strongest signal:</strong> {signal}
              </Typography>
            ) : null}
          </Stack>
        ) : null}
      </Box>
    </Stack>
  );
}

/** Badge, headline and what changed, for compact lists; the stored title when there's no plain wording. */
export function PlainHeadline({
  finding,
  titleSx,
}: {
  finding: { title: string; plain?: FindingPlain | null };
  titleSx?: object;
}) {
  if (!finding.plain) return <Typography sx={titleSx}>{finding.title}</Typography>;
  return (
    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
      <PlainBadge plain={finding.plain} />
      <Typography sx={titleSx}>{finding.plain.headline}</Typography>
      <Typography variant="body2" sx={{ fontSize: 13 }}>{plainTimes(finding.plain.what)}</Typography>
    </Stack>
  );
}
