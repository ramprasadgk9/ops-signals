import { Navigate, Route, Routes } from 'react-router-dom';
import { CaseDetailsPage } from '../pages/CaseDetailsPage';
import { CapabilitiesPage } from '../pages/CapabilitiesPage';
import { FindingsPage } from '../pages/FindingsPage';
import { HistoryPage } from '../pages/HistoryPage';
import { OverviewPage } from '../pages/OverviewPage';
import { QuestionAnswerPage } from '../pages/QuestionAnswerPage';
import { SettingsPage } from '../pages/SettingsPage';
import { SignalDetailPage } from '../pages/SignalDetailPage';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/cases/:caseId" element={<CaseDetailsPage />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/questions/:questionId" element={<QuestionAnswerPage />} />
      <Route path="/capabilities" element={<CapabilitiesPage />} />
      <Route path="/findings" element={<FindingsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/signals/:signalId" element={<SignalDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
