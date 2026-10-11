/**
 * Локальное правило flt/no-physical-direction-classes (ADR-005, 3.4; SYS-07-R17).
 *
 * Запрещает физические классы направления Tailwind (`ml-*`, `pr-*`, `left-*`,
 * `text-left` и подобные) в атрибуте `className` и в аргументах вызовов
 * `cn(...)`, `cva(...)`, `twMerge(...)`. Разрешены только логические классы
 * (`ms-*`, `pe-*`, `start-*`, `text-start`). Класс с явным вариантом `ltr:` или
 * `rtl:` допускается только внутри `src/components/ui` (зеркалирование иконок).
 */

/** Регулярное выражение ADR-005, раздел 3.4 (общее с архитектурным тестом для CSS). */
export const PHYSICAL_DIRECTION_CLASS_RE =
  /(^|[\s:'"`])(-?)(ml|mr|pl|pr|left|right|inset-x|scroll-ml|scroll-mr|scroll-pl|scroll-pr|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br|border-l|border-r)-|(^|[\s:'"`])(text-left|text-right|float-left|float-right|clear-left|clear-right)(\s|$|['"`])/;

const CLASS_FUNCTIONS = new Set(['cn', 'cva', 'twMerge', 'clsx']);
const DIRECTION_VARIANT_RE = /(^|:)(ltr|rtl):/;
const UI_KIT_RE = /[\\/]src[\\/]components[\\/]ui[\\/]/;

/**
 * Возвращает физические классы из строки классов.
 * @param {string} value строка классов
 * @param {boolean} allowDirectionVariants разрешены ли классы с вариантами `ltr:`/`rtl:`
 * @returns {string[]} найденные запрещённые классы
 */
export function findPhysicalClasses(value, allowDirectionVariants) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .filter(
      (token) => !(allowDirectionVariants && DIRECTION_VARIANT_RE.test(token)),
    )
    .filter((token) => PHYSICAL_DIRECTION_CLASS_RE.test(` ${token} `));
}

/** @type {import('eslint').Rule.RuleModule} */
const rule = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Запрещает физические классы направления Tailwind: только логические (ms-*, pe-*, start-*, text-start)',
    },
    schema: [],
    messages: {
      physical:
        'Физический класс направления "{{name}}" запрещён (SYS-07-R17): используйте логический (ms-*, me-*, ps-*, pe-*, start-*, end-*, text-start, text-end, border-s-*, rounded-e-*)',
    },
  },
  create(context) {
    const filename = context.filename ?? context.getFilename();
    const allowDirectionVariants = UI_KIT_RE.test(filename);

    function checkString(node, value) {
      for (const name of findPhysicalClasses(value, allowDirectionVariants)) {
        context.report({ node, messageId: 'physical', data: { name } });
      }
    }

    function visit(node) {
      if (!node || typeof node !== 'object') return;
      switch (node.type) {
        case 'Literal':
          if (typeof node.value === 'string') checkString(node, node.value);
          return;
        case 'TemplateLiteral':
          for (const quasi of node.quasis)
            checkString(quasi, quasi.value.cooked ?? quasi.value.raw);
          for (const expr of node.expressions) visit(expr);
          return;
        case 'JSXExpressionContainer':
          visit(node.expression);
          return;
        case 'ConditionalExpression':
          visit(node.consequent);
          visit(node.alternate);
          return;
        case 'LogicalExpression':
        case 'BinaryExpression':
          visit(node.left);
          visit(node.right);
          return;
        case 'ArrayExpression':
          node.elements.forEach(visit);
          return;
        case 'ObjectExpression':
          for (const prop of node.properties) {
            if (prop.type === 'Property') {
              visit(prop.value);
              // в cn({ 'ml-2': cond }) классы стоят в ключах
              if (prop.key.type === 'Literal') visit(prop.key);
            }
          }
          return;
        case 'CallExpression':
          // cn/cva/twMerge проверяет собственный обработчик CallExpression ниже
          if (
            node.callee.type === 'Identifier' &&
            CLASS_FUNCTIONS.has(node.callee.name)
          )
            return;
          node.arguments.forEach(visit);
          return;
        case 'TSAsExpression':
        case 'TSSatisfiesExpression':
          visit(node.expression);
          return;
        default:
      }
    }

    return {
      JSXAttribute(node) {
        if (node.name.name === 'className') visit(node.value);
      },
      CallExpression(node) {
        if (
          node.callee.type === 'Identifier' &&
          CLASS_FUNCTIONS.has(node.callee.name)
        ) {
          node.arguments.forEach(visit);
        }
      },
    };
  },
};

export default rule;
