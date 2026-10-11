import type { Meta, StoryObj } from '@storybook/react-vite';

import { Icon } from './icon';
import { RTL_MIRRORED_ICONS } from './icons/rtl-mirrored';

const meta: Meta<typeof Icon> = {
  title: 'Icon',
  component: Icon,
};

export default meta;

type Story = StoryObj<typeof Icon>;

export const Default: Story = {
  args: { name: 'ChevronRight', className: 'size-6' },
};

/** Все иконки перечня RTL_MIRRORED_ICONS (SYS-07-R18): переключите direction: rtl. */
export const RtlMirrored: Story = {
  render: () => (
    <div className="grid grid-cols-6 gap-4">
      {RTL_MIRRORED_ICONS.map((name) => (
        <div key={name} className="flex flex-col items-center gap-1 text-xs">
          <Icon name={name} className="size-6" />
          <span>{name}</span>
        </div>
      ))}
    </div>
  ),
};
