import { Typography } from '@mui/material';
import { useOverviewData } from '../hooks/useOverviewData';
import { TopFindingsList } from '../components/TopFindingsList';
import { LoadingSkeleton } from '../components/LoadingSkeleton';

export function FindingsPage() {
  const { findingQuery, signalQuery } = useOverviewData();
  if (findingQuery.isLoading) return <LoadingSkeleton />;
  return (
    <div>
      <Typography variant="h4" sx={{ mb: 2 }}>Findings</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        The chips below show only signals that appear to contribute to a problem, not signals that look normal.
      </Typography>
      <TopFindingsList findings={findingQuery.data ?? []} signals={signalQuery.data ?? []} />
    </div>
  );
}
