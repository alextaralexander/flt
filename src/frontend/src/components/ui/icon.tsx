import type { LucideProps } from 'lucide-react';

import { cn } from '@/utils/cn';

import type { IconName } from './icons/registry';
import { ICONS } from './icons/registry';
import { isRtlMirroredIcon } from './icons/rtl-mirrored';

export type IconProps = Omit<LucideProps, 'ref'> & { name: IconName };

/**
 * Иконка lucide; иконки из `RTL_MIRRORED_ICONS` в RTL отражаются
 * по горизонтали (SYS-07-R18). Декоративна по умолчанию (`aria-hidden`).
 */
export const Icon = ({ name, className, ...props }: IconProps) => {
  const Component = ICONS[name];
  return (
    <Component
      aria-hidden="true"
      data-icon={name}
      className={cn(isRtlMirroredIcon(name) && 'rtl:-scale-x-100', className)}
      {...props}
    />
  );
};
