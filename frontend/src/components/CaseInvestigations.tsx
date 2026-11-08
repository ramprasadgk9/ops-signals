import { Alert, AlertTitle, Box, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import { useQueries, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { endingBanner, investigationByline, stepTag } from '../utils/investigation';

// The guided investigations saved to a case, read-only: where it suggested looking and what people
// marked. What they marked also went into the case's investigation notes when it was saved.

export function CaseInvestigations({ caseId }: { caseId: number }) {
  const list = useQuery({ queryKey: ['investigations', { case_id: caseId }], queryFn: () => api.investigations({ case_id: caseId }) });
  const details = useQueries({
    queries: (list.data ?? []).map((item) => ({ queryKey: ['investigation', item.id], queryFn: () => api.getInvestigation(item.id) })),
  });
  if (!list.data?.length) return null;

  return (
    <Card variant="outlined" sx={{ mt: 2 }} data-testid="case-investigations">
      <CardContent>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Guided investigation
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Where it suggested looking. It doesn't decide the cause: write that in Root Cause.
        </Typography>
        <Stack spacing={2}>
          {details.map((query, index) => {
            const investigation = query.data;
            if (!investigation) return <Typography key={list.data[index].id} variant="body2" color="text.secondary">Loading…</Typography>;
            const banner = endingBanner(investigation);
            return (
              <Box key={investigation.id}>
                <Alert severity={banner.severity} sx={{ mb: 1 }}>
                  <AlertTitle sx={{ mb: 0 }}>{banner.title}</AlertTitle>
                  {investigation.summary}
                </Alert>
                <Typography variant="caption" color="text.secondary">
                  {investigationByline(investigation)}
                </Typography>
                <Stack spacing={0.75} sx={{ mt: 1 }}>
                  {investigation.steps.map((step) => {
                    const tag = stepTag(step);
                    return (
                      <Stack key={step.id} direction="row" spacing={1} alignItems="baseline">
                        <Chip size="small" label={tag.label} color={tag.color} variant={tag.color === 'default' ? 'outlined' : 'filled'} />
                        <Typography variant="body2">
                          <b>{step.title}</b>
                          {step.result ? ` · ${step.result}` : ''}
                          {step.note ? ` · Note: ${step.note}` : ''}
                        </Typography>
                      </Stack>
                    );
                  })}
                </Stack>
              </Box>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}
