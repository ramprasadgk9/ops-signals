import React, { useEffect, useState } from 'react';
import type { Novelty, PastCaseMatch, SeenBeforeResponse } from '../types';
import { fixedCountSentence, matchDate, matchOutcome, matchStatus, rankPastMatches } from '../utils/pastCaseMatches';
import { getFindingSeenBefore } from './backendClient';
import { styles } from './plainUi';
import { PluginFixCameBackBanner } from './PluginFixCameBack';

// "Seen before?" (past cases from operational memory resembling a finding) in the Grafana plugin's
// own styling. Same endpoint and ordering as the web UI's FindingDetailsDrawer + PastCaseMatches.

const STRONG = '#3fcf8e';
const NOVELTY_TONE: Record<Novelty['level'], string> = {
  new: '#5794f2',
  new_on_service: '#5794f2',
  seen_before: 'rgba(204, 204, 220, 0.82)',
  recurring: '#ffb357',
};
const BOX: React.CSSProperties = { ...styles.stack, gap: 10, border: '1px solid rgba(204, 204, 220, 0.12)', borderRadius: 8, padding: 14 };
const TWO_LINES: React.CSSProperties = { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' };
const STATUS_TONE = { resolved: STRONG, progress: '#5794f2', open: '#ffb357' } as const;
const LINK_BUTTON: React.CSSProperties = { border: 0, background: 'transparent', color: '#5794f2', padding: 0, cursor: 'pointer', fontWeight: 600, width: 'fit-content' };

type State = { status: 'loading' } | { status: 'error' } | { status: 'ready'; data: SeenBeforeResponse };

/** Past cases that look like this finding. Renders nothing for a finding that was never persisted
 * (id 0 or missing), since the backend can only search from a stored finding. `frame` replaces the
 * default bordered box, e.g. with styles.card where it sits among the page's cards. */
export function PluginSeenBefore({ backendUrl, findingId, service, frame }: { backendUrl: string; findingId?: number | null; service?: string | null; frame?: React.CSSProperties }) {
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    if (!findingId) return;
    let active = true;
    setState({ status: 'loading' });
    getFindingSeenBefore(backendUrl, findingId)
      .then((data) => { if (active) setState({ status: 'ready', data }); })
      .catch(() => { if (active) setState({ status: 'error' }); });
    return () => { active = false; };
  }, [backendUrl, findingId]);

  if (!findingId) return null;

  return (
    <section data-testid="plugin-seen-before" style={frame ? { ...styles.stack, gap: 10, ...frame } : BOX}>
      <div>
        <strong>Seen before?</strong>
        <div style={{ ...styles.helperText, marginTop: 2 }}>
          Past cases from operational memory that look like this finding, including incidents imported from postmortems. No case needed.
        </div>
      </div>
      {state.status === 'loading' ? <div style={styles.muted}>Searching past cases...</div> : null}
      {state.status === 'error' ? <div style={styles.muted}>Past cases could not be searched. Check the backend connection.</div> : null}
      {state.status === 'ready' && state.data.came_back ? (
        <PluginFixCameBackBanner backendUrl={backendUrl} cameBack={state.data.came_back} subject={{ kind: 'findings', id: findingId }} />
      ) : null}
      {state.status === 'ready' ? <SeenBeforeBody data={state.data} service={service ?? state.data.service} /> : null}
    </section>
  );
}

function SeenBeforeBody({ data, service }: { data: SeenBeforeResponse; service?: string | null }) {
  const [showOthers, setShowOthers] = useState(false);
  if (!data.available) return <div style={styles.muted}>{data.reason ?? 'Operational memory is not available.'}</div>;

  const ranked = rankPastMatches(data.matches);
  const sameService = ranked.filter((match) => match.same_service);
  const otherServices = ranked.filter((match) => !match.same_service);
  return (
    <>
      {data.novelty ? <NoveltyLine novelty={data.novelty} /> : null}
      {fixedCountSentence(ranked) ? <strong data-testid="plugin-past-case-fixed-count" style={{ fontSize: 13 }}>{fixedCountSentence(ranked)}</strong> : null}
      {!ranked.length ? (
        <div style={styles.muted}>Nothing like this in memory yet. Publish resolved cases, or import past incidents from the Recurring problems page in the Ops Signals web app, to give it history.</div>
      ) : (
        <>
          {sameService.length ? (
            <div style={{ ...styles.stack, gap: 8 }}>
              {service ? <div style={{ ...styles.tableHeader, textTransform: 'uppercase' }}>On {service}</div> : null}
              {sameService.map((match) => <MatchRow key={match.case_id} match={match} />)}
            </div>
          ) : (
            <div style={styles.muted}>No past cases on {service ?? 'this service'}.</div>
          )}
          {otherServices.length ? (
            <div style={{ ...styles.stack, gap: 8 }}>
              <button type="button" style={LINK_BUTTON} onClick={() => setShowOthers(!showOthers)}>
                {showOthers ? 'Hide' : 'Show'} {otherServices.length} {otherServices.length === 1 ? 'match' : 'matches'} on other services
              </button>
              {showOthers ? otherServices.map((match) => <MatchRow key={match.case_id} match={match} />) : null}
            </div>
          ) : null}
        </>
      )}
    </>
  );
}

