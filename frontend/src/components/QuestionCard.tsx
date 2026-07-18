import { Button, Card, CardActions, CardContent, Chip, Stack, Typography } from '@mui/material';
import type { Question } from '../types';

type Props = {
  question: Question;
  onOpen: (question: Question) => void;
  compact?: boolean;
};

export function QuestionCard({ question, onOpen, compact = false }: Props) {
  const confidence = question.confidence ?? 85; // Default confidence for display
  
  return (
    <Card
      sx={{
        display: 'flex',
        flexDirection: compact ? 'row' : 'column',
        alignItems: compact ? 'center' : 'stretch',
        justifyContent: compact ? 'space-between' : 'flex-start',
        px: compact ? 1.25 : 0,
        py: compact ? 0.75 : 0,
      }}
      variant={compact ? 'outlined' : 'elevation'}
    >
      <CardContent sx={{ flexGrow: 1, py: compact ? 1 : undefined, '&:last-child': { pb: compact ? 1 : undefined } }}>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <Typography variant={compact ? 'body2' : 'h6'} sx={{ fontWeight: 600 }}>
            {question.label}
          </Typography>
          <Chip size="small" label={`${confidence}%`} variant="outlined" />
        </Stack>
        {!compact ? (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25, mb: 2 }}>
              {question.description}
            </Typography>
            <Stack spacing={1.5}>
              <Stack>
                <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, mb: 0.5 }}>
                  Powered by
                </Typography>
                <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                  {question.contributors.map((contrib) => (
                    <Chip
                      key={contrib}
                      size="small"
                      label={contrib}
                      variant="outlined"
                    />
                  ))}
                </Stack>
              </Stack>
            </Stack>
          </>
        ) : null}
      </CardContent>
      <CardActions sx={{ p: compact ? 0.5 : undefined, pr: compact ? 1 : undefined }}>
        <Button variant={compact ? 'text' : 'contained'} size="small" onClick={() => onOpen(question)}>
          {compact ? 'Open' : 'View Answer'}
        </Button>
      </CardActions>
    </Card>
  );
}
