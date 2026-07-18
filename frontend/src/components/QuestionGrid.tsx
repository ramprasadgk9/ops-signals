import { Stack } from '@mui/material';
import type { Question } from '../types';
import { QuestionCard } from './QuestionCard';

type Props = {
  questions: Question[];
  onOpen: (question: Question) => void;
};

export function QuestionGrid({ questions, onOpen }: Props) {
  return (
    <Stack spacing={1.25}>
      {questions.map((q) => (
        <QuestionCard key={q.id} question={q} onOpen={onOpen} compact />
      ))}
    </Stack>
  );
}
