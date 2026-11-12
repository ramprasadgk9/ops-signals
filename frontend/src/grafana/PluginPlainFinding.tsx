import React, { useEffect, useState } from 'react';
import type { FindingAIWording, FindingPlain } from '../types';
import { AI_LINE_HINT, AI_SETUP, aiFooter, aiHintDismissed, dismissAiHint, hasAiLines, plainLines, plainTimes, plainTone, type PlainTone } from '../utils/findingPlain';
import { getFindingAiWording } from './backendClient';
import { usePermissions } from './permissions';
import { styles } from './plainUi';

// A finding in plain words in the plugin's own styling: the same wording as the web UI's
// PlainFindingSummary (utils/findingPlain.ts, config/finding_templates.yaml).

const TONE: Record<PlainTone, { color: string; border: string; background: string }> = {
  bad: { color: '#ff7381', border: 'rgba(255, 115, 129, 0.45)', background: 'rgba(255, 115, 129, 0.1)' },
  good: { color: '#3fcf8e', border: 'rgba(63, 207, 142, 0.45)', background: 'rgba(63, 207, 142, 0.1)' },
  gap: { color: '#ffb357', border: 'rgba(255, 179, 87, 0.45)', background: 'rgba(255, 179, 87, 0.1)' },
  neutral: { color: '#a8b3c4', border: 'rgba(204, 204, 220, 0.25)', background: 'transparent' },
};

export function PluginPlainBadge({ plain }: { plain: FindingPlain }) {
  const tone = TONE[plainTone(plain.badge)];
  const important = TONE[plain.service_importance === 'critical' ? 'gap' : 'neutral'];
  // A box of its own, so the chips keep their size in a column layout instead of stretching.
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', alignSelf: 'flex-start', flex: 'none' }}>
      <span
        data-testid="plugin-plain-badge"
        style={{ ...styles.chip, color: tone.color, borderColor: tone.border, background: tone.background, fontWeight: 600, flex: 'none' }}
      >
        {plain.badge_label}
      </span>
      {plain.service_importance_label ? (
        <span data-testid="plugin-plain-importance" style={{ ...styles.chip, color: important.color, borderColor: important.border, flex: 'none' }}>
          {plain.service_importance_label}
        </span>
      ) : null}
    </span>
  );
}

const AI_BLUE = '#5794f2';

/** AI-written lines for a saved finding, asked for after it shows; null until they arrive or without a finding id. */
function useAiWording(backendUrl: string | undefined, findingId: number | null | undefined) {
  const [state, setState] = useState<{ ai: FindingAIWording | null; pending: boolean }>({ ai: null, pending: false });
  useEffect(() => {
    if (!backendUrl || typeof findingId !== 'number') {
      setState({ ai: null, pending: false });
      return;
    }
    let current = true;
    setState({ ai: null, pending: true });
    getFindingAiWording(backendUrl, findingId)
      .then((ai) => current && setState({ ai, pending: false }))
      .catch(() => current && setState({ ai: null, pending: false }));
    return () => {
      current = false;
    };
  }, [backendUrl, findingId]);
  return state;
}

