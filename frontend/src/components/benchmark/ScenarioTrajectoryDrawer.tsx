import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Drawer,
  IconButton,
  Stack,
  Typography,
} from '@mui/material';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import SmartToyRoundedIcon from '@mui/icons-material/SmartToyRounded';
import PsychologyRoundedIcon from '@mui/icons-material/PsychologyRounded';
import BuildRoundedIcon from '@mui/icons-material/BuildRounded';
import GavelRoundedIcon from '@mui/icons-material/GavelRounded';
import type { BenchmarkScenarioResult } from '../../types/benchmark';

interface ScenarioTrajectoryDrawerProps {
  open: boolean;
  onClose: () => void;
  scenario: BenchmarkScenarioResult | null;
  systemKey: 'iam' | 'baseline_a' | 'baseline_b' | null;
}

export const ScenarioTrajectoryDrawer: React.FC<ScenarioTrajectoryDrawerProps> = ({
  open,
  onClose,
  scenario,
  systemKey,
}) => {
  if (!scenario || !systemKey) return null;

  const run = scenario[systemKey];
  if (!run) return null;

  const systemTitle =
    systemKey === 'iam'
      ? 'IAM Engine (Deterministic Behavioral Intelligence)'
      : systemKey === 'baseline_a'
      ? 'Baseline A (Direct ReAct LLM Agent)'
      : 'Baseline B (Signals-Augmented ReAct LLM Agent)';

  const trajectory = run.metadata?.trajectory || [];
  const executedAnalyzers = run.metadata?.executed_analyzers || [];
  const judge = run.judge;

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: { width: { xs: '100%', sm: 580, md: 680 }, p: 3 },
      }}
    >
      <Stack spacing={3}>
        {/* Header */}
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Stack spacing={0.5}>
            <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>
              {scenario.scenario.replace('scenario_', '').replace(/_/g, ' ').toUpperCase()}
            </Typography>
            <Typography variant="h6" sx={{ fontWeight: 800 }}>
              {systemTitle}
            </Typography>
          </Stack>
          <IconButton onClick={onClose} size="small">
            <CloseRoundedIcon />
          </IconButton>
        </Stack>

        <Divider />

        {/* Diagnosis & Ground Truth Card */}
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1.5 }}>
              Diagnosis & Benchmark Evaluation
            </Typography>
            <Stack spacing={1}>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2" color="text.secondary">Diagnostic Status:</Typography>
                <Chip
                  icon={run.status === 'SUCCESS' ? <CheckCircleRoundedIcon /> : <WarningAmberRoundedIcon />}
                  label={run.status}
                  color={run.status === 'SUCCESS' ? 'success' : 'warning'}
                  size="small"
                  sx={{ fontWeight: 700 }}
                />
              </Stack>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2" color="text.secondary">Culprit Entity:</Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {run.entity || 'None'} (Ground Truth: {scenario.ground_truth.entity})
                </Typography>
              </Stack>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2" color="text.secondary">Root Cause Class:</Typography>
                <Typography variant="body2" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                  {run.root_cause} (Ground Truth: {scenario.ground_truth.root_cause})
                </Typography>
              </Stack>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2" color="text.secondary">Evidence F1 / Window IoU:</Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  F1: {(run.evidence_f1 ?? 0).toFixed(2)} | IoU: {(run.window_iou ?? 0).toFixed(2)}
                </Typography>
              </Stack>
              <Stack direction="row" justifyContent="space-between">
                <Typography variant="body2" color="text.secondary">Execution Metrics:</Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {run.tokens.toLocaleString()} tokens | ${run.cost_usd.toFixed(4)} | {run.execution_time_seconds.toFixed(3)}s
                </Typography>
              </Stack>
              {run.summary_text && (
                <Box sx={{ mt: 1.5, p: 1.5, bgcolor: 'action.hover', borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>
                    DIAGNOSTIC SUMMARY:
                  </Typography>
                  <Typography variant="body2">{run.summary_text}</Typography>
                </Box>
              )}
            </Stack>
          </CardContent>
        </Card>

        {/* Panel Judge Ratings */}
        {judge && (
          <Card variant="outlined" sx={{ borderRadius: 2 }}>
            <CardContent>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
                <GavelRoundedIcon color="info" fontSize="small" />
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  Impartial SRE Panel Judge Evaluation
                </Typography>
              </Stack>
              <Stack spacing={1.5}>
                <Stack direction="row" spacing={1}>
                  <Chip label={`Attribution: ${judge.consensus.attribution}/5`} color="info" size="small" />
                  <Chip label={`Grounding: ${judge.consensus.grounding}/5`} color="info" size="small" />
                  <Chip label={`Actionability: ${judge.consensus.actionability}/5`} color="info" size="small" />
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {judge.consensus.justification}
                </Typography>
                {judge.scores.length > 0 && (
                  <Box sx={{ pt: 1 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>
                      INDIVIDUAL RATER SCORES:
                    </Typography>
                    <Stack spacing={1}>
                      {judge.scores.map((s) => (
                        <Box key={s.judge_id} sx={{ p: 1, border: '1px solid rgba(15,23,42,0.06)', borderRadius: 1 }}>
                          <Typography variant="caption" sx={{ fontWeight: 700 }}>
                            {s.judge_id}: Attr={s.attribution}, Grd={s.grounding}, Act={s.actionability}
                          </Typography>
                          <Typography variant="caption" color="text.secondary" display="block">
                            {s.justification}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  </Box>
                )}
              </Stack>
            </CardContent>
          </Card>
        )}

        {/* Trajectory / Algorithmic Execution Steps */}
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
            {systemKey === 'iam' ? 'Executed Intelligence Pipeline' : `Agent Reasoning Trajectory (${trajectory.length} Turns)`}
          </Typography>

          {systemKey === 'iam' ? (
            <Stack spacing={1.5}>
              <Card variant="outlined" sx={{ borderRadius: 2 }}>
                <CardContent>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                    Deterministic Statistical Analyzers
                  </Typography>
                  <Stack direction="row" flexWrap="wrap" gap={1}>
                    {executedAnalyzers.map((an) => (
                      <Chip key={an} label={an} color="success" size="small" variant="outlined" />
                    ))}
                  </Stack>
                  <Box sx={{ mt: 2 }}>
                    <Typography variant="caption" color="text.secondary">
                      Findings Discovered: <strong>{run.metadata?.finding_count ?? 0}</strong> | Signals Processed: <strong>{run.metadata?.signal_count ?? 0}</strong> | Causal Behavior Findings: <strong>{run.metadata?.behavior_finding_count ?? 0}</strong>
                    </Typography>
                  </Box>
                </CardContent>
              </Card>
            </Stack>
          ) : (
            <Stack spacing={2}>
              {trajectory.map((step, idx) => (
                <Card key={idx} variant="outlined" sx={{ borderRadius: 2 }}>
                  <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                    <Stack spacing={1.5}>
                      <Stack direction="row" alignItems="center" spacing={1}>
                        <Chip
                          icon={<SmartToyRoundedIcon fontSize="small" />}
                          label={`Turn ${step.turn}`}
                          size="small"
                          color="primary"
                          sx={{ fontWeight: 700 }}
                        />
                        {step.tool && (
                          <Chip
                            icon={<BuildRoundedIcon fontSize="small" />}
                            label={`Tool: ${step.tool}`}
                            size="small"
                            variant="outlined"
                          />
                        )}
                      </Stack>

                      {step.thought && (
                        <Box sx={{ p: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
                          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 0.5 }}>
                            <PsychologyRoundedIcon fontSize="small" color="action" />
                            <Typography variant="caption" sx={{ fontWeight: 700 }}>
                              THOUGHT:
                            </Typography>
                          </Stack>
                          <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                            {step.thought}
                          </Typography>
                        </Box>
                      )}

                      {step.input && (
                        <Box sx={{ p: 1, bgcolor: 'background.paper', border: '1px solid rgba(15,23,42,0.08)', borderRadius: 1 }}>
                          <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>
                            TOOL INPUT:
                          </Typography>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'pre-wrap' }}>
                            {typeof step.input === 'string' ? step.input : JSON.stringify(step.input, null, 2)}
                          </Typography>
                        </Box>
                      )}

                      {step.observation && (
                        <Box sx={{ p: 1, bgcolor: 'action.hover', borderRadius: 1 }}>
                          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>
                            OBSERVATION:
                          </Typography>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem', whiteSpace: 'pre-wrap', maxHeight: 160, overflowY: 'auto' }}>
                            {typeof step.observation === 'string' ? step.observation : JSON.stringify(step.observation, null, 2)}
                          </Typography>
                        </Box>
                      )}

                      {step.output && (
                        <Box sx={{ p: 1, bgcolor: 'rgba(25, 118, 210, 0.05)', borderRadius: 1 }}>
                          <Typography variant="caption" color="primary" sx={{ fontWeight: 700, display: 'block', mb: 0.5 }}>
                            FINAL DIAGNOSIS:
                          </Typography>
                          <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                            {step.output}
                          </Typography>
                        </Box>
                      )}
                    </Stack>
                  </CardContent>
                </Card>
              ))}
            </Stack>
          )}
        </Box>
      </Stack>
    </Drawer>
  );
};
