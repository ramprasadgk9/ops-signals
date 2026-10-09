import type { SxProps, Theme } from '@mui/material';

// Neutrals follow the light/dark mode through CSS variables set by theme/ThemeProviderWithMode;
// the fallbacks keep the light look anywhere that provider isn't mounted.
export const ui = {
  bg: 'var(--os-bg, #fbfcff)',
  surface: 'var(--os-surface, #ffffff)',
  border: 'var(--os-border, #e8edf5)',
  text: 'var(--os-text, #111827)',
  muted: 'var(--os-muted, #64748b)',
  red: '#ff4d57',
  blue: '#4f46e5',
  purple: '#6d5dfc',
  green: '#16a34a',
  orange: '#f97316',
  yellow: '#f59e0b',
};

export const panelSx: SxProps<Theme> = {
  bgcolor: ui.surface,
  border: `1px solid ${ui.border}`,
  borderRadius: '8px',
  boxShadow: '0 8px 28px rgba(15, 23, 42, 0.04)',
};

export function formatDateTime(value?: string | null) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function relativeTime(value?: string | null) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'n/a';
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.max(0, Math.round(diffMs / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function titleCase(value?: string | null) {
  if (!value) return 'n/a';
  return value
    .replace(/[_-]/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function severityTone(value?: string | null) {
  const severity = value?.toLowerCase();
  if (severity === 'critical') return { color: '#ef4444', bg: '#fff1f2', border: '#fecdd3' };
  if (severity === 'high' || severity === 'significant') return { color: '#f97316', bg: '#fff7ed', border: '#fed7aa' };
  if (severity === 'medium') return { color: '#d97706', bg: '#fffbeb', border: '#fde68a' };
  if (severity === 'low' || severity === 'normal') return { color: '#3b82f6', bg: '#eff6ff', border: '#bfdbfe' };
  return { color: '#64748b', bg: '#f8fafc', border: '#e2e8f0' };
}

export function statusTone(value?: string | null) {
  const status = value?.toLowerCase();
  if (status === 'resolved' || status === 'verified' || status === 'completed' || status === 'active') {
    return { color: '#059669', bg: '#ecfdf5', border: '#bbf7d0' };
  }
  if (status === 'identified') return { color: '#2563eb', bg: '#eff6ff', border: '#bfdbfe' };
  if (status === 'on_hold' || status === 'on hold') return { color: '#d97706', bg: '#fffbeb', border: '#fde68a' };
  if (status === 'investigating' || status === 'in_progress' || status === 'open') return { color: '#6d5dfc', bg: '#f3f0ff', border: '#ddd6fe' };
  return { color: '#64748b', bg: '#f8fafc', border: '#e2e8f0' };
}
