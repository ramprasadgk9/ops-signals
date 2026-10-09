import React, { useState } from 'react';
import type { GrafanaCase } from './contracts';
import { getCase } from './backendClient';
import { InvestigationDrawer } from './PanelPreview';
import { Card, styles } from './plainUi';
import { PluginAlerts } from './PluginAlerts';
import { PluginAssistant } from './PluginAssistant';
import { PluginOperationalMemory } from './PluginOperationalMemory';

/** The plugin's "Memory & Alerts" tab: the general assistant, operational memory and received
 * alerts. Any case named in them opens in the same investigation drawer as the other tabs. */
export function PluginMemoryAlertsView({ backendUrl }: { backendUrl: string }) {
  const [openCase, setOpenCase] = useState<GrafanaCase | null>(null);
  const [openError, setOpenError] = useState('');

  const openCaseById = async (caseId: number) => {
    setOpenError('');
    try {
      setOpenCase(await getCase(backendUrl, caseId));
    } catch {
      setOpenError(`Could not open case #${caseId}. Check the backend connection and retry.`);
    }
  };

  if (!backendUrl) {
    return <Card><div style={styles.muted}>Set the Ops Signals backend URL in Interactive or Autonomous Analysis first.</div></Card>;
  }

  return (
    <div style={styles.stack}>
      {openError ? <div style={styles.alert}>{openError}</div> : null}
      <Card><PluginAssistant backendUrl={backendUrl} /></Card>
      <Card><PluginOperationalMemory backendUrl={backendUrl} onOpenCase={openCaseById} /></Card>
      <Card><PluginAlerts backendUrl={backendUrl} onOpenCase={openCaseById} /></Card>
      <InvestigationDrawer
        open={openCase !== null}
        caseResult={null}
        caseDetails={openCase}
        finding={null}
        backendUrl={backendUrl}
        onClose={() => setOpenCase(null)}
        onCaseChange={setOpenCase}
        onError={setOpenError}
      />
    </div>
  );
}
