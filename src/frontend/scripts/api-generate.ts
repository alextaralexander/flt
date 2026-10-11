// pnpm api:generate — orval (REST: клиент, zod, MSW-моки) и asyncapi-to-zod
// (WebSocket) из контрактов Analytics/Specs (ADR-005, 3.5).
// pnpm api:check (флаг --check) — то же, но падает, если сгенерированный код
// в репозитории устарел. Проверка сравнивает содержимое каталогов
// generated до и после генерации и не требует git (работает в Docker-сборке).
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const FRONTEND_ROOT = path.resolve(import.meta.dirname, '..');
const SRC = path.join(FRONTEND_ROOT, 'src');

/** Хэши всех файлов внутри каталогов `generated` в src. */
const snapshotGenerated = (): Map<string, string> => {
  const result = new Map<string, string>();
  const walk = (dir: string, insideGenerated: boolean) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full, insideGenerated || entry.name === 'generated');
      } else if (insideGenerated) {
        const hash = createHash('sha256')
          .update(fs.readFileSync(full))
          .digest('hex');
        result.set(path.relative(FRONTEND_ROOT, full), hash);
      }
    }
  };
  walk(SRC, false);
  return result;
};

const diffSnapshots = (
  before: Map<string, string>,
  after: Map<string, string>,
): string[] => {
  const changed: string[] = [];
  for (const [file, hash] of after) {
    if (!before.has(file)) changed.push(`added    ${file}`);
    else if (before.get(file) !== hash) changed.push(`modified ${file}`);
  }
  for (const file of before.keys()) {
    if (!after.has(file)) changed.push(`removed  ${file}`);
  }
  return changed.sort();
};

const generate = () => {
  const bin = (name: string) =>
    path.join(FRONTEND_ROOT, 'node_modules/.bin', name);
  execFileSync(bin('orval'), [], { cwd: FRONTEND_ROOT, stdio: 'inherit' });
  execFileSync(
    process.execPath,
    [path.join(FRONTEND_ROOT, 'scripts/asyncapi-to-zod.ts')],
    { cwd: FRONTEND_ROOT, stdio: 'inherit' },
  );
};

const check = process.argv.includes('--check');
const before = snapshotGenerated();
generate();
if (check) {
  const changed = diffSnapshots(before, snapshotGenerated());
  if (changed.length > 0) {
    console.error(
      [
        'api:check: сгенерированный код не совпадает с контрактами.',
        'Выполните `pnpm api:generate` и закоммитьте изменения:',
        ...changed.map((line) => `  ${line}`),
      ].join('\n'),
    );
    process.exit(1);
  }
  console.log('api:check: сгенерированный код соответствует контрактам');
}
