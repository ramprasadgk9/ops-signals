import { useState } from 'react';

// Which overview sections someone hid, remembered in their browser only. Storage can be missing or
// blocked (private windows, previews): then every section starts shown and the choice lasts the visit.

const KEY = 'ops-signals.overview.hidden';

function readHidden(): string[] {
  try {
    const value = JSON.parse(window.localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function writeHidden(hidden: string[]) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(hidden));
  } catch {
    // Not remembered; the section still hides for this visit.
  }
}

/** [shown, setShown] for one section, shown unless this browser hid it before. */
export function useSectionShown(section: string): [boolean, (shown: boolean) => void] {
  const [shown, setShownState] = useState(() => !readHidden().includes(section));
  const setShown = (next: boolean) => {
    setShownState(next);
    const others = readHidden().filter((item) => item !== section);
    writeHidden(next ? others : [...others, section]);
  };
  return [shown, setShown];
}
