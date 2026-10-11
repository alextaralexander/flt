/// <reference types="vitest/config" />
/// <reference types="vite/client" />

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// Адреса для dev-прокси (не попадают в сборку): /api и /ws — монолит,
// /flt-* — хранилище; пути не переписываются, как в HAProxy (ADR-005, 3.5;
// ADR-007; ADR-012). При VITE_APP_ENABLE_API_MOCKING=true запросы
// перехватывает MSW в браузере.
const devEnv = loadEnv(process.env.NODE_ENV ?? 'development', process.cwd(), [
  'VITE_DEV_',
]);
const backendUrl = devEnv.VITE_DEV_BACKEND_URL ?? 'http://localhost:8000';
const storageUrl = devEnv.VITE_DEV_STORAGE_URL ?? 'http://localhost:9000';

export default defineConfig({
  // SPA с history-роутером: ассеты всегда от корня (ADR-005, 3.1)
  base: '/',
  plugins: [react(), tailwindcss()],
  resolve: { tsconfigPaths: true },
  server: {
    port: 3000,
    proxy: {
      '/api': { target: backendUrl, changeOrigin: false },
      '/ws': {
        target: backendUrl.replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: false,
      },
      '^/flt-': { target: storageUrl, changeOrigin: false },
    },
  },
  preview: {
    port: 3000,
  },
  test: {
    globals: true,
    exclude: ['**/node_modules/**', '**/e2e/**'],
    projects: [
      {
        // Приложение: компоненты, хуки, lib, архитектурные тесты
        extends: true,
        test: {
          name: 'app',
          environment: 'jsdom',
          include: ['src/**/*.test.{ts,tsx}'],
          setupFiles: './src/testing/setup-tests.ts',
        },
      },
      {
        // Репозиторные скрипты фронтенда и локальные правила ESLint
        extends: true,
        test: {
          name: 'tooling',
          environment: 'node',
          include: ['scripts/**/*.test.ts', 'eslint-rules/**/*.test.js'],
        },
      },
    ],
    // Детерминированный порядок со случайным перемешиванием (SYS-10)
    sequence: { shuffle: true, seed: 20261010 },
    env: { TZ: 'UTC' },
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary', 'html'],
      include: [
        'src/features/**',
        'src/lib/**',
        'src/components/**',
        'src/hooks/**',
        'src/utils/**',
      ],
      exclude: [
        '**/generated/**',
        '**/*.stories.tsx',
        '**/*.test.{ts,tsx}',
        'src/testing/**',
        '**/__fixtures__/**',
        'src/types/**',
        'src/app/**',
        '**/locales/**',
      ],
      // Порог покрытия ADR-005, 3.7 и SYS-10-R10: только повышается
      thresholds: {
        lines: 70,
        statements: 70,
        functions: 70,
        branches: 60,
      },
    },
  },
  optimizeDeps: { exclude: ['fsevents'] },
  build: {
    rolldownOptions: {
      // fs/promises нужен только mock-серверу (src/testing/mocks/db.ts)
      external: ['fs/promises'],
    },
  },
});
