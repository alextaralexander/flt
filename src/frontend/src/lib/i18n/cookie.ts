import type { UiLanguage } from './languages';
import { isUiLanguage } from './languages';

/** Cookie явного выбора языка интерфейса (SYS-07-R6). */
export const UI_LANGUAGE_COOKIE = 'flt_ui_language';
/** Срок жизни cookie — один год. */
export const UI_LANGUAGE_COOKIE_MAX_AGE = 31_536_000;

/**
 * Читает язык из cookie `flt_ui_language`; любое значение вне перечня
 * языков интерфейса игнорируется.
 */
export const readUiLanguageCookie = (
  cookieString: string = document.cookie,
): UiLanguage | null => {
  for (const part of cookieString.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name === UI_LANGUAGE_COOKIE) {
      const value = decodeURIComponent(rest.join('='));
      return isUiLanguage(value) ? value : null;
    }
  }
  return null;
};

/** Строка Set-Cookie: `Path=/`, `Max-Age=31536000`, `SameSite=Lax`, `Secure` при https, без `HttpOnly`. */
export const buildUiLanguageCookie = (
  code: UiLanguage,
  secure: boolean,
): string =>
  [
    `${UI_LANGUAGE_COOKIE}=${code}`,
    'Path=/',
    `Max-Age=${UI_LANGUAGE_COOKIE_MAX_AGE}`,
    'SameSite=Lax',
    ...(secure ? ['Secure'] : []),
  ].join('; ');

/** Сохраняет явный выбор языка (пишет только frontend, backend cookie читает). */
export const writeUiLanguageCookie = (code: UiLanguage): void => {
  document.cookie = buildUiLanguageCookie(
    code,
    window.location.protocol === 'https:',
  );
};
