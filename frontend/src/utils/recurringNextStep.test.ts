import { describe, expect, it } from 'vitest';
import type { RecurringProblem } from '../types';
import { caseToRecordCauseOn, recurrenceForCase, recurringNextStep } from './recurringNextStep';

const problem = (overrides: Partial<RecurringProblem> = {}): RecurringProblem => ({
  name: 'Lab value drifts',
  named_by: 'central_case',
  central_case_id: 3,
  occurrences: 3,
  services: ['trend-lab'],
  verified_root_causes: 0,
  open_cases: 1,
  causes: [],
  cases: [
    { case_id: 3, title: 'Latest', origin: 'detected', case_status: 'resolved', rca_verified: true, similarity_to_central: 1 },
    { case_id: 2, title: 'Middle', origin: 'detected', case_status: 'open', rca_verified: false, similarity_to_central: 0.9 },
    { case_id: 1, title: 'Oldest', origin: 'detected', case_status: 'open', rca_verified: false, similarity_to_central: 0.85 },
  ],
  ...overrides,
});

const cause = (case_id: number, root_cause: string, verified = true) => ({ case_id, root_cause, fix: null, verified });

describe('recurringNextStep', () => {
  it('asks for a cause when none is recorded', () => {
    expect(recurringNextStep(problem(), 'symptom').tone).toBe('record');
  });

  it('asks to confirm a cause when none is verified', () => {
    const step = recurringNextStep(problem({ causes: [cause(1, 'Pool exhausted', false), cause(2, 'Pool exhausted', false)] }), 'symptom');
    expect(step.tone).toBe('verify');
    expect(step.detail).toContain('2 cases have a cause written down');
  });

  it('calls for a lasting fix when every verified cause is the same, ignoring case and a trailing full stop', () => {
    const step = recurringNextStep(problem({ causes: [cause(3, 'Wrong image version.'), cause(2, 'wrong  image version'), cause(1, 'Traffic spike', false)] }), 'symptom');
    expect(step.tone).toBe('fix');
    expect(step.detail).toContain('Wrong image version.');
  });

  it('says the causes differ when verified causes disagree', () => {
    const step = recurringNextStep(problem({ causes: [cause(3, 'Wrong image version'), cause(2, 'Traffic spike')] }), 'symptom');
    expect(step.tone).toBe('mixed');
    expect(step.detail).toContain('2 different verified causes');
  });

  it('grouped by cause, a verified group already shares its cause', () => {
    const step = recurringNextStep(problem({ causes: [cause(3, 'Wrong image version'), cause(2, 'Bad tag pushed')] }), 'cause');
    expect(step.tone).toBe('fix');
    expect(step.detail).toBe('The same cause came back 3 times.');
  });
});

describe('caseToRecordCauseOn', () => {
  it('prefers the latest open case, else the latest case', () => {
    expect(caseToRecordCauseOn(problem())).toBe(2);
    const allResolved = problem().cases.map((item) => ({ ...item, case_status: 'resolved' }));
    expect(caseToRecordCauseOn(problem({ cases: allResolved }))).toBe(3);
  });
});

describe('recurrenceForCase', () => {
  it('finds the group a case is in and a cause found on another case', () => {
    const recurrence = recurrenceForCase([problem({ causes: [cause(1, 'Own cause'), cause(3, 'Earlier cause')] })], 1);
    expect(recurrence?.problem.central_case_id).toBe(3);
    expect(recurrence?.lastCause?.root_cause).toBe('Earlier cause');
  });

  it('is null for a case in no group', () => {
    expect(recurrenceForCase([problem()], 99)).toBeNull();
  });
});
