import type { i18n as I18nInstance, InitOptions } from 'i18next';
import i18next from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import resourcesToBackend from 'i18next-resources-to-backend';
import { initReactI18next } from 'react-i18next';

import { readUiLanguageCookie, writeUiLanguageCookie } from './cookie';
import { detectUiLanguage } from './detect-language';
import { applyDocumentDirection } from './direction';
import type { UiLanguage } from './languages';
import {
  DEFAULT_UI_LANGUAGE,
  SUPPORTED_UI_LANGUAGES,
  isUiLanguage,
} from './languages';

export { useTranslation } from 'react-i18next';

/** Ленивый загрузчик ресурсов одного языка namespace. */
export type ResourceLoader = () => Promise<
  { default: Record<string, unknown> } | Record<string, unknown>
>;
/** Ресурсы namespace по языкам интерфейса. */
export type NamespaceResources = Record<UiLanguage, ResourceLoader>;

/** Namespace app_shell и shared-слоя (ADR-005, 3.3; SYS-07-R7). */
export const COMMON_NAMESPACE = 'common';

const commonResources: NamespaceResources = {
  ru: () => import('./locales/ru/common.json'),
  en: () => import('./locales/en/common.json'),
  ar: () => import('./locales/ar/common.json'),
};

const registry: Record<string, NamespaceResources> = {
  [COMMON_NAMESPACE]: commonResources,
};

/**
 * Регистрирует namespace модулей. Вызывается только из
 * `src/app/i18n-resources.ts`: shared-слой не знает о модулях.
 */
export const registerNamespaces = (
  namespaces: Record<string, NamespaceResources>,
): void => {
  Object.assign(registry, namespaces);
};

/** Ленивая загрузка ресурсов namespace: чанк модуля грузится по требованию. */
export const loadNamespaceResources = (
  lng: string,
  ns: string,
): ReturnType<ResourceLoader> => {
  const loader = isUiLanguage(lng) ? registry[ns]?.[lng] : undefined;
  if (!loader) {
    return Promise.reject(new Error(`No i18n resources: ${lng}/${ns}`));
  }
  return loader();
};

/** Цепочки запасных языков (SYS-07-R10): только для ключей плагинов. */
export const FALLBACK_LANGUAGES = {
  ar: ['en', 'ru'],
  en: ['ru'],
  default: ['ru'],
};

/** Общие опции i18next для приложения и тестов. */
export const baseI18nOptions: InitOptions = {
  supportedLngs: [...SUPPORTED_UI_LANGUAGES],
  nonExplicitSupportedLngs: true,
  load: 'languageOnly',
  fallbackLng: FALLBACK_LANGUAGES,
  ns: [COMMON_NAMESPACE],
  defaultNS: COMMON_NAMESPACE,
  interpolation: { escapeValue: false },
  returnNull: false,
};

/** Детектор по порядку SYS-07-R3; профиль применяется позже — `applyProfileLanguage`. */
const fltLanguageDetector = {
  name: 'fltUiLanguage',
  lookup: () =>
    detectUiLanguage({
      cookie: readUiLanguageCookie(),
      navigatorLanguages:
        typeof navigator === 'undefined' ? [] : navigator.languages,
    }),
  // Выбор сохраняется в cookie только явно — в changeLanguage (SYS-07-R6)
  cacheUserLanguage: () => undefined,
};

const boundInstances = new WeakSet<I18nInstance>();

/** Синхронизирует `dir`/`lang` на `<html>` с языком экземпляра (SYS-07-R16). */
export const bindDocumentDirection = (instance: I18nInstance): void => {
  if (boundInstances.has(instance)) return;
  boundInstances.add(instance);
  instance.on('languageChanged', (lng) => applyDocumentDirection(lng));
};

/** Инициализирует i18next приложения: детектор, ленивые namespace, RTL. */
export const initI18n = async (): Promise<I18nInstance> => {
  const detector = new LanguageDetector();
  detector.addDetector(fltLanguageDetector);
  bindDocumentDirection(i18next);
  await i18next
    .use(detector)
    .use(initReactI18next)
    .use(resourcesToBackend(loadNamespaceResources))
    .init({
      ...baseI18nOptions,
      detection: { order: ['fltUiLanguage'], caches: [] },
    });
  applyDocumentDirection(i18next.resolvedLanguage ?? DEFAULT_UI_LANGUAGE);
  return i18next;
};

/**
 * Явная смена языка переключателем: без перезагрузки страницы, с записью
 * cookie (SYS-07-R5, R6). `PATCH /api/v1/auth/me` — с этапа 4 (STU-06).
 */
export const changeLanguage = async (code: UiLanguage): Promise<void> => {
  writeUiLanguageCookie(code);
  await i18next.changeLanguage(code);
};

/** Применяет `ui_language` из профиля после загрузки `me` (SYS-07-R3, источник 1). */
export const applyProfileLanguage = async (
  code: string | null | undefined,
): Promise<void> => {
  if (isUiLanguage(code) && i18next.resolvedLanguage !== code) {
    await i18next.changeLanguage(code);
  }
};

/** Текущий язык интерфейса. */
export const currentUiLanguage = (): UiLanguage => {
  const lng = i18next.resolvedLanguage;
  return isUiLanguage(lng) ? lng : DEFAULT_UI_LANGUAGE;
};
