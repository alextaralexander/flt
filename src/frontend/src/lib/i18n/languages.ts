/**
 * Языки интерфейса (SYS-07-R2): единый перечень, синхронный с backend
 * `app/core/i18n/languages.py` (`UI_LANGUAGES`, `DEFAULT_UI_LANGUAGE`).
 * Добавление языка — только новой версией SYS-07 и в обоих местах сразу.
 */
export const SUPPORTED_UI_LANGUAGES = ['ru', 'en', 'ar'] as const;

export type UiLanguage = (typeof SUPPORTED_UI_LANGUAGES)[number];

/** Язык по умолчанию (OQ-25). */
export const DEFAULT_UI_LANGUAGE: UiLanguage = 'ru';

export type TextDirection = 'ltr' | 'rtl';

/** Точное совпадение с кодом языка интерфейса. */
export const isUiLanguage = (value: unknown): value is UiLanguage =>
  typeof value === 'string' &&
  (SUPPORTED_UI_LANGUAGES as readonly string[]).includes(value);

/**
 * Приводит тег BCP-47 к языку интерфейса по первичному субтегу
 * (`ru-RU` → `ru`, `ar-EG` → `ar`); неподдерживаемый язык — `null`.
 */
export const toUiLanguage = (
  code: string | null | undefined,
): UiLanguage | null => {
  if (!code) return null;
  const primary = code.trim().split(/[-_]/)[0]?.toLowerCase();
  return isUiLanguage(primary) ? primary : null;
};

/**
 * Письменности и языки с направлением справа налево. До появления реестра
 * языков (модуль `languages`, этап 4, SYS-07-R24) — статическая таблица.
 */
const RTL_SCRIPTS = new Set(['Arab', 'Hebr', 'Thaa', 'Syrc', 'Nkoo', 'Adlm']);
const RTL_LANGUAGES = new Set([
  'ar',
  'he',
  'fa',
  'ur',
  'ps',
  'sd',
  'ug',
  'yi',
  'dv',
  'ckb',
]);
const LTR_LANGUAGES = new Set<string>([
  ...SUPPORTED_UI_LANGUAGES.filter((code) => !RTL_LANGUAGES.has(code)),
  'de',
  'fr',
  'es',
  'it',
  'pt',
  'zh',
  'ja',
  'ko',
  'tr',
  'uk',
  'pl',
]);

/**
 * Направление текста по коду языка: `rtl`, `ltr` или `auto`, если язык
 * неизвестен (SYS-07-R20, `<Bidi>`).
 */
export const textDirectionOf = (
  code: string | null | undefined,
): TextDirection | 'auto' => {
  if (!code) return 'auto';
  const [primary, ...rest] = code.trim().split('-');
  const script = rest.find((part) => /^[A-Z][a-z]{3}$/.test(part));
  if (script) return RTL_SCRIPTS.has(script) ? 'rtl' : 'ltr';
  const lang = primary?.toLowerCase() ?? '';
  if (RTL_LANGUAGES.has(lang)) return 'rtl';
  if (LTR_LANGUAGES.has(lang)) return 'ltr';
  return 'auto';
};
