import { BrowserRouter } from 'react-router-dom';
import { AppRoutes } from './routes/AppRoutes';
import { AppShell } from './components/AppShell';
import { SignInGate } from './components/SignIn';

export function StandaloneApp() {
  return (
    <BrowserRouter>
      <SignInGate>
        <AppShell>
          <AppRoutes />
        </AppShell>
      </SignInGate>
    </BrowserRouter>
  );
}
