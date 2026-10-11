# FLT frontend

React-приложение FLT на основе [bulletproof-react](https://github.com/alan2207/bulletproof-react) (`apps/react-vite`, лицензия MIT — `LICENSE`).
Стек, версии и правила — ADR-005 (`Analytics/ADR/ADR-005-frontend-stack.md`), архитектура — `docs/`.

## Начало работы

Требования:

- Node.js 24 LTS (`.nvmrc`)
- pnpm 10 через Corepack (`corepack enable`; версия задана полем `packageManager` в `package.json`)

```bash
cd src/frontend
cp .env.example .env
corepack enable
pnpm install
```

## Команды

| Команда | Что делает |
|---|---|
| `pnpm dev` | dev-сервер на порту 3000 |
| `pnpm build` | production-сборка в `dist/` |
| `pnpm lint` | ESLint |
| `pnpm check-types` | проверка типов |
| `pnpm test` | Vitest |
| `pnpm test-e2e` | Playwright на mock-сервере |
| `pnpm storybook` | Storybook на порту 6006 |
