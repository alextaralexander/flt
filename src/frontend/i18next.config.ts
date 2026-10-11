// Конфигурация i18next-cli (ADR-005, 3.3; SYS-07-R7, R10): извлечение ключей
// и проверка полноты переводов для ru (эталон), en, ar.
// i18next-parser из ADR-005 не поддерживает Node 24 (engines до ^22) и заменён
// своим преемником i18next-cli с теми же скриптами i18n:extract и i18n:check.
import { defineConfig } from 'i18next-cli';

/** namespace `common` — app_shell и shared-слой; namespace модуля — его каталог. */
const outputPath = (language: string, namespace?: string): string =>
  !namespace || namespace === 'common'
    ? `src/lib/i18n/locales/${language}/common.json`
    : `src/features/${namespace}/locales/${language}.json`;

export default defineConfig({
  locales: ['ru', 'en', 'ar'],
  extract: {
    input: ['src/**/*.{ts,tsx}'],
    ignore: [
      'src/**/*.test.{ts,tsx}',
      'src/**/*.stories.tsx',
      'src/testing/**',
      'src/**/generated/**',
      'src/features/__fixtures__/**',
    ],
    output: outputPath,
    defaultNS: 'common',
    primaryLanguage: 'ru',
    secondaryLanguages: ['en', 'ar'],
    // Пустые значения в en и ar — незавершённый перевод, `status` падает
    defaultValue: '',
    removeUnusedKeys: true,
    keySeparator: '.',
    nsSeparator: ':',
    pluralSeparator: '_',
    // Ключи с динамической частью по перечню языков интерфейса
    // и коды ошибок конверта ErrorResponseV1 (errors.<module>.<code>, SYS-07-R12)
    preservePatterns: ['language.native.*', 'errors.*'],
  },
});
