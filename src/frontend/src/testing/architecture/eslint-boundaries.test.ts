// Негативный архитектурный тест границ модулей frontend (ADR-005, 3.6;
// CLAUDE.md «Модульный монолит → Frontend»): нарушение границы ломает `eslint`.
import fs from 'node:fs';
import path from 'node:path';

import { ESLint } from 'eslint';

const FRONTEND_ROOT = path.resolve(__dirname, '../../..');
const FEATURES_DIR = path.join(FRONTEND_ROOT, 'src/features');
const FIXTURE = path.join(FEATURES_DIR, '__fixtures__/boundary-violation.tsx');
const RULE = 'import-x/no-restricted-paths';

const eslint = new ESLint({ cwd: FRONTEND_ROOT, ignore: false });

const restrictedPathErrors = (results: ESLint.LintResult[]) =>
  results.flatMap((r) => r.messages).filter((m) => m.ruleId === RULE);

/** Первый исходный файл реального модуля (не фикстуры) для импорта через границу. */
const findForeignModuleFile = (): { module: string; spec: string } => {
  const modules = fs
    .readdirSync(FEATURES_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith('__'))
    .map((d) => d.name);
  for (const module of modules) {
    const files = fs
      .readdirSync(path.join(FEATURES_DIR, module), { recursive: true })
      .map(String)
      .filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f));
    if (files.length > 0) {
      const spec = `@/features/${module}/${files[0].replace(/\.(ts|tsx)$/, '')}`;
      return { module, spec: spec.split(path.sep).join('/') };
    }
  }
  throw new Error('В src/features нет ни одного модуля с исходными файлами');
};

describe('frontend module boundaries', () => {
  it('[SYS-01-R11] fixture importing src/app from a feature module fails eslint', async () => {
    const results = await eslint.lintFiles([FIXTURE]);
    expect(restrictedPathErrors(results)).not.toHaveLength(0);
  }, 60_000);

  it('[SYS-01-R11] feature module importing another feature module fails eslint', async () => {
    const { spec } = findForeignModuleFile();
    const code = `import * as foreign from '${spec}';\n\nexport const used = foreign;\n`;
    const results = await eslint.lintText(code, {
      filePath: path.join(FEATURES_DIR, '__fixtures__/cross-module.ts'),
    });
    const errors = restrictedPathErrors(results);
    expect(errors).not.toHaveLength(0);
    expect(errors[0].message).toContain('__fixtures__');
  }, 60_000);

  it('[SYS-01-R11] shared layer importing a feature module fails eslint', async () => {
    const code =
      "import { BoundaryViolation } from '@/features/__fixtures__/boundary-violation';\n\nexport const used = BoundaryViolation;\n";
    const results = await eslint.lintText(code, {
      filePath: path.join(FRONTEND_ROOT, 'src/lib/boundary-fixture.ts'),
    });
    expect(restrictedPathErrors(results)).not.toHaveLength(0);
  }, 60_000);

  it('[SYS-01-R11] import inside the same module and from the shared layer passes', async () => {
    const code =
      "import { cn } from '@/utils/cn';\n\nexport const used = cn('ms-2');\n";
    const results = await eslint.lintText(code, {
      filePath: path.join(FEATURES_DIR, '__fixtures__/allowed.ts'),
    });
    expect(restrictedPathErrors(results)).toHaveLength(0);
  }, 60_000);
});
