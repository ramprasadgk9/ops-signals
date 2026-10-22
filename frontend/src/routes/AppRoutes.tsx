import { Navigate, Route, Routes } from 'react-router-dom';
import { CaseDetailsPage } from '../pages/CaseDetailsPage';
import { CapabilitiesPage } from '../pages/CapabilitiesPage';
import { FindingsPage } from '../pages/FindingsPage';
import { OverviewPage } from '../pages/OverviewPage';
import { AutonomousMonitoringPage } from '../pages/AutonomousMonitoringPage';
import { QuestionAnswerPage } from '../pages/QuestionAnswerPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SignalDetailPage } from '../pages/SignalDetailPage';
import { BehaviorIntelligencePage } from '../pages/BehaviorIntelligencePage';
import { AnalyzerRecommendationPage } from '../pages/AnalyzerRecommendationPage';
import { MemoryChatPage } from '../pages/MemoryChatPage';
import { DOCS_CHECK_PATH, DocsCheckPage } from '../pages/DocsCheckPage';
import { OperationalMemoryPage } from '../pages/OperationalMemoryPage';
import { ValidateDataPage } from '../pages/ValidateDataPage';
import { AnalyzerRouterExperimentPage } from '../pages/AnalyzerRouterExperimentPage';
import { AddAnalyzerPage } from '../pages/analyzer-labs/AddAnalyzerPage';
import { PyodOutlierLabPage } from '../pages/analyzer-labs/PyodOutlierLabPage';
import { ProphetForecastLabPage } from '../pages/analyzer-labs/ProphetForecastLabPage';
import { RupturesChangePointLabPage } from '../pages/analyzer-labs/RupturesChangePointLabPage';
import { StumpyMotifLabPage } from '../pages/analyzer-labs/StumpyMotifLabPage';
import { TrendLabPage } from '../pages/analyzer-labs/TrendLabPage';
import { ZScoreAnomalyLabPage } from '../pages/analyzer-labs/ZScoreAnomalyLabPage';
import { CasesPage } from '../pages/CasesPage';
import { InvestigationsPage } from '../pages/InvestigationsPage';
import { IntegrationsPage } from '../pages/IntegrationsPage';
import { AlertsPage } from '../pages/AlertsPage';
import { SetupCheckPage } from '../pages/SetupCheckPage';
import { AdminArea } from '../components/AdminArea';
import { MetricUsagePage } from '../pages/MetricUsagePage';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/autonomous-monitoring" element={<AutonomousMonitoringPage />} />
      <Route path="/investigations" element={<InvestigationsPage />} />
      <Route path="/cases" element={<CasesPage />} />
      <Route path="/cases/:caseId" element={<CaseDetailsPage />} />
      <Route path="/questions/:questionId" element={<QuestionAnswerPage />} />
      <Route path="/capabilities" element={<CapabilitiesPage />} />
      <Route path="/behavior-intelligence" element={<BehaviorIntelligencePage />} />
      {/* The Lab is now the builder panel on Behavior Intelligence; old links and bookmarks land there. */}
      <Route path="/behavior-intelligence/lab" element={<Navigate to="/behavior-intelligence?tab=patterns&builder=new" replace />} />
      <Route path="/analyzer-recommendation" element={<AnalyzerRecommendationPage />} />
      <Route path="/validate-data" element={<ValidateDataPage />} />
      {/* The experiment results page was removed; old links land on the closest replacement. */}
      <Route path="/experiments" element={<Navigate to="/experiments/ruptures-change-point-lab" replace />} />
      <Route path="/experiments/add-analyzer" element={<AdminArea><AddAnalyzerPage /></AdminArea>} />
      <Route path="/experiments/pyod-outlier-lab" element={<AdminArea><PyodOutlierLabPage /></AdminArea>} />
      <Route path="/experiments/prophet-forecast-lab" element={<AdminArea><ProphetForecastLabPage /></AdminArea>} />
      <Route path="/experiments/ruptures-change-point-lab" element={<AdminArea><RupturesChangePointLabPage /></AdminArea>} />
      <Route path="/experiments/stumpy-motif-lab" element={<AdminArea><StumpyMotifLabPage /></AdminArea>} />
      <Route path="/experiments/trend-lab" element={<AdminArea><TrendLabPage /></AdminArea>} />
      <Route path="/experiments/zscore-anomaly-lab" element={<AdminArea><ZScoreAnomalyLabPage /></AdminArea>} />
      <Route path="/analyzer-router" element={<AnalyzerRouterExperimentPage />} />
      <Route path="/assistant" element={<MemoryChatPage />} />
      <Route path={DOCS_CHECK_PATH} element={<DocsCheckPage />} />
      <Route path="/operational-memory" element={<OperationalMemoryPage />} />
      <Route path="/memory-chat" element={<MemoryChatPage />} />
      <Route path="/findings" element={<FindingsPage />} />
      <Route path="/metric-usage" element={<MetricUsagePage />} />
      <Route path="/integrations" element={<IntegrationsPage />} />
      <Route path="/alerts" element={<AlertsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/setup-check" element={<SetupCheckPage />} />
      <Route path="/system" element={<Navigate to="/setup-check" replace />} />
      <Route path="/signals/:signalId" element={<SignalDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
