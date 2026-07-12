import { Button, Card, CardActions, CardContent, Chip, Stack, Typography } from '@mui/material';
import type { Question } from '../types';

type Props = {
  question: Question;
  onOpen: (question: Question) => void;
};

export function QuestionCard({ question, onOpen }: Props) {
  const confidence = question.confidence ?? 85; // Default confidence for display
  
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>{question.label}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {question.description}
        </Typography>
        
        <Stack spacing={2}>
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
          
          <Typography variant="body2">
            <Typography component="span" variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Confidence
            </Typography>
            <Typography component="span" sx={{ ml: 1, fontWeight: 700 }}>
              {confidence}%
            </Typography>
          </Typography>
        </Stack>
      </CardContent>
      <CardActions>
        <Button variant="contained" fullWidth onClick={() => onOpen(question)}>View Answer</Button>
      </CardActions>
    </Card>
  );
}
