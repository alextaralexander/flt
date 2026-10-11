import i18next from 'i18next';

import { readUiLanguageCookie } from './cookie';
import {
  FALLBACK_LANGUAGES,
  applyProfileLanguage,
  changeLanguage,
  currentUiLanguage,
  loadNamespaceResources,
  registerNamespaces,
} from './i18n';

describe('i18n', () => {
  it('[SYS-07-R5] changeLanguage switches language, <html> dir/lang and cookie without reload', async () => {
    await changeLanguage('ar');
    expect(i18next.resolvedLanguage).toBe('ar');
    expect(currentUiLanguage()).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
    expect(document.documentElement.lang).toBe('ar');
    expect(readUiLanguageCookie()).toBe('ar');
    expect(i18next.t('ui.close')).toBe('إغلاق');

    await changeLanguage('en');
    expect(document.documentElement.dir).toBe('ltr');
    expect(i18next.t('ui.close')).toBe('Close');
  });

  it('[SYS-07-R3] profile language is applied without writing the cookie', async () => {
    await applyProfileLanguage('en');
    expect(currentUiLanguage()).toBe('en');
    expect(readUiLanguageCookie()).toBeNull();

    await applyProfileLanguage('de');
    expect(currentUiLanguage()).toBe('en');
  });

  it('[SYS-07-R10] fallback chains: ar → en → ru, en → ru', () => {
    expect(FALLBACK_LANGUAGES).toEqual({
      ar: ['en', 'ru'],
      en: ['ru'],
      default: ['ru'],
    });
  });

  it('[SYS-07-R7] namespaces load lazily from the registry', async () => {
    const common = await loadNamespaceResources('en', 'common');
    expect(JSON.stringify(common)).toContain('Close');

    await expect(loadNamespaceResources('de', 'common')).rejects.toThrow();
    await expect(loadNamespaceResources('ru', 'missing')).rejects.toThrow();

    registerNamespaces({
      'demo-module': {
        ru: () => Promise.resolve({ title: 'Заголовок' }),
        en: () => Promise.resolve({ title: 'Title' }),
        ar: () => Promise.resolve({ title: 'عنوان' }),
      },
    });
    await expect(loadNamespaceResources('ar', 'demo-module')).resolves.toEqual({
      title: 'عنوان',
    });
  });
});
