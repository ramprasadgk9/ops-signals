import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CssBaseline } from '@mui/material';
import App from './App';
import { ThemeProviderWithMode } from './theme/ThemeProviderWithMode';

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProviderWithMode>
        <CssBaseline />
        <App />
      </ThemeProviderWithMode>
    </QueryClientProvider>
  </React.StrictMode>
);
