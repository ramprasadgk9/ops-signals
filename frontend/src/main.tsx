import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CssBaseline } from '@mui/material';
import App from './App';
import { retryUnlessClientError } from './api/client';
import { StandaloneApp } from './StandaloneApp';
import { ThemeProviderWithMode } from './theme/ThemeProviderWithMode';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: retryUnlessClientError } } });

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProviderWithMode>
        <CssBaseline />
        {window.location.pathname.startsWith('/experiments') || window.location.pathname.startsWith('/analyzer-router') ? <StandaloneApp /> : <App />}
      </ThemeProviderWithMode>
    </QueryClientProvider>
  </React.StrictMode>
);
