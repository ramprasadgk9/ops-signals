import { useState, useEffect } from 'react';
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
    },
    onError: (err: any) => {
      setErrorMessage(err.message || 'Failed to promote comment to note');
    },
  });

  const handleResolveSubmit = () => {
    resolveMutation.mutate({
      action: resolutionAction,
      remote_key: resolutionAction === 'link_existing' ? remoteKeyInput.trim() : undefined,
    });
  };

  const ticket = ticketQuery.data;
  const isOperating = createMutation.isPending || syncMutation.isPending || Boolean(activeOpId);

  return (
    <Card variant="outlined" sx={{ mt: 2 }}>
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Stack direction="row" spacing={1} alignItems="center">
              <ConfirmationNumberRoundedIcon color="primary" />
              <Typography variant="h6">External Ticketing</Typography>
            </Stack>
            {ticket && (
              <Button
                size="small"
                variant="outlined"
                startIcon={<SyncRoundedIcon />}
                disabled={isOperating}
                onClick={() => syncMutation.mutate()}
              >
                {syncMutation.isPending ? 'Syncing...' : 'Sync Now'}
              </Button>
            )}
          </Stack>

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
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
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
                              color="success"
                              icon={<CheckCircleRoundedIcon sx={{ fontSize: '14px !important' }} />}
                              label="Added to notes"
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
    </Card>
  );
}
