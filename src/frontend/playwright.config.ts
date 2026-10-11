import { defineConfig, devices } from '@playwright/test';

const PORT = 3000;
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;

/**
 * Playwright (ADR-005, 3.7; SYS-10-R29, R31): проекты chromium-desktop,
 * chromium-mobile (Pixel 7) и ar (RTL), без автоматических повторов.
 * На mock-сервере приложение запускается dev-сервером с моками MSW в браузере;
 * против стенда N3 — E2E_BASE_URL=http://127.0.0.1:8080 без webServer.
 *
 * Демо-сценарии bulletproof-react (e2e/tests) рассчитаны на десктопную
 * навигацию и английский интерфейс: до их удаления в Г.7 они выполняются
 * только в chromium-desktop; сценарии Г.11 (e2e/smoke) — во всех проектах.
 */
const DEMO_TESTS = /e2e\/tests\//;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['json', { outputFile: 'playwright-report/results.json' }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
  },
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  snapshotPathTemplate:
    '{testDir}/__screenshots__/{projectName}/{testFilePath}/{arg}{ext}',
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/ },
    {
      name: 'chromium-desktop',
      testMatch: /.*\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        locale: 'en-US',
        storageState: 'e2e/.auth/user.json',
      },
      dependencies: ['setup'],
    },
    {
      name: 'chromium-mobile',
      testMatch: /.*\.spec\.ts/,
      testIgnore: DEMO_TESTS,
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'ar',
      testMatch: /.*\.spec\.ts/,
      testIgnore: DEMO_TESTS,
      use: { ...devices['Desktop Chrome'], locale: 'ar' },
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm dev --port ${PORT}`,
        env: { VITE_APP_ENABLE_API_MOCKING: 'true' },
        timeout: 60 * 1000,
        port: PORT,
        reuseExistingServer: !process.env.CI,
      },
});