function NoveltyLine({ novelty }: { novelty: Novelty }) {
  const tone = NOVELTY_TONE[novelty.level] ?? NOVELTY_TONE.seen_before;
  return (
    <div data-testid="plugin-novelty">
      <span style={{ ...styles.chip, color: tone, borderColor: `${tone}66`, fontWeight: 700, display: 'inline-block' }}>{novelty.label}</span>
      <div style={{ ...styles.muted, fontSize: 12, marginTop: 6 }}>{novelty.explanation}</div>
    </div>
  );
}

function MatchRow({ match }: { match: PastCaseMatch }) {
  const [showCopies, setShowCopies] = useState(false);
  const strong = match.strength !== 'possible';
  const copies = match.more_like_this ?? [];
  const where = [match.service, match.metric_name ?? (match.origin === 'imported' ? 'past incident' : null), matchDate(match.opened_at)].filter(Boolean).join(' · ');
  const tone = strong ? STRONG : 'rgba(204, 204, 220, 0.72)';
  const outcome = matchOutcome(match);
  const status = matchStatus(match);
  const fullOutcome = outcome.parts.map((part) => `${part.label}${part.unconfirmed ? ' (unconfirmed)' : ''}: ${part.text}`).join(' ');
  return (
    <div data-testid="plugin-past-case-match" style={{ border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12, background: strong ? 'rgba(63, 207, 142, 0.06)' : 'rgba(204, 204, 220, 0.03)' }}>
      <div style={{ ...styles.row, gap: 8 }}>
        <strong>{match.title}</strong>
        <span style={{ ...styles.chip, color: tone, borderColor: `${tone}66` }}>
          {strong ? 'Strong' : 'Possible'} match · {Math.round(match.similarity_score * 100)}%
        </span>
        {match.origin === 'imported' && match.source ? <span style={styles.chip}>Imported from {match.source}</span> : null}
      </div>
      {where ? <div style={{ ...styles.helperText, marginTop: 4 }}>{where}</div> : null}
      {outcome.parts.length ? (
        <div data-testid="plugin-past-case-outcome" title={fullOutcome} style={{ ...TWO_LINES, fontSize: 13, marginTop: 6 }}>
          {outcome.parts.map((part, index) => (
            <React.Fragment key={part.label}>
              {index ? ' ' : ''}
              <b>{part.label}</b>
              {part.unconfirmed ? <span style={{ color: '#ffb357', fontWeight: 700 }}> (unconfirmed)</span> : null}
              : {part.text}
            </React.Fragment>
          ))}
        </div>
      ) : (
        <div data-testid="plugin-past-case-outcome" style={{ ...styles.muted, fontSize: 13, marginTop: 6 }}>{outcome.empty}</div>
      )}
      {copies.length ? (
        <div style={{ marginTop: 6 }}>
          <button type="button" style={LINK_BUTTON} onClick={() => setShowCopies(!showCopies)}>
            {showCopies ? 'Hide repeats' : `+${copies.length} more like this`}
          </button>
          {showCopies ? copies.map((copy) => (
            <div key={copy.case_id} style={{ fontSize: 13, marginTop: 4 }}>
              {copy.title}<span style={styles.muted}> · Case #{copy.case_id} · {Math.round(copy.similarity_score * 100)}%</span>
            </div>
          )) : null}
        </div>
      ) : null}
      <div data-testid="plugin-past-case-status" style={{ fontSize: 13, marginTop: 8, paddingTop: 6, borderTop: '1px solid rgba(204, 204, 220, 0.12)' }}>
        <span style={{ fontWeight: 700, color: STATUS_TONE[status.tone] }}>{status.label}</span>
        {status.detail ? <span style={styles.muted}> · {status.detail}</span> : null}
        <span style={styles.muted}> · Case #{match.case_id}</span>
      </div>
    </div>
  );
}
