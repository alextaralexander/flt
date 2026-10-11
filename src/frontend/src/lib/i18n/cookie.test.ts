import {
  UI_LANGUAGE_COOKIE,
  buildUiLanguageCookie,
  readUiLanguageCookie,
  writeUiLanguageCookie,
} from './cookie';

describe('flt_ui_language cookie', () => {
  it('[SYS-07-R6] cookie attributes: Path, Max-Age one year, SameSite=Lax, no HttpOnly', () => {
    expect(buildUiLanguageCookie('ar', false)).toBe(
      'flt_ui_language=ar; Path=/; Max-Age=31536000; SameSite=Lax',
    );
    expect(buildUiLanguageCookie('en', true)).toBe(
      'flt_ui_language=en; Path=/; Max-Age=31536000; SameSite=Lax; Secure',
    );
    expect(buildUiLanguageCookie('ru', true)).not.toContain('HttpOnly');
  });

  it('[SYS-07-R6] reads only supported values', () => {
    expect(readUiLanguageCookie('a=1; flt_ui_language=en; b=2')).toBe('en');
    expect(readUiLanguageCookie('flt_ui_language=fr')).toBeNull();
    expect(readUiLanguageCookie('other=ru')).toBeNull();
    expect(readUiLanguageCookie('')).toBeNull();
  });

  it('[SYS-07-R6] writes the cookie readable by document.cookie', () => {
    writeUiLanguageCookie('ar');
    expect(document.cookie).toContain(`${UI_LANGUAGE_COOKIE}=ar`);
    expect(readUiLanguageCookie()).toBe('ar');
  });
});
