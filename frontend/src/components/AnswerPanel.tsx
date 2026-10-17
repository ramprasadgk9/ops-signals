import { Alert, Box, Button, Collapse, Divider, IconButton, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { Question, QuestionAnswer, Signal, TimeseriesPoint } from '../types';
import { MetricTimelineChart } from './MetricTimelineChart';
import { SignalEvidencePanel } from './SignalEvidencePanel';

type Props = {
  question: Question | null;
  answer: QuestionAnswer | null;
  signals: Signal[];
  timeseries: TimeseriesPoint[];
};

export function AnswerPanel({ question, answer, signals, timeseries }: Props) {
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const [panelExpanded, setPanelExpanded] = useState(true);

  if (!question) {
    return (
      <Box
        sx={{
          minHeight: 360,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '1px dashed',
          borderColor: 'divider',
          borderRadius: 2,
          bgcolor: 'background.paper',
          p: 3,
        }}
      >
        <Typography color="text.secondary">
          Select a question to see the answer here.
        </Typography>
      </Box>
    );
  }

  if (!answer) {
    return (
      <Box
        sx={{
          minHeight: 360,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '1px dashed',
          borderColor: 'divider',
          borderRadius: 2,
          bgcolor: 'background.paper',
          p: 3,
        }}
      >
        <Typography>Loading answer…</Typography>
      </Box>
    );
  }

  const evidenceSignals = signals.filter((s) => answer.evidence_signal_ids.includes(s.id));

  return (
    <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, bgcolor: 'background.paper', p: 3 }}>
      <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={2} sx={{ mb: panelExpanded ? 1 : 0 }}>
        <Box>
          <Typography variant="h5" sx={{ mb: 1, fontWeight: 700 }}>
            {question.label}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {question.description}
          </Typography>
        </Box>
        <Button size="small" variant="text" onClick={() => setPanelExpanded(!panelExpanded)}>
          {panelExpanded ? 'Collapse' : 'Expand'}
        </Button>
      </Stack>
      <Collapse in={panelExpanded}>
        <Divider sx={{ mb: 3, mt: 2 }} />
        <Stack spacing={3}>
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 600 }}>
            Finding
          </Typography>
          <Typography variant="h6" sx={{ mb: 2 }}>
            {answer.headline}
          </Typography>
        </Box>

        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 600 }}>
            Operational Summary
          </Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
            {answer.answer}
          </Typography>
        </Box>

        {(answer.key_points && answer.key_points.length > 0) && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 600 }}>
              Key Findings
            </Typography>
            <List dense sx={{ pl: 0 }}>
              {answer.key_points.map((point, idx) => (
                <ListItem key={idx} sx={{ pl: 0, py: 0.5 }}>
                  <ListItemText
                    primary={point}
                    primaryTypographyProps={{ variant: 'body2' }}
                    sx={{ my: 0 }}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 2, fontWeight: 600 }}>
            Metric Timeline
          </Typography>
          <MetricTimelineChart points={timeseries} signals={signals} />
        </Box>

        {evidenceSignals.length > 0 && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 2, fontWeight: 600 }}>
              Evidence
            </Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              {evidenceSignals.length} signal{evidenceSignals.length !== 1 ? 's' : ''} contributing to this operational answer.
            </Alert>
            <SignalEvidencePanel signals={evidenceSignals} />
          </Box>
        )}

        <Box>
          <Box
            onClick={() => setDetailsExpanded(!detailsExpanded)}
            sx={{
              display: 'flex',
              alignItems: 'center',
              cursor: 'pointer',
              py: 1,
              px: 1,
              borderRadius: 1,
              '&:hover': { bgcolor: 'action.hover' },
            }}
          >
            <IconButton
              size="small"
              aria-label={detailsExpanded ? 'Hide raw technical details' : 'Show raw technical details'}
              aria-expanded={detailsExpanded}
              sx={{
                transform: detailsExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 200ms',
                mr: 1,
              }}
            >
              <ExpandMoreIcon fontSize="small" />
            </IconButton>
            <Typography variant="subtitle2" color="text.secondary" sx={{ fontWeight: 600 }}>
              Raw Technical Details
            </Typography>
          </Box>
          <Collapse in={detailsExpanded}>
            <Box sx={{ pl: 5, pt: 1 }}>
              <Stack spacing={1}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Status</Typography>
                  <Typography variant="body2">{answer.status}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Priority</Typography>
                  <Typography variant="body2">{answer.priority}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Confidence</Typography>
                  <Typography variant="body2">{Math.round(answer.confidence * 100)}%</Typography>
                </Box>
              </Stack>
            </Box>
          </Collapse>
        </Box>
        </Stack>
      </Collapse>
    </Box>
  );
}
