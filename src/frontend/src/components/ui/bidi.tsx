import type { ReactNode } from 'react';

import { textDirectionOf } from '@/lib/i18n/languages';

export type BidiProps = {
  /** Код языка текста (BCP-47, SYS-07-R25). */
  lang?: string | null;
  children: ReactNode;
  className?: string;
};

/**
 * Изолирует текст, язык которого может отличаться от языка интерфейса:
 * `<bdi>` с `lang` и `dir` по коду языка либо `dir="auto"`, если язык
 * неизвестен (SYS-07-R20, R23).
 */
export const Bidi = ({ lang, children, className }: BidiProps) => (
  <bdi
    lang={lang ?? undefined}
    dir={textDirectionOf(lang)}
    className={className}
  >
    {children}
  </bdi>
);
