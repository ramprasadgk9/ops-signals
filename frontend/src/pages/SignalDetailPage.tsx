import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { Card, CardContent, Typography } from '@mui/material';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { SignalEvidencePanel } from '../components/SignalEvidencePanel';

export function SignalDetailPage() {
  const { signalId = '' } = useParams();
  const query = useQuery({ queryKey: ['signal', signalId], queryFn: () => api.signalDetail(signalId), enabled: Boolean(signalId) });
  if (query.isLoading) return <LoadingSkeleton />;
  if (!query.data) return <Typography>Signal not found.</Typography>;

  return (
    <Card>
      <CardContent>
        <Typography variant="h4">Signal Detail</Typography>
        <Typography>Type: {query.data.signal_type}</Typography>
        <Typography>Analyzer: {query.data.analyzer_id}</Typography>
        <Typography>Severity: {query.data.severity}</Typography>
        <Typography>Confidence: {query.data.confidence}</Typography>
        <Typography>Importance: {query.data.importance_score}</Typography>
        <Typography>Summary: {query.data.summary}</Typography>
        <SignalEvidencePanel signals={[query.data]} />
      </CardContent>
    </Card>
  );
}
