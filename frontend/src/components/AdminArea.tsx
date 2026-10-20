import type { ReactNode } from 'react';
import { Stack } from '@mui/material';
import { useWebPermissions } from '../hooks/useWebPermissions';
import { AdminOnlyNotice } from './LockNote';

/** An Admins-only page: anyone else may look, with a notice; the backend refuses their changes. */
export function AdminArea({ children }: { children: ReactNode }) {
  const { canAdmin } = useWebPermissions();
  if (canAdmin) return <>{children}</>;
  return (
    <Stack spacing={2}>
      <AdminOnlyNotice />
      {children}
    </Stack>
  );
}
