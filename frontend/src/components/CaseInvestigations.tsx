import { Alert, AlertTitle, Box, Button, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import { useMutation, useQueries, useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { endingBanner, investigationByline, stepTag } from '../utils/investigation';

// The guided investigations saved to a case, read-only: where it suggested looking and what people
// marked. Saving one to the case only adds a one-line note; "Use as note" puts a draft of what it
// found in the note box (onUseAsNote), for the person to edit and save. Renders nothing when the
// case has no guided investigation.

// What the case asks for next while a guided investigation is attached and nobody has saved a note
// of their own: go through it, do the steps it left, then use it as the note. Up to three steps,
// those worth a look first.
export function GuidedNextAction({ investigationId, onOpen }: { investigationId: number; onOpen: () => void }) {
  const query = useQuery({ queryKey: ['investigation', investigationId], queryFn: () => api.getInvestigation(investigationId) });
  const investigation = query.data;
  const steps = (investigation?.steps ?? []).filter((step) => !step.unverified && (step.status === 'worth_a_look' || step.kind === 'your_step'));
  steps.sort((a, b) => Number(b.status === 'worth_a_look') - Number(a.status === 'worth_a_look'));
  const yours = steps.filter((step) => step.kind === 'your_step').length;
  return (
    <Stack spacing={1.5} data-testid="guided-next-action">
      <Typography variant="body1" sx={{ fontWeight: 600 }}>
        Go through guided investigation #{investigationId}
      </Typography>
      <Typography variant="body2">
        {investigation ? `It ran ${investigation.checks.length} check${investigation.checks.length === 1 ? '' : 's'}${yours ? ` and left you ${yours} step${yours === 1 ? '' : 's'}` : ''}. ` : ''}
        Do the steps it left for you, then click Use as note and add what you found.
      </Typography>
      {steps.slice(0, 3).map((step) => {
        const tag = stepTag(step);
        return (
          <Stack key={step.id} direction="row" spacing={1} alignItems="baseline">
            <Chip size="small" label={tag.label} color={tag.color} variant={tag.color === 'default' ? 'outlined' : 'filled'} />
            <Typography variant="body2">{step.title}</Typography>
          </Stack>
        );
      })}
      <Button variant="contained" onClick={onOpen}>
        Open the investigation
      </Button>
    </Stack>
  );
}

// Long results (a check's raw summary) are cut here; the investigation dialog shows them whole.
const RESULT_CHARS = 240;

function shorten(text: string): string {
  return text.length > RESULT_CHARS ? `${text.slice(0, RESULT_CHARS).trimEnd()}…` : text;
}

export function CaseInvestigations({ caseId, onUseAsNote }: { caseId: number; onUseAsNote?: (text: string) => void }) {
  const list = useQuery({ queryKey: ['investigations', { case_id: caseId }], queryFn: () => api.investigations({ case_id: caseId }) });
  const details = useQueries({
    queries: (list.data ?? []).map((item) => ({ queryKey: ['investigation', item.id], queryFn: () => api.getInvestigation(item.id) })),
  });
  const draft = useMutation({ mutationFn: (id: number) => api.investigationNoteDraft(id), onSuccess: (data) => onUseAsNote?.(data.text) });
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
                  {investigation.summary ?? banner.detail}
                </Alert>
                <Typography variant="caption" color="text.secondary">
                  {investigationByline(investigation)}
                </Typography>
                {onUseAsNote ? (
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                    <Button
                      size="small"
                      variant="outlined"
                      data-testid="use-as-note"
                      disabled={draft.isPending}
                      onClick={() => draft.mutate(investigation.id)}
                    >
                      Use as note
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                      Puts a draft in the Investigation note box. Edit it, then Save Investigation.
                    </Typography>
                  </Stack>
                ) : null}
                {draft.isError && draft.variables === investigation.id ? (
                  <Typography variant="caption" color="error">
                    Couldn't build the draft. Try again.
                  </Typography>
                ) : null}
                <Stack spacing={0.75} sx={{ mt: 1 }}>
                  {investigation.steps.map((step) => {
                    const tag = stepTag(step);
                    return (
                      <Stack key={step.id} direction="row" spacing={1} alignItems="baseline">
                        <Chip size="small" label={tag.label} color={tag.color} variant={tag.color === 'default' ? 'outlined' : 'filled'} />
                        <Typography variant="body2">
                          <b>{step.title}</b>
                          {step.result ? ` · ${shorten(step.result)}` : ''}
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
