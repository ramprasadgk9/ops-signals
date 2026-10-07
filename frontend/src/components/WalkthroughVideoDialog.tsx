import type { ReactNode } from 'react';
import { Box, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material';

/** A recorded walkthrough (frontend/public/walkthroughs/) played in a dialog, next to the action it
 * explains. Paths are relative to the app's base URL. */
export function WalkthroughVideoDialog({
  open,
  onClose,
  title,
  description,
  videoPath,
  posterPath,
  videoLabel,
  action,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  videoPath: string;
  posterPath: string;
  videoLabel: string;
  action?: ReactNode;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ fontWeight: 900 }}>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 1.5 }}>{description}</DialogContentText>
        <Box
          component="video"
          src={`${import.meta.env.BASE_URL}${videoPath}`}
          poster={`${import.meta.env.BASE_URL}${posterPath}`}
          controls
          autoPlay
          aria-label={videoLabel}
          sx={{ display: 'block', width: '100%', maxHeight: '65vh', borderRadius: 2, bgcolor: '#0b1020' }}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={{ textTransform: 'none', fontWeight: 800 }}>
          Close
        </Button>
        {action}
      </DialogActions>
    </Dialog>
  );
}
