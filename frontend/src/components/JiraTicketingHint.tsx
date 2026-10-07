import { useState } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material';
import ConfirmationNumberRoundedIcon from '@mui/icons-material/ConfirmationNumberRounded';
import PlayCircleOutlineRoundedIcon from '@mui/icons-material/PlayCircleOutlineRounded';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import { WalkthroughVideoDialog } from './WalkthroughVideoDialog';

// Recorded from the real case page by scripts/record_jira_walkthrough.sh.
export const JIRA_WALKTHROUGH = {
  title: 'Track a case in Jira',
  description:
    'Create the ticket from the case, sync comments and status back, then send the resolution to Jira. Recorded on this page.',
  videoPath: 'walkthroughs/jira-ticketing.webm',
  posterPath: 'walkthroughs/jira-ticketing-poster.png',
  videoLabel: 'Jira ticketing walkthrough video',
};

const codeSx = { mt: 1, mb: 0, p: 1.5, bgcolor: 'action.hover', borderRadius: 1, fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } as const;

/** A banner at the top of the Cases list and of each case while ticketing is off: without it the
 * feature stays invisible until someone already knows to turn it on (the External Ticketing card
 * only appears once it is on). Deliberately not dismissible, so everyone sees that it exists.
 * Renders nothing while ticketing is on, or when the status can't be read. */
export function JiraTicketingHint({ subject = 'cases' }: { subject?: 'cases' | 'case' }) {
  const [videoOpen, setVideoOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const statusQuery = useQuery({
    queryKey: ['ticketingStatus'],
    queryFn: () => api.ticketingStatus(),
    staleTime: 60_000,
  });

  if (!statusQuery.isSuccess || statusQuery.data.enabled) return null;

  return (
    <>
      <Alert
        data-testid="jira-ticketing-hint"
        severity="info"
        icon={<ConfirmationNumberRoundedIcon />}
        action={
          <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap', rowGap: 1 }}>
            <Button
              size="small"
              variant="contained"
              startIcon={<PlayCircleOutlineRoundedIcon />}
              onClick={() => setVideoOpen(true)}
              sx={{ textTransform: 'none', fontWeight: 800, whiteSpace: 'nowrap' }}
            >
              Watch how (1 min)
            </Button>
            <Button
              size="small"
              variant="outlined"
              color="inherit"
              onClick={() => setSetupOpen(true)}
              sx={{ textTransform: 'none', fontWeight: 800, whiteSpace: 'nowrap' }}
            >
              How to turn it on
            </Button>
          </Stack>
        }
        sx={{ alignItems: 'center', border: 1, borderColor: 'info.light', '& .MuiAlert-action': { pt: 0, mr: 0 } }}
      >
        <AlertTitle sx={{ fontWeight: 800, mb: 0.25 }}>
          {subject === 'case' ? 'Track this case in Jira' : 'Track cases in Jira'}
        </AlertTitle>
        Create a Jira ticket from any case, and keep its comments, status and resolution in sync. Jira ticketing is
        off on this server.
      </Alert>

      <WalkthroughVideoDialog
        open={videoOpen}
        onClose={() => setVideoOpen(false)}
        {...JIRA_WALKTHROUGH}
        action={
          <Button
            variant="contained"
            onClick={() => {
              setVideoOpen(false);
              setSetupOpen(true);
            }}
            sx={{ textTransform: 'none', fontWeight: 850 }}
          >
            How to turn it on
          </Button>
        }
      />

      <Dialog open={setupOpen} onClose={() => setSetupOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ fontWeight: 900 }}>Turn on Jira ticketing</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.5} component="ol" sx={{ pl: 2.5, m: 0 }}>
            <Typography component="li" variant="body2">
              In Jira Cloud, create an API token: <strong>id.atlassian.com → Security → API tokens</strong>.
            </Typography>
            <Typography component="li" variant="body2">
              Add these settings to the <code>.env</code> file in the Ops Signals folder (on Kubernetes, see below):
              <Box component="pre" sx={codeSx}>
                {[
                  'OPS_SIGNALS_TICKETING_ENABLED=true',
                  'OPS_SIGNALS_JIRA_BASE_URL=https://your-site.atlassian.net',
                  'OPS_SIGNALS_JIRA_EMAIL=you@example.com',
                  'OPS_SIGNALS_JIRA_API_TOKEN=<the token>',
                  'OPS_SIGNALS_JIRA_PROJECT_KEY=OPS',
                ].join('\n')}
              </Box>
            </Typography>
            <Typography component="li" variant="body2">
              Restart the backend so it reads them. How depends on how you run Ops Signals:
              <Stack component="ul" spacing={1} sx={{ pl: 2.5, mt: 1, mb: 0 }}>
                <Typography component="li" variant="body2">
                  <strong>On your laptop</strong> (<code>./scripts/run_all.sh</code>): press Ctrl+C in its terminal, then run it again.
                </Typography>
                <Typography component="li" variant="body2">
                  <strong>On a team server</strong> (Docker Compose): in the Ops Signals folder, run
                  <Box component="pre" sx={codeSx}>docker compose -f docker-compose.packaged.yml up -d backend</Box>
                </Typography>
                <Typography component="li" variant="body2">
                  <strong>On Kubernetes</strong> (Helm): put the settings as keys in the Secret named by{' '}
                  <code>prometheusConnections.secretName</code> (its keys become the backend's settings), then restart the backend
                  deployment:
                  <Box component="pre" sx={codeSx}>
                    kubectl rollout restart deployment -l app.kubernetes.io/instance=&lt;release&gt;,app.kubernetes.io/component=backend
                  </Box>
                </Typography>
              </Stack>
            </Typography>
            <Typography component="li" variant="body2">
              Reload this page. Every case then shows <strong>External Ticketing</strong> with <strong>Create Jira Ticket</strong>, and
              this banner goes away.
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
            The issue type defaults to Task; every setting is listed in docs/configuration.md.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSetupOpen(false)} sx={{ textTransform: 'none', fontWeight: 800 }}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
