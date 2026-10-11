import { applyDocumentDirection, directionOf, getDirection } from './direction';
import { SUPPORTED_UI_LANGUAGES } from './languages';

describe('direction', () => {
  it('[SYS-07-R26] getDirection covers every interface language', () => {
    const directions = Object.fromEntries(
      SUPPORTED_UI_LANGUAGES.map((code) => [code, getDirection(code)]),
    );
    expect(directions).toEqual({ ru: 'ltr', en: 'ltr', ar: 'rtl' });
    expect(directionOf('xx')).toBe('ltr');
  });

  it('[SYS-07-R16] sets dir and lang on <html>', () => {
    applyDocumentDirection('ar');
    expect(document.documentElement.dir).toBe('rtl');
    expect(document.documentElement.lang).toBe('ar');
    applyDocumentDirection('en');
    expect(document.documentElement.dir).toBe('ltr');
    expect(document.documentElement.lang).toBe('en');
  });
});
