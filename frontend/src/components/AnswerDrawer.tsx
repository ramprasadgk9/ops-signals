import { Box, Drawer } from '@mui/material';
import type { Question, QuestionAnswer, Signal, TimeseriesPoint } from '../types';
import { AnswerPanel } from './AnswerPanel';

type Props = {
  open: boolean;
  question: Question | null;
  answer: QuestionAnswer | null;
  signals: Signal[];
  timeseries: TimeseriesPoint[];
  onClose: () => void;
};

export function AnswerDrawer({ open, question, answer, signals, timeseries, onClose }: Props) {
  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: { xs: '100vw', md: 600 }, p: 3, overflowY: 'auto', height: '100vh' }}>
        <AnswerPanel
          question={question}
          answer={answer}
          signals={signals}
          timeseries={timeseries}
        />
      </Box>
    </Drawer>
  );
}
