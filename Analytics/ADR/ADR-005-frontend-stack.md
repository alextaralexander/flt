# ADR-005 — Frontend на основе bulletproof-react: версии, pnpm, i18n и RTL, генерация клиента, WebSocket, покрытие

| Поле | Значение |
|---|---|
| Статус | accepted |
| Версия | 1.0 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-10 (PR #2) |
| Пункт(ы) BRD | все (frontend обслуживает все пункты); напрямую — VIS-01…VIS-05, STU-06 (язык интерфейса) |
| Модуль | app_shell (frontend shared), все frontend-модули `src/features/<модуль>` |
| Зависимости | ADR-001 (политика версий), ADR-004 (формат сообщений WebSocket и переподключение), ADR-006 (способ передачи токена) |
| Связанные ADR/SYS | ADR-007 (dev-прокси `/flt-*`, источники CSP для файлов), ADR-009 (сообщения стрима), ADR-011 (CI, git-хуки), ADR-012 (маршруты HAProxy `/api`, `/ws`, `/flt-*` без переписывания), SYS-02 (CSP, безопасность), SYS-03 (OpenAPI), SYS-04 (AsyncAPI), SYS-07 (i18n), SYS-10 (тесты), SYS-11 (контейнер Nginx), SYS-12 (CI); спецификация `Analytics/Specs/app_shell/_module.md` |

## 1. Контекст

- **Проблема**: frontend импортирован из bulletproof-react (`apps/react-vite`, коммит `9506629` от 2026-05-14) с устаревшими версиями (`src/frontend/package.json`: React 18.3, Vite 5.2, Tailwind 3.4, ESLint 8 с `.eslintrc.cjs`, TypeScript 5.4, Vitest 2.1, Storybook 8.0, yarn 1 с `yarn.lock`). В нём нет i18n и RTL, WebSocket-клиента, генерации API-клиента из контрактов, Dockerfile с Nginx; аутентификация построена на `react-query-auth` и cookie-сессии; `.env.example` указывает адрес `https://api.bulletproofapp.com`; порог покрытия не задан; зоны ESLint `import/no-restricted-paths` перечислены вручную для пяти демо-фич (`auth`, `comments`, `discussions`, `teams`, `users`). Нужно зафиксировать целевой стек и порядок миграции, чтобы этап 1 Г.1 и Г.7 выполнялись без устных пояснений.
- **Почему сейчас**: этап 1, пункты Г.1 (доработка frontend boilerplate), Г.2 (правила ESLint), Г.3 (моки REST и WebSocket), Г.7 (app-shell), Г.11 (E2E на трёх языках интерфейса). Решение пользователя от 2026-10-10: менеджер пакетов — pnpm.
- **Ограничения**:
  - CLAUDE.md, «Frontend (boilerplate)» и «Отличия проекта от boilerplate» (10 пунктов): последние стабильные версии, flat config ESLint, модули `src/features/<модуль>` повторяют backend-модули, i18next с ru/en/ar, логические классы Tailwind и `DirectionProvider` Radix, клиент из OpenAPI и моки MSW по тем же контрактам, относительные адреса `/api` и `/ws`, WebSocket-клиент в shared-слое, Nginx для статики, порог покрытия, git-хуки на уровне репозитория;
  - CLAUDE.md, «Модульный монолит → Frontend»: модули не импортируют друг друга, связываются только в `src/app`, barrel-файлы не используются, структура допускает вынос модуля в микрофронтенд;
  - CLAUDE.md, «Масштабирование и состояние»: одна и та же сборка статики работает на всех стендах, поэтому адреса бэкенда в сборку не встраиваются;
  - решение пользователя (2026-10-10): pnpm; аутентификация — httpOnly-cookie для браузера (ADR-006);
  - правила `src/frontend/docs` (структура проекта, API-слой, тесты) действуют там, где этот ADR их не меняет.
- **Если не решить**: Г.1 выполняется по памяти с разными версиями и инструментами в разных ветках; i18n и RTL добавляются постфактум и требуют переписывания стилей; контракты OpenAPI и код расходятся; порог покрытия и зоны ESLint не проверяются в CI.
- **Ссылки**: CLAUDE.md «Frontend (boilerplate)», «Модульный монолит», «Взаимодействие», «Ключевые архитектурные требования»; SDD_plan.md этап 1 А.5, Г.1, Г.2, Г.3, Г.7, Г.11; OQ-25 (язык по умолчанию — SYS-07); `src/frontend/docs/project-structure.md`, `api-layer.md`, `testing.md`.

## 2. Рассматриваемые варианты

### Вариант A. Оставить boilerplate как есть (yarn 1, текущие версии), добавлять только недостающее

- **Описание**: не обновлять версии; i18n, WebSocket, генерацию клиента и Dockerfile добавить поверх React 18 / Vite 5 / Tailwind 3 / ESLint 8.
- **Плюсы**:
  - нулевая стоимость миграции на старте;
  - `eslint-plugin-tailwindcss` 3.x работает с Tailwind 3 без замены.
- **Минусы**:
  - нарушает правило CLAUDE.md «последние стабильные версии»;
  - ESLint 8 снят с поддержки (EOL 2024-10-05), `.eslintrc` удалён в ESLint 10 — отложенная миграция дорожает с каждым модулем;
  - Tailwind 3 поддерживает логические утилиты (`ms-*`, `pe-*`, `start-*`), но не CSS-first конфигурацию и `@theme`; миграция на Tailwind 4 после появления компонентов FLT затронет все файлы стилей;
  - yarn 1 заморожен (только исправления безопасности), lock-файл не воспроизводит peer-зависимости строго;
  - React 18 без `<title>`/`<meta>` в компонентах — остаётся `react-helmet-async`.
- **Масштабирование на N инстансах**: нейтрально — статика.
- **Выделение модулей в микрофронтенды**: нейтрально.
- **Трудоёмкость и риски**: низкая сейчас, высокая позже (миграция поверх кода FLT).

### Вариант B. Обновить boilerplate на месте до последних стабильных версий, перейти на pnpm, добавить i18n/RTL, генерацию клиента, WebSocket и Dockerfile по шагам

- **Описание**: сохранить структуру и правила bulletproof-react, обновить все зависимости до последних стабильных мажорных версий, перевести ESLint на flat config, Tailwind на 4 с CSS-first конфигурацией, Storybook на 9+, yarn → pnpm; добавить i18next, `DirectionProvider`, orval для генерации клиента и моков из OpenAPI, WebSocket-клиент в `src/lib/ws`, многоступенчатый Dockerfile с Nginx. Порядок шагов — раздел 3.
- **Плюсы**:
  - выполняет все 10 пунктов «Отличий проекта от boilerplate»;
  - миграция делается до появления кода FLT, когда ломать нечего, кроме пяти демо-фич, которые всё равно удаляются;
  - pnpm: строгий `node_modules` (нет фантомных зависимостей), content-addressable store, `packageManager` + corepack дают одинаковую версию менеджера у человека, Claude и CI;
  - сохраняются документы `src/frontend/docs` как правила архитектуры.
- **Минусы**:
  - одноразовая работа в Г.1: замена плагинов ESLint без поддержки flat config, переписывание `tailwind.config.cjs` в CSS, миграция Storybook;
  - строгий `node_modules` pnpm ломает пакеты, которые полагаются на hoisting (решается `public-hoist-pattern` в `.npmrc`);
  - pnpm 10 не выполняет postinstall-скрипты зависимостей без явного списка `onlyBuiltDependencies` (нужно перечислить `esbuild`, `msw`).
- **Масштабирование на N инстансах**: нейтрально — статика; одна сборка для всех стендов благодаря относительным адресам.
- **Выделение модулей в микрофронтенды**: помогает — генерация клиента и ресурсов i18n на модуль, зоны ESLint на модуль, отсутствие barrel-файлов и общего состояния между модулями.
- **Трудоёмкость и риски**: средняя, разовая (оценочно 2–3 шага конвейера Г.1); риск — несовместимость отдельных плагинов на дату выполнения, смягчается правилом выбора версий (раздел 3).

### Вариант C. Пересобрать frontend на другом стартере (Next.js, TanStack Start, Vite + TanStack Router)

- **Описание**: отказаться от bulletproof-react, создать приложение заново на мета-фреймворке с SSR или на другом роутере.
- **Плюсы**:
  - SSR/SSG для лендинга и каталога (SEO VIS-01, VIS-02).
- **Минусы**:
  - противоречит CLAUDE.md: frontend развивается из boilerplate в `src/frontend`;
  - SSR требует Node-сервера в составе контейнеров вместо Nginx со статикой — изменение «Состава контейнеров» и ADR-012;
  - теряются правила `src/frontend/docs`, генераторы plop, тесты boilerplate;
  - SEO лендинга решается пререндером статики или на стороне `cms` (вопрос ТЗ VIS-01), не требует SSR всего приложения.
- **Масштабирование на N инстансах**: SSR-сервер добавляет ещё один горизонтально масштабируемый сервис без состояния.
- **Выделение модулей в микрофронтенды**: нейтрально.
- **Трудоёмкость и риски**: высокая; не соответствует принятым правилам.

### 2.4. Частные выборы внутри варианта B

| Вопрос | Кандидаты | Выбор и причина |
|---|---|---|
| Генерация API-клиента из OpenAPI | (1) orval: TanStack Query-хуки, axios-mutator, zod-схемы и MSW-моки из одного контракта; (2) openapi-typescript + openapi-fetch + openapi-react-query: только типы и тонкий fetch-клиент, моки пишутся вручную | (1) orval: требование CLAUDE.md «моки MSW по тем же контрактам» выполняется генерацией, а не вручную; сохраняется axios-клиент boilerplate (`src/lib/api-client.ts`) как mutator |
| i18n-библиотека | (1) i18next + react-i18next; (2) FormatJS (react-intl); (3) Lingui | (1) i18next: задан CLAUDE.md; формы множественного числа через `Intl.PluralRules` (арабский — 6 форм, русский — 4 категории CLDR); ленивые namespace на модуль через `i18next-resources-to-backend` |
| Типы сообщений WebSocket из AsyncAPI | (1) `@asyncapi/modelina` — только TypeScript-типы без runtime-валидации; (2) `@asyncapi/parser` + `json-schema-to-zod` — zod-схемы с выводом типов; (3) ручные zod-схемы | (2): входящие сообщения валидируются в runtime (zod), типы выводятся из схем, источник — `asyncapi.yaml` модуля; ручные схемы (3) расходятся с контрактом |
| Запрет физических классов направления | (1) `eslint-plugin-tailwindcss` — не поддерживает Tailwind 4 в стабильной версии; (2) `eslint-plugin-better-tailwindcss` (поддерживает Tailwind 4) + собственное локальное правило ESLint; (3) только скрипт в CI | (2): локальное правило `flt/no-physical-direction-classes` даёт ошибку в IDE и в lint-staged; `better-tailwindcss` проверяет незарегистрированные классы и порядок; для `.css` — архитектурный Vitest-тест с тем же регулярным выражением |
| Аутентификация на фронте | (1) оставить `react-query-auth`; (2) свой `src/lib/auth.tsx` на TanStack Query поверх сгенерированного клиента `identity` | (2): запросы `login`, `logout`, `me`, `refresh` приходят из контракта `identity` (orval), а не пишутся вручную; `react-query-auth` не даёт silent refresh и CSRF-заголовок; имена хуков `useUser`, `useLogin`, `useLogout`, `useRegister`, `AuthLoader`, `ProtectedRoute` сохраняются |
| Git-хуки | (1) husky + lint-staged внутри `src/frontend` (как в boilerplate); (2) единый pre-commit (Python-фреймворк) в корне репозитория с хуком `repo: local`, вызывающим `pnpm --dir src/frontend lint-staged` | (2): одно место для хуков backend и frontend (CLAUDE.md, «Отличия», п. 10); окончательно утверждает ADR-011 |

## 3. Решение

- **Выбран**: Вариант B с частными выборами из раздела 2.4.
- **Решение**: frontend остаётся bulletproof-react в `src/frontend`, обновляется на месте до последних стабильных версий (политика ниже) и переводится на pnpm; добавляются i18next с namespace на модуль и RTL через `dir` на `<html>` + логические классы Tailwind 4 + `DirectionProvider` Radix; API-клиент, zod-схемы и MSW-моки генерируются orval из `Analytics/Specs/<модуль>/api/openapi.yaml`; типы и zod-схемы WebSocket-сообщений генерируются из `asyncapi.yaml`; WebSocket-клиент живёт в `src/lib/ws`; порог покрытия — 70 % `lines`, `functions`, `statements` и 60 % `branches` для `src/features`, `src/lib`, `src/components`, `src/hooks`, `src/utils`, а `src/app/routes` исключены и проверяются E2E (подтверждено пользователем 2026-10-10); базовые адреса относительные — `/api/v1` и `/ws`, HAProxy пути не переписывает (ADR-012); production-образ — многоступенчатый Dockerfile с Nginx только для статики.
- **Обоснование**: вариант B единственный выполняет все требования CLAUDE.md без смены основы; миграция делается до появления кода FLT (см. сравнение в разделе 2).
- **Отвергнуты**:
  - Вариант A — нарушает политику версий, откладывает неизбежную миграцию ESLint и Tailwind на момент, когда она дороже.
  - Вариант C — противоречит правилу «frontend развивается из boilerplate», требует Node-сервера в составе контейнеров.
- **Границы решения**: формат сообщений WebSocket, heartbeat и семантику переподключения задаёт ADR-004 (здесь — только клиентская реализация); имена cookie и CSRF-схему — ADR-006; порядок определения языка интерфейса, шрифты, форматы дат и чисел, текст со смешанным направлением — SYS-07; заголовки безопасности, кроме CSP, — ADR-012 (HAProxy), требования к ним — SYS-02; маршруты HAProxy — ADR-012; состав CI — ADR-011 и SYS-12. Нативные мобильные приложения не рассматриваются.

### 3.1. Политика версий и целевые версии

Правило: при выполнении Г.1 берётся последняя стабильная (не pre-release) мажорная версия каждого пакета, вышедшая не позднее чем за 60 дней до даты выполнения; мажорная версия моложе 60 дней не берётся (экосистема плагинов не успевает). Точные версии фиксирует `pnpm-lock.yaml`; `package.json` указывает диапазоны `^`. Проверка актуальности — `pnpm outdated` в начале Г.1 и далее раз в этап (ревью этапа, SDD_plan.md раздел 8).

Минимальные мажорные версии, известные на 2026-10-10 (ниже этих не опускаться):

| Пакет | Было (boilerplate) | Минимум | Что ломается при переходе |
|---|---|---|---|
| Node.js | не задан | 24 LTS (`engines.node >= 24`, файл `.nvmrc` — его читает `actions/setup-node` в ADR-011) | — |
| pnpm | yarn 1 | 10 (`"packageManager": "pnpm@10.x.y"`, corepack) | `onlyBuiltDependencies` обязателен для `esbuild`, `msw` |
| react, react-dom | 18.3 | 19 | `useRef` требует аргумент; `forwardRef` не нужен; `react-helmet-async` удаляется — `<title>` и `<meta>` рендерятся в компонентах нативно; `@types/react` 19 |
| vite | 5.2 | 7 | `@vitejs/plugin-react` 5, `vite-tsconfig-paths` 5; `base: './'` меняется на `'/'` (SPA с history-роутером) |
| typescript | 5.4 | 5.9; переход на 7.x (нативный компилятор) выполняется только после его поддержки в typescript-eslint, Vitest и `@vitejs/plugin-react` | `erasableSyntaxOnly`, `verbatimModuleSyntax: true` включаются в `tsconfig.json` |
| tailwindcss | 3.4 | 4 | `tailwind.config.cjs` и `postcss.config.cjs` удаляются; `@tailwindcss/vite`; `@import "tailwindcss"` и `@theme` в `src/index.css`; `tailwindcss-animate` → `tw-animate-css`; `@tailwindcss/typography` подключается через `@plugin`; `tailwind-merge` 3 |
| eslint | 8 | 9 (flat config `eslint.config.js`) | `.eslintrc.cjs` удаляется; `typescript-eslint` 8 (единый пакет); `eslint-plugin-import` → `eslint-plugin-import-x`; `eslint-plugin-react-hooks` 5+, `eslint-plugin-jsx-a11y` 6.10+, `eslint-plugin-testing-library` 7, `eslint-plugin-jest-dom` 5.5+, `eslint-plugin-vitest` → `@vitest/eslint-plugin`, `eslint-plugin-playwright` 2, `eslint-plugin-check-file` 2.8+; `eslint-plugin-tailwindcss` → `eslint-plugin-better-tailwindcss`; `eslint-plugin-prettier` удаляется, Prettier запускается отдельно (`prettier --check`) с `eslint-config-prettier` 10 |
| vitest | 2.1 | 3 | `@vitest/coverage-v8` того же мажора; `jsdom` 26; конфигурация тестов остаётся в `vite.config.ts` с `/// <reference types="vitest/config" />` |
| react-router | 7.0 | 7 (library mode, `createBrowserRouter`) | framework mode не используется: нет SSR, статика на Nginx |
| @tanstack/react-query | 5 | 5 | — |
| storybook, @storybook/react-vite | 8.0 | 9 | `npx storybook@latest upgrade`; `addon-essentials` входит в ядро; импорты `@storybook/test` → `storybook/test`; `@storybook/addon-vitest` вместо test-runner |
| msw, @mswjs/data | 2.2 | 2 (не ниже 2.6 — поддержка `ws` для моков WebSocket) | — |
| @playwright/test | 1.49 | 1 (последняя минорная) | добавляются проекты `mobile` и `ar` (раздел 3.7) |
| zod | 3 | 4 | генерируемые orval схемы — zod 4 |
| zustand | 4 | 5 | `vi.mock('zustand')` в `setup-tests.ts` обновляется под мок v5 |
| react-hook-form, @hookform/resolvers | 7, 3 | 7, 5 | — |
| axios | 1 | 1 | — |
| i18next, react-i18next, i18next-browser-languagedetector, i18next-resources-to-backend, i18next-parser | — | 25, 16, 8, 1, 9 | новые |
| orval | — | 7 | новый (devDependency) |
| @faker-js/faker | `@ngneat/falso` 7 | 10 | orval генерирует моки на faker; `falso` удаляется, `src/testing/data-generators.ts` переводится на faker |
| @radix-ui/react-direction | — | 1 | новый (`DirectionProvider`) |
| husky, lint-staged в `src/frontend` | 9, 15 | удаляются | хуки переезжают в корневой `.pre-commit-config.yaml` (ADR-011) |

### 3.2. Порядок миграции (шаги Г.1, каждый — отдельный коммит при зелёных `pnpm lint`, `pnpm check-types`, `pnpm test`, `pnpm build`)

1. **pnpm**: `corepack enable`; `pnpm import` (строит `pnpm-lock.yaml` из `yarn.lock`), удалить `yarn.lock`; добавить в `package.json` `"packageManager"`, `"engines"`, секцию `"pnpm": { "onlyBuiltDependencies": ["esbuild", "msw"] }`; создать `.npmrc`:
   ```ini
   engine-strict=true
   auto-install-peers=true
   strict-peer-dependencies=false
   public-hoist-pattern[]=*eslint*
   public-hoist-pattern[]=*prettier*
   ```
   Заменить `yarn` на `pnpm` в `scripts` (`test-e2e`, `run-mock-server`), в `playwright.config.ts` (`webServer.command`), в README. Проверить, что 21 тест boilerplate проходит.
2. **Сборка и тесты**: TypeScript, Vite 7, `@vitejs/plugin-react`, `vite-tsconfig-paths`, Vitest 3, jsdom, `@vitest/coverage-v8`; `base: '/'`; скрипт `build` → `tsc --noEmit && vite build`.
3. **React 19**: `react`, `react-dom`, `@types/react*`, `@testing-library/react` 16; удалить `react-helmet-async`, заменить компонент `src/components/seo/head.tsx` на нативные `<title>`/`<meta>`; обновить `zustand` 5, `zod` 4, `@hookform/resolvers` 5.
4. **ESLint 9 flat config**: создать `eslint.config.js` (раздел 3.6), удалить `.eslintrc.cjs`; заменить плагины по таблице 3.1; скрипт `lint` → `eslint src`; добавить скрипт `format:check` → `prettier --check .`.
5. **Tailwind 4**: `@tailwindcss/vite`; перенести тему из `tailwind.config.cjs` в `@theme` в `src/index.css`; удалить `postcss.config.cjs`, `autoprefixer`, `postcss`; `tw-animate-css`; `tailwind-merge` 3; все физические классы направления в компонентах `src/components/ui` заменить на логические (раздел 3.4).
6. **Storybook 9+**: `npx storybook@latest upgrade`; декоратор `DirectionProvider` с переключателем `dir` в тулбаре (`.storybook/preview.tsx`, globals `direction: ltr | rtl`).
7. **i18n и RTL** (раздел 3.3, 3.4): `src/lib/i18n/`, `DirectionProvider` в `src/app/provider.tsx`, переключатель языка в лэйауте.
8. **Генерация клиента** (раздел 3.5): `orval.config.ts`, скрипты `api:generate`, `api:check`; первый контракт — `identity` (`/auth/me`, `/auth/login`, `/auth/logout`, `/auth/refresh`); `src/lib/auth.tsx` переписывается на сгенерированный клиент, `react-query-auth` удаляется.
9. **WebSocket-клиент** (раздел 3.5): `src/lib/ws/`, моки через `msw` `ws.link`.
10. **Dockerfile и Nginx** (раздел 3.8), `.env.example` (раздел 3.9), прокси dev-сервера.
11. **Удаление демо-фич** — выполняется в Г.7 после появления app-shell: удаляются `src/features/{auth,comments,discussions,teams,users}`, их роуты в `src/app/routes/app/*`, моки `src/testing/mocks/handlers/*`, `src/testing/mocks/db.ts`, тесты и E2E `e2e/tests/*`; `src/types/api.ts` заменяется сгенерированными типами. До Г.7 демо-фичи остаются образцом стиля и проходят lint и тесты. Для E2E Г.11 «войти тестовым пользователем» экран входа не требуется (экраны входа — этап 2, VIS-05): тест выполняет `POST /api/v1/auth/login` через Playwright `request` и получает cookie (SYS-10 фиксирует фикстуру).

### 3.3. i18n

- Библиотеки: `i18next`, `react-i18next`, `i18next-browser-languagedetector`, `i18next-resources-to-backend`; инициализация — `src/lib/i18n/i18n.ts`; языки `ru`, `en`, `ar`; `supportedLngs: ['ru', 'en', 'ar']`, `nonExplicitSupportedLngs: true` (`ru-RU` → `ru`), `load: 'languageOnly'`.
- Определение языка: `i18next-browser-languagedetector` с порядком источников и ключом хранения, которые задаёт SYS-07 (OQ-25: профиль → явный выбор в `localStorage` ключ `flt.ui_language` → `navigator.languages` → язык по умолчанию). Язык из профиля (STU-06, этап 4) применяется вызовом `i18n.changeLanguage` после загрузки `me`. Хранение выбора в `localStorage` — состояние браузера, а не инстанса (допустимо по CLAUDE.md «Масштабирование и состояние»).
- Структура ресурсов — namespace на модуль, файлы рядом с модулем:
  ```
  src/lib/i18n/
    i18n.ts                      # init, детектор, resources-to-backend
    direction.ts                 # getDirection(lng): 'ltr' | 'rtl'; applyDocumentDirection(lng)
    locales/{ru,en,ar}/common.json   # namespace "common": app-shell, shared components, ошибки
  src/features/<module>/locales/{ru,en,ar}.json   # namespace "<module>" (kebab-case имени модуля)
  src/features/<module>/locales/resources.ts      # export const <module>Resources = { ru: () => import('./ru.json'), en: ..., ar: ... }
  src/app/i18n-resources.ts    # регистрирует namespaces всех модулей: import { identityResources } from '@/features/identity/locales/resources'
  ```
  Shared-слой не знает о модулях: namespaces модулей регистрируются в `src/app/i18n-resources.ts` (слой `app` импортирует `features` — разрешено зонами ESLint). Загрузка ленивая (`import()`), ресурсы попадают в чанк модуля. `i18next-resources-to-backend` получает функцию `(lng, ns) => registry[ns][lng]()`.
- Ключи: английские, вложенные через точку (`login.form.submit`), namespace через двоеточие (`identity:login.form.submit`); хук `useTranslation('identity')` в модуле. Эталонный язык ключей — `ru` (аудитория РФ, OQ-25); `en` и `ar` обязаны содержать те же ключи.
- Контроль полноты: `i18next-parser` (конфиг `i18next-parser.config.ts`, `locales: ['ru','en','ar']`, `keepRemoved: false`); скрипт `i18n:extract` обновляет файлы, `i18n:check` (`i18next-parser --fail-on-update`) падает в CI при неизвлечённых или лишних ключах; пустые значения в `en`/`ar` запрещены (проверка — тот же скрипт с `--fail-on-warnings`).
- Типизация ключей: `src/types/i18next.d.ts` объявляет `CustomTypeOptions.resources` из `ru`-файлов (`common` + все модули) — опечатка в ключе ломает `pnpm check-types`.
- Множественное число: суффиксы i18next v4 (`_zero`, `_one`, `_two`, `_few`, `_many`, `_other`) через `Intl.PluralRules`; интерполяция `{{count}}`. Даты и числа: `Intl.DateTimeFormat`/`Intl.NumberFormat` через `i18next` `interpolation.format`; система счисления для `ar` (`latn` или `arab`) — SYS-07. `dayjs` остаётся для вычислений с датами, локали `ru`, `en`, `ar` подключаются вместе с ресурсами.
- Строки UI вне `t()` запрещены: правило `react/jsx-no-literals` в режиме `noStrings: true, ignoreProps: false, allowedStrings: []` для `src/features/**` и `src/components/**` (исключения — `*.stories.tsx`, `*.test.tsx`, `src/testing/**`).
- Тесты компонентов рендерят с реальными ресурсами `ru` (обёртка `src/testing/test-utils.tsx` инициализирует i18n синхронно с `initImmediate: false`); запросы в тестах — по роли и `aria-label`, не по тексту, где это возможно.

### 3.4. RTL

- Направление задаётся для всего документа: `applyDocumentDirection(lng)` ставит `document.documentElement.dir` (`rtl` для `ar`, иначе `ltr`) и `document.documentElement.lang` при инициализации и на событие `languageChanged`. Текст со смешанным направлением внутри страницы (например, английские примеры в арабском интерфейсе) — `dir="auto"` и `<bdi>` по правилам SYS-07.
- Radix: `<DirectionProvider dir={direction}>` оборачивает приложение в `src/app/provider.tsx`; `direction` берётся из хука `useDirection()` (`src/lib/i18n/use-direction.ts`), подписанного на `languageChanged`.
- Tailwind: только логические утилиты — `ms-*`, `me-*`, `ps-*`, `pe-*`, `start-*`, `end-*`, `inset-s-*`, `inset-e-*`, `text-start`, `text-end`, `rounded-s-*`, `rounded-e-*`, `rounded-ss-*`, `rounded-se-*`, `rounded-es-*`, `rounded-ee-*`, `border-s-*`, `border-e-*`, `scroll-ms-*`, `scroll-me-*`, `scroll-ps-*`, `scroll-pe-*`, `float-start`, `float-end`, `clear-start`, `clear-end`. Варианты `rtl:` и `ltr:` разрешены только для зеркалирования иконок и фоновых изображений (`rtl:-scale-x-100` для `ChevronRight`, `ArrowRight` из lucide).
- Запрет физических классов — локальное правило ESLint `flt/no-physical-direction-classes` (файл `eslint-rules/no-physical-direction-classes.js`, подключается в `eslint.config.js` как плагин `flt`). Правило проверяет строковые литералы и шаблонные строки в атрибуте `className` и в аргументах вызовов `cn(...)`, `cva(...)`, `twMerge(...)` регулярным выражением:
  ```
  (^|[\s:'"`])(-?)(ml|mr|pl|pr|left|right|inset-x|scroll-ml|scroll-mr|scroll-pl|scroll-pr|rounded-l|rounded-r|rounded-tl|rounded-tr|rounded-bl|rounded-br|border-l|border-r)-|(^|[\s:'"`])(text-left|text-right|float-left|float-right|clear-left|clear-right)(\s|$|['"`])
  ```
  Исключение — класс с явным вариантом `ltr:` или `rtl:` (разрешено только внутри `src/components/ui`). Для `.css`-файлов — архитектурный тест `src/testing/architecture/no-physical-direction.test.ts` с тем же выражением плюс свойства `margin-left`, `margin-right`, `padding-left`, `padding-right`, `left:`, `right:`, `text-align: left`, `text-align: right`, `border-left`, `border-right` (разрешены логические `margin-inline-start`, `padding-inline-end`, `inset-inline-start`, `text-align: start`).
- Шрифты для арабской вязи и иероглифов, fallback-цепочки — SYS-07; подключаются в `@theme` (`--font-sans`) и `src/assets/fonts`.
- Storybook: тулбар `direction`; E2E: проект Playwright `ar` (раздел 3.7) делает скриншотные проверки лэйаута app-shell в RTL.

### 3.5. API-слой, генерация клиента и WebSocket

- Базовые адреса относительные: REST `/api/v1` (монолит обслуживает `/api/v1/<module>/...` сам, HAProxy и dev-прокси путь не переписывают — ADR-004, ADR-012), WebSocket `/ws` (ADR-004); `src/config/env.ts`: `API_URL` по умолчанию `/api/v1`, `WS_URL` по умолчанию `/ws`. Dev-сервер Vite проксирует на бэкенд без `rewrite`: `server.proxy = { '/api': { target: 'http://localhost:8000', changeOrigin: false }, '/ws': { target: 'ws://localhost:8000', ws: true }, '^/flt-': { target: 'http://localhost:9000', changeOrigin: false } }` (последнее — path-style запросы к хранилищу по бакетам `flt-<module>`, ADR-007); при `VITE_APP_ENABLE_API_MOCKING=true` вместо прокси работает MSW service worker (`src/testing/mocks/browser.ts`). Маршруты приложения в `src/app/routes` не начинаются с `/api`, `/ws` и `/flt-` — проверяется архитектурным тестом `src/testing/architecture/reserved-paths.test.ts`.
- `src/lib/api-client.ts` (axios) сохраняется как единственный HTTP-клиент: `baseURL: env.API_URL`, `withCredentials: true`, интерсептор запроса добавляет `X-CSRF-Token` из cookie `flt_csrf` (имя и схема — ADR-006) для методов `POST`, `PUT`, `PATCH`, `DELETE`; интерсептор ответа при `401` один раз выполняет `POST /auth/refresh` (single-flight: все параллельные 401 ждут один промис), повторяет запрос, при повторном `401` очищает кэш `me` и переходит на `/auth/login?redirectTo=…`. Ошибки показываются через `useNotifications` только при `error.config.meta.notify !== false`.
- Генерация orval: `orval.config.ts` в `src/frontend` с одной записью на модуль, построенной из списка каталогов `Analytics/Specs/*/api/openapi.yaml`:
  ```ts
  // orval.config.ts (фрагмент)
  export default defineConfig({
    identity: {
      input: '../../Analytics/Specs/identity/api/openapi.yaml',
      output: {
        mode: 'tags-split',
        target: 'src/features/identity/api/generated/client.ts',
        schemas: 'src/features/identity/api/generated/model',
        client: 'react-query',
        httpClient: 'axios',
        mock: { type: 'msw', generateEachHttpStatus: true },
        override: {
          mutator: { path: 'src/lib/api-client.ts', name: 'apiMutator' },
          query: { useQuery: true, useInfinite: true, signal: true },
        },
      },
    },
    'identity-zod': {
      input: '../../Analytics/Specs/identity/api/openapi.yaml',
      output: { client: 'zod', target: 'src/features/identity/api/generated/zod.ts' },
    },
  });
  ```
  Сгенерированный код коммитится (`src/features/<module>/api/generated/**`), исключается из ESLint, Prettier и покрытия; скрипт `api:generate` = `orval`, `api:check` = `orval && git diff --exit-code -- 'src/**/generated/**'` выполняется в CI, чтобы код не расходился с контрактом. Шаблон ТЗ (раздел «Контракты») ссылается на эту команду. Ручные обёртки над сгенерированными хуками (ключи запросов, инвалидация) лежат в `src/features/<module>/api/*.ts`, как в `docs/api-layer.md`.
- Моки: сгенерированные MSW-обработчики (`*.msw.ts`, faker с фиксированным `seed`) подключаются в `src/testing/mocks/handlers/<module>.ts`, где при необходимости дополняются состоянием на `@mswjs/data`; `mock-server.ts` (Express + `@mswjs/http-middleware`) остаётся для E2E на mock-сервере.
- WebSocket-клиент — shared-слой `src/lib/ws/`:
  ```
  src/lib/ws/ws-client.ts        # класс WsClient: connect(), close(), send(msg), subscribe(type, schema, handler) → unsubscribe
  src/lib/ws/use-ws-subscription.ts  # хук useWsSubscription(type, schema, handler) с автоотпиской
  src/lib/ws/envelope.ts         # zod-схема конверта из ADR-004 (type, correlation_id, channel, seq, ts, payload); бинарные кадры — заголовок 9 байт (тип, stream_id, seq)
  src/lib/ws/backoff.ts          # экспоненциальная задержка 500 мс × 2^n, максимум 30 с, jitter ±20 %
  ```
  Одно соединение на вкладку, создаётся после успешного `me` и закрывается при выходе; аутентификация — cookie при handshake (ADR-006); переподключение по `backoff.ts` с повторной аутентификацией и переподпиской на каналы, после чего состояние каждого канала перечитывается по его REST-эндпоинту (ADR-004); незавершённый стрим LLM не возобновляется — клиент показывает частичный ответ с `interrupted = true` и предлагает повторить (ADR-009); heartbeat и коды закрытия — ADR-004; при `close 4401` (ADR-006, отзыв сессии) клиент вызывает refresh и переподключается один раз, затем переходит на экран входа. Входящие сообщения валидируются zod-схемой подписки; невалидные логируются и отбрасываются, счётчик отдаётся в консоль dev-режима.
- Типы сообщений WebSocket генерируются из `Analytics/Specs/<module>/api/asyncapi.yaml` скриптом `scripts/asyncapi-to-zod.ts` (`@asyncapi/parser` → JSON Schema каждого message payload → `json-schema-to-zod`) в `src/features/<module>/ws/generated/messages.ts`: `export const LlmStreamDeltaSchema = z.object({...}); export type LlmStreamDelta = z.infer<typeof LlmStreamDeltaSchema>;`. Скрипт входит в `api:generate` и `api:check`.
- Моки WebSocket в тестах и E2E — `msw` `ws.link(env.WS_URL)`: обработчики в `src/testing/mocks/ws/<module>.ts` отправляют сообщения по сценарию теста (пример для Г.11 — стрим `start/delta/end` заглушки LLM, ADR-009).

### 3.6. Границы модулей и правила ESLint

`eslint.config.js` (flat config, ESM). Зоны строятся автоматически из списка каталогов `src/features/*`, чтобы новый модуль получал зону без правки конфига:

```js
import fs from 'node:fs';
const features = fs.readdirSync('src/features', { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name);
const featureZones = features.map(name => ({
  target: `./src/features/${name}`,
  from: './src/features',
  except: [`./${name}`],
  message: `Модуль ${name} не импортирует другие модули: связывание только в src/app`,
}));
export default [
  { ignores: ['dist', 'node_modules', 'public/mockServiceWorker.js', 'generators', 'storybook-static', '**/generated/**'] },
  // ... конфиги typescript-eslint, react, react-hooks, jsx-a11y, import-x, testing-library, jest-dom, vitest, playwright, better-tailwindcss, prettier
  { rules: {
      'import-x/no-restricted-paths': ['error', { zones: [
        ...featureZones,
        { target: './src/features', from: './src/app' },
        { target: ['./src/components', './src/hooks', './src/lib', './src/types', './src/utils', './src/config'], from: ['./src/features', './src/app'] },
      ] }],
      'import-x/no-cycle': ['error', { maxDepth: Infinity }],
      'check-file/filename-naming-convention': ['error', { '**/*.{ts,tsx}': 'KEBAB_CASE' }, { ignoreMiddleExtensions: true }],
      'check-file/folder-naming-convention': ['error', { 'src/**/!(__tests__)': 'KEBAB_CASE' }],
      'check-file/filename-blocklist': ['error', { 'src/features/**/index.{ts,tsx}': '*.ts', 'src/{components,hooks,lib,utils,types,config}/**/index.{ts,tsx}': '*.ts' }],
      'flt/no-physical-direction-classes': 'error',
      'react/jsx-no-literals': ['error', { noStrings: true, ignoreProps: false }],
  } },
];
```

- Barrel-файлы запрещены правилом `check-file/filename-blocklist` на `index.ts(x)` в модулях и shared-слое (единственный допустимый `index.tsx` — `src/app/index.tsx`); импорт — напрямую из файла через `@/`.
- Негативный архитектурный тест Г.2: файл `src/features/__fixtures__/boundary-violation.tsx` с импортом из другого модуля должен давать ошибку `eslint` (проверяется в `src/testing/architecture/eslint-boundaries.test.ts` через `ESLint` API) — критерий выхода этапа 1 «нарушение границы ломает сборку».
- Общий код между модулями не допускается: если двум модулям нужен один компонент, он переезжает в `src/components` без бизнес-логики или дублируется.

### 3.7. Тесты и порог покрытия

- Уровни — как в CLAUDE.md: unit и компоненты (Vitest + Testing Library + MSW), модульные тесты с моками REST и WebSocket по контракту, E2E (Playwright). Имя теста или `describe` содержит ID критерия приёмки (`VIS-05-AC2`).
- Порог покрытия (Vitest `coverage.thresholds`, провайдер `v8`): `lines: 70`, `statements: 70`, `functions: 70`, `branches: 60` для `include: ['src/features/**', 'src/lib/**', 'src/components/**', 'src/hooks/**', 'src/utils/**']`, `exclude: ['**/generated/**', '**/*.stories.tsx', '**/*.test.{ts,tsx}', 'src/testing/**', 'src/types/**', 'src/app/**', '**/locales/**']`. `src/app/routes` исключён, так как страницы покрывает E2E. Значения подтверждены пользователем 2026-10-10. Обоснование числа: 70 % строк ниже backend-порога 75 % на величину презентационного кода без логики (разметка, варианты `cva`), который дешевле проверять E2E и Storybook; как и для backend, порог можно повышать и нельзя понижать (`fail_under`-аналог — `thresholds`, падение сборки). Порог проверяется скриптом `test:cov` в CI (SYS-12, ADR-011).
- Playwright: проекты `chromium-desktop` (`Desktop Chrome`), `chromium-mobile` (`Pixel 7`), `ar` (`Desktop Chrome`, `locale: 'ar'`, проверяет `html[dir=rtl]` и скриншоты лэйаута); сценарии Г.11 выполняются на стенде из N инстансов (SYS-10), демо-E2E boilerplate удаляются в Г.7.
- Storybook собирается в CI (`build-storybook`) как проверка компонентов; `@storybook/addon-a11y` сохраняется.

### 3.8. Сборка, Dockerfile, Nginx

- Одна production-сборка для всех стендов: в сборку встраивается только `VITE_APP_ENABLE_API_MOCKING=false`; адреса — относительные.
- `src/frontend/Dockerfile` (контекст сборки — корень репозитория, как у backend `make docker-build`):
  ```dockerfile
  FROM node:24-alpine AS build
  RUN corepack enable
  WORKDIR /app
  COPY src/frontend/package.json src/frontend/pnpm-lock.yaml src/frontend/.npmrc ./
  RUN pnpm install --frozen-lockfile
  COPY src/frontend/ ./
  COPY Analytics/Specs ../Analytics/Specs
  RUN pnpm api:check && pnpm build

  FROM nginxinc/nginx-unprivileged:1.28-alpine
  COPY deploy/config/nginx/frontend.conf /etc/nginx/conf.d/default.conf
  COPY --from=build /app/dist /usr/share/nginx/html
  EXPOSE 8080
  ```
  Образ — `flt-frontend`. Контракты копируются для `api:check`, чтобы образ не собрался из устаревшего клиента.
- `deploy/config/nginx/frontend.conf` — только статика и SPA fallback, без прокси `/api` и `/ws` (они идут через HAProxy, ADR-012):
  ```nginx
  server {
    listen 8080;
    root /usr/share/nginx/html;
    index index.html;
    gzip on; gzip_types text/css application/javascript application/json image/svg+xml;
    location /assets/ { add_header Cache-Control "public, max-age=31536000, immutable"; try_files $uri =404; }
    location = /index.html { add_header Cache-Control "no-cache"; }
    location / { try_files $uri $uri/ /index.html; }
    location = /healthz { return 200 'ok'; add_header Content-Type text/plain; }
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
  }
  ```
  `Content-Security-Policy` задаёт Nginx в этом же файле (ADR-012 закрепляет CSP за ADR-005, так как политика зависит от сборки frontend); HSTS, `X-Frame-Options`, `Permissions-Policy` ставит HAProxy (ADR-012). Стартовая политика для HTML-ответов (`location = /index.html`):
  ```
  Content-Security-Policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
  ```
  Обоснование: сборка Vite не содержит inline-скриптов (`<script type="module" src>`), поэтому `script-src` без хэшей; `'wasm-unsafe-eval'` нужен для VAD в WASM на этапе 5 (ADR-009); `'unsafe-inline'` в `style-src` — для inline-атрибутов `style` компонентов Radix (нонсы к атрибутам неприменимы); `connect-src 'self'` покрывает `/api` и `/ws` того же origin; `media-src blob:` — воспроизведение аудио TTS; файлы хранилища отдаются с того же origin по путям `/flt-*` (ADR-007, ADR-012), поэтому покрываются `'self'` и отдельных источников не требуют. Любое расширение политики фиксируется в ТЗ, которое его требует. Один и тот же файл используется в docker-compose (копируется в образ) и в Helm (тот же образ; переопределение через ConfigMap — SYS-11). Healthcheck контейнера — `GET /healthz`.

### 3.9. Переменные окружения

`src/frontend/.env.example`:
```ini
# Относительные адреса: один и тот же build на всех стендах, маршрутизация через HAProxy (ADR-012)
VITE_APP_API_URL=/api/v1
VITE_APP_WS_URL=/ws
# Моки MSW в браузере вместо бэкенда (только dev)
VITE_APP_ENABLE_API_MOCKING=false
# Адрес бэкенда для dev-прокси Vite (не попадает в сборку)
VITE_DEV_BACKEND_URL=http://localhost:8000
```
`.env.example-e2e` — то же с `VITE_APP_ENABLE_API_MOCKING=true` и `VITE_APP_APP_URL=http://localhost:3000`. Переменные `APP_URL`, `APP_MOCK_API_PORT` из `src/config/env.ts` сохраняются для mock-сервера.

