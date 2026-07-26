import { Alert, Button, Stack } from '@mui/material';

type Props = {
  message: string;
  onRetry?: () => void;
};

export function ErrorState({ message, onRetry }: Props) {
  return (
    <Alert severity="error">
      <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={1.5}>
        <span>{message}</span>
        {onRetry ? <Button color="inherit" size="small" onClick={onRetry}>Retry</Button> : null}
      </Stack>
    </Alert>
  );
}
