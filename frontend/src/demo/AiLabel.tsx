import type { ReactElement } from 'react';
import { Chip, Tooltip } from '@mui/material';
import { useDemo } from './demo';

/** Wraps an "AI" chip. In demo mode with recorded answers it becomes "Recorded example", and hovering
 * says what that means; everywhere else the chip shows as it is. */
export function AiLabel({ children, suffix = '' }: { children: ReactElement; suffix?: string }) {
  const demo = useDemo();
  if (demo?.ai !== 'recorded') return children;
  const model = demo.ai_model ? ` (${demo.ai_model})` : '';
  return (
    <Tooltip
      describeChild
      title={`Recorded example. A real model${model} wrote this from this demo's own data when the demo was built; it passed the same checks as a live answer. Live AI is off on this site. For live answers on your own data, run Ops Signals yourself with --profile ai.`}
    >
      <Chip
        size="small"
        label={`Recorded example${suffix}`}
        tabIndex={0}
        data-testid="ai-recorded"
        sx={{ height: 20, fontSize: '0.68rem', fontWeight: 800, color: '#6b4b00', bgcolor: '#fff9e8', border: '1px solid #f5dfa3' }}
      />
    </Tooltip>
  );
}
