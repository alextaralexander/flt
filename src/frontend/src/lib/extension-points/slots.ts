/**
 * Реестр UI-слотов app_shell (SYS-09-R5, R6): единственный способ, которым
 * модуль встраивает компонент в чужой экран без импорта другого модуля.
 * Вклады регистрируются только в src/app/extensions.ts при инициализации.
 */
import type { ComponentType } from 'react';

import type { User } from '@/types/api';

/** Контекст каждого слота этапа 1 (SYS-09-R6). */
export type SlotContexts = {
  'app.header.actions': { user: User | null };
  'app.nav.items': { user: User | null };
  'app.user_menu.items': { user: User };
  'settings.sections': { user: User };
};

export type SlotId = keyof SlotContexts;

/** Перечень слотов этапа 1; новый слот — только через ТЗ модуля-владельца экрана. */
export const SLOT_IDS = [
  'app.header.actions',
  'app.nav.items',
  'app.user_menu.items',
  'settings.sections',
] as const satisfies readonly SlotId[];

export type SlotProps<Id extends SlotId> = { context: SlotContexts[Id] };

export type SlotContribution<Id extends SlotId> = {
  /** Уникальный идентификатор вклада `<module>.<name>`. */
  id: string;
  /** Порядок вывода: по возрастанию. */
  order: number;
  /** Ключ i18n подписи вклада (SYS-07). */
  labelKey: string;
  /** Условие показа по контексту слота. */
  when?: (context: SlotContexts[Id]) => boolean;
  component: ComponentType<SlotProps<Id>>;
};

type AnyContribution = SlotContribution<SlotId>;

const contributions = new Map<SlotId, AnyContribution[]>();

/** Регистрирует вклад; повторная регистрация с тем же `id` заменяет прежний. */
export const registerSlotContribution = <Id extends SlotId>(
  slotId: Id,
  contribution: SlotContribution<Id>,
): void => {
  const current = (contributions.get(slotId) ?? []).filter(
    (item) => item.id !== contribution.id,
  );
  contributions.set(slotId, [
    ...current,
    contribution as unknown as AnyContribution,
  ]);
};

/** Вклады слота по возрастанию `order`. */
export const getSlotContributions = <Id extends SlotId>(
  slotId: Id,
): SlotContribution<Id>[] =>
  [...(contributions.get(slotId) ?? [])].sort(
    (a, b) => a.order - b.order,
  ) as unknown as SlotContribution<Id>[];

/** Очищает реестр (только для тестов). */
export const resetSlotContributions = (): void => {
  contributions.clear();
};
