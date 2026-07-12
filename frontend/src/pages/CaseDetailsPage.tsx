import { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  Alert,
} from '@mui/material';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ErrorState } from '../components/ErrorState';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`case-tabpanel-${index}`}
      aria-labelledby={`case-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

export function CaseDetailsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [tabValue, setTabValue] = useState(0);
  const queryClient = useQueryClient();

  // Investigation form state
  const [investigationStatus, setInvestigationStatus] = useState('');
  const [investigationNote, setInvestigationNote] = useState('');

  // RCA form state
  const [rcaStatus, setRcaStatus] = useState('');
  const [rcaSummary, setRcaSummary] = useState('');
  const [rcaConfidence, setRcaConfidence] = useState<number | string>('');
  const [rcaVerified, setRcaVerified] = useState(false);

  // Resolution form state
  const [outcomeStatus, setOutcomeStatus] = useState('');
  const [outcomeSummary, setOutcomeSummary] = useState('');
  const [correctiveAction, setCorrectiveAction] = useState('');

  const caseQuery = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.getCase(parseInt(caseId || '0')),
    enabled: Boolean(caseId),
  });

  // Initialize form state when case loads
  if (caseQuery.data && investigationStatus === '') {
    setInvestigationStatus(caseQuery.data.investigation_status);
    setRcaStatus(caseQuery.data.root_cause_status);
    setRcaSummary(caseQuery.data.root_cause_summary || '');
    setRcaConfidence(caseQuery.data.root_cause_confidence || '');
    setRcaVerified(caseQuery.data.root_cause_verified);
    setOutcomeStatus(caseQuery.data.outcome_status);
    setOutcomeSummary(caseQuery.data.outcome_summary || '');
    setCorrectiveAction(caseQuery.data.corrective_action || '');
  }

  const updateInvestigationMutation = useMutation({
    mutationFn: () =>
      api.updateInvestigation(parseInt(caseId || '0'), {
        investigation_status: investigationStatus,
        investigation_note: investigationNote || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
      setInvestigationNote('');
    },
  });

  const updateRCAMutation = useMutation({
    mutationFn: () =>
      api.updateRCA(parseInt(caseId || '0'), {
        root_cause_status: rcaStatus,
        root_cause_summary: rcaSummary || undefined,
        root_cause_confidence: rcaConfidence ? parseFloat(rcaConfidence.toString()) : undefined,
        root_cause_verified: rcaVerified,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  const updateResolutionMutation = useMutation({
    mutationFn: () =>
      api.updateResolution(parseInt(caseId || '0'), {
        outcome_status: outcomeStatus,
        outcome_summary: outcomeSummary || undefined,
        corrective_action: correctiveAction || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  const indexMemoryMutation = useMutation({
    mutationFn: () => api.indexCaseMemory(parseInt(caseId || '0')),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] });
    },
  });

  if (caseQuery.isLoading) return <LoadingSkeleton />;
  if (caseQuery.error) return <ErrorState message="Failed to load case details" />;
  if (!caseQuery.data) return <ErrorState message="Case not found" />;

  const caseData = caseQuery.data;
  const finding = caseData.finding_snapshot;

  const getHealthColor = (status?: string): 'error' | 'warning' | 'success' | 'default' => {
    switch (status?.toLowerCase()) {
      case 'critical':
        return 'error';
      case 'significant':
        return 'warning';
      case 'normal':
        return 'success';
      default:
        return 'default';
    }
  };

  const getCategoryLabel = (category?: string): string => {
    if (!category) return 'Insight';
    return category
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  return (
    <Box sx={{ pb: 4 }}>
      {/* Case Header */}
      <Box sx={{ mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 2 }}>
          <div>
            <Typography variant="h4" sx={{ mb: 1 }}>{caseData.case_title}</Typography>
            <Typography variant="body2" color="text.secondary">Case #{caseData.id}</Typography>
          </div>
        </Stack>

        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Stack spacing={2}>
              <Box>
                <Typography variant="caption" color="text.secondary">Finding Summary</Typography>
                <Typography variant="body2" sx={{ mt: 0.5 }}>{finding.summary}</Typography>
              </Box>

              <Stack direction="row" spacing={3} sx={{ pt: 1, borderTop: 1, borderColor: 'divider' }}>
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Case Status</Typography>
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {caseData.case_status.charAt(0).toUpperCase() + caseData.case_status.slice(1)}
                    </Typography>
                    {caseData.case_status === 'resolved' && <Typography sx={{ fontSize: '1.2rem' }}>🟢</Typography>}
                    {caseData.case_status === 'in_progress' && <Typography sx={{ fontSize: '1.2rem' }}>🟡</Typography>}
                    {caseData.case_status === 'open' && <Typography sx={{ fontSize: '1.2rem' }}>🔴</Typography>}
                  </Stack>
                </Box>

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Investigation</Typography>
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {caseData.investigation_status === 'completed' ? 'Completed' : caseData.investigation_status === 'in_progress' ? 'In Progress' : 'Not Started'}
                    </Typography>
                    {caseData.investigation_status === 'completed' && <Typography sx={{ fontSize: '1.2rem' }}>✅</Typography>}
                    {caseData.investigation_status === 'in_progress' && <Typography sx={{ fontSize: '1.2rem' }}>🔄</Typography>}
                  </Stack>
                </Box>

                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>Memory Status</Typography>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {caseData.memory_status === 'not_indexed' && 'Not Indexed'}
                        {caseData.memory_status === 'indexing' && 'Indexing...'}
                        {caseData.memory_status === 'indexed' && 'Indexed'}
                        {caseData.memory_status === 'stale' && 'Update Available'}
                        {caseData.memory_status === 'failed' && 'Failed'}
                      </Typography>
                      {caseData.memory_status === 'indexed' && <Typography sx={{ fontSize: '1rem' }}>✅</Typography>}
                      {caseData.memory_status === 'indexing' && <CircularProgress size={16} sx={{ ml: 1 }} />}
                      {caseData.memory_status === 'stale' && <Typography sx={{ fontSize: '1rem' }}>⚠️</Typography>}
                      {caseData.memory_status === 'failed' && <Typography sx={{ fontSize: '1rem' }}>❌</Typography>}
                    </Stack>
                    
                    {(caseData.memory_status === 'not_indexed' || caseData.memory_status === 'stale' || caseData.memory_status === 'failed') && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => indexMemoryMutation.mutate()}
                        disabled={indexMemoryMutation.isPending}
                        sx={{ ml: 'auto' }}
                      >
                        {indexMemoryMutation.isPending ? 'Indexing...' : 'Add to Memory'}
                      </Button>
                    )}
                  </Stack>
                </Box>
              </Stack>

              <Stack direction="row" spacing={2} sx={{ pt: 1 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Severity</Typography>
                  <Chip
                    label={finding.health_status.charAt(0).toUpperCase() + finding.health_status.slice(1)}
                    color={getHealthColor(finding.health_status)}
                    size="small"
                    sx={{ mt: 0.5 }}
                  />
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Importance</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5, fontWeight: 700 }}>
                    {(finding.importance_score * 100).toFixed(0)}%
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Category</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    {getCategoryLabel(finding.category)}
                  </Typography>
                </Box>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      </Box>

      {/* Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tabValue} onChange={(e, newValue) => setTabValue(newValue)}>
          <Tab label="Summary" id="case-tab-0" aria-controls="case-tabpanel-0" />
          <Tab label="Evidence" id="case-tab-1" aria-controls="case-tabpanel-1" />
          <Tab label="Investigation" id="case-tab-2" aria-controls="case-tabpanel-2" />
          <Tab label="RCA" id="case-tab-3" aria-controls="case-tabpanel-3" />
          <Tab label="Resolution" id="case-tab-4" aria-controls="case-tabpanel-4" />
          <Tab label="Similar Cases" id="case-tab-5" aria-controls="case-tabpanel-5" />
        </Tabs>
      </Box>

      {/* Tab Panels */}
      <TabPanel value={tabValue} index={0}>
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>Case Overview</Typography>
              <Stack spacing={2}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Title</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{caseData.case_title}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Status</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{caseData.case_status}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Created</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    {new Date(caseData.created_at).toLocaleString()}
                  </Typography>
                </Box>
                {caseData.resolved_at && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">Resolved</Typography>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      {new Date(caseData.resolved_at).toLocaleString()}
                    </Typography>
                  </Box>
                )}
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>Finding Details</Typography>
              <Stack spacing={2}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Finding Title</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{finding.title}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Metric</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>{finding.metric_name}</Typography>
                </Box>
                {finding.service && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">Service</Typography>
                    <Typography variant="body2" sx={{ mt: 0.5 }}>{finding.service}</Typography>
                  </Box>
                )}
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </TabPanel>

      <TabPanel value={tabValue} index={1}>
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>Anomaly Windows</Typography>
              <Typography variant="body2" sx={{ mb: 2 }}>
                {finding.signal_ids.length} anomaly window{finding.signal_ids.length !== 1 ? 's' : ''} detected
              </Typography>
              
              {finding.signal_ids.length > 0 && (
                <Box sx={{ backgroundColor: '#f5f5f5', p: 2, borderRadius: 1, maxHeight: 400, overflowY: 'auto' }}>
                  <Typography variant="caption" sx={{ display: 'block', mb: 1, fontWeight: 600 }}>Signal IDs:</Typography>
                  {finding.signal_ids.map((id) => (
                    <Typography key={id} variant="caption" component="div" sx={{ fontFamily: 'monospace', fontSize: '0.75rem', mb: 0.5 }}>
                      {id}
                    </Typography>
                  ))}
                </Box>
              )}
            </CardContent>
          </Card>

          {Object.keys(finding.comparison_json).length > 0 && (
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 2 }}>Comparison Analysis</Typography>
                <Box sx={{ backgroundColor: '#f5f5f5', p: 2, borderRadius: 1, maxHeight: 300, overflowY: 'auto' }}>
                  <Typography variant="caption" component="pre" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: '0.75rem' }}>
                    {JSON.stringify(finding.comparison_json, null, 2)}
                  </Typography>
                </Box>
              </CardContent>
            </Card>
          )}
        </Stack>
      </TabPanel>

      <TabPanel value={tabValue} index={2}>
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>Update Investigation</Typography>
              <Stack spacing={2}>
                <FormControl fullWidth>
                  <InputLabel>Status</InputLabel>
                  <Select
                    value={investigationStatus}
                    onChange={(e) => setInvestigationStatus(e.target.value)}
                    label="Status"
                  >
                    <MenuItem value="not_started">Not Started</MenuItem>
                    <MenuItem value="in_progress">In Progress</MenuItem>
                    <MenuItem value="completed">Completed</MenuItem>
                  </Select>
                </FormControl>

                <TextField
                  label="Add Investigation Note"
                  multiline
                  rows={3}
                  value={investigationNote}
                  onChange={(e) => setInvestigationNote(e.target.value)}
                  placeholder="Add notes about your investigation..."
                />

                <Button
                  variant="contained"
                  onClick={() => updateInvestigationMutation.mutate()}
                  disabled={updateInvestigationMutation.isPending}
                >
                  {updateInvestigationMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                  Update Investigation
                </Button>
              </Stack>
            </CardContent>
          </Card>

          {caseData.investigation_notes.length > 0 && (
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 2 }}>Investigation Notes</Typography>
                <Stack spacing={1}>
                  {caseData.investigation_notes.map((note, idx) => (
                    <Box key={idx} sx={{ p: 1.5, backgroundColor: '#f5f5f5', borderRadius: 1 }}>
                      <Typography variant="caption" color="text.secondary">
                        {note.timestamp ? new Date(note.timestamp).toLocaleString() : 'No timestamp'}
                      </Typography>
                      <Typography variant="body2" sx={{ mt: 0.5 }}>{note.note}</Typography>
                    </Box>
                  ))}
                </Stack>
              </CardContent>
            </Card>
          )}
        </Stack>
      </TabPanel>

      <TabPanel value={tabValue} index={3}>
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>Root Cause Analysis</Typography>
              <Stack spacing={2}>
                <FormControl fullWidth>
                  <InputLabel>Status</InputLabel>
                  <Select
                    value={rcaStatus}
                    onChange={(e) => setRcaStatus(e.target.value)}
                    label="Status"
                  >
                    <MenuItem value="unknown">Unknown</MenuItem>
                    <MenuItem value="investigating">Investigating</MenuItem>
                    <MenuItem value="identified">Identified</MenuItem>
                    <MenuItem value="confirmed">Confirmed</MenuItem>
                  </Select>
                </FormControl>

                <TextField
                  label="Root Cause Summary"
                  multiline
                  rows={3}
                  value={rcaSummary}
                  onChange={(e) => setRcaSummary(e.target.value)}
                  placeholder="Describe the root cause..."
                />

                <TextField
                  label="Confidence (0-1)"
                  type="number"
                  inputProps={{ step: 0.01, min: 0, max: 1 }}
                  value={rcaConfidence}
                  onChange={(e) => setRcaConfidence(e.target.value)}
                />

                <FormControlLabel
                  control={
                    <Checkbox
                      checked={rcaVerified}
                      onChange={(e) => setRcaVerified(e.target.checked)}
                    />
                  }
                  label="Verified"
                />

                <Button
                  variant="contained"
                  onClick={() => updateRCAMutation.mutate()}
                  disabled={updateRCAMutation.isPending}
                >
                  {updateRCAMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                  Update RCA
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </TabPanel>

      <TabPanel value={tabValue} index={4}>
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>Resolution & Outcome</Typography>
              <Stack spacing={2}>
                <FormControl fullWidth>
                  <InputLabel>Outcome Status</InputLabel>
                  <Select
                    value={outcomeStatus}
                    onChange={(e) => setOutcomeStatus(e.target.value)}
                    label="Outcome Status"
                  >
                    <MenuItem value="pending">Pending</MenuItem>
                    <MenuItem value="in_progress">In Progress</MenuItem>
                    <MenuItem value="resolved">Resolved</MenuItem>
                    <MenuItem value="escalated">Escalated</MenuItem>
                  </Select>
                </FormControl>

                <TextField
                  label="Outcome Summary"
                  multiline
                  rows={3}
                  value={outcomeSummary}
                  onChange={(e) => setOutcomeSummary(e.target.value)}
                  placeholder="Describe the outcome..."
                />

                <TextField
                  label="Corrective Action"
                  multiline
                  rows={3}
                  value={correctiveAction}
                  onChange={(e) => setCorrectiveAction(e.target.value)}
                  placeholder="Describe actions taken to resolve..."
                />

                <Button
                  variant="contained"
                  onClick={() => updateResolutionMutation.mutate()}
                  disabled={updateResolutionMutation.isPending}
                >
                  {updateResolutionMutation.isPending ? <CircularProgress size={20} sx={{ mr: 1 }} /> : null}
                  Update Resolution
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </TabPanel>

      <TabPanel value={tabValue} index={5}>
        {caseData.memory_status === 'indexed' ? (
          <SimilarCasesList caseId={parseInt(caseId || '0')} />
        ) : (
          <Alert severity="info">
            Case needs to be indexed first. {
              caseData.memory_status === 'not_indexed' && 'Click "Add to Memory" to enable similar case search.'
            }
          </Alert>
        )}
      </TabPanel>
    </Box>
  );
}

function SimilarCasesList({ caseId }: { caseId: number }) {
  const { data: similarCases, isLoading, error } = useQuery({
    queryKey: ['similarCases', caseId],
    queryFn: () => api.getSimilarCases(caseId, 5, 0.7),
  });

  if (isLoading) return <CircularProgress />;
  if (error) return <Alert severity="error">Failed to load similar cases</Alert>;

  if (!similarCases?.matches || similarCases.matches.length === 0) {
    return <Alert severity="info">No similar cases found</Alert>;
  }

  return (
    <Stack spacing={2}>
      {similarCases.matches.map((match: any) => (
        <Box key={match.case_id} sx={{ border: '1px solid #ddd', p: 2, borderRadius: 1 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
            <Box>
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {match.title}
              </Typography>
              <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
                <Typography variant="caption">
                  <strong>Service:</strong> {match.service}
                </Typography>
                <Typography variant="caption">
                  <strong>Metric:</strong> {match.metric_name}
                </Typography>
                <Typography variant="caption">
                  <strong>Status:</strong> {match.case_status}
                </Typography>
              </Stack>
              {match.root_cause_summary && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    <strong>RCA:</strong> {match.root_cause_summary}
                  </Typography>
                </Box>
              )}
              {match.corrective_action && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    <strong>Action:</strong> {match.corrective_action}
                  </Typography>
                </Box>
              )}
            </Box>
            <Box sx={{ textAlign: 'right' }}>
              <Typography variant="h6" sx={{ fontWeight: 700, color: '#2196F3' }}>
                {(match.similarity_score * 100).toFixed(0)}%
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Similarity
              </Typography>
              <Box sx={{ mt: 1 }}>
                <Button
                  size="small"
                  variant="text"
                  onClick={() => window.location.href = `/cases/${match.case_id}`}
                >
                  View Case
                </Button>
              </Box>
            </Box>
          </Stack>
        </Box>
      ))}
    </Stack>
  );
}