/** Shown to Grafana admins when no AI provider is on, until they choose "Not now". */
function PluginEnableAiHint() {
  const [dismissed, setDismissed] = useState(aiHintDismissed);
  const [open, setOpen] = useState(false);
  if (dismissed) return null;
  return (
    <div data-testid="plugin-enable-ai-hint" style={{ ...styles.muted, fontSize: 12, borderTop: '1px solid rgba(204, 204, 220, 0.15)', paddingTop: 6 }}>
      <span>These lines are the same for every finding of this kind. Turn on AI to have them written for this metric and service. </span>
      <button type="button" aria-expanded={open} style={{ ...styles.tableRowButton, padding: 0, color: AI_BLUE }} onClick={() => setOpen(!open)}>
        {open ? 'Hide how' : 'How to turn it on'}
      </button>
      <button type="button" style={{ ...styles.tableRowButton, padding: '0 0 0 10px', color: 'inherit' }} onClick={() => { dismissAiHint(); setDismissed(true); }}>
        Not now
      </button>
      {open ? (
        <div style={{ marginTop: 6, display: 'grid', gap: 6 }}>
          <span>{AI_SETUP.intro}</span>
          <ol style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
            {AI_SETUP.steps.map((step) => (
              <li key={step.text}>
                {step.text}
                {step.command ? <pre style={{ margin: '4px 0 0', padding: 6, borderRadius: 4, background: '#111217', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{step.command}</pre> : null}
              </li>
            ))}
          </ol>
          <span>{AI_SETUP.other}</span>
        </div>
      ) : null}
    </div>
  );
}

export function PluginPlainFinding({ plain, details, signal, findingId, backendUrl }: {
  plain: FindingPlain;
  /** The stored title and summary, under Technical details. */
  details: string;
  /** The strongest signal in analyzer words (utils/findingPlain leadSignalText), also under Technical details. */
  signal?: string | null;
  /** A saved finding's id and the backend: its details then get AI-written lines when AI is on. */
  findingId?: number | null;
  backendUrl?: string;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const [templateOnly, setTemplateOnly] = useState(false);
  const { canAdmin } = usePermissions();
  const { ai, pending } = useAiWording(backendUrl, findingId);
  const written = hasAiLines(ai);
  const lines = plainLines(plain, {}, written && !templateOnly ? ai : null);
  return (
    <div data-testid="plugin-plain" style={{ ...styles.stack, gap: 8 }}>
      <p style={{ margin: 0 }}>{plainTimes(plain.what)}</p>
      {lines.length ? (
        <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'minmax(96px, auto) minmax(0, 1fr)', columnGap: 12, rowGap: 6, fontSize: 13 }}>
          {lines.map((line, index) => (
            <React.Fragment key={`${line.label}-${index}`}>
              <dt style={{ ...styles.muted, fontWeight: 600 }}>
                {line.hint ? (
                  <span title={line.hint} tabIndex={0} data-testid="plugin-plain-hint" style={{ cursor: 'help', borderBottom: '1px dotted currentColor' }}>
                    {line.label}
                  </span>
                ) : (
                  line.label
                )}
              </dt>
              <dd style={{ margin: 0, minWidth: 0 }}>
                {line.ai ? (
                  <span title={AI_LINE_HINT} tabIndex={0} data-testid="plugin-plain-ai" style={{ ...styles.chip, padding: '0 6px', fontSize: 10.5, fontWeight: 700, color: AI_BLUE, borderColor: AI_BLUE, marginRight: 6, cursor: 'help' }}>
                    AI
                  </span>
                ) : null}
                {line.href ? (
                  <>
                    <a href={line.href} target="_blank" rel="noopener noreferrer" data-testid="plugin-plain-link" style={{ color: '#5794f2' }}>
                      {line.linkText ?? line.href}
                    </a>{' '}
                  </>
                ) : null}
                {line.text}
              </dd>
            </React.Fragment>
          ))}
        </dl>
      ) : null}
      {pending ? <span data-testid="plugin-plain-ai-pending" style={{ ...styles.muted, fontSize: 12 }}>Writing for this finding...</span> : null}
      {written && ai ? (
        <span data-testid="plugin-plain-ai-footer" style={{ ...styles.muted, fontSize: 12 }}>
          {templateOnly ? 'Template wording' : aiFooter(ai)}{' '}
          <button type="button" style={{ ...styles.tableRowButton, padding: 0, color: AI_BLUE }} onClick={() => setTemplateOnly(!templateOnly)}>
            {templateOnly ? 'Show AI wording' : 'Show template wording'}
          </button>
        </span>
      ) : null}
      {ai?.reason === 'ai_off' && canAdmin ? <PluginEnableAiHint /> : null}
      <div>
        <button type="button" aria-expanded={showDetails} style={{ ...styles.tableRowButton, padding: 0 }} onClick={() => setShowDetails(!showDetails)}>
          {showDetails ? '▾' : '▸'} Technical details
        </button>
        {showDetails ? (
          <div data-testid="plugin-plain-details" style={{ ...styles.muted, margin: '4px 0 0', fontSize: 13, display: 'grid', gap: 4 }}>
            <span>{details}</span>
            {signal ? <span data-testid="plugin-plain-signal"><strong>Strongest signal:</strong> {signal}</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
