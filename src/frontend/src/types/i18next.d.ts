// Типизация ключей i18n (ADR-005, 3.3; SYS-07-R11): эталон — файлы `ru`.
// Опечатка в ключе или неверный namespace ломают `pnpm check-types`.
// Namespace модуля добавляется сюда вместе с регистрацией в
// src/app/i18n-resources.ts: `<module>: typeof import('@/features/<module>/locales/ru.json')`.
import 'i18next';

import type common from '@/lib/i18n/locales/ru/common.json';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common';
    resources: {
      common: typeof common;
    };
  }
}
