// Demo mode's "Things to try" (ThingsToTry.tsx) listens for these; elsewhere they go unheard.
// No imports, so any module (the API client too) can fire one.
export const DEMO_STEP_EVENT = 'ops-signals:demo-step';

export function markDemoStep(mark: string): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(DEMO_STEP_EVENT, { detail: mark }));
}
