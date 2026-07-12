import { Skeleton, Stack } from '@mui/material';

export function LoadingSkeleton() {
  return (
    <Stack spacing={2}>
      <Skeleton variant="rounded" height={120} />
      <Skeleton variant="rounded" height={120} />
      <Skeleton variant="rounded" height={120} />
    </Stack>
  );
}
