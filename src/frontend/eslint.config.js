// ESLint 9, flat config (ADR-005, раздел 3.6; SYS-12-R7).
import fs from 'node:fs';
import path from 'node:path';

import commentsConfigs from '@eslint-community/eslint-plugin-eslint-comments/configs';
import js from '@eslint/js';
import vitest from '@vitest/eslint-plugin';
import prettierConfig from 'eslint-config-prettier';
import betterTailwind from 'eslint-plugin-better-tailwindcss';
import { createTypeScriptImportResolver } from 'eslint-import-resolver-typescript';
import checkFile from 'eslint-plugin-check-file';
import importX from 'eslint-plugin-import-x';
import jestDom from 'eslint-plugin-jest-dom';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import playwright from 'eslint-plugin-playwright';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import testingLibrary from 'eslint-plugin-testing-library';
import globals from 'globals';
import tseslint from 'typescript-eslint';

import fltPlugin from './eslint-rules/flt-plugin.js';

const rootDir = import.meta.dirname;
const featuresDir = path.join(rootDir, 'src/features');

/**
 * Зоны границ модулей строятся автоматически из каталогов src/features/*:
 * новый модуль получает зону без правки конфига (ADR-005, 3.6).
 */
const features = fs.existsSync(featuresDir)
  ? fs
      .readdirSync(featuresDir, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
  : [];

const featureZones = features.map((name) => ({
  target: `./src/features/${name}`,
  from: './src/features',
  except: [`./${name}`],
  message: `Модуль ${name} не импортирует другие модули: связывание только в src/app`,
}));

const SHARED_LAYER = [
  './src/components',
  './src/hooks',
  './src/lib',
  './src/types',
  './src/utils',
  './src/config',
];

export default tseslint.config(
  {
    ignores: [
      'dist',
      'coverage',
      'node_modules',
      'public/mockServiceWorker.js',
      'generators',
      'storybook-static',
      'playwright-report',
      'test-results',
      '**/generated/**',
      // Фикстура негативного теста границ: проверяется только из
      // src/testing/architecture/eslint-boundaries.test.ts
      'src/features/__fixtures__/**',
    ],
  },
  {
    files: ['**/*.{js,mjs,cjs,ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    linterOptions: { reportUnusedDisableDirectives: 'error' },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [
      importX.flatConfigs.recommended,
      importX.flatConfigs.typescript,
      react.configs.flat.recommended,
      react.configs.flat['jsx-runtime'],
      reactHooks.configs.flat.recommended,
      jsxA11y.flatConfigs.recommended,
      commentsConfigs.recommended,
    ],
    plugins: {
      'check-file': checkFile,
      flt: fltPlugin,
      'better-tailwindcss': betterTailwind,
    },
    settings: {
      react: { version: 'detect' },
      'better-tailwindcss': {
        entryPoint: path.join(rootDir, 'src/index.css'),
      },
      'import-x/resolver-next': [
        createTypeScriptImportResolver({
          project: path.join(rootDir, 'tsconfig.json'),
        }),
      ],
    },
    rules: {
      'import-x/no-restricted-paths': [
        'error',
        {
          basePath: rootDir,
          zones: [
            ...featureZones,
            // src/app импортирует features, но не наоборот
            { target: './src/features', from: './src/app' },
            // shared-слой не импортирует features и app
            { target: SHARED_LAYER, from: ['./src/features', './src/app'] },
          ],
        },
      ],
      'import-x/no-cycle': ['error', { maxDepth: Infinity }],
      'import-x/order': [
        'error',
        {
          groups: [
            'builtin',
            'external',
            'internal',
            'parent',
            'sibling',
            'index',
            'object',
          ],
          'newlines-between': 'always',
          alphabetize: { order: 'asc', caseInsensitive: true },
        },
      ],
      'import-x/default': 'off',
      'import-x/no-named-as-default-member': 'off',
      'import-x/no-named-as-default': 'off',
      'check-file/filename-naming-convention': [
        'error',
        { '**/*.{ts,tsx}': 'KEBAB_CASE' },
        { ignoreMiddleExtensions: true },
      ],
      'check-file/folder-naming-convention': [
        'error',
        { 'src/**/!(__tests__|__fixtures__|__snapshots__)': 'KEBAB_CASE' },
      ],
      // Barrel-файлы запрещены (единственный index.tsx — src/app/index.tsx)
      'check-file/filename-blocklist': [
        'error',
        {
          'src/features/**/index.{ts,tsx}': '*.ts',
          'src/{components,hooks,lib,utils,types,config}/**/index.{ts,tsx}':
            '*.ts',
        },
      ],
      'react/prop-types': 'off',
      'react/react-in-jsx-scope': 'off',
      'jsx-a11y/anchor-is-valid': 'off',
      '@typescript-eslint/no-unused-vars': ['error'],
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-empty-function': 'off',
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { fixStyle: 'separate-type-imports' },
      ],
      // SYS-12-R7: директивы eslint-disable — с именем правила и причиной
      '@eslint-community/eslint-comments/require-description': 'error',
      '@eslint-community/eslint-comments/no-unlimited-disable': 'error',
      'linebreak-style': ['error', 'unix'],
      // SYS-07-R17: только логические классы направления
      'flt/no-physical-direction-classes': 'error',
      // Классы Tailwind 4: незарегистрированные, конфликтующие, устаревшие, порядок
      ...betterTailwind.configs['correctness-error'].rules,
      'better-tailwindcss/no-deprecated-classes': 'error',
      'better-tailwindcss/no-duplicate-classes': 'error',
      'better-tailwindcss/no-unnecessary-whitespace': 'error',
      'better-tailwindcss/enforce-consistent-class-order': 'error',
      'better-tailwindcss/enforce-canonical-classes': 'error',
    },
  },
  {
    files: ['src/**/*.test.{ts,tsx}', 'src/testing/**/*.{ts,tsx}'],
    extends: [
      testingLibrary.configs['flat/react'],
      jestDom.configs['flat/recommended'],
      vitest.configs.recommended,
    ],
    languageOptions: { globals: { ...vitest.environments.env.globals } },
    rules: {
      // SYS-10-R9: транспорт подменяется только через MSW, не через vi.mock
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.object.name='vi'][callee.property.name='mock'][arguments.0.value=/^(axios|@.lib.api-client)$/]",
          message:
            'SYS-10-R9: HTTP подменяется обработчиками MSW, а не vi.mock',
        },
        {
          selector:
            "CallExpression[callee.object.name='vi'][callee.property.name='stubGlobal'][arguments.0.value=/^(fetch|WebSocket)$/]",
          message:
            'SYS-10-R9: fetch и WebSocket подменяются MSW (http, ws.link), а не vi.stubGlobal',
        },
      ],
    },
  },
  {
    files: ['eslint-rules/**/*.test.js'],
    languageOptions: { globals: { ...vitest.environments.env.globals } },
  },
  {
    files: ['e2e/**/*.ts'],
    extends: [playwright.configs['flat/recommended']],
  },
  prettierConfig,
);
