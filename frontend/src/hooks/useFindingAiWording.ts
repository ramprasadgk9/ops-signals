import { useQuery } from '@tanstack/react-query';
import { api } from '../api/queries';
import type { FindingAIWording, FindingPlain } from '../types';
import { useWebPermissions } from './useWebPermissions';

// AI wording for a saved finding's plain lines (GET /api/findings/{id}/ai-wording), asked for after
// the finding shows, so nothing waits for the model; the template shows meanwhile and without AI.

export function useFindingAiWording(finding: { id?: number | null; plain?: FindingPlain | null } | null | undefined, enabled = true) {
  const { canAdmin } = useWebPermissions();
  const findingId = finding?.id;
  const query = useQuery({
    queryKey: ['finding-ai-wording', findingId],
    queryFn: () => api.findingAiWording(findingId as number),
    enabled: enabled && typeof findingId === 'number' && Boolean(finding?.plain),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60_000,
  });
  const ai: FindingAIWording | undefined = query.data;
  return {
    ai,
    aiPending: query.isPending && query.fetchStatus === 'fetching',
    /** No AI provider is on and this person could turn one on. */
    showAiHint: ai?.reason === 'ai_off' && canAdmin,
  };
}
