import type { NamespaceResources } from '@/lib/i18n/i18n';
import { registerNamespaces } from '@/lib/i18n/i18n';

/**
 * Namespace i18n feature-модулей (ADR-005, 3.3; SYS-07-R7). Shared-слой не
 * знает о модулях, поэтому ресурсы модулей регистрируются здесь, в слое app:
 *
 *   import { identityResources } from '@/features/identity/locales/resources';
 *   export const moduleI18nResources = { identity: identityResources };
 *
 * Namespace — имя модуля в kebab-case; тип ключей — в src/types/i18next.d.ts.
 */
export const moduleI18nResources: Record<string, NamespaceResources> = {};

export const registerI18nResources = (): void => {
  registerNamespaces(moduleI18nResources);
};
