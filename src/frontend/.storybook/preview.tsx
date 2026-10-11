import type { Decorator, Preview } from '@storybook/react-vite';
import { DirectionProvider } from '@radix-ui/react-direction';
import i18next from 'i18next';
import { useEffect } from 'react';
import { MemoryRouter } from 'react-router';

import { initTestI18n } from '../src/testing/i18n';

import '../src/index.css';

initTestI18n();

type Direction = 'ltr' | 'rtl';
type Locale = 'ru' | 'en' | 'ar';

/**
 * Декоратор языка и направления (ADR-005, 3.2 шаг 6; SYS-10-R32):
 * язык интерфейса меняет i18next, `dir` на <html> выставляется по глобалу
 * direction, как applyDocumentDirection в приложении; истории обёрнуты в
 * DirectionProvider Radix.
 */
const withLocaleAndDirection: Decorator = (Story, context) => {
  const locale = (context.globals.locale ?? 'ru') as Locale;
  const direction = (context.globals.direction ?? 'ltr') as Direction;
  useEffect(() => {
    void i18next.changeLanguage(locale).then(() => {
      document.documentElement.dir = direction;
    });
  }, [locale, direction]);
  return (
    <DirectionProvider dir={direction}>
      <Story />
    </DirectionProvider>
  );
};

const withRouter: Decorator = (Story) => (
  <MemoryRouter>
    <Story />
  </MemoryRouter>
);

const preview: Preview = {
  globalTypes: {
    locale: {
      description: 'Язык интерфейса',
      toolbar: {
        title: 'Locale',
        icon: 'globe',
        items: [
          { value: 'ru', title: 'Русский' },
          { value: 'en', title: 'English' },
          { value: 'ar', title: 'العربية' },
        ],
        dynamicTitle: true,
      },
    },
    direction: {
      description: 'Направление письма',
      toolbar: {
        title: 'Direction',
        icon: 'transfer',
        items: [
          { value: 'ltr', title: 'LTR' },
          { value: 'rtl', title: 'RTL' },
        ],
        dynamicTitle: true,
      },
    },
  },
  initialGlobals: { locale: 'ru', direction: 'ltr' },
  decorators: [withRouter, withLocaleAndDirection],
};

export default preview;
