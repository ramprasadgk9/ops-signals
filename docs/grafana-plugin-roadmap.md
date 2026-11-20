# Grafana Plugin Roadmap

Where the Ops Signals Grafana plugin stands, and what is left before it can be listed in Grafana's
plugin catalog. Today the plugin ships as a zip from GitHub releases and people install it by hand,
which works without any of the steps below. The catalog listing is optional; this page keeps the
plan in one place for when we decide to do it.

Tracking issue: [#58](https://github.com/ramprasadgk9/ops-signals/issues/58).

## Where it stands (plugin 1.0.39)

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

Grafana's plugin validator (`npx @grafana/plugin-validator`, run by the plugin workflow, which fails
on an error) reports no errors. Its only warning that matters is "unsigned plugin", which is expected for a plugin
that isn't published yet.

## How the plugin is built

The plugin uses Grafana's [`@grafana/create-plugin`](https://grafana.com/developers/plugin-tools/)
build (webpack), which the catalog review checks for. It lives in `frontend/`, next to the
standalone web UI, which is still built with Vite:

- `frontend/.config/` is create-plugin's configuration, copied as scaffolded (create-plugin 9.0.4).
  Don't edit it; `npx @grafana/create-plugin update` replaces it.
- `frontend/webpack.config.ts` extends it: the newer JSX runtime (Grafana provides
  `react/jsx-runtime`), LICENSE from the repository root, one entry (`src/module.ts`), and the
  build-time default backend URL (`VITE_OPS_SIGNALS_BACKEND_URL`).
- `frontend/src/plugin.json` and `frontend/src/img/` are the plugin's metadata and images. The build
  fills in `%VERSION%` and `%TODAY%`.
- `frontend/package.json` carries the **plugin** version (1.0.x), because the validator compares it
  with `plugin.json`. The project version lives in `pyproject.toml` and the git tag.
- `npm run build:grafana` builds into `frontend/dist`; `npm run dev:grafana` rebuilds on change.
  The build needs Node 24 (it loads its TypeScript config with Node's built-in type stripping).

The plugin code is in `frontend/src/grafana/` and `frontend/src/datasource/`, and imports shared
code (types, `utils/`, `autonomous/` models). It must not import the web UI's pages or components;
`importBoundary.test.ts` checks that.

## Next steps to the catalog

### 1. Move the plugin build to Grafana's create-plugin setup (done)

Before submitting, check the plugin against a real Grafana:

- the plugin unit tests (`npm run test:plugin` and the `src/grafana` tests);
- the Playwright plugin project (`npm run test:integration:plugin`);
- by hand: the Configuration page saves a backend URL; Interactive Analysis runs through both
  "Grafana data source" and "Ops Signals connection"; Autonomous Configure previews and runs once,
  and the Overview loads; Memory & Alerts opens; no errors in the browser console;
- `npx @grafana/plugin-validator` on the new zip reports no errors.

### 2. Submit to the catalog

A new plugin is submitted unsigned. The validator reports "unsigned plugin" only as a warning for a
plugin that isn't published yet; Grafana tells you during the review when it can be signed.

1. Create a GitHub Release for the tag, so the plugin workflow attaches the zip and its `.sha1`.
   The workflow's validator step fails on catalog errors (warnings don't fail it).
2. On grafana.com, under the organization's plugins, submit a new plugin with the zip's public URL,
   its SHA1 and the source code URL. The source code URL must point at the `frontend/` folder of
   the tag (`https://github.com/ramprasadgk9/ops-signals/tree/<tag>/frontend`), where the validator
   finds `package.json`, `.config/` and `src/`. The plugin needs the Ops Signals backend, so include
   short steps for reviewers to start one.

### 3. Sign the plugin

Once Grafana says the plugin can be signed:

1. On grafana.com, in the publishing organization, create an access policy token with the
   `plugins:write` scope.
2. Add it to the GitHub repository as the secret `GRAFANA_ACCESS_POLICY_TOKEN`. The plugin workflow
   and `build_grafana_plugin_artifact.sh` sign the zip when it is set.
3. Build the next release signed, then update [`frontend/README.md`](../frontend/README.md) to
   install from the catalog and drop the `allow_loading_unsigned_plugins` step.

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
