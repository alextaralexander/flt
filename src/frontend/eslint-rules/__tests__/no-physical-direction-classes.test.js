import { RuleTester } from 'eslint';

import rule, { findPhysicalClasses } from '../no-physical-direction-classes.js';

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

const FEATURE_FILE = '/repo/src/frontend/src/features/demo/components/card.tsx';
const UI_FILE = '/repo/src/frontend/src/components/ui/icon.tsx';

describe('flt/no-physical-direction-classes', () => {
  it('[SYS-07-R17] finds physical classes and ignores logical ones', () => {
    expect(findPhysicalClasses('ms-2 pe-4 start-0 text-start', false)).toEqual(
      [],
    );
    expect(
      findPhysicalClasses('ml-2 sm:pr-4 -left-1 text-right', false),
    ).toEqual(['ml-2', 'sm:pr-4', '-left-1', 'text-right']);
    expect(findPhysicalClasses('rtl:ml-2', true)).toEqual([]);
    expect(findPhysicalClasses('rtl:ml-2', false)).toEqual(['rtl:ml-2']);
  });

  ruleTester.run('no-physical-direction-classes', rule, {
    valid: [
      {
        code: '<div className="ms-2 pe-4 text-start border-s-4 rounded-e-lg" />',
        filename: FEATURE_FILE,
      },
      {
        code: "cn('ms-2', cond && 'me-2', { 'ps-1': cond })",
        filename: FEATURE_FILE,
      },
      {
        code: "cva('inline-flex', { variants: { size: { sm: 'ps-3 pe-3' } } })",
        filename: FEATURE_FILE,
      },
      {
        code: '<Icon className="rtl:-scale-x-100 ltr:ml-1" />',
        filename: UI_FILE,
      },
      // строки вне className и функций классов не проверяются
      { code: "const align = 'text-left';", filename: FEATURE_FILE },
    ],
    invalid: [
      {
        code: '<div className="ml-2 text-left" />',
        filename: FEATURE_FILE,
        errors: [{ messageId: 'physical' }, { messageId: 'physical' }],
      },
      {
        code: "<div className={cn('pr-4', active ? 'left-0' : 'right-0')} />",
        filename: FEATURE_FILE,
        errors: [
          { messageId: 'physical' },
          { messageId: 'physical' },
          { messageId: 'physical' },
        ],
      },
      {
        code: "cva('border-l-4', { variants: { size: { sm: 'rounded-r-lg' } } })",
        filename: FEATURE_FILE,
        errors: [{ messageId: 'physical' }, { messageId: 'physical' }],
      },
      {
        code: '<div className={`sm:ml-2 ${x}`} />',
        filename: FEATURE_FILE,
        errors: [{ messageId: 'physical' }],
      },
      {
        // варианты rtl:/ltr: разрешены только в src/components/ui
        code: '<Icon className="ltr:ml-1" />',
        filename: FEATURE_FILE,
        errors: [{ messageId: 'physical' }],
      },
    ],
  });
});
