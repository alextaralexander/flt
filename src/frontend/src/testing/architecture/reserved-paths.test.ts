// Маршруты приложения не пересекаются с путями HAProxy и не содержат язык
// (ADR-005, 3.5; ADR-007; ADR-012; SYS-07-R4).
import fs from 'node:fs';
import path from 'node:path';

import { paths } from '@/config/paths';
import { SUPPORTED_UI_LANGUAGES } from '@/lib/i18n/languages';

const RESERVED_PREFIXES = ['/api', '/ws', '/flt-'];

/** Все значения `path` из src/config/paths.ts с учётом вложенности `app`. */
const collectConfigPaths = (node: unknown, parent = ''): string[] => {
  if (!node || typeof node !== 'object') return [];
  const record = node as Record<string, unknown>;
  const own = typeof record.path === 'string' ? record.path : null;
  const full =
    own === null
      ? parent
      : own.startsWith('/')
        ? own
        : `${parent.replace(/\/$/, '')}/${own}`;
  const nested = Object.entries(record)
    .filter(([key]) => key !== 'path' && key !== 'getHref')
    .flatMap(([, value]) =>
      collectConfigPaths(value, own === null ? parent : full),
    );
  return own === null ? nested : [full, ...nested];
};

/** Строковые `path:` в роутере и файлах роутов. */
const collectLiteralPaths = (): string[] => {
  const appDir = path.resolve(__dirname, '../../app');
  const files = fs
    .readdirSync(appDir, { recursive: true })
    .map(String)
    .filter((file) => /\.(ts|tsx)$/.test(file) && !file.includes('__tests__'));
  return files.flatMap((file) =>
    [
      ...fs
        .readFileSync(path.join(appDir, file), 'utf8')
        .matchAll(/\bpath:\s*['"`]([^'"`]+)['"`]/g),
    ].map((match) => match[1] ?? ''),
  );
};

const isReserved = (route: string) =>
  RESERVED_PREFIXES.some(
    (prefix) => route === prefix || route.startsWith(prefix),
  );

const hasLanguagePrefix = (route: string) =>
  route.includes(':lang') ||
  SUPPORTED_UI_LANGUAGES.some(
    (code) => route === `/${code}` || route.startsWith(`/${code}/`),
  );

describe('reserved paths', () => {
  const routes = [...collectConfigPaths(paths), ...collectLiteralPaths()];

  it('[SYS-07-R4] the check itself detects reserved and language prefixes', () => {
    expect(isReserved('/api/v1/x')).toBe(true);
    expect(isReserved('/flt-cms/public/a.png')).toBe(true);
    expect(isReserved('/ws')).toBe(true);
    expect(isReserved('/app/workspace')).toBe(false);
    expect(hasLanguagePrefix('/ar/courses')).toBe(true);
    expect(hasLanguagePrefix('/:lang/courses')).toBe(true);
    expect(hasLanguagePrefix('/arabic')).toBe(false);
  });

  it('[SYS-07-R4] application routes do not start with /api, /ws or /flt-', () => {
    expect(routes.length).toBeGreaterThan(0);
    expect(routes.filter(isReserved)).toEqual([]);
  });

  it('[SYS-07-R4] application routes carry no language prefix', () => {
    expect(routes.filter(hasLanguagePrefix)).toEqual([]);
  });
});
