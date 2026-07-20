import { PluginPage } from '@grafana/runtime';
import { OpsSignalsPlugin } from './plugin/OpsSignalsPlugin';

function App() {
  return (
    <PluginPage>
      <OpsSignalsPlugin />
    </PluginPage>
  );
}

export default App;
