import { useState } from 'react';
import { Box, Button, CircularProgress, Link, Stack, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { apiUrl } from '../api/client';
import type { SampleFile } from '../types';

type Props = {
  /** Analyze a sample in one click (the demo); without it the box only shows and downloads them. */
  onAnalyze?: (sample: SampleFile) => void;
  analyzingId?: string | null;
  /** A line in front of the usual one (the hosted demo says why uploads are off). */
  note?: string;
};

// The columns a sample file has, and which ones an upload needs.
const COLUMNS: [string, string, boolean][] = [
  ['timestamp', 'ISO time, UTC', true],
  ['value', 'a number', true],
  ['metric_name', 'or type it in Metric', false],
  ['service', 'or type it in Service', false],
  ['env', '', false],
];

/** The bundled sample CSVs (backend/app/api/demo.py, /api/samples) on New Analysis → CSV Upload:
 * download one, or look at its first rows, to see what a file to upload looks like. */
export function SampleFiles({ onAnalyze, analyzingId, note }: Props) {
  const files = useQuery({ queryKey: ['sample-files'], queryFn: () => api.sampleFiles(), staleTime: Infinity, retry: false });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const samples = files.data ?? [];
  if (!samples.length) return null;
  const selected = samples.find((sample) => sample.id === selectedId) ?? samples[0];

  return (
    <Box data-testid="sample-files" sx={{ p: 1.5, borderRadius: '8px', border: '1px solid var(--os-border)', bgcolor: 'var(--os-surface-alt)' }}>
      <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{onAnalyze ? 'Try a sample file' : 'Sample files'}</Typography>
      <Typography sx={{ fontSize: 13, color: 'text.secondary', mb: 1 }}>
        {note ? `${note} ` : ''}
        {samples.length} small files in the format Ops Signals reads, one row per sample. {onAnalyze ? 'Analyze one here, or download it' : 'Download one'} to see how your own file should look.
      </Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: `repeat(${Math.min(samples.length, 4)}, 1fr)` }, gap: 1 }}>
        {samples.map((sample) => {
          const isSelected = sample.id === selected.id;
          return (
            <Box
              key={sample.id}
              data-testid={`sample-${sample.id}`}
              data-selected={isSelected || undefined}
              onClick={() => setSelectedId(sample.id)}
              sx={{
                p: 1.25,
                borderRadius: '8px',
                cursor: 'pointer',
                bgcolor: 'background.paper',
                border: '1px solid',
                borderColor: isSelected ? 'primary.main' : 'var(--os-border)',
                boxShadow: isSelected ? (theme) => `inset 0 0 0 1px ${theme.palette.primary.main}` : 'none',
              }}
            >
              <Typography sx={{ fontWeight: 800, fontSize: 13 }}>{sample.title}</Typography>
              <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.25, mb: 1 }}>{sample.description}</Typography>
              <Stack direction="row" spacing={1.25} alignItems="center" useFlexGap flexWrap="wrap">
                {onAnalyze ? (
                  <Button
                    size="small"
                    variant={isSelected ? 'contained' : 'outlined'}
                    disabled={Boolean(analyzingId)}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedId(sample.id);
                      onAnalyze(sample);
                    }}
                    sx={{ textTransform: 'none', fontWeight: 750 }}
                  >
                    {analyzingId === sample.id ? <CircularProgress size={16} color="inherit" sx={{ mr: 1 }} /> : null}
                    Analyze it
                  </Button>
                ) : null}
                <Link
                  href={apiUrl(`/api/samples/${encodeURIComponent(sample.file)}`)}
                  download={sample.file}
                  onClick={(event) => event.stopPropagation()}
                  underline="hover"
                  sx={{ fontSize: 12, fontWeight: 700 }}
                  aria-label={`Download ${sample.file}`}
                >
                  Download CSV
                </Link>
              </Stack>
            </Box>
          );
        })}
      </Box>
      <Typography sx={{ fontWeight: 800, fontSize: 13, mt: 1.5 }}>
        What's in it{' '}
        <Box component="span" sx={{ fontWeight: 600, fontSize: 12, color: 'text.secondary' }}>
          · first rows of {selected.file}: {selected.rows} rows, one every {selected.interval}
        </Box>
      </Typography>
      <Box
        component="pre"
        data-testid="sample-preview"
        sx={{ m: '6px 0 0', p: 1.25, fontSize: 12, fontFamily: 'monospace', overflowX: 'auto', borderRadius: '6px', border: '1px solid var(--os-border)', bgcolor: 'background.default' }}
      >
        {[...selected.preview, '…'].join('\n')}
      </Box>
      <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.25, m: '8px 0 0', fontSize: 12 }}>
        {COLUMNS.map(([name, what, needed]) => (
          <Box key={name} sx={{ display: 'contents' }}>
            <Box component="dt" sx={{ fontFamily: 'monospace' }}>{name}</Box>
            <Box component="dd" sx={{ m: 0, color: needed ? 'warning.main' : 'text.secondary' }}>
              {needed ? 'needed' : 'optional'}{what ? ` · ${what}` : ''}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
