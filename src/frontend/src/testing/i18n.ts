import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';

import { UI_LANGUAGE_COOKIE } from '@/lib/i18n/cookie';
import { baseI18nOptions, bindDocumentDirection } from '@/lib/i18n/i18n';
import ar from '@/lib/i18n/locales/ar/common.json';
import en from '@/lib/i18n/locales/en/common.json';
import ru from '@/lib/i18n/locales/ru/common.json';

/**
 * Синхронная инициализация i18n для тестов (ADR-005, 3.3; SYS-10-R9):
 * реальные ресурсы, язык по умолчанию `ru`, без ленивой загрузки.
 */
export const initTestI18n = () => {
  if (i18next.isInitialized) return i18next;
  bindDocumentDirection(i18next);
  void i18next.use(initReactI18next).init({
    ...baseI18nOptions,
    lng: 'ru',
    resources: {
      ru: { common: ru },
      en: { common: en },
      ar: { common: ar },
    },
    initAsync: false,
  });
  return i18next;
};

/** Возвращает язык `ru`, `dir`/`lang` документа и удаляет cookie выбора языка. */
export const resetTestI18n = async () => {
  document.cookie = `${UI_LANGUAGE_COOKIE}=; Max-Age=0; Path=/`;
  await i18next.changeLanguage('ru');
};
