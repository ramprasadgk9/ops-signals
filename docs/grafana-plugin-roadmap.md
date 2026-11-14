# Grafana Plugin Roadmap

Where the Ops Signals Grafana plugin stands, and what is left before it can be listed in Grafana's
plugin catalog. Today the plugin ships as a zip from GitHub releases and people install it by hand,
which works without any of the steps below. The catalog listing is optional; this page keeps the
plan in one place for when we decide to do it.

Tracking issue: [#58](https://github.com/ramprasadgk9/ops-signals/issues/58).

## Where it stands (plugin 1.0.38)

- **Id:** `breezypoppy3596-opssignals-app`. `breezypoppy3596` is the grafana.com organization that
  will publish it. Grafana's id rule allows one word between the organization and `-app`, so the
  product name is written `opssignals` here and `ops-signals` everywhere else.
- **Install:** a zip attached to each release by `.github/workflows/plugin.yml`, installed with the
  Grafana CLI or unzipped into Grafana's plugins folder. See
  [`frontend/README.md`](../frontend/README.md).
- **Unsigned:** Grafana loads it only when `allow_loading_unsigned_plugins` names it.
- **Configuration page:** a Grafana admin sets the backend URL once (or in provisioning,
  `jsonData.backendUrl`).
- **Catalog details in `plugin.json`:** description, links, screenshots, minimum Grafana 13.1.
- **Forms:** Interactive Analysis (Data, What, When) and Autonomous Configure (Data, Scope, Watch,
  When) use the same step layout.

Grafana's plugin validator (`npx @grafana/plugin-validator`, run report-only in the plugin workflow)
still reports three errors. They block the catalog, not installing the zip.

| Validator error | What it means | Fixed by |
| --- | --- | --- |
| Non-standard frontend build tooling | The plugin is built with Vite; the catalog wants Grafana's `create-plugin` setup | Step 1 |
| Known issues in dev dependencies | vite 5, vitest 2 and their dependencies are flagged | Step 1 |
| `package.json` version differs from `plugin.json` | The plugin shares `frontend/package.json` (project version 0.x) with the web UI | Step 1 |

## Next steps to the catalog

Do these in order, after the repository is public.

### 1. Move the plugin build to Grafana's create-plugin setup

**What it is.** [`@grafana/create-plugin`](https://grafana.com/developers/plugin-tools/) is
Grafana's official starter kit for plugins: a webpack build Grafana maintains, a `.config/` folder,
standard build and test commands, and the plugin's own `package.json`. The catalog review checks
for it.

**How it works today.** The plugin lives in `frontend/`, next to the standalone web UI, and shares
its `package.json`. `npm run build:grafana` builds it with Vite (`frontend/vite.plugin.config.ts`),
which includes a small fix so Grafana's module loader gets React correctly. The plugin code is in
`frontend/src/grafana/` and imports shared code (types, `utils/`, `autonomous/` models). It must
not import the web UI's pages or components; `importBoundary.test.ts` checks that.

**The work.**

1. Create a plugin project in its own folder (for example `grafana-plugin/`) with
   `npx @grafana/create-plugin`, keeping the id `breezypoppy3596-opssignals-app` and the plugin
   version (1.0.x) in its `package.json`.
2. Point it at the existing plugin code. Either move `frontend/src/grafana/` and the shared code it
   imports, or make the shared code importable from both projects (a path alias or a small shared
   package). Keep the import boundary test.
3. Replace `npm run build:grafana` and update everything that uses its output:
   `docker-compose.yml` (mounts `frontend/dist` into Grafana), `scripts/run_grafana_stack.sh`,
   `scripts/record_screenshots.sh`, `scripts/release/build_grafana_plugin_artifact.sh`, the CI
   workflows, and the setup docs ([`grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md)).
4. Move the plugin's unit tests and the Playwright plugin project to the new setup.

**Is it a breaking change?** Not for people using the plugin: the id, address, settings, screens and
install steps stay the same, and the update is an ordinary version bump. It is a large change for
development: folder layout, build commands, compose mount, scripts, CI and docs.

**The risk.** The webpack build must produce a `module.js` that behaves exactly like today's,
especially in how it loads React and `@grafana/*` from Grafana (the reason for the Vite fix).

**How to check it.** Before merging, all of these pass against a real Grafana:

- the plugin unit tests (`npm run test:plugin` and the `src/grafana` tests);
- the Playwright plugin project (`npm run test:integration:plugin`);
- by hand: the Configuration page saves a backend URL; Interactive Analysis runs through both
  "Grafana data source" and "Ops Signals connection"; Autonomous Configure previews and runs once,
  and the Overview loads; Memory & Alerts opens; no errors in the browser console;
- `npx @grafana/plugin-validator` on the new zip reports no errors.

This step also fixes the other two validator errors: the new `package.json` carries the plugin
version, and the new project starts on current build and test tools.

### 2. Sign the plugin

1. On grafana.com, in the publishing organization, create an access policy token with the
   `plugins:write` scope.
2. Add it to the GitHub repository as the secret `GRAFANA_ACCESS_POLICY_TOKEN`. The plugin workflow
   and `build_grafana_plugin_artifact.sh` sign the zip when it is set.
3. Make the validator step in `.github/workflows/plugin.yml` blocking (remove
   `continue-on-error`).

A community signature comes through the catalog review in step 3. Until then the zip stays
unsigned.

### 3. Submit to the catalog

1. Create a GitHub Release for the tag, so the plugin workflow attaches the zip and its `.sha1`.
2. On grafana.com, under the organization's plugins, submit a new plugin with the zip's public URL,
   its SHA1 and the source code URL.
3. Once it is accepted, update [`frontend/README.md`](../frontend/README.md) to install from the
   catalog and drop the `allow_loading_unsigned_plugins` step.

## Later, not needed for the catalog

- **Validate Data options from the web UI:** several metrics at once, choosing the analyzer, step,
  and preview.
- **Behavior findings show no cluster** (the backend doesn't record one yet). Cases created before
  2026-10-09 have no saved cluster either.
- **Ask Ops Signals sometimes answers "what caused X" with documentation text** instead of cases
  ([#44](https://github.com/ramprasadgk9/ops-signals/issues/44),
  [#65](https://github.com/ramprasadgk9/ops-signals/issues/65)). The catalog screenshots leave the
  assistant out until this is fixed.
- **Retake the catalog screenshots** after visible changes: `./scripts/record_screenshots.sh`, then
  copy the plugin captures as described in [`release-packaging.md`](release-packaging.md).
