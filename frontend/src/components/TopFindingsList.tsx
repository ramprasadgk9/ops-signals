import { Grid2 as Grid } from '@mui/material';
import type { Finding, Signal } from '../types';
import { FindingCard } from './FindingCard';

type Props = {
  findings: Finding[];
  signals?: Signal[];
  onViewDetails?: (finding: Finding) => void;
};

export function TopFindingsList({ findings, signals = [], onViewDetails }: Props) {
  const ranked = [...findings].sort((a, b) => b.importance_score - a.importance_score).slice(0, 5);
  return (
    <Grid container spacing={2}>
      {ranked.map((finding) => (
        <Grid key={finding.id} size={{ xs: 12, md: 6 }}>
          <FindingCard finding={finding} signals={signals} onViewDetails={onViewDetails} />
        </Grid>
      ))}
    </Grid>
  );
}
