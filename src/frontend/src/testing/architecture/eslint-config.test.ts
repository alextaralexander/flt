// Сверка настроек ESLint с SYS-07-R9: перечень allowedStrings не расширяется
// под конкретный экран, строки UI в JSX и атрибутах ломают `eslint`.
import path from 'node:path';

import { ESLint } from 'eslint';

import { ALLOWED_JSX_STRINGS } from '../../../eslint-rules/allowed-strings.js';

const FRONTEND_ROOT = path.resolve(__dirname, '../../..');
const eslint = new ESLint({ cwd: FRONTEND_ROOT });

const ruleIds = async (code: string, file: string) => {
  const [result] = await eslint.lintText(code, {
    filePath: path.join(FRONTEND_ROOT, file),
  });
  return (result?.messages ?? []).map((m) => m.ruleId);
};

describe('eslint i18n rules', () => {
  it('[SYS-07-R9] allowedStrings match the SYS-07 table', () => {
    expect(ALLOWED_JSX_STRINGS).toEqual([
      ' ',
      '.',
      ',',
      ':',
      ';',
      '—',
      '–',
      '/',
      '|',
      '(',
      ')',
      '%',
      '+',
      '×',
      ...'0123456789'.split(''),
    ]);
  });

  it('[SYS-07-R9] JSX text and aria-label literals fail in shared components', async () => {
    const code =
      'export const A = () => <button aria-label="Close" className="ms-2">Close</button>;\n';
    const ids = await ruleIds(code, 'src/components/ui/zz-fixture.tsx');
    expect(ids).toContain('react/jsx-no-literals');
    expect(ids).toContain('no-restricted-syntax');
  }, 60_000);

  it('[SYS-07-R18] direct lucide-react import fails outside src/components/ui', async () => {
    const code = "import { X } from 'lucide-react';\n\nexport const A = X;\n";
    const ids = await ruleIds(code, 'src/lib/zz-fixture.ts');
    expect(ids).toContain('no-restricted-imports');
  }, 60_000);
});
