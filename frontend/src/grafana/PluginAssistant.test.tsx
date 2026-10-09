import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AssistantChatResponse } from '../types';
import { askAssistantWithMemory, getStarterQuestions, sendAssistantFeedback, updateAssistantFeedbackReason } from './backendClient';
import { PluginAssistant } from './PluginAssistant';

vi.mock('./backendClient', () => ({
  askAssistantWithMemory: vi.fn(),
  getStarterQuestions: vi.fn(),
  sendAssistantFeedback: vi.fn(),
  updateAssistantFeedbackReason: vi.fn(),
}));
const ask = vi.mocked(askAssistantWithMemory);
const starters = vi.mocked(getStarterQuestions);
const feedback = vi.mocked(sendAssistantFeedback);
const reason = vi.mocked(updateAssistantFeedbackReason);

function response(overrides: Partial<AssistantChatResponse> = {}): AssistantChatResponse {
  return {
    conversation_id: 'conv-1',
    intent: 'case_lookup',
    answer: 'Checkout latency rose after the v2.3 deploy; case #3 rolled it back.',
    ai_synthesis_used: false,
    limitations: [],
    suggested_questions: ['What fixed it last time?'],
    sources: [{ source_type: 'case', title: 'Checkout latency after deploy', score: 0.9, reference: 'case:3' }],
    ...overrides,
  };
}

describe('PluginAssistant', () => {
  beforeEach(() => {
    ask.mockReset();
    starters.mockReset();
    feedback.mockReset();
    reason.mockReset();
  });

  it('asks a starter question and shows the answer, its sources and follow-ups', async () => {
    starters.mockResolvedValue({ has_data: true, questions: ['What changed on checkout today?'] });
    ask.mockResolvedValue(response());
    render(<PluginAssistant backendUrl="http://backend" />);

    fireEvent.click(await screen.findByRole('button', { name: 'What changed on checkout today?' }));

    const answer = await screen.findByTestId('plugin-assistant-answer');
    expect(ask).toHaveBeenCalledWith('http://backend', { message: 'What changed on checkout today?', conversationId: null });
    expect(answer).toHaveTextContent('rolled it back');
    expect(answer).toHaveTextContent('Case Checkout latency after deploy');
    expect(screen.getByRole('button', { name: 'What fixed it last time?' })).toBeInTheDocument();
  });

  it('keeps the conversation going on the next question', async () => {
    starters.mockResolvedValue({ has_data: true, questions: [] });
    ask.mockResolvedValue(response());
    render(<PluginAssistant backendUrl="http://backend" />);

    fireEvent.change(screen.getByLabelText('Ask a question'), { target: { value: 'latency on checkout' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await screen.findByTestId('plugin-assistant-answer');
    fireEvent.click(screen.getByRole('button', { name: 'What fixed it last time?' }));

    await screen.findAllByTestId('plugin-assistant-answer');
    expect(ask).toHaveBeenLastCalledWith('http://backend', { message: 'What fixed it last time?', conversationId: 'conv-1' });
  });

  it('saves "No" and then the reason', async () => {
    starters.mockResolvedValue({ has_data: true, questions: ['Q?'] });
    ask.mockResolvedValue(response());
    feedback.mockResolvedValue({ id: 11, question: 'Q?', helpful: false, reason: null, status: 'open', created_at: '2026-10-09T00:00:00Z' });
    reason.mockResolvedValue({ id: 11, question: 'Q?', helpful: false, reason: 'outdated', status: 'open', created_at: '2026-10-09T00:00:00Z' });
    render(<PluginAssistant backendUrl="http://backend" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Q?' }));
    fireEvent.click(await screen.findByRole('button', { name: 'No' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Outdated' }));

    expect(await screen.findByText('Thanks - saved for review')).toBeInTheDocument();
    expect(feedback).toHaveBeenCalledWith('http://backend', expect.objectContaining({ question: 'Q?', helpful: false, conversation_id: 'conv-1', cited: ['case:3'] }));
    expect(reason).toHaveBeenCalledWith('http://backend', 11, 'outdated');
  });

  it('says when nothing has been analysed yet', async () => {
    starters.mockResolvedValue({ has_data: false, questions: [] });
    render(<PluginAssistant backendUrl="http://backend" />);

    expect(await screen.findByText(/Nothing has been analysed yet/)).toBeInTheDocument();
  });

  it('says when the assistant could not answer', async () => {
    starters.mockResolvedValue({ has_data: true, questions: [] });
    ask.mockRejectedValue(new Error('down'));
    render(<PluginAssistant backendUrl="http://backend" />);

    fireEvent.change(screen.getByLabelText('Ask a question'), { target: { value: 'anything' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(await screen.findByText(/The assistant could not answer/)).toBeInTheDocument();
  });
});
