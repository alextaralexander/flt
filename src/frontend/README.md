# FLT frontend

React-приложение FLT на основе [bulletproof-react](https://github.com/alan2207/bulletproof-react) (`apps/react-vite`, лицензия MIT — `LICENSE`).
Стек, версии и правила — ADR-005 (`Analytics/ADR/ADR-005-frontend-stack.md`), i18n и RTL — SYS-07, архитектура — `docs/`.

## Начало работы

Требования:

- Node.js 24 LTS (`.nvmrc`)
- pnpm 10 через Corepack (`corepack enable`; версия задана полем `packageManager` в `package.json`)

```bash
cd src/frontend
cp .env.example .env   # необязательно: значения по умолчанию — относительные /api/v1 и /ws
corepack enable
pnpm install
```

Адреса бэкенда относительные (`/api/v1`, `/ws`, файлы — `/flt-*`): одна сборка работает на всех стендах.
Dev-сервер проксирует `/api` и `/ws` на `VITE_DEV_BACKEND_URL`, `/flt-*` — на `VITE_DEV_STORAGE_URL`;
при `VITE_APP_ENABLE_API_MOCKING=true` запросы перехватывает MSW в браузере.

## Команды

| Команда                | Что делает                                                                      |
| ---------------------- | ------------------------------------------------------------------------------- |
| `pnpm dev`             | dev-сервер на порту 3000                                                        |
| `pnpm build`           | `tsc --noEmit` и production-сборка в `dist/`                                    |
| `pnpm lint`            | ESLint 9 (flat config, зоны модулей, правила `flt/*`)                           |
| `pnpm format:check`    | Prettier                                                                        |
| `pnpm check-types`     | проверка типов                                                                  |
| `pnpm test`            | Vitest (проекты `app` и `tooling`)                                              |
| `pnpm test:cov`        | Vitest с порогом покрытия 70/60 (ADR-005, 3.7)                                  |
| `pnpm i18n:extract`    | извлечь ключи i18n в `locales` (i18next-cli)                                    |
| `pnpm i18n:check`      | полнота переводов `ru`, `en`, `ar` (SYS-07-R10)                                 |
| `pnpm api:generate`    | клиент, zod-схемы и MSW-моки из `Analytics/Specs/*/api/{openapi,asyncapi}.yaml` |
| `pnpm api:check`       | то же и проверка, что сгенерированный код не устарел                            |
| `pnpm check`           | lint, format:check, check-types, i18n:check, api:check, test:cov, build         |
| `pnpm test-e2e`        | Playwright: `chromium-desktop`, `chromium-mobile`, `ar`                         |
| `pnpm storybook`       | Storybook на порту 6006 (тулбар: язык и направление)                            |
| `pnpm build-storybook` | сборка Storybook                                                                |

## Образ

```bash
# из корня репозитория
docker build -f src/frontend/Dockerfile -t flt-frontend .
```

Nginx (`deploy/config/nginx/frontend.conf`): статика, SPA fallback, CSP, `/healthz`, порт 8080.
