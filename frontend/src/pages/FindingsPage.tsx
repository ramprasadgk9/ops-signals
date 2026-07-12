import { Typography } from '@mui/material';
import { useOverviewData } from '../hooks/useOverviewData';
import { TopFindingsList } from '../components/TopFindingsList';
import { LoadingSkeleton } from '../components/LoadingSkeleton';

export function FindingsPage() {
  const { findingQuery } = useOverviewData();
  if (findingQuery.isLoading) return <LoadingSkeleton />;
  return (
    <div>
      <Typography variant="h4" sx={{ mb: 2 }}>Findings</Typography>
      <TopFindingsList findings={findingQuery.data ?? []} />
    </div>
  );
}
