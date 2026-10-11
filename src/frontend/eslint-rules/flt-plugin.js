/**
 * Локальный плагин ESLint `flt` (ADR-005, 3.4 и 3.6): правила проекта FLT.
 */
import noPhysicalDirectionClasses from './no-physical-direction-classes.js';

const fltPlugin = {
  meta: { name: 'eslint-plugin-flt', version: '1.0.0' },
  rules: {
    'no-physical-direction-classes': noPhysicalDirectionClasses,
  },
};

export default fltPlugin;
