// Фикстура негативного архитектурного теста границ модулей (ADR-005, 3.6):
// псевдомодуль `__fixtures__` импортирует слой src/app, что запрещено зонами
// import-x/no-restricted-paths. Файл исключён из `pnpm lint` (ignores в
// eslint.config.js) и проверяется только тестом
// src/testing/architecture/eslint-boundaries.test.ts.
import { AppRouter } from '@/app/router';

export const BoundaryViolation = () => <AppRouter />;
