import { useMemo, useState } from 'react';
import { Alert, Box, Button, Chip, CircularProgress, Stack, TextField, Typography } from '@mui/material';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import DeleteRoundedIcon from '@mui/icons-material/DeleteRounded';
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/queries';
import { WorkspacePanel } from '../../standalone/components';
import { ui } from '../../standalone/theme';
import { downloadText, type LabPassFailStatus } from './labConfig';

type Props = {
  analyzerId: string;
  labName: string;
  yamlText: string;
  implementation: Record<string, unknown>;
  findingRules: Record<string, unknown>;
  passFailStatus: LabPassFailStatus;
  passFailReason: string;
  productionNote: string;
  benchmarkSummary?: Record<string, unknown>;
};

function statusColor(status: LabPassFailStatus) {
  if (status === 'pass') return 'success';
  if (status === 'fail') return 'error';
  return 'default';
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

export function AnalyzerLabConfigPanel({
  analyzerId,
  labName,
  yamlText,
  implementation,
  findingRules,
  passFailStatus,
  passFailReason,
  productionNote,
  benchmarkSummary = {},
}: Props) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [suggestionName, setSuggestionName] = useState(`${labName} suggestion`);
  const queryKey = ['analyzer-lab-config-suggestions', analyzerId];
  const filename = `${analyzerId}-config-suggestion.yaml`;

  const suggestionsQuery = useQuery({
    queryKey,
    queryFn: () => api.analyzerLabConfigSuggestions(analyzerId),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      api.saveAnalyzerLabConfigSuggestion({
        analyzer_id: analyzerId,
        lab_name: labName,
        suggestion_name: suggestionName.trim() || `${labName} suggestion`,
        yaml_text: yamlText,
        implementation_json: implementation,
        finding_rules_json: findingRules,
        benchmark_summary_json: benchmarkSummary,
        pass_fail_status: passFailStatus,
        created_by: 'local',
      }),
    onSuccess: () => {
      setMessage('Saved config suggestion.');
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteAnalyzerLabConfigSuggestion(id),
    onSuccess: () => {
      setMessage('Deleted config suggestion.');
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => api.clearAnalyzerLabConfigSuggestions(analyzerId),
    onSuccess: () => {
      setMessage('Cleared saved suggestions for this analyzer.');
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const latestSuggestions = useMemo(() => suggestionsQuery.data?.slice(0, 5) ?? [], [suggestionsQuery.data]);

  return (
    <WorkspacePanel sx={{ p: 2.5 }}>
      <Stack spacing={2}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: 20 }}>Config Suggestion</Typography>
            <Typography sx={{ color: ui.muted }}>Save the tested YAML as a suggestion. This does not edit analyzers.yaml.</Typography>
          </Box>
          <Chip label={passFailStatus.toUpperCase()} color={statusColor(passFailStatus)} sx={{ fontWeight: 900, alignSelf: { xs: 'flex-start', md: 'center' } }} />
        </Stack>

        <Alert severity={passFailStatus === 'fail' ? 'warning' : 'info'}>{passFailReason}</Alert>
        <Alert severity="success">
          <strong>Use this in production when:</strong> {productionNote}
        </Alert>

        <TextField label="Suggestion name" value={suggestionName} onChange={(event) => setSuggestionName(event.target.value)} />
        <Box component="pre" sx={{ m: 0, p: 2, borderRadius: 2, bgcolor: '#0f172a', color: '#e2e8f0', overflow: 'auto', fontSize: 13 }}>
          {yamlText}
        </Box>

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button startIcon={<SaveRoundedIcon />} variant="contained" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            Save YAML Suggestion
          </Button>
          <Button startIcon={<ContentCopyRoundedIcon />} variant="outlined" onClick={() => copyText(yamlText).then(() => setMessage('Copied YAML.'))}>
            Copy YAML
          </Button>
          <Button startIcon={<DownloadRoundedIcon />} variant="outlined" onClick={() => downloadText(filename, yamlText)}>
            Download YAML
          </Button>
          <Button startIcon={<DeleteRoundedIcon />} color="error" variant="outlined" onClick={() => clearMutation.mutate()} disabled={clearMutation.isPending}>
            Clear All
          </Button>
        </Stack>

        {message && <Alert severity="success" onClose={() => setMessage(null)}>{message}</Alert>}
        {(saveMutation.error || deleteMutation.error || clearMutation.error) && (
          <Alert severity="error">{(saveMutation.error || deleteMutation.error || clearMutation.error as Error)?.message ?? 'Config suggestion action failed'}</Alert>
        )}

        <Box>
          <Typography sx={{ fontWeight: 900, mb: 1 }}>Saved Suggestions</Typography>
          {suggestionsQuery.isLoading ? (
            <CircularProgress size={20} />
          ) : latestSuggestions.length === 0 ? (
            <Typography sx={{ color: ui.muted }}>No saved suggestions yet.</Typography>
          ) : (
            <Stack spacing={1}>
              {latestSuggestions.map((suggestion) => (
                <Box key={suggestion.id} sx={{ p: 1.5, border: `1px solid ${ui.border}`, borderRadius: 2 }}>
                  <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1}>
                    <Box>
                      <Typography sx={{ fontWeight: 800 }}>{suggestion.suggestion_name}</Typography>
                      <Typography sx={{ color: ui.muted, fontSize: 13 }}>
                        {new Date(suggestion.created_at).toLocaleString()} · {suggestion.pass_fail_status}
                      </Typography>
                    </Box>
                    <Stack direction="row" spacing={1}>
                      <Button size="small" onClick={() => copyText(suggestion.yaml_text).then(() => setMessage('Copied saved YAML.'))}>Copy</Button>
                      <Button size="small" onClick={() => downloadText(filename, suggestion.yaml_text)}>Download</Button>
                      <Button size="small" color="error" onClick={() => deleteMutation.mutate(suggestion.id)}>Delete</Button>
                    </Stack>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </Box>
      </Stack>
    </WorkspacePanel>
  );
}
