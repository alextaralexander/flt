import { rtlRender, screen } from '@/testing/test-utils';

import { ExtensionSlot } from './extension-slot';
import {
  SLOT_IDS,
  getSlotContributions,
  registerSlotContribution,
  resetSlotContributions,
} from './slots';

const First = () => <span data-testid="contribution">{'first'}</span>;
const Second = () => <span data-testid="contribution">{'second'}</span>;
const Hidden = () => <span data-testid="contribution">{'hidden'}</span>;

describe('ExtensionSlot', () => {
  afterEach(() => resetSlotContributions());

  it('[SYS-09-R6] stage 1 slot ids', () => {
    expect([...SLOT_IDS]).toEqual([
      'app.header.actions',
      'app.nav.items',
      'app.user_menu.items',
      'settings.sections',
    ]);
  });

  it('[SYS-09-R5] renders contributions ordered by order and filtered by when', () => {
    registerSlotContribution('app.header.actions', {
      id: 'demo.second',
      order: 20,
      labelKey: 'common:ui.close',
      component: Second,
    });
    registerSlotContribution('app.header.actions', {
      id: 'demo.first',
      order: 10,
      labelKey: 'common:ui.close',
      component: First,
    });
    registerSlotContribution('app.header.actions', {
      id: 'demo.hidden',
      order: 5,
      labelKey: 'common:ui.close',
      when: ({ user }) => user !== null,
      component: Hidden,
    });

    rtlRender(
      <ExtensionSlot id="app.header.actions" context={{ user: null }} />,
    );

    expect(
      screen.getAllByTestId('contribution').map((el) => el.textContent),
    ).toEqual(['first', 'second']);
  });

  it('[SYS-09-R5] renders fallback when there are no contributions', () => {
    rtlRender(
      <ExtensionSlot
        id="app.nav.items"
        context={{ user: null }}
        fallback={<span data-testid="fallback" />}
      />,
    );
    expect(screen.getByTestId('fallback')).toBeInTheDocument();
  });

  it('[SYS-09-R5] re-registration with the same id replaces the contribution', () => {
    registerSlotContribution('app.nav.items', {
      id: 'demo.item',
      order: 1,
      labelKey: 'common:ui.close',
      component: First,
    });
    registerSlotContribution('app.nav.items', {
      id: 'demo.item',
      order: 1,
      labelKey: 'common:ui.close',
      component: Second,
    });
    expect(getSlotContributions('app.nav.items')).toHaveLength(1);
    expect(getSlotContributions('app.nav.items')[0]?.component).toBe(Second);
  });
});
