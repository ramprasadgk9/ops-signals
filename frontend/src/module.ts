import { AppPlugin, DataSourcePlugin, PanelPlugin } from '@grafana/data';
import { OpsSignalsDataSourceApi } from './datasource/OpsSignalsDataSourceApi';
import { ConfigEditor } from './datasource/ConfigEditor';
import { QueryEditor } from './datasource/QueryEditor';
import { QueryEditorHelp } from './datasource/QueryEditorHelp';
import { AppConfig } from './grafana/AppConfig';
import { PluginApp } from './grafana/PluginApp';
import { PluginPanel } from './grafana/PluginPanel';
import type { OpsSignalsDataSourceOptions } from './datasource/types';

export const pluginId = 'breezypoppy3596-opssignals-app';

export const plugin = new AppPlugin().setRootPage(PluginApp as any).addConfigPage({
  title: 'Configuration',
  icon: 'cog',
  body: AppConfig as any,
  id: 'configuration',
});

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
