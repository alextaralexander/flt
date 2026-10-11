import type { Meta, StoryObj } from '@storybook/react-vite';

import { Bidi } from './bidi';

const meta: Meta<typeof Bidi> = {
  component: Bidi,
};

export default meta;

type Story = StoryObj<typeof Bidi>;

/** Английский пример внутри арабского абзаца (SYS-07-R20). */
export const MixedDirection: Story = {
  render: () => (
    <p dir="rtl" lang="ar">
      مثال: <Bidi lang="en">Hello, world! (v1.2)</Bidi> — نهاية الجملة.
    </p>
  ),
};

export const UnknownLanguage: Story = {
  args: { lang: 'xx', children: 'text 123' },
};
