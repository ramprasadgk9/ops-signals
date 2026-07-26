import { Navigate, Route, Routes } from 'react-router-dom';
import { CaseDetailsPage } from '../pages/CaseDetailsPage';
import { CapabilitiesPage } from '../pages/CapabilitiesPage';
import { FindingsPage } from '../pages/FindingsPage';
import { HistoryPage } from '../pages/HistoryPage';
import { OverviewPage } from '../pages/OverviewPage';
import { QuestionAnswerPage } from '../pages/QuestionAnswerPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SignalDetailPage } from '../pages/SignalDetailPage';
import { BehaviorIntelligencePage } from '../pages/BehaviorIntelligencePage';
import { AnalyzerRecommendationPage } from '../pages/AnalyzerRecommendationPage';
import { MemoryChatPage } from '../pages/MemoryChatPage';
import { OperationalMemoryPage } from '../pages/OperationalMemoryPage';
import { ValidateDataPage } from '../pages/ValidateDataPage';
import { ExperimentDashboardPage } from '../pages/ExperimentDashboardPage';
import { AnalyzerRouterExperimentPage } from '../pages/AnalyzerRouterExperimentPage';
import { CasesPage } from '../pages/CasesPage';
import { InvestigationsPage } from '../pages/InvestigationsPage';
import { SystemPage } from '../pages/SystemPage';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/investigations" element={<InvestigationsPage />} />
      <Route path="/cases" element={<CasesPage />} />
      <Route path="/cases/:caseId" element={<CaseDetailsPage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/questions/:questionId" element={<QuestionAnswerPage />} />
      <Route path="/capabilities" element={<CapabilitiesPage />} />
      <Route path="/behavior-intelligence" element={<BehaviorIntelligencePage />} />
      <Route path="/analyzer-recommendation" element={<AnalyzerRecommendationPage />} />
      <Route path="/validate-data" element={<ValidateDataPage />} />
      <Route path="/experiments" element={<ExperimentDashboardPage />} />
      <Route path="/analyzer-router" element={<AnalyzerRouterExperimentPage />} />
      <Route path="/assistant" element={<MemoryChatPage />} />
      <Route path="/operational-memory" element={<OperationalMemoryPage />} />
      <Route path="/memory-chat" element={<MemoryChatPage />} />
      <Route path="/findings" element={<FindingsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/system" element={<SystemPage />} />
      <Route path="/signals/:signalId" element={<SignalDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
