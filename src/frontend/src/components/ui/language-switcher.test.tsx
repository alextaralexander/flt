import i18next from 'i18next';

import { readUiLanguageCookie } from '@/lib/i18n/cookie';
import { rtlRender, screen, userEvent, waitFor } from '@/testing/test-utils';

import { LanguageSwitcher } from './language-switcher';

const openSwitcher = async () => {
  await userEvent.click(
    screen.getByRole('button', { name: i18next.t('language.switcher.label') }),
  );
};

describe('LanguageSwitcher', () => {
  it('[SYS-07-R5] switches ru → en → ar without reload and stores the choice', async () => {
    rtlRender(<LanguageSwitcher />);
    expect(document.documentElement.lang).toBe('ru');

    await openSwitcher();
    await userEvent.click(
      await screen.findByRole('menuitemradio', { name: 'English' }),
    );
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    expect(document.documentElement.dir).toBe('ltr');
    expect(readUiLanguageCookie()).toBe('en');
    expect(
      screen.getByRole('button', { name: 'Interface language' }),
    ).toBeInTheDocument();

    await openSwitcher();
    await userEvent.click(
      await screen.findByRole('menuitemradio', { name: 'العربية' }),
    );
    await waitFor(() => expect(document.documentElement.dir).toBe('rtl'));
    expect(document.documentElement.lang).toBe('ar');
    expect(readUiLanguageCookie()).toBe('ar');
  });

  it('[SYS-07-R5] marks the current language and labels items with their own lang', async () => {
    rtlRender(<LanguageSwitcher />);
    await openSwitcher();
    const russian = await screen.findByRole('menuitemradio', {
      name: 'Русский',
    });
    expect(russian).toBeChecked();
    expect(russian).toHaveAttribute('lang', 'ru');
    expect(
      screen.getByRole('menuitemradio', { name: 'العربية' }),
    ).toHaveAttribute('lang', 'ar');
  });
});
