import { defineConfig, devices } from '@playwright/test';

/**
 * Runs against the real local stack (scripts/run_all.sh / scripts/run_grafana_stack.sh),
 * not a mocked backend. See scripts/test_local_integration_scenarios.sh for orchestration.
 */
export default defineConfig({
  testDir: '../tests/scenarios/integration',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'web-ui',
      testDir: '../tests/scenarios/integration/web-ui',
      use: { ...devices['Desktop Chrome'], baseURL: process.env.OPS_SIGNALS_WEB_UI_URL ?? 'http://localhost:5174' },
    },
    {
      name: 'plugin',
      testDir: '../tests/scenarios/integration/plugin',
      use: { ...devices['Desktop Chrome'], baseURL: process.env.OPS_SIGNALS_GRAFANA_URL ?? 'http://localhost:3000' },
    },
  ],
});
