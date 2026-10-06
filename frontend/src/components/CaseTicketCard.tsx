import { useState, useEffect, useMemo } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  Radio,
  RadioGroup,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import ConfirmationNumberRoundedIcon from '@mui/icons-material/ConfirmationNumberRounded';
import WarningAmberRoundedIcon from '@mui/icons-material/WarningAmberRounded';
import NoteAddRoundedIcon from '@mui/icons-material/NoteAddRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded';
import CableRoundedIcon from '@mui/icons-material/CableRounded';
import TaskAltRoundedIcon from '@mui/icons-material/TaskAltRounded';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { AmbiguousResolutionPayload, CaseTicketOperation } from '../types';

interface CaseTicketCardProps {
  caseId: number;
}

export function CaseTicketCard({ caseId }: CaseTicketCardProps) {
  const queryClient = useQueryClient();
  const [activeOpId, setActiveOpId] = useState<string | null>(null);
  const [ambiguousOp, setAmbiguousOp] = useState<CaseTicketOperation | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [resolutionAction, setResolutionAction] = useState<'check_again' | 'link_existing' | 'force_create_new'>('check_again');
  const [remoteKeyInput, setRemoteKeyInput] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [triageFeedback, setTriageFeedback] = useState<string | null>(null);
  const [isWebhookGuideOpen, setIsWebhookGuideOpen] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  // 1. Fetch active ticket link
  const ticketQuery = useQuery({
    queryKey: ['caseTicket', caseId],
    queryFn: () => api.getCaseTicket(caseId),
  });

  // 2. Fetch ticket timeline events
  const eventsQuery = useQuery({
    queryKey: ['caseTicketEvents', caseId],
    queryFn: () => api.getCaseTicketEvents(caseId),
    enabled: Boolean(ticketQuery.data),
  });

  // 3. Fetch case details to inspect outcome status
  const caseQuery = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.getCase(caseId),
  });

  // 4. Fetch webhook configuration info
  const webhookQuery = useQuery({
    queryKey: ['ticketingWebhookInfo', 'jira'],
    queryFn: () => api.getTicketingWebhookInfo('jira'),
    enabled: isWebhookGuideOpen,
  });

  // 3. Poll active operation if present
  useEffect(() => {
    if (!activeOpId) return;
    const interval = setInterval(async () => {
      try {
        const op = await api.getCaseTicketOperation(caseId, activeOpId);
        if (op.status === 'completed') {
          setActiveOpId(null);
          setAmbiguousOp(null);
          queryClient.invalidateQueries({ queryKey: ['caseTicket', caseId] });
          queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
          queryClient.invalidateQueries({ queryKey: ['case'] });
          queryClient.invalidateQueries({ queryKey: ['cases'] });
          queryClient.invalidateQueries({ queryKey: ['cases-investigations'] });
        } else if (op.status === 'ambiguous_outcome') {
          setActiveOpId(null);
          setAmbiguousOp(op);
        } else if (op.status === 'failed') {
          setActiveOpId(null);
          setErrorMessage(op.last_error || 'Operation failed');
        }
      } catch (err: any) {
        setActiveOpId(null);
        setErrorMessage(err.message || 'Error tracking operation');
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [activeOpId, caseId, queryClient]);

  // Mutations
  const createMutation = useMutation({
    mutationFn: () => api.createCaseTicket(caseId),
    onSuccess: (data) => {
      setErrorMessage(null);
      if (data.status === 'completed') {
        queryClient.invalidateQueries({ queryKey: ['caseTicket', caseId] });
      } else if (data.status === 'ambiguous_outcome') {
        setAmbiguousOp(data);
      } else {
        setActiveOpId(data.operation_id);
      }
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to request ticket creation');
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => api.syncCaseTicket(caseId),
    onSuccess: (data) => {
      setErrorMessage(null);
      if (data.status === 'completed') {
        queryClient.invalidateQueries({ queryKey: ['caseTicket', caseId] });
        queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
        queryClient.invalidateQueries({ queryKey: ['case'] });
        queryClient.invalidateQueries({ queryKey: ['cases'] });
        queryClient.invalidateQueries({ queryKey: ['cases-investigations'] });
      } else {
        setActiveOpId(data.operation_id);
      }
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to sync ticket');
    },
  });

  const resolveMutation = useMutation({
    mutationFn: (payload: AmbiguousResolutionPayload) =>
      api.resolveAmbiguousTicket(caseId, payload),
    onSuccess: () => {
      setIsModalOpen(false);
      setAmbiguousOp(null);
      queryClient.invalidateQueries({ queryKey: ['caseTicket', caseId] });
      queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to resolve ambiguity');
    },
  });

  const promoteMutation = useMutation({
    mutationFn: (eventId: number) => api.promoteTicketCommentToNote(caseId, eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case'] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['cases-investigations'] });
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to promote comment to note');
    },
  });

  const triageMutation = useMutation({
    mutationFn: () => api.triageCaseTicketComments(caseId),
    onSuccess: (data) => {
      setErrorMessage(null);
      if (data.promoted_count > 0) {
        setTriageFeedback(
          `AI Triage complete: auto-promoted ${data.promoted_count} operational clue${data.promoted_count > 1 ? 's' : ''} into case notes.`
        );
      } else if (data.evaluated_count > 0) {
        setTriageFeedback('AI Triage evaluated new comments, but no substantive operational clues were found.');
      } else {
        setTriageFeedback('No unpromoted comments to evaluate.');
      }
      queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
      queryClient.invalidateQueries({ queryKey: ['case'] });
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      queryClient.invalidateQueries({ queryKey: ['cases-investigations'] });
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to triage comments with AI');
    },
  });

  const resolveTicketMutation = useMutation({
    mutationFn: () => api.resolveCaseTicket(caseId),
    onSuccess: (data) => {
      setErrorMessage(null);
      if (data) {
        if (data.status === 'completed') {
          queryClient.invalidateQueries({ queryKey: ['caseTicket', caseId] });
          queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
        } else {
          setActiveOpId(data.operation_id);
        }
      }
      queryClient.invalidateQueries({ queryKey: ['caseTicket', caseId] });
      queryClient.invalidateQueries({ queryKey: ['caseTicketEvents', caseId] });
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to sync resolution to Jira');
    },
  });

  const ticket = ticketQuery.data;

  const webhookTargetUrl = useMemo(() => {
    const backendUrl = webhookQuery.data?.webhook_url;
    if (backendUrl && (backendUrl.startsWith('http://') || backendUrl.startsWith('https://'))) {
      return backendUrl;
    }
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origin}${backendUrl || '/api/integrations/ticketing/jira/webhook'}`;
  }, [webhookQuery.data?.webhook_url]);

  const jiraWebhookAdminUrl = useMemo(() => {
    if (ticket?.ticket_url) {
      try {
        const origin = new URL(ticket.ticket_url).origin;
        return `${origin}/plugins/servlet/webhooks`;
      } catch {
        return null;
      }
    }
    return null;
  }, [ticket?.ticket_url]);

  const handleCopyWebhookUrl = () => {
    navigator.clipboard.writeText(webhookTargetUrl);
    setCopiedUrl(true);
    setTimeout(() => setCopiedUrl(false), 2000);
  };

  const handleResolveSubmit = () => {
    resolveMutation.mutate({
      action: resolutionAction,
      remote_key: resolutionAction === 'link_existing' ? remoteKeyInput.trim() : undefined,
    });
  };
  const isOperating =
    createMutation.isPending ||
    syncMutation.isPending ||
    resolveTicketMutation.isPending ||
    Boolean(activeOpId);
  const isCaseResolved =
    caseQuery.data?.outcome_status === 'resolved' ||
    caseQuery.data?.outcome_status === 'mitigated';
  const resolutionPostedEvent = eventsQuery.data?.find(
    (e) => e.event_type === 'resolution_posted'
  );

  return (
    <Card variant="outlined" sx={{ mt: 2 }}>
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Stack direction="row" spacing={1} alignItems="center">
              <ConfirmationNumberRoundedIcon color="primary" />
              <Typography variant="h6">External Ticketing</Typography>
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <Button
                size="small"
                variant="text"
                startIcon={<CableRoundedIcon />}
                onClick={() => setIsWebhookGuideOpen(true)}
                sx={{ textTransform: 'none' }}
              >
                Webhook Setup
              </Button>
              {ticket && (
                <>
                  <Button
                    size="small"
                    variant="outlined"
                    color="secondary"
                    startIcon={
                      triageMutation.isPending ? (
                        <CircularProgress size={14} color="inherit" />
                      ) : (
                        <AutoAwesomeRoundedIcon sx={{ fontSize: '15px !important' }} />
                      )
                    }
                    disabled={isOperating || triageMutation.isPending}
                    onClick={() => triageMutation.mutate()}
                    sx={{ textTransform: 'none' }}
                  >
                    {triageMutation.isPending ? 'Triaging...' : '⚡ AI Triage'}
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<SyncRoundedIcon />}
                    disabled={isOperating || triageMutation.isPending}
                    onClick={() => syncMutation.mutate()}
                    sx={{ textTransform: 'none' }}
                  >
                    {syncMutation.isPending ? 'Syncing...' : 'Sync Now'}
                  </Button>
                </>
              )}
            </Stack>
          </Stack>

          {triageFeedback && (
            <Alert severity="info" onClose={() => setTriageFeedback(null)}>
              {triageFeedback}
            </Alert>
          )}

          {errorMessage && (
            <Alert severity="error" onClose={() => setErrorMessage(null)}>
              {errorMessage}
            </Alert>
          )}

          {/* Ambiguous State Warning Banner */}
          {ambiguousOp && (
            <Alert
              severity="warning"
              icon={<WarningAmberRoundedIcon />}
              action={
                <Button color="inherit" size="small" onClick={() => setIsModalOpen(true)}>
                  Resolve
                </Button>
              }
            >
              <AlertTitle>Creation Outcome Uncertain</AlertTitle>
              A remote timeout or gateway error occurred while contacting Jira. An issue may already have been created.
            </Alert>
          )}

          {/* Ticket Body: Linked vs Unlinked */}
          {ticket ? (
            <Box sx={{ p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }} justifyContent="space-between">
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Remote Issue ({ticket.provider})
                  </Typography>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5, flexWrap: 'wrap', gap: 1 }}>
                    <Chip
                      label={ticket.display_key}
                      color="primary"
                      clickable
                      component="a"
                      href={ticket.ticket_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      icon={<OpenInNewRoundedIcon fontSize="small" />}
                    />
                    <Chip
                      label={ticket.observed_remote_status || 'Unknown'}
                      color={
                        ticket.observed_remote_status?.toLowerCase().includes('done') ||
                        ticket.observed_remote_status?.toLowerCase().includes('resolved')
                          ? 'success'
                          : 'default'
                      }
                      size="small"
                    />
                    {isCaseResolved && (
                      resolutionPostedEvent ? (
                        <Chip
                          icon={<TaskAltRoundedIcon />}
                          label={
                            resolutionPostedEvent.summary.includes('transitioned to')
                              ? 'Resolution Synced to Jira ✓'
                              : 'Resolution Posted ✓'
                          }
                          color="success"
                          variant="outlined"
                          size="small"
                        />
                      ) : (
                        <Button
                          size="small"
                          variant="contained"
                          color="success"
                          startIcon={
                            resolveTicketMutation.isPending ? (
                              <CircularProgress size={12} color="inherit" />
                            ) : (
                              <TaskAltRoundedIcon sx={{ fontSize: '15px !important' }} />
                            )
                          }
                          disabled={isOperating || resolveTicketMutation.isPending}
                          onClick={() => resolveTicketMutation.mutate()}
                          sx={{ textTransform: 'none', height: 26, fontSize: '0.75rem' }}
                        >
                          {resolveTicketMutation.isPending ? 'Syncing...' : 'Sync Resolution to Jira'}
                        </Button>
                      )
                    )}
                  </Stack>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Last Synced
                  </Typography>
                  <Typography variant="body2" sx={{ mt: 0.5 }}>
                    {ticket.last_synced_at
                      ? new Date(ticket.last_synced_at).toLocaleString()
                      : 'Just now'}
                  </Typography>
                </Box>
              </Stack>
            </Box>
          ) : (
            <Box sx={{ py: 1 }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                Link this operational investigation to a Jira Cloud tracking ticket.
              </Typography>
              <Stack direction="row" spacing={2} alignItems="center">
                <Button
                  variant="contained"
                  disabled={isOperating}
                  onClick={() => createMutation.mutate()}
                >
                  {isOperating ? (
                    <Stack direction="row" spacing={1} alignItems="center">
                      <CircularProgress size={16} color="inherit" />
                      <span>Creating Jira Ticket...</span>
                    </Stack>
                  ) : (
                    'Create Jira Ticket'
                  )}
                </Button>
              </Stack>
            </Box>
          )}

          {/* External Timeline Events Feed */}
          {ticket && eventsQuery.data && eventsQuery.data.length > 0 && (
            <Box sx={{ pt: 1 }}>
              <Divider sx={{ mb: 1.5 }} />
              <Typography variant="overline" color="text.secondary">
                External Activity Feed
              </Typography>
              <Stack spacing={1} sx={{ mt: 1 }}>
                {eventsQuery.data.map((evt) => (
                  <Box
                    key={evt.id}
                    sx={{
                      p: 1.5,
                      border: 1,
                      borderColor: 'divider',
                      borderRadius: 1,
                      bgcolor: 'background.paper',
                    }}
                  >
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Chip size="small" variant="outlined" label={evt.event_type.replace('_', ' ')} />
                        {evt.author && (
                          <Typography variant="caption" color="text.secondary">
                            by {evt.author}
                          </Typography>
                        )}
                      </Stack>
                      <Stack direction="row" spacing={1} alignItems="center">
                        {(evt.event_type === 'comment_added' || evt.event_type === 'comment') && (
                          evt.promoted_to_note ? (
                            <Chip
                              size="small"
                              variant="outlined"
                              color={evt.auto_promoted ? 'secondary' : 'success'}
                              icon={
                                evt.auto_promoted ? (
                                  <AutoAwesomeRoundedIcon sx={{ fontSize: '14px !important' }} />
                                ) : (
                                  <CheckCircleRoundedIcon sx={{ fontSize: '14px !important' }} />
                                )
                              }
                              label={evt.auto_promoted ? 'AI Promoted ⚡' : 'Added to notes'}
                              sx={{ height: 22, fontSize: '0.7rem' }}
                            />
                          ) : (
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={
                                promoteMutation.isPending && promoteMutation.variables === evt.id ? (
                                  <CircularProgress size={12} color="inherit" />
                                ) : (
                                  <NoteAddRoundedIcon sx={{ fontSize: '14px !important' }} />
                                )
                              }
                              disabled={promoteMutation.isPending}
                              onClick={() => promoteMutation.mutate(evt.id)}
                              sx={{
                                height: 22,
                                fontSize: '0.7rem',
                                py: 0,
                                px: 1,
                                textTransform: 'none',
                              }}
                            >
                              + Add to Notes
                            </Button>
                          )
                        )}
                        <Typography variant="caption" color="text.secondary">
                          {new Date(evt.occurred_at).toLocaleTimeString()}
                        </Typography>
                      </Stack>
                    </Stack>
                    <Typography variant="body2" sx={{ mt: 1 }}>
                      {evt.summary}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Box>
          )}
        </Stack>
      </CardContent>

      {/* 3-way Ambiguous Outcome Resolution Modal */}
      <Dialog open={isModalOpen} onClose={() => setIsModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Resolve Remote Ticket Ambiguity</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            The Jira API request did not return a definitive confirmation. To prevent duplicates, choose how to proceed:
          </Typography>
          <FormControl component="fieldset" fullWidth>
            <RadioGroup
              value={resolutionAction}
              onChange={(e) => setResolutionAction(e.target.value as any)}
            >
              <FormControlLabel
                value="check_again"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="subtitle2">Check Jira Again (Recommended)</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Search Jira for the operation correlation label to see if the issue was created.
                    </Typography>
                  </Box>
                }
                sx={{ mb: 1.5 }}
              />
              <FormControlLabel
                value="link_existing"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="subtitle2">Link Existing Ticket</Typography>
                    <Typography variant="caption" color="text.secondary">
                      If you already know the Jira issue key that was created, link it manually.
                    </Typography>
                  </Box>
                }
                sx={{ mb: 1.5 }}
              />
              {resolutionAction === 'link_existing' && (
                <TextField
                  size="small"
                  label="Jira Issue Key"
                  placeholder="e.g. OPS-123"
                  value={remoteKeyInput}
                  onChange={(e) => setRemoteKeyInput(e.target.value)}
                  sx={{ ml: 4, mb: 1.5, width: 250 }}
                />
              )}
              <FormControlLabel
                value="force_create_new"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="subtitle2">Force Create New Ticket</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Disregard the prior attempt and issue a new create request with fresh idempotency keys.
                    </Typography>
                  </Box>
                }
              />
            </RadioGroup>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsModalOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleResolveSubmit}
            disabled={
              resolveMutation.isPending ||
              (resolutionAction === 'link_existing' && !remoteKeyInput.trim())
            }
          >
            {resolveMutation.isPending ? 'Resolving...' : 'Confirm'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Webhook Configuration Guide Modal */}
      <Dialog
        open={isWebhookGuideOpen}
        onClose={() => setIsWebhookGuideOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <CableRoundedIcon color="primary" />
          <span>Jira Webhook Configuration</span>
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2.5}>
            <Typography variant="body2" color="text.secondary">
              Configure Jira Cloud System Webhooks to ingest comments and issue updates instantaneously, eliminating polling delays.
            </Typography>

            <Box sx={{ p: 2, bgcolor: 'action.hover', borderRadius: 1 }}>
              <Typography variant="caption" fontWeight={600} color="text.secondary">
                WEBHOOK TARGET URL
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                <TextField
                  fullWidth
                  size="small"
                  value={webhookTargetUrl}
                  slotProps={{ input: { readOnly: true } }}
                  sx={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
                />
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<ContentCopyRoundedIcon />}
                  onClick={handleCopyWebhookUrl}
                  sx={{ minWidth: 100, textTransform: 'none' }}
                >
                  {copiedUrl ? 'Copied!' : 'Copy'}
                </Button>
              </Stack>
            </Box>

            <Box sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}>
              <Typography variant="caption" fontWeight={600} color="text.secondary">
                SECURITY & DELIVERY HEALTH
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                <Chip
                  size="small"
                  label={
                    webhookQuery.data?.is_secret_configured
                      ? 'HMAC-SHA256 Active'
                      : 'Secret Not Configured'
                  }
                  color={webhookQuery.data?.is_secret_configured ? 'success' : 'warning'}
                />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${webhookQuery.data?.deliveries_count ?? 0} deliveries received`}
                />
              </Stack>
              {webhookQuery.data?.last_delivery_at && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                  Last delivery received at {new Date(webhookQuery.data.last_delivery_at).toLocaleString()}
                </Typography>
              )}
            </Box>

            <Box>
              <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                <Typography variant="subtitle2">
                  Setup Steps in Atlassian Jira Cloud:
                </Typography>
                {jiraWebhookAdminUrl && (
                  <Button
                    component="a"
                    href={jiraWebhookAdminUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    size="small"
                    variant="outlined"
                    startIcon={<OpenInNewRoundedIcon fontSize="small" />}
                    sx={{ textTransform: 'none', fontSize: '0.8rem', py: 0.25 }}
                  >
                    Open Jira Webhooks Console
                  </Button>
                )}
              </Stack>
              <Stack spacing={1} component="ol" sx={{ pl: 2.5, m: 0, fontSize: '0.875rem' }}>
                <Typography component="li" variant="body2">
                  Open Jira Settings ➔ <strong>System</strong> ➔ <strong>Webhooks</strong>
                  {!jiraWebhookAdminUrl && (
                    <Typography component="span" variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      (direct path: <code>https://&lt;your-domain&gt;.atlassian.net/plugins/servlet/webhooks</code>)
                    </Typography>
                  )}.
                </Typography>
                <Typography component="li" variant="body2">
                  Click <strong>Create a Webhook</strong> and paste the target URL above.
                </Typography>
                <Typography component="li" variant="body2">
                  Under <strong>Issue related events</strong>, check:
                  <br />
                  • <strong>Issue:</strong> updated, created
                  <br />
                  • <strong>Comment:</strong> created, updated
                </Typography>
                <Typography component="li" variant="body2">
                  Scroll to bottom and click <strong>Save</strong>. Incoming comments will now triage instantly!
                </Typography>
              </Stack>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setIsWebhookGuideOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
