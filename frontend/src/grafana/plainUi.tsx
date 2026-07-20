import React from 'react';
import type { PropsWithChildren, ReactNode } from 'react';

export const styles = {
  shell: { display: 'flex', flexDirection: 'column', gap: 16, padding: 18, color: 'inherit' },
  card: { border: '1px solid rgba(204, 204, 220, 0.2)', borderRadius: 8, padding: 18, background: 'rgba(24, 27, 31, 0.68)' },
  grid: { display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' },
  row: { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' },
  rowBetween: { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' },
  stack: { display: 'flex', flexDirection: 'column', gap: 12 },
  input: {
    width: '100%',
    minHeight: 36,
    borderRadius: 4,
    border: '1px solid rgba(204, 204, 220, 0.28)',
    background: '#111217',
    color: 'inherit',
    padding: '7px 10px',
  },
  button: {
    border: 0,
    borderRadius: 4,
    padding: '8px 14px',
    background: '#5794f2',
    color: '#fff',
    fontWeight: 600,
    cursor: 'pointer',
  },
  buttonDisabled: {
    background: 'rgba(204, 204, 220, 0.18)',
    color: 'rgba(204, 204, 220, 0.55)',
    cursor: 'not-allowed',
  },
  label: { display: 'block', marginBottom: 6, fontSize: 12, color: 'rgba(204, 204, 220, 0.72)' },
  muted: { color: 'rgba(204, 204, 220, 0.72)' },
  chip: { border: '1px solid rgba(204, 204, 220, 0.2)', borderRadius: 999, padding: '4px 10px', fontSize: 12 },
  pre: { margin: 0, padding: 12, borderRadius: 6, overflow: 'auto', background: '#111217' },
  alert: { border: '1px solid rgba(87, 148, 242, 0.4)', borderRadius: 8, padding: 12, background: 'rgba(87, 148, 242, 0.1)' },
  toolbar: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 14, alignItems: 'end' },
  contentGrid: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(280px, 0.36fr)', gap: 16, alignItems: 'start' },
  compactStats: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 16 },
  summaryStrip: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(120px, 1fr)) minmax(180px, auto)', gap: 18, alignItems: 'center' },
  summaryItem: { display: 'grid', gridTemplateColumns: '42px auto', columnGap: 12, alignItems: 'center' },
  summaryIcon: { gridRow: 'span 2', display: 'grid', placeItems: 'center', width: 42, height: 42, borderRadius: 6, background: 'rgba(87, 148, 242, 0.16)', color: '#5794f2', fontSize: 20 },
  runDetails: { justifySelf: 'end', minWidth: 160 },
  primaryFinding: { display: 'grid', gridTemplateColumns: '92px minmax(0, 1fr)', gap: 20, border: '1px solid rgba(242, 73, 92, 0.38)', borderRadius: 8, padding: 20, background: 'linear-gradient(135deg, rgba(242, 73, 92, 0.13), rgba(24, 27, 31, 0.76) 42%)' },
  findingIcon: { display: 'grid', placeItems: 'center', minHeight: 88, borderRadius: 8, background: 'rgba(242, 73, 92, 0.18)', color: '#ff7381', fontSize: 56 },
  questionButton: { display: 'flex', gap: 10, alignItems: 'center', width: '100%', border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 6, padding: '12px 14px', background: 'rgba(204, 204, 220, 0.05)', color: 'inherit', cursor: 'pointer', textAlign: 'left' },
  answerCard: { border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12, background: 'rgba(17, 18, 23, 0.72)' },
  evidenceHero: { display: 'grid', gridTemplateColumns: '42px 1fr', columnGap: 12, alignItems: 'center', border: '1px solid rgba(204, 204, 220, 0.16)', borderRadius: 8, padding: 12, background: 'rgba(63, 207, 142, 0.08)' },
  detailGrid: { display: 'grid', gridTemplateColumns: 'minmax(120px, 1fr) minmax(120px, 1fr)', gap: '10px 16px', alignItems: 'center' },
  compactTable: { display: 'grid', gridTemplateColumns: '0.7fr 1.4fr 1fr 1fr', gap: '8px 12px', alignItems: 'center', fontSize: 12 },
  tableHeader: { color: 'rgba(204, 204, 220, 0.68)', fontSize: 12, fontWeight: 600 },
  caseTable: { display: 'grid', gridTemplateColumns: '0.6fr 2fr 1fr 1.4fr 1.2fr', gap: '10px 14px', alignItems: 'center', marginTop: 14 },
  tableRowButton: { border: 0, background: 'transparent', color: '#5794f2', padding: 0, textAlign: 'left', cursor: 'pointer' },
  drawerBackdrop: { position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', justifyContent: 'flex-end', background: 'rgba(0, 0, 0, 0.25)' },
  drawer: { width: 'min(460px, 100vw)', height: '100%', display: 'grid', gridTemplateRows: 'auto auto auto 1fr auto', gap: 14, padding: 18, borderLeft: '1px solid rgba(204, 204, 220, 0.2)', background: 'rgba(18, 21, 26, 0.98)', boxShadow: '-16px 0 40px rgba(0,0,0,0.28)', overflow: 'hidden' },
  drawerHeader: { display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' },
  drawerBody: { overflow: 'auto', paddingRight: 4 },
  drawerFooter: { display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center', borderTop: '1px solid rgba(204, 204, 220, 0.16)', paddingTop: 14 },
  stepList: { display: 'flex', flexDirection: 'column', gap: 0, border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, overflow: 'hidden' },
  step: { display: 'flex', gap: 12, alignItems: 'center', width: '100%', border: 0, borderBottom: '1px solid rgba(204, 204, 220, 0.1)', padding: '14px 12px', background: 'rgba(204, 204, 220, 0.03)', color: 'inherit', cursor: 'pointer', textAlign: 'left' },
  stepActive: { display: 'flex', gap: 12, alignItems: 'center', width: '100%', border: 0, borderBottom: '1px solid rgba(204, 204, 220, 0.1)', padding: '14px 12px', background: 'rgba(87, 148, 242, 0.14)', color: 'inherit', cursor: 'pointer', textAlign: 'left' },
  stepNumber: { display: 'grid', placeItems: 'center', width: 24, height: 24, borderRadius: 999, border: '1px solid rgba(204, 204, 220, 0.28)', color: '#5794f2', fontSize: 12 },
  infoNote: { borderTop: '1px solid rgba(204, 204, 220, 0.12)', paddingTop: 10, color: 'rgba(204, 204, 220, 0.72)', fontSize: 12 },
  emptyHero: { display: 'grid', placeItems: 'center', minHeight: 220, textAlign: 'center', color: 'rgba(204, 204, 220, 0.72)' },
} as const;

export function Card({ children }: PropsWithChildren) {
  return <section style={styles.card}>{children}</section>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label>
      <span style={styles.label}>{label}</span>
      {children}
    </label>
  );
}

export function Chip({ children, onClick }: PropsWithChildren<{ onClick?: () => void }>) {
  return (
    <button type="button" onClick={onClick} style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: onClick ? 'pointer' : 'default' }}>
      {children}
    </button>
  );
}