## 4. Последствия

### 4.1. Положительные

- Все десять «Отличий проекта от boilerplate» фронтенда получают конкретную реализацию и порядок выполнения.
- Контракты OpenAPI и AsyncAPI становятся единственным источником клиента, схем валидации, моков и типов сообщений; расхождение ловит `api:check` в CI.
- i18n и RTL встроены в каркас до первого экрана FLT: новый модуль получает namespace и зону ESLint автоматически.
- Один и тот же образ `flt-frontend` работает на всех стендах; Nginx не знает о бэкенде.
- Структура «модуль = каталог с api, locales, ws, components» позволяет вынести модуль в микрофронтенд вместе с его ресурсами.

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Разовая миграция в Г.1 (11 шагов) до начала кода FLT | Каждый шаг — отдельный коммит с зелёными `lint`, `check-types`, `test`, `build`; порядок зафиксирован в 3.2 |
| `eslint-plugin-better-tailwindcss` и собственное правило `flt/*` — две разные проверки классов | Локальное правило покрывает только направление; остальное — плагин; оба в `eslint.config.js`, тесты правила в `eslint-rules/__tests__` |
| Сгенерированный код в репозитории увеличивает диффы | Каталоги `generated/` исключены из lint, Prettier, покрытия и ревью-диффа (`.gitattributes` `linguist-generated`) |
| `react/jsx-no-literals` требует `t()` даже для символов и чисел | Допускаются `{' '}`, числа и знаки пунктуации через `allowedStrings`, список фиксируется в `eslint.config.js` |
| Строгий `node_modules` pnpm и `onlyBuiltDependencies` могут потребовать правок при добавлении зависимостей | Правила в `.npmrc` и `package.json` описаны в 3.2 шаг 1; ошибки видны при `pnpm install` локально и в CI |
| Порог 70 % ниже backend-порога | Порог только повышается; `src/app/routes` покрывается E2E; пересмотр на ревью каждого этапа |
| Мажорная версия моложе 60 дней не берётся | Правило 3.1 защищает от несовместимости плагинов; актуализация раз в этап |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Выполнить шаги 1–10 раздела 3.2 | `src/frontend` (этап 1 Г.1) | Claude | не начато |
| Удалить демо-фичи, их моки, тесты и роуты (шаг 11) | `src/frontend/src/features/*`, `src/testing/mocks`, `e2e/tests` (этап 1 Г.7) | Claude | не начато |
| Переписать раздел «Frontend (boilerplate)»: pnpm вместо yarn в описании и в «Командах», ссылка на ADR-005, снять TODO из «Отличий» | CLAUDE.md, разделы «Frontend (boilerplate)», «Отличия проекта от boilerplate» (frontend), «Команды» | Claude после accepted | не начато |
| Добавить в «Модульный монолит → Frontend» правила: автоматические зоны ESLint, запрет `index.ts`, locales и ws на модуль, запрет физических классов направления | CLAUDE.md, «Модульный монолит → Frontend» | Claude после accepted | не начато |
| Контейнер Nginx: образ `flt-frontend`, порт 8080, healthcheck `/healthz`; конфигурация `deploy/config/nginx/frontend.conf` | `deploy/docker-compose/docker-compose.yml` и `deploy/helm` одновременно (этап 1 Г.8), SYS-11 | Claude | не начато |
| Зафиксировать порядок определения языка, ключ `localStorage`, язык по умолчанию, шрифты, систему счисления `ar`, правила `dir="auto"` и `<bdi>` | SYS-07 (OQ-25) | Claude (черновик), человек (G1) | не начато |
| Зафиксировать путь WebSocket (`/ws`), конверт сообщения, heartbeat, коды закрытия; `resume_token`/`last_seq` — только для событий, не для дельт стрима (ADR-009) | ADR-004 (сделано в 0.2), SYS-04 | Claude | ADR — сделано; SYS-04 — не начато |
| Зафиксировать имена cookie, заголовок `X-CSRF-Token`, поведение при 401 и код закрытия WebSocket при отзыве сессии | ADR-006 | Claude | сделано в черновике ADR-006 |
| Маршруты `/api/*` и `/ws/*` без переписывания пути, `/flt-*` → MinIO | ADR-012 | Claude | сделано в 0.2 |
| Единый pre-commit в корне репозитория с хуком `pnpm --dir src/frontend lint-staged`; удалить husky из `src/frontend` | ADR-011, SYS-12, `.pre-commit-config.yaml` (этап 1 Г.1) | Claude | не начато |
| Добавить в CI: `pnpm install --frozen-lockfile`, `lint`, `format:check`, `check-types`, `i18n:check`, `api:check`, `test:cov` с порогом, `build`, `build-storybook`, Playwright-проекты `chromium-desktop`, `chromium-mobile`, `ar` | SYS-12, ADR-011 (имена приведены в 0.2; workflow — этап 1 Г.10) | Claude | ADR-011 — сделано; SYS-12 и workflow — не начато |
| Описать фикстуру входа тестового пользователя через `POST /api/v1/auth/login` для E2E Г.11, стенд N инстансов для Playwright | SYS-10 | Claude | не начато |
| Добавить в шаблон ТЗ, раздел «Контракты», указание: после изменения `openapi.yaml`/`asyncapi.yaml` выполнить `pnpm api:generate`; в раздел «UI» — namespace i18n модуля и проверка RTL | `Analytics/Specs/_templates/feature-spec.md` | Claude после accepted | не начато |
| Описать app-shell: провайдеры (`DirectionProvider`, i18n, QueryClient, WsClient), лэйаут, переключатель языка, регистрация namespaces модулей | `Analytics/Specs/app_shell/_module.md` (этап 1 В) | Claude | не начато |
| Уточнить формулировку А.5 (pnpm выбран) и Г.1 (ссылка на шаги 3.2) | `Analytics/BRD/SDD_plan.md`, этап 1 | Claude после accepted | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-001](ADR-001-tech-stack.md) | зависит от | политика «последние стабильные версии»; здесь она конкретизирована правилом 60 дней для frontend |
| [ADR-004](ADR-004-communication-patterns.md) | зависит от | конверт сообщений WebSocket, heartbeat, переподключение — клиент в `src/lib/ws` реализует их |
| [ADR-006](ADR-006-authentication-and-authorization.md) | зависит от | cookie + `X-CSRF-Token`, refresh при 401, код закрытия 4401 |
| [ADR-007](ADR-007-file-storage.md) | дополняет | dev-прокси `/flt-*`, запрет маршрутов приложения с префиксом `/flt-`, источники CSP для файлов хранилища |
| [ADR-009](ADR-009-llm-streaming-and-voice.md) | дополняет | сообщения стрима LLM — первая подписка WebSocket-клиента (Г.6, Г.11); бинарные аудио-кадры (этап 5) |
| [ADR-011](ADR-011-ci-cd.md) | ограничен | pre-commit на уровне репозитория, состав job-ов CI, имена скриптов `api:check`, `test:cov`, `format:check`, `i18n:check`, `build-storybook` |
| [ADR-012](ADR-012-haproxy-entry-point.md) | зависит от | маршруты `/api`, `/ws` без переписывания, `/flt-*` → MinIO, остальное → Nginx |
| [SYS-02](../Specs/_system/SYS-02-non-functional-requirements.md) | ограничен | требования к заголовкам безопасности; CSP реализована в `frontend.conf` (3.8) |
| [SYS-03](../Specs/_system/SYS-03-rest-api-conventions.md) | зависит от | формат OpenAPI, из которого генерирует orval |
| [SYS-04](../Specs/_system/SYS-04-async-messaging.md) | зависит от | AsyncAPI, из которого генерируются zod-схемы сообщений |
| [SYS-07](../Specs/_system/SYS-07-i18n-and-rtl.md) | дополняет | SYS-07 задаёт порядок определения языка, шрифты, форматы; ADR-005 — механизм |
| [SYS-10](../Specs/_system/SYS-10-test-strategy.md) | дополняет | порог покрытия 70 %, проекты Playwright, фикстура входа |
| [SYS-11](../Specs/_system/SYS-11-deployment-and-environments.md) | дополняет | контейнер Nginx `flt-frontend` |
| [SYS-12](../Specs/_system/SYS-12-ci-cd-and-quality.md) | дополняет | job-ы CI frontend |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Решение пользователя 2026-10-10: порог покрытия 70 % lines/functions/statements, 60 % branches, `src/app/routes` исключены. Согласование с ADR-012 и ADR-004 (без переписывания `/api` → `/v1`, путь `/ws`, поля конверта `channel` и `ts`), ADR-007 (dev-прокси `/flt-*`, запрет маршрутов с этим префиксом), ADR-011 (имена скриптов CI) | proposed |
| 1.0 | 2026-10-10 | пользователь | Принят без изменений (PR #2, слияние в main) | accepted |
