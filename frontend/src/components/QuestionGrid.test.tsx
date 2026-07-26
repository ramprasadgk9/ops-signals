import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import '@testing-library/jest-dom/vitest';
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
          confidence: 85,
        },
      ]}
      onOpen={() => {}}
    />
  );

  expect(screen.getByText('What changed yesterday?')).toBeInTheDocument();
  expect(screen.getByText('85%')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument();
});
