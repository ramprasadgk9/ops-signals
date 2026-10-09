import React, { useEffect, useState } from 'react';
import type { AssistantChatResponse, AssistantFeedbackReason, StarterQuestions } from '../types';
import { askAssistantWithMemory, getStarterQuestions, sendAssistantFeedback, updateAssistantFeedbackReason } from './backendClient';
import { styles } from './plainUi';

// The general assistant (questions about any service, metric, finding, case or the docs, not tied to
// one run) in the Grafana plugin's own styling. Same endpoints and wording as the web UI's
// MemoryChatPage, without its docs-authoring tools.

const FEEDBACK_REASONS: Array<{ value: AssistantFeedbackReason; label: string }> = [
  { value: 'wrong_section', label: 'Wrong section' },
  { value: 'missing_step', label: 'Missing a step' },
  { value: 'outdated', label: 'Outdated' },
  { value: 'not_in_docs', label: 'Not in the docs' },
];
const SOURCES_SHOWN = 4;
const BOX: React.CSSProperties = { border: '1px solid rgba(204, 204, 220, 0.14)', borderRadius: 8, padding: 12 };
const LINK_BUTTON: React.CSSProperties = { border: 0, background: 'transparent', color: '#5794f2', padding: 0, cursor: 'pointer', fontWeight: 600, textAlign: 'left' };
const PICKED: React.CSSProperties = { background: '#5794f2', color: '#fff', border: '1px solid #5794f2' };

type Turn = { question: string; response: AssistantChatResponse | null; failed?: boolean };

function sourceLabel(sourceType: string) {
  if (sourceType === 'case' || sourceType === 'historical_case') return 'Case';
  if (sourceType === 'finding') return 'Finding';
  if (sourceType === 'behavior') return 'Behavior';
  if (sourceType === 'app_documentation') return 'Doc';
  return sourceType;
}

export function PluginAssistant({ backendUrl }: { backendUrl: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setMessage('');
    setBusy(true);
    setTurns((current) => [...current, { question, response: null }]);
    try {
      const response = await askAssistantWithMemory(backendUrl, { message: question, conversationId });
      setConversationId(response.conversation_id);
      setTurns((current) => current.map((turn, index) => (index === current.length - 1 ? { ...turn, response } : turn)));
    } catch {
      setTurns((current) => current.map((turn, index) => (index === current.length - 1 ? { ...turn, failed: true } : turn)));
    } finally {
      setBusy(false);
    }
  };

  const latest = turns[turns.length - 1]?.response;
  return (
    <section data-testid="plugin-assistant" style={{ ...styles.stack, gap: 12 }}>
      <div>
        <strong style={{ fontSize: 16 }}>Ask Ops Signals</strong>
        <div style={{ ...styles.helperText, marginTop: 2 }}>
          Ask about any service, metric, finding or case by name, or how to use Ops Signals. Answers cite the cases, findings and docs they use.
        </div>
      </div>
      {!turns.length ? <StarterList backendUrl={backendUrl} onAsk={ask} /> : null}
      {turns.map((turn, index) => (
        <div key={`${index}-${turn.question}`} style={{ ...styles.stack, gap: 8 }}>
          <div style={{ ...BOX, alignSelf: 'flex-end', maxWidth: '85%', background: 'rgba(87, 148, 242, 0.12)' }}>{turn.question}</div>
          {turn.response ? (
            <Answer backendUrl={backendUrl} question={turn.question} response={turn.response} conversationId={conversationId} />
          ) : turn.failed ? (
            <div style={{ ...styles.muted, color: '#ff7381' }}>The assistant could not answer. Check the backend connection and try again.</div>
          ) : (
            <div style={styles.muted}>Thinking...</div>
          )}
        </div>
      ))}
      {latest?.suggested_questions?.length ? (
        <div style={{ ...styles.row, gap: 8 }}>
          {latest.suggested_questions.slice(0, 4).map((question) => (
            <button key={question} type="button" style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: 'pointer' }} disabled={busy} onClick={() => ask(question)}>{question}</button>
          ))}
        </div>
      ) : null}
      <form
        style={{ display: 'flex', gap: 8 }}
        onSubmit={(event) => {
          event.preventDefault();
          void ask(message);
        }}
      >
        <input
          aria-label="Ask a question"
          style={styles.input}
          value={message}
          placeholder='e.g. "latency on checkout-api last night" or "how do I import past incidents?"'
          onChange={(event) => setMessage(event.target.value)}
        />
        <button type="submit" style={{ ...styles.button, ...(busy || !message.trim() ? styles.buttonDisabled : {}) }} disabled={busy || !message.trim()}>Ask</button>
      </form>
    </section>
  );
}

