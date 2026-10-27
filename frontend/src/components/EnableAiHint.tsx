import { useState } from 'react';
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import { AI_SETUP, aiHintDismissed, dismissAiHint } from '../utils/findingPlain';

// Under a finding's plain wording when no AI provider is on, for people who can turn one on: once,
// until they choose "Not now". The how-to sits right here, next to the lines it would improve.

export function EnableAiHint() {
  const [dismissed, setDismissed] = useState(aiHintDismissed);
  const [open, setOpen] = useState(false);
  if (dismissed) return null;
  return (
    <Box data-testid="enable-ai-hint" sx={{ borderTop: 1, borderColor: 'divider', pt: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ fontSize: 13 }}>
        These lines are the same for every finding of this kind. Turn on AI to have them written for this metric and service.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
        <Button size="small" onClick={() => setOpen(true)} sx={{ textTransform: 'none', px: 0, minWidth: 0 }}>
          How to turn it on
        </Button>
        <Button
          size="small"
          color="inherit"
          onClick={() => {
            dismissAiHint();
            setDismissed(true);
          }}
          sx={{ textTransform: 'none', color: 'text.secondary' }}
        >
          Not now
        </Button>
      </Stack>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth aria-labelledby="enable-ai-title">
        <DialogTitle id="enable-ai-title">Turn on AI wording</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>{AI_SETUP.intro}</Typography>
          <Box component="ol" sx={{ m: 0, pl: 2.5, display: 'grid', gap: 1.5 }}>
            {AI_SETUP.steps.map((step) => (
              <li key={step.text}>
                <Typography variant="body2">{step.text}</Typography>
                {step.command ? (
                  <Box component="pre" sx={{ m: 0, mt: 0.5, p: 1, borderRadius: 1, bgcolor: 'action.hover', fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                    {step.command}
                  </Box>
                ) : null}
              </li>
            ))}
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2, fontSize: 13 }}>
            To check the connection, open Integrations → AI provider → Test connection. {AI_SETUP.other}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} sx={{ textTransform: 'none' }}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
