import { LanguageSwitcher } from '@/components/ui/language-switcher';
import { registerSlotContribution } from '@/lib/extension-points/slots';

/**
 * Единственное место регистрации вкладов в UI-слоты (SYS-09-R5).
 * Вызывается один раз при инициализации приложения; повторный вызов
 * идемпотентен (вклад с тем же id заменяется).
 */
export const registerExtensions = (): void => {
  // Переключатель языка — первый вклад в шапку (SYS-09-R6, SYS-07-R5)
  registerSlotContribution('app.header.actions', {
    id: 'app_shell.language_switcher',
    order: 100,
    labelKey: 'common:language.switcher.label',
    component: LanguageSwitcher,
  });
};
