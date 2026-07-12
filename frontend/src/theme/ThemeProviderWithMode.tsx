import { createContext, useContext, useMemo, useState, type PropsWithChildren } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';

const ColorModeContext = createContext({ toggle: () => {}, mode: 'light' as 'light' | 'dark' });

export const useColorMode = () => useContext(ColorModeContext);

export function ThemeProviderWithMode({ children }: PropsWithChildren) {
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const value = useMemo(() => ({ mode, toggle: () => setMode((m) => (m === 'light' ? 'dark' : 'light')) }), [mode]);
  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: '#0f766e' },
          secondary: { main: '#7c2d12' },
          background: {
            default: mode === 'light' ? '#f4f7f6' : '#0f1720',
            paper: mode === 'light' ? '#ffffff' : '#111827',
          },
        },
        shape: { borderRadius: 14 },
        typography: {
          fontFamily: 'IBM Plex Sans, sans-serif',
          h1: { fontFamily: 'Space Grotesk, sans-serif', fontWeight: 700 },
          h2: { fontFamily: 'Space Grotesk, sans-serif', fontWeight: 700 },
          h3: { fontFamily: 'Space Grotesk, sans-serif', fontWeight: 600 },
        },
      }),
    [mode]
  );

  return (
    <ColorModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>{children}</ThemeProvider>
    </ColorModeContext.Provider>
  );
}
