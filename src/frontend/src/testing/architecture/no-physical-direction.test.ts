// Архитектурный тест: в .css нет физических классов и свойств направления
// (ADR-005, 3.4; SYS-07-R17). Для TSX то же проверяет правило ESLint
// flt/no-physical-direction-classes с тем же регулярным выражением.
import fs from 'node:fs';
import path from 'node:path';

import { PHYSICAL_DIRECTION_CLASS_RE } from '../../../eslint-rules/no-physical-direction-classes.js';

const SRC = path.resolve(__dirname, '../..');

/** Физические CSS-свойства направления; логические (margin-inline-start и т.п.) разрешены. */
const PHYSICAL_PROPERTY_RE =
  /(^|[\s;{])(margin-left|margin-right|padding-left|padding-right|left|right|border-left|border-right)\s*:|text-align\s*:\s*(left|right)\b/;

const listCssFiles = (dir: string): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return listCssFiles(full);
    return entry.name.endsWith('.css') ? [full] : [];
  });

/** Нарушения в тексте CSS: строки с физическими свойствами или классами в @apply. */
const findCssViolations = (css: string): string[] => {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');
  return withoutComments.split('\n').filter((line) => {
    if (PHYSICAL_PROPERTY_RE.test(line)) return true;
    const apply = line.match(/@apply\s+([^;]+)/);
    return apply !== null && PHYSICAL_DIRECTION_CLASS_RE.test(` ${apply[1]} `);
  });
};

describe('no physical direction in CSS', () => {
  it('[SYS-07-R17] detects physical properties and @apply classes', () => {
    expect(findCssViolations('.a { margin-left: 4px; }')).toHaveLength(1);
    expect(findCssViolations('.a { text-align: right; }')).toHaveLength(1);
    expect(findCssViolations('.a { @apply ml-2 text-sm; }')).toHaveLength(1);
    expect(findCssViolations('.a { left: 0; }')).toHaveLength(1);
    expect(
      findCssViolations(
        '.a { margin-inline-start: 4px; inset-inline-start: 0; text-align: start; @apply ms-2; }',
      ),
    ).toEqual([]);
  });

  it('[SYS-07-R17] project CSS files use only logical properties', () => {
    const files = listCssFiles(SRC);
    expect(files.length).toBeGreaterThan(0);
    const violations = files.flatMap((file) =>
      findCssViolations(fs.readFileSync(file, 'utf8')).map(
        (line) => `${path.relative(SRC, file)}: ${line.trim()}`,
      ),
    );
    expect(violations).toEqual([]);
  });
});
