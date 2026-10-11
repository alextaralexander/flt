import type { Decorator, Preview } from '@storybook/react-vite';
import { DirectionProvider } from '@radix-ui/react-direction';
import { useEffect } from 'react';
import { MemoryRouter } from 'react-router';

import '../src/index.css';

type Direction = 'ltr' | 'rtl';

/**
 * Декоратор направления (ADR-005, 3.2 шаг 6; SYS-10-R32):
 * выставляет dir на <html>, как applyDocumentDirection в приложении,
 * и оборачивает историю в DirectionProvider Radix.
 */
const withDirection: Decorator = (Story, context) => {
  const direction = (context.globals.direction ?? 'ltr') as Direction;
  useEffect(() => {
    document.documentElement.dir = direction;
  }, [direction]);
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
  initialGlobals: { direction: 'ltr' },
  decorators: [withRouter, withDirection],
};

export default preview;
