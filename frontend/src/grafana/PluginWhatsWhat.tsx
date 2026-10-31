import React, { useEffect, useState } from 'react';
import { CHAIN, CHAIN_INTRO, GLOSSARY_URL, PAGE_GLOSSARY, type GlossaryPage } from '../utils/glossaryTerms';
import { styles } from './plainUi';

const border = '1px solid rgba(204, 204, 220, 0.16)';

/** The web UI's "What's what?" in the plugin's plain styles: the signal → finding → case → memory
 * chain, the words this page uses, and a link to the full glossary. */
export function PluginWhatsWhat({ page }: { page: GlossaryPage }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);
  const { step: current, terms } = PAGE_GLOSSARY[page];
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        style={{ border: 0, borderBottom: '1px dashed #5794f2', background: 'transparent', color: '#5794f2', padding: 0, marginLeft: 6, cursor: 'pointer', font: 'inherit', fontWeight: 600 }}
      >
        What's what?
      </button>
      {open ? (
        <div style={{ ...styles.drawerBackdrop, justifyContent: 'center', alignItems: 'flex-start', paddingTop: '8vh' }} onClick={() => setOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="plugin-whats-what-title"
            onClick={(event) => event.stopPropagation()}
            style={{ width: 'min(760px, 94vw)', maxHeight: '80vh', overflow: 'auto', borderRadius: 8, border, background: 'rgba(18, 21, 26, 0.98)', boxShadow: '0 20px 50px rgba(0,0,0,0.4)', color: '#d8d9da' }}
          >
            <div style={{ ...styles.rowBetween, padding: '14px 18px', borderBottom: border }}>
              <h3 id="plugin-whats-what-title" style={{ margin: 0 }}>What's what?</h3>
              <button type="button" aria-label="Close" onClick={() => setOpen(false)} style={{ border: 0, background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: 16 }}>✕</button>
            </div>
            <div style={{ padding: '14px 18px', fontSize: 13, lineHeight: 1.5 }}>
              <div style={{ marginBottom: 10 }}>{CHAIN_INTRO}</div>
              <ol aria-label="From signal to memory" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, margin: 0, padding: 0, listStyle: 'none' }}>
                {CHAIN.map((item) => {
                  const here = item.step === current;
                  return (
                    <li key={item.step} aria-current={here ? 'page' : undefined} style={{ border: here ? '2px solid #5794f2' : border, background: here ? 'rgba(87, 148, 242, 0.12)' : 'transparent', borderRadius: 8, padding: 10 }}>
                      <strong style={{ display: 'block' }}>{item.title}</strong>
                      <span>{item.text}</span>
                      <span style={{ ...styles.helperText, display: 'block', textTransform: 'uppercase', fontWeight: 600 }}>{here ? 'This page' : item.who}</span>
                    </li>
                  );
                })}
              </ol>
              <h4 style={{ ...styles.muted, margin: '16px 0 4px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Words on this page</h4>
              <dl style={{ margin: 0 }}>
                {terms.map((item, index) => (
                  <div key={item.term} style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 170px) 1fr', gap: 10, padding: '7px 0', borderBottom: index < terms.length - 1 ? border : 'none' }}>
                    <dt style={{ fontWeight: 600 }}>{item.term}</dt>
                    <dd style={{ margin: 0 }}>{item.text}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div style={{ ...styles.rowBetween, padding: '12px 18px', borderTop: border }}>
              <a href={GLOSSARY_URL} target="_blank" rel="noopener noreferrer" style={{ color: '#5794f2', fontWeight: 600 }}>Full glossary ↗</a>
              <button type="button" style={styles.button} onClick={() => setOpen(false)}>Close</button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
