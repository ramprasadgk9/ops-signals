import { useMemo, useState } from 'react';
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Stack, TextField, Typography } from '@mui/material';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/queries';
import { ErrorState } from '../components/ErrorState';
import type { AssistantChatResponse } from '../types';

const starterPrompts = [
  'Have we seen this before?',
  'What changed in the most similar case?',
  'Show me the root cause from related cases.',
  'What usually causes this pattern?',
];

export function MemoryChatPage() {
  const [message, setMessage] = useState('Have we seen this before?');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [result, setResult] = useState<AssistantChatResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.assistantChat({
        conversation_id: conversationId,
        message,
        top_k: 5,
        minimum_score: 0.55,
        same_service_only: false,
      }),
    onSuccess: (data) => {
      setConversationId(data.conversation_id);
      setResult(data);
    },
  });

  const sources = useMemo(() => result?.sources ?? [], [result]);

  return (
    <Box sx={{ pb: 4 }}>
      <Stack spacing={2} sx={{ mb: 3 }}>
        <Typography variant="h4">Operational Intelligence Assistant</Typography>
        <Typography variant="body1" color="text.secondary">
          Ask about historical operational knowledge, analyzers, behaviors, architecture, and how the application works.
        </Typography>
      </Stack>

      <Stack spacing={2}>
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <TextField
                label="Ask a question"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                fullWidth
                multiline
                minRows={3}
              />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {starterPrompts.map((prompt) => (
                  <Chip key={prompt} label={prompt} onClick={() => setMessage(prompt)} clickable />
                ))}
              </Stack>
              <Stack direction="row" spacing={1} alignItems="center">
                <Button
                  variant="contained"
                  onClick={() => mutation.mutate()}
                  disabled={mutation.isPending || !message.trim()}
                >
                  {mutation.isPending ? 'Searching...' : 'Send'}
                </Button>
                {conversationId ? <Typography variant="caption" color="text.secondary">Conversation {conversationId}</Typography> : null}
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        {mutation.isError ? <ErrorState message="Failed to search operational memory" /> : null}

        {mutation.isPending ? (
          <Card>
            <CardContent>
              <Stack direction="row" spacing={2} alignItems="center">
                <CircularProgress size={22} />
                <Typography>Retrieving relevant cases and documentation…</Typography>
              </Stack>
            </CardContent>
          </Card>
        ) : null}

        {result ? (
          <>
            <Card>
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="h6">Answer</Typography>
                  <Typography whiteSpace="pre-line">{result.answer}</Typography>
                </Stack>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Stack spacing={1.5}>
                  <Typography variant="h6">Sources</Typography>
                  {sources.length > 0 ? (
                    sources.map((source) => (
                      <Alert key={source.reference} severity="info">
                        <Stack spacing={0.5}>
                          <Typography variant="subtitle2">
                            {source.source_type === 'historical_case' ? 'Case' : 'Doc'} · {source.title} · {source.score.toFixed(2)}
                          </Typography>
                          <Typography variant="body2">
                            {source.reference}
                          </Typography>
                          {source.summary ? <Typography variant="body2">{source.summary}</Typography> : null}
                        </Stack>
                      </Alert>
                    ))
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      No strong source cases were found for this question.
                    </Typography>
                  )}
                </Stack>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Stack spacing={1.5}>
                  <Typography variant="h6">What to expect</Typography>
                  {result.limitations.map((item) => (
                    <Typography key={item} variant="body2">
                      • {item}
                    </Typography>
                  ))}
                  <Typography variant="body2" color="text.secondary">
                    Chat is for evidence-backed retrieval and explanation, not final root-cause truth.
                  </Typography>
                </Stack>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Stack spacing={1.5}>
                  <Typography variant="h6">Follow-up questions</Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {result.suggested_questions.map((question) => (
                      <Chip key={question} label={question} onClick={() => setMessage(question)} clickable />
                    ))}
                  </Stack>
                </Stack>
              </CardContent>
            </Card>
          </>
        ) : null}
      </Stack>
    </Box>
  );
}
