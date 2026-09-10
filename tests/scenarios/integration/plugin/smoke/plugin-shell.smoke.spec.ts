import { test } from '@playwright/test';
import { expectPluginLoadsCleanly } from '../../shared/pluginSmoke';

test('the plugin app mounts cleanly inside Grafana', async ({ page }) => {
  await expectPluginLoadsCleanly(page);
});
