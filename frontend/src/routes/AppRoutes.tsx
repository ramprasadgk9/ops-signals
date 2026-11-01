import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
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
import { AnalyzerSettingsPage } from '../pages/AnalyzerSettingsPage';
import { MemoryChatPage } from '../pages/MemoryChatPage';
import { DOCS_CHECK_PATH, DocsCheckPage } from '../pages/DocsCheckPage';
import { RecurringProblemsPage } from '../pages/RecurringProblemsPage';
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
import { IntegrationsPage } from '../pages/IntegrationsPage';
import { AlertsPage } from '../pages/AlertsPage';
import { SetupCheckPage } from '../pages/SetupCheckPage';
import { RoleArea } from '../components/RoleArea';
import { MetricUsagePage } from '../pages/MetricUsagePage';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RoleArea name="Overview"><OverviewPage /></RoleArea>} />
      <Route path="/autonomous-monitoring" element={<RoleArea name="Autonomous Analysis"><AutonomousMonitoringPage /></RoleArea>} />
      <Route path="/investigations" element={<Navigate to="/cases?tab=in-progress" replace />} />
      <Route path="/cases" element={<RoleArea name="Cases"><CasesPage /></RoleArea>} />
      <Route path="/cases/:caseId" element={<RoleArea name="Cases"><CaseDetailsPage /></RoleArea>} />
      <Route path="/questions/:questionId" element={<RoleArea name="This question"><QuestionAnswerPage /></RoleArea>} />
      <Route path="/capabilities" element={<RoleArea name="Capabilities"><CapabilitiesPage /></RoleArea>} />
      <Route path="/behavior-intelligence" element={<RoleArea name="Behavior Intelligence"><BehaviorIntelligencePage /></RoleArea>} />
      {/* The Lab is now the builder panel on Behavior Intelligence; old links and bookmarks land there. */}
      <Route path="/behavior-intelligence/lab" element={<Navigate to="/behavior-intelligence?tab=patterns&builder=new" replace />} />
      <Route path="/analyzer-recommendation" element={<RoleArea name="Which analyzer fits"><AnalyzerRecommendationPage /></RoleArea>} />
      <Route path="/analyzer-settings" element={<RoleArea name="Settings in use"><AnalyzerSettingsPage /></RoleArea>} />
      <Route path="/validate-data" element={<RoleArea name="New Analysis"><ValidateDataPage /></RoleArea>} />
      {/* The experiment results page was removed; old links land on the closest replacement. */}
      <Route path="/experiments" element={<Navigate to="/experiments/ruptures-change-point-lab" replace />} />
      <Route path="/experiments/add-analyzer" element={<RoleArea name="Add Analyzer"><AddAnalyzerPage /></RoleArea>} />
      <Route path="/experiments/pyod-outlier-lab" element={<RoleArea name="PyOD Outlier Lab"><PyodOutlierLabPage /></RoleArea>} />
      <Route path="/experiments/prophet-forecast-lab" element={<RoleArea name="Prophet Forecast Lab"><ProphetForecastLabPage /></RoleArea>} />
      <Route path="/experiments/ruptures-change-point-lab" element={<RoleArea name="Ruptures Change Point Lab"><RupturesChangePointLabPage /></RoleArea>} />
      <Route path="/experiments/stumpy-motif-lab" element={<RoleArea name="STUMPY Motif Lab"><StumpyMotifLabPage /></RoleArea>} />
      <Route path="/experiments/trend-lab" element={<RoleArea name="Trend Lab"><TrendLabPage /></RoleArea>} />
      <Route path="/experiments/zscore-anomaly-lab" element={<RoleArea name="Z-Score Anomaly Lab"><ZScoreAnomalyLabPage /></RoleArea>} />
      <Route path="/analyzer-router" element={<RoleArea name="Analyzer router"><AnalyzerRouterExperimentPage /></RoleArea>} />
      <Route path="/assistant" element={<RoleArea name="Ask Ops Signals"><MemoryChatPage /></RoleArea>} />
      <Route path={DOCS_CHECK_PATH} element={<RoleArea name="Docs check"><DocsCheckPage /></RoleArea>} />
      <Route path="/recurring-problems" element={<RoleArea name="Recurring problems"><RecurringProblemsPage /></RoleArea>} />
      <Route path="/operational-memory" element={<RedirectKeepingQuery to="/recurring-problems" />} />
      <Route path="/memory-chat" element={<RoleArea name="Ask Ops Signals"><MemoryChatPage /></RoleArea>} />
      <Route path="/findings" element={<RoleArea name="Findings"><FindingsPage /></RoleArea>} />
      <Route path="/metric-usage" element={<RoleArea name="Metric Usage"><MetricUsagePage /></RoleArea>} />
      <Route path="/integrations" element={<RoleArea name="Integrations"><IntegrationsPage /></RoleArea>} />
      <Route path="/alerts" element={<RoleArea name="Alerts"><AlertsPage /></RoleArea>} />
      <Route path="/settings" element={<RoleArea name="Settings"><SettingsPage /></RoleArea>} />
      <Route path="/setup-check" element={<RoleArea name="Setup check"><SetupCheckPage /></RoleArea>} />
      <Route path="/system" element={<Navigate to="/setup-check" replace />} />
      <Route path="/signals/:signalId" element={<RoleArea name="This signal"><SignalDetailPage /></RoleArea>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/** An old page address, kept working for bookmarks and links: same query string, new path. */
function RedirectKeepingQuery({ to }: { to: string }) {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}
