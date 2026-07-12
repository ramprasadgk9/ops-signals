import { render, screen } from '@testing-library/react';
import { QuestionGrid } from './QuestionGrid';

it('renders dynamic questions and labels', () => {
  render(
    <QuestionGrid
      questions={[
        {
          id: 'what_changed',
          label: 'What changed yesterday?',
          description: 'Summarize changes.',
          contributors: ['Baseline Analysis', 'Trend Analysis'],
          available: true,
        },
      ]}
      onOpen={() => {}}
    />
  );

  expect(screen.getByText('What changed yesterday?')).toBeInTheDocument();
  expect(screen.getByText('Summarize changes.')).toBeInTheDocument();
  expect(screen.getByText('Baseline Analysis')).toBeInTheDocument();
});
