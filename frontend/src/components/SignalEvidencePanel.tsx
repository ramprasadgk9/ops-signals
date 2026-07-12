import { Accordion, AccordionDetails, AccordionSummary, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { Signal } from '../types';

type Props = {
  signals: Signal[];
};

export function SignalEvidencePanel({ signals }: Props) {
  return (
    <div>
      <Typography variant="h6" sx={{ mt: 2 }}>Evidence</Typography>
      {signals.map((signal) => (
        <Accordion key={signal.id}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography>{signal.signal_type} | {signal.summary}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(signal.evidence, null, 2)}</pre>
          </AccordionDetails>
        </Accordion>
      ))}
    </div>
  );
}
