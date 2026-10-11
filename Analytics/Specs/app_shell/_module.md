# app_shell — Frontend app-shell и shared-слой

| Поле | Значение |
|---|---|
| Статус | approved |
| Версия | 1.0 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-11 (PR #4) |
| Пункт(ы) BRD | все (каркас интерфейса; собственных пунктов BRD нет); STU-06 (переключатель языка интерфейса — часть app shell) |
| Модуль | app_shell (код — `src/frontend/src/app` и shared-слой `components`, `hooks`, `lib`, `utils`, `types`, `config`, `testing`) |
| Зависимости | backend-модули через контракты: `identity` (вход, `/me`), `llm_gateway` (стрим для E2E этапа 1); shared kernel (конверт ошибок, `/ws`) |
| Связанные ADR/SYS | ADR-004, ADR-005, ADR-006, ADR-012; SYS-02, SYS-03, SYS-04, SYS-05, SYS-06, SYS-07, SYS-09, SYS-10, SYS-11, SYS-12 |

## 1. Назначение и границы

- **Отвечает за**: оболочку frontend-приложения и общий слой без бизнес-логики (ADR-005, CLAUDE.md «Frontend»): точку входа, провайдеры (`DirectionProvider`, i18n, `QueryClient`, `WsClient`, аутентификация), роутер и лэйаут, регистрацию namespace i18n модулей (`src/app/i18n-resources.ts`), подключение feature-модулей на уровне роутов, общий HTTP-клиент `src/lib/api-client.ts`, клиент WebSocket `src/lib/ws`, слой аутентификации `src/lib/auth.tsx`, i18n и RTL `src/lib/i18n`, UI-кит `src/components/ui` (обёртки Radix, `<Icon>`, `<Bidi>`, переключатель языка), реестр UI-слотов `src/lib/extension-points` (SYS-09), отображение прав пользователя, общие страницы ошибок, тестовую инфраструктуру `src/testing`, архитектурные тесты фронтенда, ESLint-правила `flt/*`, сборку и раздачу (`Dockerfile`, Nginx `frontend.conf`).
- **Ключевые сущности**: язык интерфейса (`ui_language`), направление письма, слот UI (`slot`), вклад в слот, ID запроса (`request_id`).
- **Появляется на этапе**: 1 (Г.1 — миграция boilerplate по ADR-005, раздел 3.2, шаги 1–10; Г.7 — app-shell и удаление демо-фич, шаг 11; Г.11 — сквозной E2E).
- **Не отвечает за**:
  - экраны и логику доменных модулей — модули `src/features/<module>` (каждый со своим `_module.md`, раздел 11);
  - wizard STU-32 и TCH-09 как бизнес-сценарии — композиции страниц в `src/app/routes` по ТЗ этих пунктов (SYS-01, раздел 4); app shell даёт только каркас маршрутов;
  - права пользователя — сервер (`identity`, SYS-06-R9): интерфейс только скрывает недоступное по списку `permissions` из `/me`;
  - тексты CMS-страниц — модуль `cms`.

## 2. Пункты BRD и ТЗ модуля

Собственных пунктов BRD у app shell нет: объём этапа 1 задаёт SDD_plan.md, этап 1, Г.1, Г.7, Г.11, требования — ADR-005 и SYS (раздел 4 каждой SYS, строки «frontend», «app shell»). Тесты помечаются ID требований SYS (SYS-10).

| ID | Пункт BRD | ТЗ | Этап | Статус ТЗ |
|---|---|---|---|---|
| — | Каркас интерфейса: язык, RTL, вход, стрим, слоты | нет ТЗ фичи: объём — SDD_plan.md, этап 1, Г.1, Г.7, Г.11; требования — ADR-005, SYS-07, SYS-09 | 1 | не начато |
| STU-06 | Язык интерфейса | ТЗ этапа 4 (модуль `learner_profile` или app shell; сохранение в профиль — `identity`); переключатель и детектор — этап 1 | 1, 4 | не начато |
| VIS-01 | Стартовая страница портала | ТЗ в модуле `cms` (этап 2); лэйаут и навигация — app shell | 2 | не начато |
| STU-32, TCH-09 | Wizard настройки | ТЗ этапов 4 и 6; маршруты — `src/app/routes` | 4, 6 | не начато |

## 3. Публичный API

Публичный API app shell — модули shared-слоя, которые разрешено импортировать feature-модулям через `@/` (barrel-файлы запрещены, импорт напрямую из файла — ADR-005, раздел 3.6). Shared-слой не импортирует `src/features` и `src/app`.

### 3.1. Сервисные интерфейсы

| Интерфейс | Метод | Назначение | Кто вызывает |
|---|---|---|---|
| `src/lib/api-client.ts` | `apiClient` (axios), `apiMutator<T>(config): Promise<T>` | единственный HTTP-клиент: `baseURL` `/api/v1`, `withCredentials`, заголовок `X-CSRF-Token` из cookie `__Host-flt_csrf` для `POST`, `PUT`, `PATCH`, `DELETE` (ADR-006, раздел 3.4), один single-flight `POST /api/v1/auth/refresh` при `401` и повтор, разбор `ErrorResponseV1`, обработка не-JSON `413`, `429`, `503`, предупреждение по `Deprecation` (SYS-03, раздел 4) | клиенты, сгенерированные orval для всех модулей |
| `src/lib/ws/ws-client.ts` | `WsClient`: `connect()`, `subscribe(channel, handler) -> Unsubscribe`, `send(type, payload, channel?)`, события `open`, `close`, `reconnect` | одно соединение `/ws` на вкладку, конверт `WsEnvelope`, переподключение 1–30 с с джиттером, поведение по кодам закрытия, переподписка и перечитывание состояния по `state_url` (SYS-04-R10, R12; SYS-05-R25) | feature-модули через хук |
| `src/lib/ws/use-ws-subscription.ts` | `useWsSubscription(channel, handler, options)` | подписка компонента на канал с автоматической отпиской | feature-модули |
| `src/lib/auth.tsx` | `useUser()`, `useLogin()`, `useLogout()`, `AuthLoader`, `ProtectedRoute`, `useHasPermission(code)` | аутентификация браузера на httpOnly-cookie поверх клиента `identity` (те же имена хуков, что у `react-query-auth`, ADR-005, раздел 3.2, п. 7); права из `GET /api/v1/auth/me` только для отображения (SYS-06-R9) | `src/app`, feature-модули |
| `src/lib/i18n/i18n.ts` | `initI18n()`, `changeLanguage(code)`, `useTranslation(ns)` | i18next: детектор по порядку профиль → cookie `flt_ui_language` → `navigator.languages` → `ru` (SYS-07-R3), ленивые namespace модулей, `fallbackLng` (SYS-07-R10) | `src/app`, feature-модули |
| `src/lib/i18n/direction.ts` | `directionOf(code) -> "ltr" \| "rtl"`, `applyDocumentDirection(code)` | `dir` и `lang` на `<html>` (SYS-07-R16) | `src/app/provider.tsx` |
| `src/lib/i18n/format.ts` | `formatNumber`, `formatDate`, `formatRelativeTime`, `formatList` | форматирование только через `Intl` с локалью интерфейса и часовым поясом пользователя (SYS-07-R19, R21) | feature-модули |
| `src/lib/i18n/cookie.ts` | `readUiLanguageCookie()`, `writeUiLanguageCookie(code)` | cookie `flt_ui_language` (SYS-07-R6) | переключатель языка |
| `src/lib/extension-points/slots.ts` | `SLOT_IDS`, `registerSlotContribution(slotId, contribution)`, `<ExtensionSlot id context fallback>` | UI-слоты этапа 1: `app.header.actions`, `app.nav.items`, `app.user_menu.items`, `settings.sections` (SYS-09-R5, R6) | `src/app/extensions.ts`, страницы |
| `src/components/ui/icon.tsx` | `<Icon name>` | иконки lucide с зеркалированием по `RTL_MIRRORED_ICONS` (SYS-07-R18, OQ-82) | feature-модули |
| `src/components/ui/bidi.tsx` | `<Bidi lang>` | изоляция текста другого направления и атрибут `lang` (SYS-07-R20, R23) | feature-модули |
| `src/components/ui/language-switcher.tsx` | `<LanguageSwitcher>` | переключатель языка интерфейса; первый вклад в слот `app.header.actions` (SYS-09) | `src/app/extensions.ts` |

### 3.2. Pydantic-схемы

Не применимо: frontend-модуль. Типы и zod-схемы общих компонентов генерируются из `Analytics/Specs/_system/openapi-common.yaml` (`ErrorResponseV1`) и `asyncapi-common.yaml` (`WsEnvelope`) в `src/lib/api-types/generated/` и `src/lib/ws/generated/` (ADR-005, раздел 3.5).

### 3.3. События

Не применимо: frontend-модуль не публикует событий Kafka. Внутренние события приложения передаются через состояние React и TanStack Query.

## 4. Зависимости

### 4.1. От каких модулей зависит

| Модуль | Что используется | Способ | Зачем |
|---|---|---|---|
| `identity` (backend) | `POST /api/v1/auth/login`, `/refresh`, `/logout`, `GET /api/v1/auth/me` | REST через сгенерированный клиент `src/features/identity/api/generated` | аутентификация и права для отображения |
| shared kernel (backend) | конверт `ErrorResponseV1`, эндпоинт `/ws`, `ws.*` | REST и WebSocket по общим контрактам | разбор ошибок, соединение WebSocket |
| `llm_gateway` (backend) | канал `llm_gateway.stream` | WebSocket через `WsClient` | сквозной E2E этапа 1 (стрим заглушки) |

### 4.2. Кто зависит от модуля

| Модуль | Что использует | Способ |
|---|---|---|
| все feature-модули `src/features/*` | раздел 3.1 | импорт `@/lib/*`, `@/components/*`, `@/hooks/*`, `@/utils/*` |
| `src/app/routes` | лэйаут, `ProtectedRoute`, слоты | импорт |

## 5. Владение данными

Не применимо: frontend-модуль. Данные пользователя хранит сервер; в браузере — только cookie (`__Host-flt_access`, `flt_refresh`, `__Host-flt_csrf` — httpOnly, кроме CSRF; `flt_ui_language` — выбор языка) и кэш TanStack Query в памяти вкладки.

### 5.1. PostgreSQL

Не применимо: frontend-модуль.

### 5.2. Redis

Не применимо: frontend-модуль.

### 5.3. MinIO

Не применимо: frontend-модуль; загрузку файлов по presigned URL выполняют feature-модули через `/flt-*` (ADR-007).

### 5.4. OpenSearch

Не применимо: frontend-модуль.

### 5.5. Qdrant

Не применимо: frontend-модуль.

## 6. События Kafka

Не применимо: frontend-модуль.

### 6.1. Публикуемые топики

Не применимо: frontend-модуль.

### 6.2. Потребляемые топики

Не применимо: frontend-модуль.

## 7. REST-роутер и WebSocket-обработчики

### 7.1. REST

Не применимо: frontend-модуль. Адреса бэкенда относительные: `/api/v1`, `/ws`, файлы — `/flt-*`; маршруты приложения с этими префиксами запрещены (архитектурный тест `reserved-paths`, ADR-005). Dev-сервер Vite проксирует `/api`, `/ws`, `/flt-*` на `VITE_DEV_BACKEND_URL` без переписывания пути.

### 7.2. WebSocket

App shell — клиент, а не обработчик. Служебные сообщения, которые обрабатывает `WsClient`:

| Тип сообщения | Направление | Схема | Канал Redis pub/sub | Описан в ТЗ |
|---|---|---|---|---|
| `ws.subscribe`, `ws.unsubscribe` | клиент → сервер | `WsSubscribePayload` | — | SYS-04-R6 |
| `ws.ack`, `ws.error` | сервер → клиент | `WsAckPayload` (`state_url`), `WsErrorPayload` | — | SYS-04-R6 |
| `ws.ping`, `ws.pong` | клиент ↔ сервер, каждые 30 с | `WsPingPayload` | — | SYS-04-R11 |
| `identity.session.revoked` | сервер → клиент | `SessionRevokedMessage` | — | спецификация `identity`, раздел 7.2 |

Поведение по кодам закрытия (SYS-04-R10, R12): `1012` — немедленное переподключение; `4401` — переподключение после успешного `refresh`, при неуспехе — выход на `/auth/login`; `4429` — сообщение «закройте лишние вкладки» и переподключение через 10 с; `1008` — переподключение не раньше чем через 30 с; `1009`, `1011`, `1013` — экспоненциальная задержка 1–30 с с полным джиттером, состояние каналов — по REST; `1000` — без переподключения.

## 8. Секция настроек

Переменные сборки `VITE_APP_*` (ADR-005, раздел 3.9); одна сборка работает на всех стендах, значения от стенда не зависят (SYS-11, раздел 4).

| Переменная | Тип | По умолчанию | Секрет | Назначение |
|---|---|---|---|---|
| `VITE_APP_API_URL` | str | `/api/v1` | нет | базовый адрес REST |
| `VITE_APP_WS_URL` | str | `/ws` | нет | адрес WebSocket |
| `VITE_APP_ENABLE_API_MOCKING` | bool | `false` (`true` в `.env.example-e2e`) | нет | моки MSW в браузере (только dev и E2E на mock-сервере) |
| `VITE_APP_ENABLE_DEV_PAGES` | bool | `false` | нет | служебные страницы этапа 1 (`/dev/llm-stream` для E2E Г.11); в сборке образа `flt-frontend` всегда `false`, E2E на стенде N3 использует отдельную сборку с `true` |
| `VITE_APP_APP_URL` | str | `http://localhost:3000` | нет | адрес приложения для E2E на mock-сервере |
| `VITE_DEV_BACKEND_URL` | str | `http://localhost:8000` | нет | адрес бэкенда для dev-прокси Vite (не попадает в сборку) |

## 9. Права и роли

App shell не объявляет прав и не является источником прав (SYS-06-R9). Правила:

| Permission | Роли | Правило |
|---|---|---|
| — | все роли | `useHasPermission(code)` скрывает или блокирует элементы по списку `permissions` из `GET /api/v1/auth/me`; сервер проверяет право независимо; ответ `403 core.forbidden` показывается сообщением по коду, `404 core.not_found` — страницей «не найдено» (SYS-03-R22) |
| — | аноним | `ProtectedRoute` переводит на `/auth/login` (экран — этап 2; на этапе 1 — заглушка с сообщением) |

## 10. Наблюдаемость

### 10.1. Метрики

Не применимо: frontend не отдаёт метрик Prometheus. Качество интерфейса контролирует CI: Lighthouse CI (LCP, CLS, размер JavaScript, категория `accessibility`) и axe WCAG 2.2 AA в job `e2e` (SYS-02-R5, R53; SYS-12-R37).

| Имя | Тип | Метки | Описана в ТЗ |
|---|---|---|---|
| — | — | — | Не применимо: см. выше |

### 10.2. Логи

- Поле `module`: не применимо (логи браузера не собираются).
- Ошибки API показываются пользователю по коду и содержат `request_id` в деталях экрана ошибки, чтобы найти запрос в логах монолита (ADR-010).

### 10.3. Дашборды и алерты

Не применимо: дашбордов фронтенда нет; доступность раздачи статики контролирует healthcheck `/healthz` Nginx и алерт `FltInstanceDown` (ADR-010).

## 11. Frontend-модуль

Код: `src/frontend/src/app` (точка входа `index.tsx`, `provider.tsx`, `router.tsx`, `routes/`, `i18n-resources.ts`, `extensions.ts`) и shared-слой. Пространство ключей i18n: namespace `common` (`src/lib/i18n/locales/{ru,en,ar}.json`): навигация, ошибки `errors.<module>.<code>`, общие кнопки, переключатель языка.

### 11.1. Страницы

| Страница | Роут | Роли | Описана в ТЗ |
|---|---|---|---|
| Главная (каркас; содержимое — `cms`, этап 2) | `/` | все | SDD_plan.md, этап 1, Г.7 |
| Заглушка входа (до экрана VIS-05) | `/auth/login` | аноним | SDD_plan.md, этап 1, Г.7 |
| Не найдено | `*` | все | SDD_plan.md, этап 1, Г.7 |
| Ошибка приложения | граница ошибок | все | SDD_plan.md, этап 1, Г.7 |
| Диагностика стрима LLM (вклад `llm_gateway`) | `/dev/llm-stream` при `VITE_APP_ENABLE_DEV_PAGES=true` | `learner` | SDD_plan.md, этап 1, Г.11 |

### 11.2. API-хуки

| Хук | operationId | Назначение |
|---|---|---|
| `useUser` (обёртка) | `identity_getMe` | текущий пользователь, роли, `permissions`, `ui_language` |
| `useLogin` (обёртка) | `identity_login` | вход (на этапе 1 — заглушка и фикстура E2E) |
| `useLogout` (обёртка) | `identity_logout` | выход |

### 11.3. Подписки WebSocket

| Тип сообщения | Что обновляет |
|---|---|
| `identity.session.revoked` | сбрасывает кэш пользователя, закрывает соединение, переводит на `/auth/login` |

### 11.4. Клиентское состояние

zustand: `useUiStore` — открытость меню и боковых панелей, уведомления-тосты (`notifications` слой UI без бизнес-логики); выбранный язык хранится в i18next и cookie `flt_ui_language`, не в zustand. Данные с сервера — только в кэше TanStack Query.

### 11.5. Архитектурные тесты и правила качества

- `src/testing/architecture/eslint-boundaries.test.ts` — нарушение границы модулей ломает `eslint` (ADR-005, раздел 3.6).
- Архитектурные тесты `reserved-paths` (маршруты не начинаются с `/api`, `/ws`, `/flt-`) и `no-physical-direction` (физические классы и CSS-свойства направления запрещены, SYS-07-R17).
- ESLint: зоны `import-x/no-restricted-paths` из `src/features/*`, `import-x/no-cycle`, `check-file` (kebab-case, запрет barrel-файлов), `react/jsx-no-literals` с `allowedStrings` (SYS-07-R9, OQ-82), правила `flt/no-physical-direction-classes`, `flt/test-title-has-id`, `flt/playwright-test-has-tag`, `flt/no-unreferenced-skip` (SYS-10), `eslint-comments/require-description` (SYS-12).
- Порог покрытия Vitest: 70 % `lines`, `functions`, `statements`, 60 % `branches` для `src/features`, `src/lib`, `src/components`, `src/hooks`, `src/utils` (ADR-005, раздел 3.7).
- Playwright: проекты `chromium-desktop`, `chromium-mobile`, `ar`, `retries: 0`, фикстура `loginAs`, каталог `e2e/smoke/`; axe и Lighthouse CI в job `e2e` (SYS-10, SYS-12-R37).
- Nginx `deploy/config/nginx/frontend.conf`: статика, SPA fallback, CSP (SYS-02-R17), `/healthz`; `/api` и `/ws` не проксируются (ADR-005, раздел 3.8).

## 12. Готовность к выделению в микросервис

App shell — основа для будущих микрофронтендов: feature-модули связываются только в `src/app`, поэтому модуль можно вынести в отдельную сборку без переписывания.

| Что потребуется | Описание | Готово сейчас |
|---|---|---|
| Замена вызовов в процессе на сетевые | не применимо: модули фронтенда общаются только через `src/app` и слоты | да |
| Отдельная БД | не применимо: frontend-модуль | да |
| Конфигурация | раздел 8; адреса относительные | да |
| Развёртывание | образ `flt-frontend`, маршрут HAProxy «остальные пути» → Nginx | да |
| Известные препятствия | общий namespace `common` и UI-кит потребуют отдельного пакета при выделении микрофронтендов | нет: решается ADR при выделении |

## 13. Вне рамок

- Экраны входа, регистрации и профиля — ТЗ VIS-04, VIS-05, STU-06 (этапы 2 и 4).
- Нативные мобильные приложения — нет в BRD; API и аутентификация готовы к ним (ADR-006).
- Офлайн-режим и service worker — не входят в BRD.
- Тёмная тема — не входит в этап 1; при появлении требования — ТЗ app shell.
- Сбор клиентских ошибок в отдельный сервис (Sentry и подобные) — не используется; при появлении требования — ADR.

## 14. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-82](../../open-questions.md) | перечни зеркалируемых иконок и `allowedStrings` | нет | open: стартовые перечни утверждены |
| [OQ-25](../../open-questions.md) | язык интерфейса по умолчанию и порядок определения | нет | resolved: профиль → cookie → браузер → `ru` |
| [OQ-08](../../open-questions.md) | бренд и домен (отображаемое название `APP_NAME` и ключ i18n) | нет | deferred до этапа 2 |

## 15. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-11 | Claude | Черновик | draft |
| 0.1 | 2026-10-11 | Claude | Передан на гейт G1 (PR блока В) | review |
| 1.0 | 2026-10-11 | пользователь | Утверждена на гейте G1 блока В (PR #4) | approved |
