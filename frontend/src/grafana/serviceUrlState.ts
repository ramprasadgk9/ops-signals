import { locationService } from '@grafana/runtime';

/** The overview's Service filter lives in the page URL (`?service=`), so a Grafana link can open it
 * already filtered. Grafana owns the router, so this goes through its location service. */
export function readServiceParam(): string | null {
  try {
    const value = locationService.getSearchObject().service;
    return typeof value === 'string' && value ? value : null;
  } catch {
    return null;
  }
}

export function writeServiceParam(service: string | null) {
  try {
    locationService.partial({ service }, true);
  } catch {
    // Outside Grafana (tests, previews) the filter still works; it just isn't kept in the URL.
  }
}
