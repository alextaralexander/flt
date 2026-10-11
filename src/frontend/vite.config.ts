/// <reference types="vitest/config" />
/// <reference types="vite/client" />

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  // SPA с history-роутером: ассеты всегда от корня (ADR-005, 3.1)
  base: '/',
  plugins: [react(), tailwindcss()],
  resolve: { tsconfigPaths: true },
  server: {
    port: 3000,
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
