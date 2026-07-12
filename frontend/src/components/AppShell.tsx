import { Box, Container } from '@mui/material';
import type { PropsWithChildren } from 'react';
import { TopNavigation } from './TopNavigation';

export function AppShell({ children }: PropsWithChildren) {
  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(180deg, rgba(15,118,110,0.08), rgba(124,45,18,0.05))' }}>
      <TopNavigation />
      <Container maxWidth="xl" sx={{ py: 3 }}>
        {children}
      </Container>
    </Box>
  );
}
