import { detectUiLanguage } from './detect-language';
import {
  DEFAULT_UI_LANGUAGE,
  SUPPORTED_UI_LANGUAGES,
  isUiLanguage,
  textDirectionOf,
  toUiLanguage,
} from './languages';

describe('detectUiLanguage', () => {
  it('[SYS-07-R3] profile language wins over cookie and browser', () => {
    expect(
      detectUiLanguage({
        profile: 'ar',
        cookie: 'en',
        navigatorLanguages: ['ru-RU'],
      }),
    ).toBe('ar');
  });

  it('[SYS-07-R3] cookie wins over browser languages', () => {
    expect(
      detectUiLanguage({ cookie: 'en', navigatorLanguages: ['ar-EG'] }),
    ).toBe('en');
  });

  it('[SYS-07-R3] first supported browser language without region', () => {
    expect(
      detectUiLanguage({ navigatorLanguages: ['de-DE', 'zh-Hans', 'ar-EG'] }),
    ).toBe('ar');
    expect(detectUiLanguage({ navigatorLanguages: ['ru-RU', 'en'] })).toBe(
      'ru',
    );
  });

  it('[SYS-07-R3] unsupported values fall through to the default ru', () => {
    expect(
      detectUiLanguage({
        profile: 'de',
        cookie: '',
        navigatorLanguages: ['de', 'zh-Hans'],
      }),
    ).toBe('ru');
    expect(detectUiLanguage({})).toBe(DEFAULT_UI_LANGUAGE);
  });
});

describe('languages', () => {
  it('[SYS-07-R2] interface languages are ru, en, ar with default ru', () => {
    expect(SUPPORTED_UI_LANGUAGES).toEqual(['ru', 'en', 'ar']);
    expect(DEFAULT_UI_LANGUAGE).toBe('ru');
    expect(isUiLanguage('en')).toBe(true);
    expect(isUiLanguage('en-GB')).toBe(false);
    expect(isUiLanguage(42)).toBe(false);
  });

  it('[SYS-07-R3] normalizes BCP-47 tags to interface languages', () => {
    expect(toUiLanguage('ru-RU')).toBe('ru');
    expect(toUiLanguage('AR_eg')).toBe('ar');
    expect(toUiLanguage('zh-Hans')).toBeNull();
    expect(toUiLanguage(undefined)).toBeNull();
  });

  it('[SYS-07-R20] text direction by language and script', () => {
    expect(textDirectionOf('ar')).toBe('rtl');
    expect(textDirectionOf('he')).toBe('rtl');
    expect(textDirectionOf('en')).toBe('ltr');
    expect(textDirectionOf('zh-Hans')).toBe('ltr');
    expect(textDirectionOf('az-Arab')).toBe('rtl');
    expect(textDirectionOf('xx')).toBe('auto');
    expect(textDirectionOf(null)).toBe('auto');
  });
});