function StarterList({ backendUrl, onAsk }: { backendUrl: string; onAsk: (question: string) => void }) {
  const [starters, setStarters] = useState<StarterQuestions | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    getStarterQuestions(backendUrl)
      .then((data) => { if (active) setStarters(data); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [backendUrl]);

  if (failed) return <div style={styles.muted}>Couldn't load examples. Ask about a service, metric, finding or case by name.</div>;
  if (!starters) return null;
  if (!starters.has_data) {
    return <div style={styles.muted}>Nothing has been analysed yet, so there are no findings or cases to ask about. Run an analysis first, or ask how Ops Signals works.</div>;
  }
  return (
    <div style={{ ...styles.stack, gap: 6 }}>
      <div style={styles.helperText}>From what was analysed most recently</div>
      {starters.questions.map((question) => (
        <button key={question} type="button" style={{ ...styles.questionButton, padding: '8px 12px' }} onClick={() => onAsk(question)}>{question}</button>
      ))}
    </div>
  );
}

function Answer({ backendUrl, question, response, conversationId }: { backendUrl: string; question: string; response: AssistantChatResponse; conversationId: string | null }) {
  const [showAllSources, setShowAllSources] = useState(false);
  const sources = showAllSources ? response.sources : response.sources.slice(0, SOURCES_SHOWN);
  return (
    <div data-testid="plugin-assistant-answer" style={{ ...BOX, ...styles.stack, gap: 8 }}>
      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{response.answer}</div>
      {response.limitations.length ? (
        <div style={styles.helperText}>{response.limitations.join(' ')}</div>
      ) : null}
      {response.sources.length ? (
        <div style={{ ...styles.stack, gap: 4 }}>
          <div style={{ ...styles.tableHeader, textTransform: 'uppercase' }}>Based on</div>
          {sources.map((source) => (
            <div key={`${source.source_type}-${source.reference}`} style={{ fontSize: 13 }}>
              <span style={styles.chip}>{sourceLabel(source.source_type)}</span>{' '}
              {source.title}
              {source.quote ? <div style={{ ...styles.helperText, margin: '2px 0 0', fontStyle: 'italic' }}>"{source.quote}"</div> : null}
            </div>
          ))}
          {response.sources.length > SOURCES_SHOWN ? (
            <button type="button" style={LINK_BUTTON} onClick={() => setShowAllSources(!showAllSources)}>
              {showAllSources ? 'Show fewer' : `Show ${response.sources.length - SOURCES_SHOWN} more`}
            </button>
          ) : null}
        </div>
      ) : null}
      <AnswerFeedback backendUrl={backendUrl} question={question} response={response} conversationId={conversationId} />
    </div>
  );
}

function AnswerFeedback({ backendUrl, question, response, conversationId }: { backendUrl: string; question: string; response: AssistantChatResponse; conversationId: string | null }) {
  const [helpful, setHelpful] = useState<boolean | null>(null);
  const [feedbackId, setFeedbackId] = useState<number | null>(null);
  const [reason, setReason] = useState<AssistantFeedbackReason | null>(null);
  const [state, setState] = useState<'idle' | 'saved' | 'failed' | 'reason_saved' | 'reason_failed'>('idle');

  const choose = async (value: boolean) => {
    if (helpful !== null) return;
    setHelpful(value);
    try {
      const saved = await sendAssistantFeedback(backendUrl, {
        question,
        helpful: value,
        answer: response.answer,
        conversation_id: conversationId,
        ai_synthesis_used: response.ai_synthesis_used,
        cited: response.sources.slice(0, 3).map((source) => source.reference).filter(Boolean),
      });
      setFeedbackId(saved.id);
      setState('saved');
    } catch {
      setState('failed');
    }
  };

  const explain = async (value: AssistantFeedbackReason) => {
    if (reason !== null || feedbackId === null) return;
    setReason(value);
    try {
      await updateAssistantFeedbackReason(backendUrl, feedbackId, value);
      setState('reason_saved');
    } catch {
      setState('reason_failed');
    }
  };

  const choice = (value: boolean, label: string) => (
    <button
      type="button"
      aria-pressed={helpful === value}
      aria-disabled={helpful !== null}
      onClick={() => choose(value)}
      style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: helpful === null ? 'pointer' : 'default', ...(helpful === value ? PICKED : {}) }}
    >
      {label}
    </button>
  );

  return (
    <div style={{ ...styles.stack, gap: 6, borderTop: '1px solid rgba(204, 204, 220, 0.12)', paddingTop: 8 }}>
      <div style={{ ...styles.row, gap: 8 }}>
        <span style={{ ...styles.muted, fontSize: 13 }}>Did this answer your question?</span>
        {choice(true, 'Yes')}
        {choice(false, 'No')}
        {helpful === true && state === 'saved' ? <span style={{ fontSize: 13, color: '#3fcf8e', fontWeight: 700 }}>Thanks</span> : null}
        {state === 'failed' ? <span style={{ fontSize: 13, color: '#ff7381' }}>Couldn't save feedback</span> : null}
      </div>
      {helpful === false && feedbackId !== null ? (
        <div style={{ ...styles.row, gap: 8 }}>
          <span style={{ ...styles.muted, fontSize: 13 }}>What was wrong?</span>
          {FEEDBACK_REASONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={reason === option.value}
              onClick={() => explain(option.value)}
              style={{ ...styles.chip, background: 'transparent', color: 'inherit', cursor: reason === null ? 'pointer' : 'default', ...(reason === option.value ? { ...PICKED, background: '#ffb357', border: '1px solid #ffb357', color: '#111217' } : {}) }}
            >
              {option.label}
            </button>
          ))}
          {state === 'reason_saved' ? <span style={{ fontSize: 13, color: '#3fcf8e', fontWeight: 700 }}>Thanks - saved for review</span> : null}
          {state === 'reason_failed' ? <span style={{ fontSize: 13, color: '#ff7381' }}>Couldn't save the reason</span> : null}
        </div>
      ) : null}
    </div>
  );
}
