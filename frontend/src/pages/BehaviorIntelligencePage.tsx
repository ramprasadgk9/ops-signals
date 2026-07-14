import { useState } from 'react';
import { Box, Chip, Collapse, Divider, IconButton, Paper, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';

function formatFactValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value === null || value === undefined) return 'n/a';
  return JSON.stringify(value);
}

export function BehaviorIntelligencePage() {
  const definitionsQuery = useQuery({ queryKey: ['behavior-definitions'], queryFn: api.behaviorDefinitions });
  const findingsQuery = useQuery({ queryKey: ['behavior-findings'], queryFn: api.behaviorFindings });
  const [openReasoning, setOpenReasoning] = useState<Record<string, boolean>>({});

  if (definitionsQuery.isLoading || findingsQuery.isLoading) return <LoadingSkeleton />;
  if (definitionsQuery.error || findingsQuery.error) return <ErrorState message="Failed to load behavior intelligence" />;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Box>
        <Typography variant="h4" sx={{ mb: 1 }}>Behavior Intelligence</Typography>
        <Typography variant="body2" color="text.secondary">
          Declarative behavior definitions combine analyzer signals across metrics to surface higher-level operational patterns.
        </Typography>
      </Box>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>Behavior Definitions</Typography>
        <Stack spacing={2}>
          {(definitionsQuery.data ?? []).map((definition) => (
            <Box key={definition.id} sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default' }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle1">{definition.title}</Typography>
                <Chip size="small" label={definition.enabled ? 'Enabled' : 'Disabled'} color={definition.enabled ? 'success' : 'default'} />
                <Chip size="small" label={`v${definition.version}`} />
              </Stack>
              <Typography variant="body2" color="text.secondary">{definition.description}</Typography>
            </Box>
          ))}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>Behavior Findings</Typography>
        <Stack spacing={2}>
          {(findingsQuery.data ?? []).map((finding) => (
            <Box key={`${finding.definition_id}-${finding.analysis_run_id}-${finding.id}`} sx={{ p: 2, borderRadius: 2, bgcolor: 'background.default' }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle1">{finding.title}</Typography>
                <Chip size="small" label={`Confidence ${Math.round(finding.confidence * 100)}%`} />
                <Chip size="small" label={finding.severity} />
                <Box sx={{ flex: 1 }} />
                <IconButton
                  size="small"
                  onClick={() =>
                    setOpenReasoning((current) => ({
                      ...current,
                      [finding.id]: !current[finding.id],
                    }))
                  }
                  aria-label="toggle reasoning"
                >
                  <ExpandMoreIcon
                    style={{
                      transform: openReasoning[finding.id] ? 'rotate(180deg)' : 'rotate(0deg)',
                      transition: 'transform 0.2s ease',
                      color: '#0f766e',
                    }}
                  />
                </IconButton>
              </Stack>
              <Typography variant="body2" color="text.secondary">{finding.description}</Typography>
              <Collapse in={openReasoning[finding.id]} timeout="auto" unmountOnExit>
                <Divider sx={{ my: 2, borderColor: 'rgba(15, 118, 110, 0.2)' }} />
                <Stack spacing={1.5}>
                  <Box
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      bgcolor: 'rgba(15, 118, 110, 0.08)',
                      border: '1px solid rgba(15, 118, 110, 0.18)',
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ color: 'primary.main', mb: 0.5 }}>
                      Why this matched
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'text.primary' }}>
                      Category: {finding.category} • Service: {finding.service ?? 'any'} • Analysis run: {finding.analysis_run_id ?? 'n/a'}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.75, color: 'text.secondary' }}>
                      Confidence rises when the key facts are true, the correlation windows overlap, and the required conditions pass.
                    </Typography>
                  </Box>

                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(124, 45, 18, 0.08)',
                        border: '1px solid rgba(124, 45, 18, 0.16)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'secondary.main', fontWeight: 700 }}>
                        Matched facts
                      </Typography>
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'IBM Plex Mono, monospace', fontSize: 13 }}>
                        {JSON.stringify(finding.facts_json, null, 2)}
                      </Typography>
                    </Box>

                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(15, 118, 110, 0.06)',
                        border: '1px solid rgba(15, 118, 110, 0.14)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'primary.main', fontWeight: 700 }}>
                        Condition check
                      </Typography>
                      <Stack spacing={0.75}>
                        {finding.matched_conditions_json.map((condition, index) => (
                          <Box
                            key={`${finding.id}-${index}`}
                            sx={{
                              p: 1,
                              borderRadius: 1.5,
                              bgcolor: condition.passed ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.10)',
                              border: condition.passed ? '1px solid rgba(34, 197, 94, 0.25)' : '1px solid rgba(239, 68, 68, 0.20)',
                            }}
                          >
                            <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {condition.group ?? 'all'} • {condition.fact}
                              </Typography>
                              <Chip
                                size="small"
                                label={condition.passed ? 'passed' : 'failed'}
                                color={condition.passed ? 'success' : 'error'}
                                sx={{ height: 22 }}
                              />
                            </Stack>
                            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary' }}>
                              {condition.operator} {String(condition.value)}
                            </Typography>
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  </Stack>

                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(15, 118, 110, 0.05)',
                        border: '1px solid rgba(15, 118, 110, 0.14)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'primary.main', fontWeight: 700 }}>
                        Evidence fields
                      </Typography>
                      <Stack spacing={0.75}>
                        {(finding.evidence_json ?? []).map((evidence) => {
                          const segments = evidence.split('.');
                          const label = segments[segments.length - 1] ?? evidence;
                          return (
                            <Box
                              key={evidence}
                              sx={{
                                p: 1,
                                borderRadius: 1.5,
                                bgcolor: 'background.paper',
                                border: '1px solid rgba(15, 118, 110, 0.10)',
                              }}
                            >
                              <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }}>
                                {label.replaceAll('_', ' ')}
                              </Typography>
                              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                derived from {evidence}
                              </Typography>
                            </Box>
                          );
                        })}
                      </Stack>
                    </Box>

                    <Box
                      sx={{
                        flex: 1,
                        p: 1.5,
                        borderRadius: 2,
                        bgcolor: 'rgba(124, 45, 18, 0.05)',
                        border: '1px solid rgba(124, 45, 18, 0.14)',
                      }}
                    >
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'secondary.main', fontWeight: 700 }}>
                        Correlation summary
                      </Typography>
                      <Stack spacing={0.75}>
                        {Object.entries(finding.correlation_json ?? {}).map(([key, value]) => (
                          <Box
                            key={key}
                            sx={{
                              p: 1,
                              borderRadius: 1.5,
                              bgcolor: 'background.paper',
                              border: '1px solid rgba(124, 45, 18, 0.12)',
                            }}
                          >
                            <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }}>
                              {key.replaceAll('_', ' ')}
                            </Typography>
                            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                              {formatFactValue(value)}
                            </Typography>
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  </Stack>
                </Stack>
              </Collapse>
            </Box>
          ))}
          {(findingsQuery.data ?? []).length === 0 && (
            <Typography variant="body2" color="text.secondary">No behavior evaluations found yet.</Typography>
          )}
        </Stack>
      </Paper>
    </Box>
  );
}
