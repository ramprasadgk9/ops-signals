import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from 'react';
import { GlobalStyles } from '@mui/material';
import { ThemeProvider, createTheme } from '@mui/material/styles';

type Mode = 'light' | 'dark';

const ColorModeContext = createContext({ toggle: () => {}, mode: 'light' as Mode });

export const useColorMode = () => useContext(ColorModeContext);

export const COLOR_MODE_KEY = 'ops-signals-color-mode';

// Neutral colors as CSS variables, so the many sx props that use them (via standalone/theme `ui`
// and `var(--os-*)`) follow the mode without each reading the theme. Accent colors (red, blue,
// green...) stay the same in both modes.
const TOKENS: Record<Mode, Record<string, string>> = {
  light: {
    bg: '#fbfcff',
    surface: '#ffffff',
    'surface-alt': '#f8fafc',
    border: '#e8edf5',
    'border-strong': '#cbd5e1',
    text: '#111827',
    'text-2': '#475569',
    muted: '#64748b',
    'header-bg': 'rgba(255, 255, 255, 0.92)',
    'tint-amber': '#fffbeb',
    'tint-orange': '#fff7ed',
    'tint-blue': '#eff6ff',
    'tint-indigo': '#eef2ff',
    'tint-violet': '#ede9fe',
    'tint-rose': '#fff1f2',
    'tint-green': '#ecfdf5',
    'tint-cyan': '#ecfeff',
    'tint-amber-border': '#fde68a',
    'tint-orange-border': '#fed7aa',
    'tint-blue-border': '#bfdbfe',
    'tint-violet-border': '#ddd6fe',
    'tint-rose-border': '#fecdd3',
    'tint-green-border': '#bbf7d0',
    'tint-cyan-border': '#b6d5dd',
    'ink-amber': '#92400e',
    'ink-orange': '#9a3412',
    'ink-green': '#166534',
    'ink-red': '#b91c1c',
    'ink-blue': '#1d4ed8',
    'ink-brand': '#0f766e',
  },
  dark: {
    bg: '#0b1120',
    surface: '#111827',
    'surface-alt': '#172031',
    border: '#253041',
    'border-strong': '#3a475c',
    text: '#e5e9f0',
    'text-2': '#c2cad6',
    muted: '#8d99ab',
    'header-bg': 'rgba(17, 24, 39, 0.92)',
    'tint-amber': 'rgba(245, 158, 11, 0.14)',
    'tint-orange': 'rgba(249, 115, 22, 0.14)',
    'tint-blue': 'rgba(59, 130, 246, 0.15)',
    'tint-indigo': 'rgba(99, 102, 241, 0.16)',
    'tint-violet': 'rgba(139, 92, 246, 0.16)',
    'tint-rose': 'rgba(244, 63, 94, 0.14)',
    'tint-green': 'rgba(34, 197, 94, 0.14)',
    'tint-cyan': 'rgba(6, 182, 212, 0.14)',
    'tint-amber-border': 'rgba(245, 158, 11, 0.4)',
    'tint-orange-border': 'rgba(249, 115, 22, 0.4)',
    'tint-blue-border': 'rgba(59, 130, 246, 0.4)',
    'tint-violet-border': 'rgba(139, 92, 246, 0.4)',
    'tint-rose-border': 'rgba(244, 63, 94, 0.4)',
    'tint-green-border': 'rgba(34, 197, 94, 0.4)',
    'tint-cyan-border': 'rgba(6, 182, 212, 0.4)',
    'ink-amber': '#fbbf24',
    'ink-orange': '#fdba74',
    'ink-green': '#86efac',
    'ink-red': '#fca5a5',
    'ink-blue': '#93c5fd',
    'ink-brand': '#5eead4',
  },
};

function cssVariables(mode: Mode): Record<string, string> {
  return Object.fromEntries(Object.entries(TOKENS[mode]).map(([name, value]) => [`--os-${name}`, value]));
}

/** The saved choice, else the system setting. Storage can be missing or throw (private windows). */
export function initialMode(): Mode {
  try {
    const saved = window.localStorage.getItem(COLOR_MODE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // fall through to the system setting
  }
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function ThemeProviderWithMode({ children }: PropsWithChildren) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const value = useMemo(
    () => ({
      mode,
      toggle: () =>
        setMode((current) => {
          const next = current === 'light' ? 'dark' : 'light';
          try {
            window.localStorage.setItem(COLOR_MODE_KEY, next);
          } catch {
            // the choice just isn't remembered
          }
          return next;
        }),
    }),
    [mode]
  );
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
  }, [mode]);
  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: '#0f766e' },
          secondary: { main: '#7c2d12' },
          background: {
            default: TOKENS[mode].bg,
            paper: TOKENS[mode].surface,
          },
          ...(mode === 'dark'
            ? { text: { primary: TOKENS.dark.text, secondary: TOKENS.dark.muted }, divider: TOKENS.dark.border }
            : {}),
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
      <ThemeProvider theme={theme}>
        <GlobalStyles
          styles={{
            ':root': { ...cssVariables(mode), colorScheme: mode },
            // Recharts draws its tooltip and axis labels with fixed light colors; follow the mode instead.
            '.recharts-default-tooltip': {
              backgroundColor: 'var(--os-surface) !important',
              borderColor: 'var(--os-border) !important',
              color: 'var(--os-text)',
            },
            '.recharts-cartesian-axis-tick-value, .recharts-legend-item-text': { fill: 'var(--os-muted)' },
          }}
        />
        {children}
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}
