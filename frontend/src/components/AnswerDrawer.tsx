import { Alert, Box, Collapse, Divider, Drawer, IconButton, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import { useState } from 'react';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { Question, QuestionAnswer, Signal, TimeseriesPoint } from '../types';
import { MetricTimelineChart } from './MetricTimelineChart';
import { SignalEvidencePanel } from './SignalEvidencePanel';

type Props = {
  open: boolean;
  question: Question | null;
  answer: QuestionAnswer | null;
  signals: Signal[];
  timeseries: TimeseriesPoint[];
  onClose: () => void;
};

export function AnswerDrawer({ open, question, answer, signals, timeseries, onClose }: Props) {
  const [detailsExpanded, setDetailsExpanded] = useState(false);

  if (!answer) {
    return (
      <Drawer anchor="right" open={open} onClose={onClose}>
        <Box sx={{ width: { xs: '100vw', md: 560 }, p: 3 }}>
          <Typography>No answer loaded.</Typography>
        </Box>
      </Drawer>
    );
  }

  const evidenceSignals = signals.filter((s) => answer.evidence_signal_ids.includes(s.id));

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', md: 600 }, p: 3, overflowY: 'auto', height: '100vh' }}>
        {/* Question */}
        <Typography variant="h5" sx={{ mb: 3, fontWeight: 700 }}>
          {question?.label}
        </Typography>
        <Divider sx={{ mb: 3 }} />

        {/* Headline - Operational Summary */}
        <Stack spacing={3}>
          {/* Headline */}
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 600 }}>
              Finding
            </Typography>
            <Typography variant="h6" sx={{ mb: 2 }}>
              {answer.headline}
            </Typography>
          </Box>

          {/* Operational Summary */}
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, fontWeight: 600 }}>
              Operational Summary
            </Typography>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
              {answer.answer}
            </Typography>
          </Box>

          {/* Key Findings */}
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

          {/* Metric Timeline */}
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 2, fontWeight: 600 }}>
              Metric Timeline
            </Typography>
            <MetricTimelineChart points={timeseries} signals={signals} />
          </Box>

          {/* Evidence - Contributing Signals */}
          {(evidenceSignals.length > 0) && (
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

          {/* Raw Technical Details - Collapsed */}
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
      </Box>
    </Drawer>
  );
}
