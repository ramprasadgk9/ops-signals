import { useState } from 'react';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Typography,
} from '@mui/material';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import ConfirmationNumberRoundedIcon from '@mui/icons-material/ConfirmationNumberRounded';
import PlayCircleOutlineRoundedIcon from '@mui/icons-material/PlayCircleOutlineRounded';
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

const DISMISSED_KEY = 'ops-signals.jira-ticketing-hint.dismissed';

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

/** Shown on a case while ticketing is off, where the External Ticketing card would be: the feature
 * otherwise stays invisible until someone already knows to turn it on. Dismissing it is remembered
 * in this browser. */
export function JiraTicketingHint() {
  const [dismissed, setDismissed] = useState(readDismissed);
  const [videoOpen, setVideoOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);

  if (dismissed) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // Private windows can refuse storage; the hint then just comes back next time.
    }
  };

  return (
    <>
      <Box
        data-testid="jira-ticketing-hint"
        sx={{ mt: 2, px: 1.5, py: 1, border: 1, borderColor: 'divider', borderRadius: 1, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}
      >
        <ConfirmationNumberRoundedIcon fontSize="small" color="action" />
        <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
          Track this case in Jira
        </Typography>
        <Button size="small" startIcon={<PlayCircleOutlineRoundedIcon />} onClick={() => setVideoOpen(true)} sx={{ textTransform: 'none' }}>
          Watch how (1 min)
        </Button>
        <Button size="small" onClick={() => setSetupOpen(true)} sx={{ textTransform: 'none' }}>
          How to turn it on
        </Button>
        <IconButton size="small" aria-label="Hide this tip" onClick={dismiss}>
          <CloseRoundedIcon fontSize="small" />
        </IconButton>
      </Box>

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

      <Dialog open={setupOpen} onClose={() => setSetupOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 900 }}>Turn on Jira ticketing</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.5} component="ol" sx={{ pl: 2.5, m: 0 }}>
            <Typography component="li" variant="body2">
              In Jira Cloud, create an API token: <strong>id.atlassian.com → Security → API tokens</strong>.
            </Typography>
            <Typography component="li" variant="body2">
              Set these on the Ops Signals backend:
              <Box component="pre" sx={{ mt: 1, mb: 0, p: 1.5, bgcolor: 'action.hover', borderRadius: 1, fontSize: 13, overflowX: 'auto' }}>
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
              Restart the backend. Every case then shows <strong>External Ticketing</strong> with <strong>Create Jira Ticket</strong>.
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
