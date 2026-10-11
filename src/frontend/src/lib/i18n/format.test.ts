import {
  INTL_LOCALES,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatDuration,
  formatList,
  formatNumber,
  formatRelativeTime,
} from './format';

// Неразрывные пробелы Intl приводятся к обычным для сравнения
const NBSP = new RegExp(
  `[${String.fromCharCode(0xa0)}${String.fromCharCode(0x202f)}]`,
  'g',
);
const plain = (value: string) => value.replace(NBSP, ' ');

describe('format', () => {
  it('[SYS-07-R19] locales by interface language', () => {
    expect(INTL_LOCALES).toEqual({
      ru: 'ru',
      en: 'en-GB',
      ar: 'ar-u-nu-latn-ca-gregory',
    });
  });

  it('[SYS-07-R19] numbers use latin digits in all three languages', () => {
    expect(plain(formatNumber(1234.5, 'ru'))).toBe('1 234,5');
    expect(formatNumber(1234.5, 'en')).toBe('1,234.5');
    expect(formatNumber(1234.5, 'ar')).toMatch(/1,234\.5/);
    expect(formatNumber(1234.5, 'ar')).not.toMatch(/[٠-٩]/);
  });

  it('[SYS-07-R21] the same UTC instant is shown in the user time zone', () => {
    const iso = '2026-10-10T12:00:00Z';
    expect(formatDateTime(iso, 'en', 'Europe/Moscow')).toContain('15:00');
    expect(formatDateTime(iso, 'en', 'Asia/Dubai')).toContain('16:00');
    expect(formatDateTime(iso, 'en', 'UTC')).toContain('12:00');
    expect(formatDate(iso, 'en', 'UTC')).toBe('10 October 2026');
    expect(formatDateTime(iso, 'ar', 'Asia/Riyadh')).not.toMatch(/[٠-٩]/);
  });

  it('[SYS-07-R19] relative time, lists, currency and durations', () => {
    expect(formatRelativeTime(-1, 'day', 'ru')).toBe('вчера');
    expect(formatRelativeTime(-1, 'day', 'en')).toBe('yesterday');
    expect(formatList(['a', 'b', 'c'], 'en')).toBe('a, b and c');
    expect(formatList(['a', 'b', 'c'], 'ru')).toBe('a, b и c');
    expect(plain(formatCurrency(1500, 'RUB', 'ru'))).toBe('1 500,00 ₽');
    expect(formatDuration(5400, 'en')).toMatch(/1.*hr.*30.*min/);
    expect(formatDuration(5400, 'ru')).toMatch(/1.*ч.*30.*мин/);
  });
});
