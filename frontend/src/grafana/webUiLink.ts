import { createContext, useContext } from 'react';

// The Ops Signals web UI's address from the plugin settings (optional). Writing and changing
// behavior rules happens there; the plugin only links to it, and shows no link when it is unset.

export const WebUiContext = createContext<string | null>(null);

/** A web UI link for `path` ("/behavior-intelligence?tab=patterns"), or null without an address. */
export function useWebUiHref(path: string | null): string | null {
  const base = useContext(WebUiContext);
  return base && path ? `${base}${path}` : null;
}
