import { AppPlugin, DataSourcePlugin, PanelPlugin } from '@grafana/data';
import { OpsSignalsDataSourceApi } from './datasource/OpsSignalsDataSourceApi';
import { ConfigEditor } from './datasource/ConfigEditor';
import { QueryEditor } from './datasource/QueryEditor';
import { QueryEditorHelp } from './datasource/QueryEditorHelp';
import { PluginApp } from './grafana/PluginApp';
import { PluginPanel } from './grafana/PluginPanel';
import type { OpsSignalsDataSourceOptions } from './datasource/types';

export const pluginId = 'ops-signals-app';

export const plugin = new AppPlugin().setRootPage(PluginApp as any);

export const dataSourcePlugin = new DataSourcePlugin<OpsSignalsDataSourceApi, any, OpsSignalsDataSourceOptions>(OpsSignalsDataSourceApi)
  .setConfigEditor(ConfigEditor as any)
  .setQueryEditor(QueryEditor as any)
  .setQueryEditorHelp(QueryEditorHelp);

export const panelPlugin = new PanelPlugin(PluginPanel as any);

export const pluginModules = {
  app: plugin,
  datasource: dataSourcePlugin,
  panel: panelPlugin,
};
