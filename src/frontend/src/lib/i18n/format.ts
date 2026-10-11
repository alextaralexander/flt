/**
 * Форматирование чисел, дат, времени, валют и списков — только через `Intl`
 * с локалью интерфейса и часовым поясом пользователя (SYS-07-R19, R21).
 * Вызовы `toLocaleString` и `Intl.*` вне `src/lib/i18n` запрещены.
 */
import type { UiLanguage } from './languages';

/** Локаль `Intl` по языку интерфейса (таблица SYS-07-R19). */
export const INTL_LOCALES: Record<UiLanguage, string> = {
  ru: 'ru',
  en: 'en-GB',
  ar: 'ar-u-nu-latn-ca-gregory',
};

type DateInput = string | number | Date;

const toDate = (value: DateInput): Date =>
  value instanceof Date ? value : new Date(value);

export const formatNumber = (
  value: number,
  lng: UiLanguage,
  options?: Intl.NumberFormatOptions,
): string => new Intl.NumberFormat(INTL_LOCALES[lng], options).format(value);

export const formatCurrency = (
  amount: number,
  currency: string,
  lng: UiLanguage,
): string =>
  new Intl.NumberFormat(INTL_LOCALES[lng], {
    style: 'currency',
    currency,
  }).format(amount);

/** Дата в часовом поясе пользователя; без пояса — пояс браузера. */
export const formatDate = (
  value: DateInput,
  lng: UiLanguage,
  timeZone?: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'long' },
): string =>
  new Intl.DateTimeFormat(INTL_LOCALES[lng], { ...options, timeZone }).format(
    toDate(value),
  );

/** Дата и время: ISO-строка в UTC показывается в поясе пользователя (SYS-07-R21). */
export const formatDateTime = (
  value: DateInput,
  lng: UiLanguage,
  timeZone?: string,
): string =>
  formatDate(value, lng, timeZone, { dateStyle: 'medium', timeStyle: 'short' });

export const formatRelativeTime = (
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  lng: UiLanguage,
): string =>
  new Intl.RelativeTimeFormat(INTL_LOCALES[lng], { numeric: 'auto' }).format(
    value,
    unit,
  );

export const formatList = (
  items: readonly string[],
  lng: UiLanguage,
  type: Intl.ListFormatType = 'conjunction',
): string =>
  new Intl.ListFormat(INTL_LOCALES[lng], { type, style: 'long' }).format(items);

type DurationFormatter = {
  format: (duration: Record<string, number>) => string;
};
type DurationFormatConstructor = new (
  locale: string,
  options: { style: 'short' | 'long' | 'narrow' },
) => DurationFormatter;

/** Длительность в секундах: «1 ч 30 мин». */
export const formatDuration = (
  totalSeconds: number,
  lng: UiLanguage,
): string => {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const duration = { hours, minutes, seconds };
  const DurationFormat = (
    Intl as unknown as { DurationFormat?: DurationFormatConstructor }
  ).DurationFormat;
  if (DurationFormat) {
    return new DurationFormat(INTL_LOCALES[lng], { style: 'short' }).format(
      duration,
    );
  }
  const parts = (
    [
      ['hour', hours],
      ['minute', minutes],
      ['second', seconds],
    ] as const
  )
    .filter(([, amount]) => amount > 0)
    .map(([unit, amount]) =>
      formatNumber(amount, lng, { style: 'unit', unit, unitDisplay: 'short' }),
    );
  return formatList(parts.length > 0 ? parts : ['0'], lng, 'unit');
};
