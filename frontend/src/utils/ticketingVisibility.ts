// Shared by the web UI's CaseTicketCard and the Grafana plugin's ticket section.

/** The subset of GET /api/integrations/ticketing/status this rule needs. */
type TicketingStatusLike = { enabled: boolean } | null | undefined;

/** Ticket actions show when ticketing is on, or when the case already has a linked ticket (so
 * turning ticketing off doesn't hide existing links). If the status can't be read (an older
 * backend without the endpoint), show them as before. */
export function shouldShowTicketCard(status: TicketingStatusLike, statusFailed: boolean, linkedTicket: unknown): boolean {
  if (linkedTicket) return true;
  if (statusFailed) return true;
  return Boolean(status?.enabled);
}
