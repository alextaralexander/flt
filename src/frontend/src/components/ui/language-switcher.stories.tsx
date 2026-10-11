import type { Meta, StoryObj } from '@storybook/react-vite';

import { LanguageSwitcher } from './language-switcher';

const meta: Meta<typeof LanguageSwitcher> = {
  component: LanguageSwitcher,
};

export default meta;

type Story = StoryObj<typeof LanguageSwitcher>;

export const Default: Story = {};
