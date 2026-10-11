// Генерация API-клиента, zod-схем и MSW-моков из контрактов OpenAPI
// (ADR-005, 3.5; SYS-03-R23). Записи строятся автоматически из списка
// Analytics/Specs/<module>/api/openapi.yaml: новый контракт подхватывается
// без правки конфига. Пустой список контрактов — допустимое состояние
// (этап 1 до появления контрактов модулей): генерация ничего не делает.
import fs from 'node:fs';
import path from 'node:path';

import type { Options } from 'orval';
import { defineConfig } from 'orval';

const FRONTEND_ROOT = import.meta.dirname;
// FLT_SPECS_DIR — только для проверки генератора на фикстурах
const SPECS_DIR = path.resolve(
  FRONTEND_ROOT,
  process.env.FLT_SPECS_DIR ?? '../../Analytics/Specs',
);

/** Имя frontend-модуля — kebab-case имени backend-модуля (SYS-01-R11). */
export const featureNameOf = (module: string) => module.replaceAll('_', '-');

/** Модули с контрактом OpenAPI; служебные каталоги `_system`, `_templates` пропускаются. */
export const listOpenApiModules = (specsDir: string = SPECS_DIR): string[] =>
  fs.existsSync(specsDir)
    ? fs
        .readdirSync(specsDir, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && !entry.name.startsWith('_'))
        .map((entry) => entry.name)
        .filter((module) =>
          fs.existsSync(path.join(specsDir, module, 'api/openapi.yaml')),
        )
        .sort()
    : [];

const relativeToFrontend = (absolute: string) =>
  path.relative(FRONTEND_ROOT, absolute).split(path.sep).join('/');

const moduleEntries = (module: string): Record<string, Options> => {
  const input = relativeToFrontend(
    path.join(SPECS_DIR, module, 'api/openapi.yaml'),
  );
  const generated = `src/features/${featureNameOf(module)}/api/generated`;
  return {
    [module]: {
      input,
      output: {
        mode: 'tags-split',
        target: `${generated}/client.ts`,
        schemas: `${generated}/model`,
        client: 'react-query',
        httpClient: 'axios',
        clean: true,
        mock: {
          generators: [
            { type: 'msw', generateEachHttpStatus: true, delay: false },
          ],
        },
        override: {
          mutator: { path: 'src/lib/api-client.ts', name: 'apiMutator' },
          query: { useQuery: true, useInfinite: true, signal: true },
        },
      },
    },
    [`${module}-zod`]: {
      input,
      output: {
        mode: 'single',
        client: 'zod',
        target: `${generated}/zod.ts`,
      },
    },
  };
};

/** Общие схемы (`ErrorResponseV1`) из Analytics/Specs/_system/openapi-common.yaml. */
const commonEntries = (): Record<string, Options> => {
  const common = path.join(SPECS_DIR, '_system/openapi-common.yaml');
  if (!fs.existsSync(common)) return {};
  return {
    'common-zod': {
      input: relativeToFrontend(common),
      output: {
        mode: 'single',
        client: 'zod',
        target: 'src/lib/api-types/generated/zod.ts',
      },
    },
  };
};

export default defineConfig({
  ...commonEntries(),
  ...Object.assign({}, ...listOpenApiModules().map(moduleEntries)),
});
