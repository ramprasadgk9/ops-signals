import { Grid2 as Grid } from '@mui/material';
import type { Question } from '../types';
import { QuestionCard } from './QuestionCard';

type Props = {
  questions: Question[];
  onOpen: (question: Question) => void;
};

export function QuestionGrid({ questions, onOpen }: Props) {
  return (
    <Grid container spacing={2}>
      {questions.map((q) => (
        <Grid key={q.id} size={{ xs: 12, md: 6, lg: 4 }}>
          <QuestionCard question={q} onOpen={onOpen} />
        </Grid>
      ))}
    </Grid>
  );
}
