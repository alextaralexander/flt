import type { UiLanguage } from './languages';
import { DEFAULT_UI_LANGUAGE, isUiLanguage, toUiLanguage } from './languages';

export type LanguageSources = {
  /** `ui_language` аутентифицированного пользователя из `GET /api/v1/auth/me`. */
  profile?: string | null;
  /** Значение cookie `flt_ui_language`. */
  cookie?: string | null;
  /** `navigator.languages`. */
  navigatorLanguages?: readonly string[];
};

/**
 * Язык интерфейса по порядку SYS-07-R3 (OQ-25): профиль → cookie →
 * первый поддерживаемый из `navigator.languages` (без региона) → `ru`.
 */
export const detectUiLanguage = ({
  profile,
  cookie,
  navigatorLanguages = [],
}: LanguageSources): UiLanguage => {
  if (isUiLanguage(profile)) return profile;
  if (isUiLanguage(cookie)) return cookie;
  for (const language of navigatorLanguages) {
    const uiLanguage = toUiLanguage(language);
    if (uiLanguage) return uiLanguage;
  }
  return DEFAULT_UI_LANGUAGE;
};
