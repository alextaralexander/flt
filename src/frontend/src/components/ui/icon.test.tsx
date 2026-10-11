import { rtlRender, screen } from '@/testing/test-utils';

import { Bidi } from './bidi';
import { Icon } from './icon';
import { ICONS } from './icons/registry';
import { RTL_MIRRORED_ICONS } from './icons/rtl-mirrored';

describe('Icon', () => {
  it('[SYS-07-R18] mirrors icons from RTL_MIRRORED_ICONS in RTL', () => {
    rtlRender(
      <>
        <Icon name="ChevronRight" data-testid="chevron" />
        <Icon name="Check" data-testid="check" />
      </>,
    );
    const chevron = screen.getByTestId('chevron');
    expect(chevron).toHaveClass('rtl:-scale-x-100');
    expect(chevron).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByTestId('check')).not.toHaveClass('rtl:-scale-x-100');
  });

  it('[SYS-07-R18] every mirrored icon is available in the registry', () => {
    const missing = RTL_MIRRORED_ICONS.filter((name) => !(name in ICONS));
    expect(missing).toEqual([]);
  });
});

describe('Bidi', () => {
  it('[SYS-07-R20] isolates text with lang and dir by language code', () => {
    rtlRender(
      <>
        <Bidi lang="ar">{'مرحبا'}</Bidi>
        <Bidi lang="en">{'hello'}</Bidi>
        <Bidi lang="xx">{'unknown'}</Bidi>
      </>,
    );
    const arabic = screen.getByText('مرحبا');
    expect(arabic.tagName).toBe('BDI');
    expect(arabic).toHaveAttribute('dir', 'rtl');
    expect(arabic).toHaveAttribute('lang', 'ar');
    expect(screen.getByText('hello')).toHaveAttribute('dir', 'ltr');
    expect(screen.getByText('unknown')).toHaveAttribute('dir', 'auto');
  });
});
