import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';

const CUSTOM_ANALYZERS_PATH = path.resolve(__dirname, '../../../../config/custom_analyzers.yaml');

/**
 * Seeds a custom analyzer draft with no runtime mapping (runtime_mapping defaults to
 * "not_implemented" in backend/app/api/admin_analyzers.py::AnalyzerConfigIn) and promotes it,
 * so the router can recommend it while the pipeline reports it as unavailable to execute.
 * This is the "unavailable" outcome in the recommendation matrix — see
 * docs/analyzer-recommendation.md, "Router-to-pipeline mapping".
 */
export async function seedUnmappedCustomAnalyzer(backendUrl: string, analyzerId: string): Promise<{ draftId: number }> {
  const config = {
    analyzer_id: analyzerId,
    display_name: `Integration suite unmapped analyzer (${analyzerId})`,
    template_type: 'custom',
    library: 'integration-suite-stub',
    enabled: true,
    supported_profiles: ['trend', 'anomaly', 'spike', 'seasonal'],
    min_samples: 10,
    requires_regular_sampling: false,
    requires_numeric: true,
    base_score: 0.95,
    // At least one scoring rule is required by the backend (confirmed live: "At least one scoring
    // rule is required."). sample_count gte 0 is always true, so eligibility is driven by base_score.
    scoring_rules: [{ metric: 'sample_count', operator: 'gte', threshold: 0, add: 0 }],
    runtime_params: {},
    selected_explanation: 'Always eligible so the integration suite can force an "unavailable" outcome deterministically.',
    excluded_explanation: 'Not excluded by design for this fixture.',
  };

  const draftResponse = await fetch(`${backendUrl}/api/analyzer-labs/drafts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, created_by: 'integration-suite' }),
  });
  if (!draftResponse.ok) {
    throw new Error(`Failed to seed custom analyzer draft: ${draftResponse.status} ${await draftResponse.text()}`);
  }
  const draft = (await draftResponse.json()) as { id: number };

  const promoteResponse = await fetch(`${backendUrl}/api/analyzer-labs/drafts/${draft.id}/promote`, { method: 'POST' });
  if (!promoteResponse.ok) {
    throw new Error(`Failed to promote custom analyzer draft: ${promoteResponse.status} ${await promoteResponse.text()}`);
  }

  return { draftId: draft.id };
}

/**
 * Deletes the draft row via the API, then strips the promoted entry out of
 * config/custom_analyzers.yaml directly — promote() writes that file but there is no
 * corresponding API to un-write it, so leaving this out would leak the fixture analyzer
 * into every later run's routing config.
 */
export async function deleteCustomAnalyzerDraft(backendUrl: string, draftId: number, analyzerId: string): Promise<void> {
  await fetch(`${backendUrl}/api/analyzer-labs/drafts/${draftId}`, { method: 'DELETE' });

  if (!existsSync(CUSTOM_ANALYZERS_PATH)) return;
  const custom = (yaml.load(readFileSync(CUSTOM_ANALYZERS_PATH, 'utf-8')) ?? {}) as { analyzers?: Record<string, unknown> };
  if (custom.analyzers && analyzerId in custom.analyzers) {
    delete custom.analyzers[analyzerId];
    writeFileSync(CUSTOM_ANALYZERS_PATH, yaml.dump(custom, { sortKeys: false }));
  }
}
