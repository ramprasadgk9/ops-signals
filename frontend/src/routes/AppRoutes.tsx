import { Navigate, Route, Routes } from 'react-router-dom';
import { CaseDetailsPage } from '../pages/CaseDetailsPage';
import { CapabilitiesPage } from '../pages/CapabilitiesPage';
import { FindingsPage } from '../pages/FindingsPage';
import { HistoryPage } from '../pages/HistoryPage';
import { OverviewPage } from '../pages/OverviewPage';
import { AutonomousMonitoringPage } from '../pages/AutonomousMonitoringPage';
import { QuestionAnswerPage } from '../pages/QuestionAnswerPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SignalDetailPage } from '../pages/SignalDetailPage';
import { BehaviorIntelligencePage } from '../pages/BehaviorIntelligencePage';
import { BehaviorLabPage } from '../pages/BehaviorLabPage';
import { AnalyzerRecommendationPage } from '../pages/AnalyzerRecommendationPage';
import { MemoryChatPage } from '../pages/MemoryChatPage';
import { OperationalMemoryPage } from '../pages/OperationalMemoryPage';
import { ValidateDataPage } from '../pages/ValidateDataPage';
import { ExperimentDashboardPage } from '../pages/ExperimentDashboardPage';
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
import { SystemPage } from '../pages/SystemPage';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/autonomous-monitoring" element={<AutonomousMonitoringPage />} />
      <Route path="/investigations" element={<InvestigationsPage />} />
      <Route path="/cases" element={<CasesPage />} />
      <Route path="/cases/:caseId" element={<CaseDetailsPage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/questions/:questionId" element={<QuestionAnswerPage />} />
      <Route path="/capabilities" element={<CapabilitiesPage />} />
      <Route path="/behavior-intelligence" element={<BehaviorIntelligencePage />} />
      <Route path="/behavior-intelligence/lab" element={<BehaviorLabPage />} />
      <Route path="/analyzer-recommendation" element={<AnalyzerRecommendationPage />} />
      <Route path="/validate-data" element={<ValidateDataPage />} />
      <Route path="/experiments" element={<ExperimentDashboardPage />} />
      <Route path="/experiments/add-analyzer" element={<AddAnalyzerPage />} />
      <Route path="/experiments/pyod-outlier-lab" element={<PyodOutlierLabPage />} />
      <Route path="/experiments/prophet-forecast-lab" element={<ProphetForecastLabPage />} />
      <Route path="/experiments/ruptures-change-point-lab" element={<RupturesChangePointLabPage />} />
      <Route path="/experiments/stumpy-motif-lab" element={<StumpyMotifLabPage />} />
      <Route path="/experiments/trend-lab" element={<TrendLabPage />} />
      <Route path="/experiments/zscore-anomaly-lab" element={<ZScoreAnomalyLabPage />} />
      <Route path="/analyzer-router" element={<AnalyzerRouterExperimentPage />} />
      <Route path="/assistant" element={<MemoryChatPage />} />
      <Route path="/operational-memory" element={<OperationalMemoryPage />} />
      <Route path="/memory-chat" element={<MemoryChatPage />} />
      <Route path="/findings" element={<FindingsPage />} />
      <Route path="/integrations" element={<IntegrationsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/system" element={<SystemPage />} />
      <Route path="/signals/:signalId" element={<SignalDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
