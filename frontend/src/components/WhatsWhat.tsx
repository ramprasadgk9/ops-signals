import { useState } from 'react';
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import { ui } from '../standalone/theme';
import { CHAIN, CHAIN_INTRO, GLOSSARY_URL, PAGE_GLOSSARY, type GlossaryPage } from '../utils/glossaryTerms';

/** "What's what?" at the end of a page subtitle: the signal → finding → case → memory chain with this
 * page's step highlighted, the words this page uses, and a link to the full glossary. */
export function WhatsWhat({ page }: { page: GlossaryPage }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="text"
        size="small"
        onClick={() => setOpen(true)}
        sx={{ textTransform: 'none', fontWeight: 750, p: 0, ml: 0.75, minWidth: 0, verticalAlign: 'baseline', lineHeight: 'inherit', fontSize: 'inherit', borderBottom: `1px dashed currentColor`, borderRadius: 0 }}
      >
        What's what?
      </Button>
      <WhatsWhatDialog page={page} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

export function WhatsWhatDialog({ page, open, onClose }: { page: GlossaryPage; open: boolean; onClose: () => void }) {
  const { step: current, terms } = PAGE_GLOSSARY[page];
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth aria-labelledby="whats-what-title">
      <DialogTitle id="whats-what-title" sx={{ fontWeight: 850, pr: 6 }}>
        What's what?
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: 'absolute', right: 12, top: 12 }}>
          <CloseRoundedIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Typography sx={{ fontSize: 14, mb: 1.5 }}>{CHAIN_INTRO}</Typography>
        <Box component="ol" aria-label="From signal to memory" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(4, 1fr)' }, gap: 1.25, m: 0, p: 0, listStyle: 'none' }}>
          {CHAIN.map((item) => {
            const here = item.step === current;
            return (
              <Box
                component="li"
                key={item.step}
                aria-current={here ? 'page' : undefined}
                sx={{ border: here ? `2px solid ${ui.blue}` : `1px solid ${ui.border}`, bgcolor: here ? 'var(--os-tint-blue, #eef2ff)' : 'transparent', borderRadius: '10px', p: 1.25 }}
              >
                <Typography sx={{ fontSize: 14, fontWeight: 800 }}>{item.title}</Typography>
                <Typography sx={{ fontSize: 13, lineHeight: 1.4 }}>{item.text}</Typography>
                <Typography sx={{ fontSize: 11.5, color: ui.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em', mt: 0.75 }}>
                  {here ? 'This page' : item.who}
                </Typography>
              </Box>
            );
          })}
        </Box>
        <Typography component="h3" sx={{ fontSize: 12.5, color: ui.muted, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.04em', mt: 2.5, mb: 0.5 }}>
          Words on this page
        </Typography>
        <Box component="dl" sx={{ m: 0 }}>
          {terms.map((item) => (
            <Box key={item.term} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '170px 1fr' }, gap: { xs: 0.25, sm: 1.25 }, py: 0.9, borderBottom: `1px solid ${ui.border}`, '&:last-of-type': { borderBottom: 'none' } }}>
              <Typography component="dt" sx={{ fontSize: 13.5, fontWeight: 750 }}>{item.term}</Typography>
              <Typography component="dd" sx={{ fontSize: 13.5, m: 0 }}>{item.text}</Typography>
            </Box>
          ))}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 1.5, justifyContent: 'space-between' }}>
        <Button component="a" href={GLOSSARY_URL} target="_blank" rel="noopener noreferrer" endIcon={<OpenInNewRoundedIcon fontSize="small" />} sx={{ textTransform: 'none', fontWeight: 750 }}>
          Full glossary
        </Button>
        <Button variant="outlined" onClick={onClose} sx={{ textTransform: 'none', fontWeight: 750 }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
