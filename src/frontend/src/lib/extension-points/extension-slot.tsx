import type { ReactNode } from 'react';

import type { SlotContexts, SlotId } from './slots';
import { getSlotContributions } from './slots';

export type ExtensionSlotProps<Id extends SlotId> = {
  id: Id;
  context: SlotContexts[Id];
  /** Показывается, если подходящих вкладов нет. */
  fallback?: ReactNode;
};

/**
 * Рендерит вклады слота по возрастанию `order` с фильтром `when`
 * (SYS-09-R5).
 */
export const ExtensionSlot = <Id extends SlotId>({
  id,
  context,
  fallback = null,
}: ExtensionSlotProps<Id>) => {
  const items = getSlotContributions(id).filter(
    (item) => !item.when || item.when(context),
  );
  if (items.length === 0) return <>{fallback}</>;
  return (
    <>
      {items.map(({ id: contributionId, component: Component }) => (
        <Component key={contributionId} context={context} />
      ))}
    </>
  );
};
