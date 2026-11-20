import CopyWebpackPlugin from 'copy-webpack-plugin';
import webpack, { type Configuration, type RuleSetRule } from 'webpack';
import { merge } from 'webpack-merge';

import grafanaConfig, { type Env } from './.config/webpack/webpack.config.ts';
import { copyFilePatterns } from './.config/bundler/copyFiles.ts';

// The Grafana plugin build: create-plugin's config (.config/, left as scaffolded) plus what this repo
// needs. The web UI in the same folder is built with Vite (vite.config.ts).
const config = async (env: Env): Promise<Configuration> => {
  const base = await grafanaConfig(env);

  // The newer JSX runtime: Grafana provides react/jsx-runtime, so files need no `import React`.
  const rules = (base.module?.rules ?? []).map((rule) => {
    const use = (rule as RuleSetRule).use as { loader?: string; options?: { jsc?: object } } | undefined;
    if (use?.loader !== 'swc-loader') return rule;
    return {
      ...(rule as RuleSetRule),
      use: { ...use, options: { ...use.options, jsc: { ...use.options?.jsc, transform: { react: { runtime: 'automatic' } } } } },
    };
  });

  // LICENSE sits at the repository root, not next to src/. Only plugin.json is copied of the JSON
  // files (create-plugin copies every src/**/*.json).
  const copyPatterns = copyFilePatterns
    .filter((pattern) => pattern.from !== '**/*.json')
    .map((pattern) => (pattern.from === '../LICENSE' ? { ...pattern, from: '../../LICENSE' } : pattern));
  const plugins = (base.plugins ?? []).filter((plugin) => !(plugin instanceof CopyWebpackPlugin));

  return merge(
    { ...base, module: { ...base.module, rules }, plugins },
    {
      // One plugin, one entry (create-plugin otherwise searches the folder for plugin.json files).
      entry: { module: './module.ts' },
      plugins: [
        new CopyWebpackPlugin({ patterns: copyPatterns }),
        // Dev scripts set the backend address the plugin offers before one is configured.
        new webpack.DefinePlugin({
          'import.meta.env.VITE_OPS_SIGNALS_BACKEND_URL': process.env.VITE_OPS_SIGNALS_BACKEND_URL
            ? JSON.stringify(process.env.VITE_OPS_SIGNALS_BACKEND_URL)
            : 'undefined',
        }),
      ],
    }
  );
};

export default config;
