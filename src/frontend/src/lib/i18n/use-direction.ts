import { useTranslation } from 'react-i18next';

import { directionOf } from './direction';
import type { TextDirection } from './languages';
import { DEFAULT_UI_LANGUAGE } from './languages';

/**
 * Направление интерфейса для `DirectionProvider` Radix; компонент
 * перерисовывается на `languageChanged` (ADR-005, 3.4).
 */
export const useDirection = (): TextDirection => {
  const { i18n } = useTranslation();
  return directionOf(i18n.resolvedLanguage ?? DEFAULT_UI_LANGUAGE);
};
