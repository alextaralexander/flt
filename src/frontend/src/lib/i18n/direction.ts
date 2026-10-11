import type { TextDirection } from './languages';
import { textDirectionOf } from './languages';

/**
 * Направление интерфейса для языка: `rtl` для `ar`, иначе `ltr`
 * (ADR-005, 3.4; SYS-07-R16).
 */
export const directionOf = (code: string): TextDirection =>
  textDirectionOf(code) === 'rtl' ? 'rtl' : 'ltr';

/** Синоним `directionOf` из ADR-005, 3.3. */
export const getDirection = directionOf;

/**
 * Ставит `dir` и `lang` на `<html>`: направление задаётся для всего
 * документа (SYS-07-R16).
 */
export const applyDocumentDirection = (
  code: string,
  doc: Document = document,
): void => {
  doc.documentElement.dir = directionOf(code);
  doc.documentElement.lang = code;
};
