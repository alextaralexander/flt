# shared_kernel — Shared kernel (ядро монолита)

| Поле | Значение |
|---|---|
| Статус | approved |
| Версия | 1.1 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-11 (PR #4) |
| Пункт(ы) BRD | все (сквозная инфраструктура; собственных пунктов BRD нет) |
| Модуль | shared_kernel (код — `src/backend/py-monolyth/app/core` и `configs/`) |
| Зависимости | нет доменных модулей; единственная обратная связь — интерфейс `RolePermissionsProvider`, который регистрирует `identity` (раздел 4) |
| Связанные ADR/SYS | ADR-001…ADR-004, ADR-006, ADR-007, ADR-009, ADR-010, ADR-012…ADR-014; SYS-01…SYS-12 |

## 1. Назначение и границы

- **Отвечает за**: сквозную техническую инфраструктуру монолита без знания о предметной области (SYS-01-R10, ADR-002, раздел 3.8): реестр модулей и `ModuleDefinition`; HTTP-слой (конверт ошибок `ErrorResponseV1`, коды `core.*`, пагинация, идемпотентность, локаль, `X-Request-ID`, `X-Instance-Id`); базу SQLAlchemy (`EntityBase`, `new_id()`, `Clock`) и общий `env.py` Alembic; обёртку Redis `ModuleRedis`, распределённые блокировки, ограничитель запросов, предохранитель `RedisCircuitBreaker`; Kafka (конверт события, `OutboxPublisher`, relay, inbox `processed_events`, ретраи и DLQ, фоновые задания, планировщик, декларации топиков); инфраструктуру WebSocket (`/ws`, `/ws/agent`, конверт, подписки, мост Redis pub/sub); контейнер зависимостей; проверку токенов и прав (`TokenVerifier`, `auth_user`); клиент файлового хранилища `FileStorage`; клиенты поиска; SMTP-клиент; провайдер капчи; шифрование `SecretBox`; i18n backend; точки расширения (`ExtensionPoint`); логи, метрики, трейсинг, health и readiness; настройки стендов и ролей запуска.
- **Ключевые сущности**: модуль (`module`), публичный API модуля, outbox, inbox, фоновое задание (`background_job`), команда (`command`), декларация топика (`TopicDeclaration`), точка расширения (`extension_point`), вклад в точку расширения (`contribution`), ID запроса (`request_id`), инстанс (`instance`) — термины глоссария, раздел 12.
- **Появляется на этапе**: 1 (блок Г: Г.1 — раскладка и роли запуска, Г.3 — тестовая инфраструктура, Г.4 — ядро, Г.9 — наблюдаемость).
- **Не отвечает за**:
  - выпуск токенов, пользователей, роли, согласия и матрицу «роль → права» — это модуль `identity` (ADR-006; ядро только проверяет токен и спрашивает права у `RolePermissionsProvider`);
  - провайдеров LLM, эмбеддингов и речи, ключи учеников — это модули `llm_gateway` и `speech` (SYS-08; ядро даёт только `SecretBox` и `RedisCircuitBreaker`);
  - шаблоны и решение о доставке писем и уведомлений — модули-источники и `notifications` (SYS-01-R13); ядро даёт только SMTP-клиент;
  - бизнес-метрики, топики, каналы WebSocket, права и индексы конкретных модулей — модули-владельцы (ядро даёт механизм объявления);
  - frontend-инфраструктуру — `app_shell` ([../app_shell/_module.md](../app_shell/_module.md)).

## 2. Пункты BRD и ТЗ модуля

Собственных пунктов BRD у ядра нет: оно реализует требования системных спецификаций, на которые опираются все ТЗ. Отдельных ТЗ фич у ядра нет; объём работ этапа 1 задаёт SDD_plan.md, этап 1, блок Г, а критерии готовности — требования `SYS-NN-R<M>` (тесты помечаются `@pytest.mark.req("SYS-NN-R<M>")`, SYS-10).

| ID | Пункт BRD | ТЗ | Этап | Статус ТЗ |
|---|---|---|---|---|
| — | Каркас платформы (BRD, порядок реализации, п. 1) | нет ТЗ фичи: объём — SDD_plan.md, этап 1, Г.1, Г.3, Г.4, Г.9; требования — SYS-01…SYS-12 | 1 | не начато |
| VIS-03 | Быстрый тест без регистрации | ТЗ в модуле `assessment` (этап 2); ядро даёт `Idempotent()` для анонима (`flt_anon_session`, OQ-77), `rate_limiter`, `CaptchaProvider` | 2 | не начато |
| VIS-04, VIS-05 | Регистрация и вход | ТЗ в модуле `identity` (этап 2); ядро даёт `TokenVerifier`, CSRF, SMTP-клиент, `CaptchaProvider` | 2 | не начато |

## 3. Публичный API

Ядро не является модулем `app/modules/<module>`: его импортируют все модули напрямую из `app.core.<подпакет>`. Внутренние детали (реализация relay, Lua-скрипты, фабрики клиентов) импортируются только внутри `app/core`; модули используют перечисленные ниже классы и функции. Прямой импорт `redis`, брокера Kafka, `aioboto3`, `botocore`, `opensearchpy`, `qdrant_client` модулями запрещён контрактами import-linter (ADR-002, SYS-01-R10).

### 3.1. Сервисные интерфейсы

| Интерфейс | Метод | Назначение | Кто вызывает |
|---|---|---|---|
| `app.core.modules.ModuleDefinition` | поля `name`, `router`, `extra_prefixes`, `kafka_router`, `ws_handlers`, `metadata`, `settings`, `permissions`, `topics`, `schedules`, `extension_points`, `contributions`, `role_permissions_provider` | декларация модуля для реестра (ADR-002, SYS-09-R1) | все модули в `module.py` |
| `app.core.modules.load_modules` | `load_modules(names: Sequence[str]) -> ModuleRegistry` | подключение модулей из `app/modules/registry.py`, проверка префиксов, прав, топиков и точек расширения при старте | `create_app()`, роли `worker` и `migrate` |
| `app.core.container.provide` | `provide(protocol: type[T]) -> Callable[..., T]`; `container.resolve(protocol: type[T]) -> T` | контейнер зависимостей для `Protocol` из `public/` модулей (ADR-004, раздел 2.6) | контроллеры (`Depends(provide(...))`), консьюмеры и планировщик (`container.resolve`) |
| `app.core.ids.new_id` | `new_id() -> UUID` | UUID v7 для первичных ключей и `event_id` (ADR-003) | все модули |
| `app.core.time.Clock` | `now() -> datetime` (UTC, `timestamptz`) | единственный источник времени; в тестах — `frozen_clock` (SYS-10) | все модули |
| `app.core.dao.db_helpers.make_module_base` | `make_module_base(schema: str) -> type[DeclarativeBase]` | база моделей модуля со схемой PostgreSQL модуля (ADR-002, ADR-003) | `models/__init__.py` модулей |
| `app.core.dao.db_helpers.EntityBase` | колонки `id`, `created_at`, `updated_at`, `version` (`version_id_col`); миксины `SoftDeleteMixin`, `StoredFileMixin` | общая форма сущности; `StaleDataError` → `409 core.version_conflict` (SYS-05-R18, SYS-03-R17) | модели модулей |
| `app.core.dao.db_helpers.get_session` | `async with get_session(module: str) as session` | сессия SQLAlchemy одного модуля; пул по роли (SYS-05-R23, R40) | DAO модулей |
| `app.core.dao.caching.ModuleRedis` | `ModuleRedis(prefix)`: `get(key)`, `set(key, value, *, ttl)`, `delete(key)`, `incr(key, *, ttl)`, `publish(channel, message)`; свойства `locks`, `rate_limiter` | все обращения к Redis только с префиксом модуля и обязательным TTL (ADR-003, SYS-05-R12–R14) | все модули |
| `ModuleRedis.locks` | `async with locks.acquire(name, ttl, wait)` | распределённая блокировка `SET NX PX` с токеном и Lua-освобождением (SYS-05) | модули, планировщик, relay |
| `ModuleRedis.rate_limiter` | `await rate_limiter.hit(scope, subject, limit, window) -> RateLimitResult` | скользящее окно на `ZSET` в Lua; политика fail-open или fail-closed задаётся вызывающим (ADR-003, раздел 3, п. 8) | модули с лимитами |
| `app.core.resilience.RedisCircuitBreaker` | `RedisCircuitBreaker(name, window, threshold, open_seconds, half_open_calls)`; `async with breaker.guard()` | предохранитель внешних вызовов с общим для всех инстансов состоянием в Redis (SYS-08-R16) | `llm_gateway`, позже `speech` |
| `app.core.http.errors.DomainError` | `DomainError(code: str, message: str, details: dict, status: int)` | доменная ошибка, которую `error_envelope()` превращает в `ErrorResponseV1` (SYS-03-R7, R8) | все модули |
| `app.core.http.deps.Idempotent` | `Depends(Idempotent())` | идемпотентность `POST` по `Idempotency-Key` (SYS-03-R18) | контроллеры модулей |
| `app.core.http.pagination` | `paginate_keyset(...)`, `paginate_offset(...)`, `parse_sort(...)` | курсорная и (только для администратора) смещённая пагинация, сортировка (SYS-03-R12, R13) | контроллеры модулей |
| `app.core.http.context.RequestContext` | поля `request_id`, `instance_id`, `locale`, `user` | контекст запроса для логов и локализуемого содержимого (SYS-03-R20, R30) | контроллеры и сервисы модулей |
| `app.core.security.auth_user` | `auth_user(permission: str) -> Depends[UserSecuritySchema]`; `auth_user_optional()`; `auth_websocket()`; маркер `public=True` | аутентификация cookie или Bearer, CSRF, проверка права по матрице SYS-06 (ADR-006, раздел 3.4; SYS-06-R5) | роутеры и обработчики WebSocket модулей |
| `app.core.security.TokenVerifier` | `async verify(token: str) -> UserSecuritySchema` | проверка access JWT EdDSA по `kid`, отзыв в Redis с fail-open (ADR-006, раздел 3.2) | `auth_user`, `auth_websocket` |
| `app.core.security.RolePermissionsProvider` | `grants_for(roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]` | интерфейс, объявленный в ядре; реализацию регистрирует `identity` (ADR-006, раздел 3.8; SYS-06-R4) | `auth_user` |
| `app.core.kafka.OutboxPublisher` | `await publish(session, event: BaseEvent)`; `await send_command(session, command: JobCommand)` | запись события или команды в `<module>.outbox` в транзакции с данными (ADR-004, SYS-04-R24) | сервисы модулей |
| `app.core.kafka.idempotent_consumer` | декоратор `@idempotent_consumer(module, handler)` | inbox `<module>.processed_events`, ретраи 1 с, 5 с, 25 с, затем `<topic>.dlq` (SYS-04-R26, R27) | консьюмеры модулей |
| `app.core.kafka.TopicDeclaration` | `TopicDeclaration(name, kind, visibility, partitions, retention, message_model, description)` | декларация топика в `public/topics.py` модуля (SYS-04-R21, SYS-09-R12) | все модули с Kafka |
| `app.core.kafka.JobRunner` | `JobRunner(kind, handler)`; таблица `<module>.jobs` | фоновое задание: запись + команда, прогресс по WebSocket (SYS-04-R16, R29) | модули с фоновыми заданиями |
| `app.core.kafka.ScheduleDeclaration` | `ScheduleDeclaration(name, cron, handler, lock_ttl)` | периодическая задача роли `worker` под блокировкой `shared_kernel:lock:schedule:<module>.<task>` (SYS-04-R32, SYS-05-R28) | `identity` (`purge_tokens`), другие модули |
| `app.core.ws.WsChannelHandler` | `can_subscribe(user, channel_id) -> bool`; `state_url(channel_id) -> str \| None`; `on_command(conn, envelope)` | обработчик канала WebSocket модуля (SYS-04-R5–R8) | `api/ws.py` модулей |
| `app.core.ws.WsPublisher` | `await publish_to_channel(channel, message)`; `await publish_to_user(user_id, message)`; `await close_user_connections(user_id, code)` | доставка сообщений на любой инстанс через Redis pub/sub `ws:channel:*`, `ws:user:*` (SYS-04-R13, SYS-05-R24) | модули |
| `app.core.storage.FileStorage` | `presign_upload(...)`, `presign_get(...)`, `confirm(...)`, `delete_prefix(...)`, `public_url(...)` | работа с бакетом `flt-<module>` без прохождения байтов через монолит (ADR-007) | модули с файлами |
| `app.core.search` | `ModuleOpenSearch(prefix)`, `ModuleQdrant(prefix)`, `SearchIndexer`, декларации `IndexDeclaration`, `QdrantCollection` | клиенты поиска с префиксом модуля и признаком `private` (ADR-014) | модули с индексами |
| `app.core.mail.MailClient` | `await send(to, subject, html, text, *, headers)` | единый SMTP-клиент; в тестах — `mail_outbox` (SYS-10) | `identity`, `notifications` (SYS-01-R13) |
| `app.core.captcha.CaptchaProvider` | `await verify(token: str, ip: str) -> bool` | Yandex SmartCaptcha за интерфейсом; заглушка в тестах (OQ-10) | `identity`, `assessment` |
| `app.core.crypto.SecretBox` | `encrypt(plaintext, aad) -> Sealed(ciphertext, nonce, key_version)`; `decrypt(sealed, aad) -> bytes` | AES-256-GCM с версиями ключей (ADR-013, раздел 3.4; SYS-08-R6) | `llm_gateway` |
| `app.core.i18n` | `UI_LANGUAGES`, `LanguageCode`, `request_language(...)`, `format_*` (Babel), `translate(key, locale, **params)` | языки интерфейса, локаль запроса, форматы (SYS-07) | все модули |
| `app.core.extensions` | `ExtensionPoint[T]`, `ExtensionContribution`, `ExtensionRegistry` | точки расширения и вклады (SYS-09-R1–R3) | `llm_gateway`, `languages`, `lessons`, `assessment`, `speech`, `local_runtime` |
| `app.core.metrics` | `module_counter(module, name, ...)`, `module_histogram(...)`, `module_gauge(...)` | бизнес-метрики `flt_<module>_*` без меток с неограниченным множеством значений (ADR-010) | все модули |
| `app.core.logging` | `get_logger("flt.<module>.<name>")`, процессор `redact_sensitive_keys` | JSON-логи с обязательными полями и маскированием (ADR-010) | все модули |

### 3.2. Pydantic-схемы

| Схема | Назначение | Кто использует |
|---|---|---|
| `ErrorResponseV1`, `ErrorMessage` | конверт ошибок 4xx и 5xx (SYS-03-R7) | все роутеры; общие компоненты контракта `Analytics/Specs/_system/openapi-common.yaml` |
| `CorePage[T]`, `CoreOffsetPage[T]`, `CoreJobAcceptedResponse` | страницы ответов и ответ `202` фонового задания (SYS-03-R12, R13, R27) | роутеры модулей |
| `UserSecuritySchema` | `user_id`, `sid`, `roles`, `permissions`, `client`, `email_verified`, `age_confirmed` (ADR-006, раздел 3.2) | контроллеры и обработчики WebSocket |
| `EventEnvelope`, `BaseEvent[P]`, `JobCommand[P]` | конверт события (`event_id`, `event_type`, `event_version`, `occurred_at`, `producer`, `aggregate_id`, `correlation_id`, `causation_id`, `payload`) и команды задания (SYS-04-R20, R29) | события и команды модулей; `asyncapi-common.yaml` |
| `WsEnvelope` | `{type, correlation_id, channel, seq, ts, payload}` (ADR-004, SYS-04-R3) | обработчики WebSocket; `asyncapi-common.yaml` |
| `Grant`, `Permission` | право `<module>:<resource>:<action>` и область `own`/`rel`/`any` (SYS-06-R2) | `permissions.py` модулей, `identity` |
| `HealthResponse`, `ReadinessResponse` | тела `/v1/health` и `/v1/ready` вне конверта ошибок (ADR-010) | служебные эндпоинты |

### 3.3. События

Ядро не публикует доменных событий. Оно даёт механизм публикации (`OutboxPublisher`, relay) и потребления (`idempotent_consumer`); события и топики объявляют модули (раздел 6).

## 4. Зависимости

### 4.1. От каких модулей зависит

| Модуль | Что используется | Способ | Зачем |
|---|---|---|---|
| `identity` | реализация `RolePermissionsProvider` из `ModuleDefinition.role_permissions_provider` | регистрация при `load_modules`, вызов в процессе через интерфейс, объявленный в ядре | вывести права из ролей при проверке запроса (ADR-006, раздел 3.8; SYS-06-R4). Код ядра не импортирует `app.modules` (контракт import-linter, ADR-002) |

### 4.2. Кто зависит от модуля

| Модуль | Что использует | Способ |
|---|---|---|
| все модули реестра SYS-01 | раздел 3.1 целиком в объёме своих функций | импорт `app.core.*` в процессе |
| `src/tools` (`flt_tools`) | реестр модулей и декларации (для `flt-tools modules check`, `permissions check`, SYS-12-R38) | чтение деклараций через `python -m cli list-modules`, `list-settings` |

## 5. Владение данными

### 5.1. PostgreSQL

- Собственной схемы с доменными таблицами у ядра нет; схема `public` таблиц не содержит (ADR-003, SYS-05).
- Ядро объявляет **шаблоны** служебных таблиц, которые создаются в схеме каждого модуля его собственной миграцией: `<module>.outbox`, `<module>.processed_events`, `<module>.jobs`, `<module>.alembic_version` (ADR-002, ADR-004, SYS-04-R24, R26, R29).
- Миграции Alembic: общий `env.py` и `script.py.mako` в `app/core/dao/db_helpers/migrations/`; ревизии лежат в модулях (ADR-002).
- Тестовая сущность `core_probe` для тестов ядра на стенде N3 (SYS-05, раздел 4) существует только в тестовом коде `tests/n_instances/core/` и в продуктивную схему не попадает.

| Таблица | Назначение | Описана в ТЗ |
|---|---|---|
| `<module>.outbox` (шаблон) | исходящие события и команды модуля до отправки relay | SYS-04-R24 |
| `<module>.processed_events` (шаблон) | inbox: обработанные `event_id` для идемпотентности консьюмеров | SYS-04-R26 |
| `<module>.jobs` (шаблон) | фоновые задания модуля: `id`, `kind`, `status`, `progress`, `result`, `error` | SYS-04-R29 |

### 5.2. Redis

Префикс ключей ядра: `shared_kernel:`; каналы pub/sub WebSocket — `ws:*` (ADR-004). Все ключи — с TTL (ADR-003).

| Шаблон ключа | Назначение | TTL | Описан в ТЗ |
|---|---|---|---|
| `shared_kernel:idempotency:<subject>:<key>` | сохранённый ответ идемпотентного `POST` | 24 ч | SYS-03-R18 |
| `shared_kernel:lock:outbox:<module>` | блокировка relay outbox модуля | 60 с с продлением | SYS-05-R30 |
| `shared_kernel:lock:schedule:<module>.<task>` | блокировка периодической задачи | интервал задачи | SYS-04-R32 |
| `shared_kernel:ws:conns:<user_id>` | счётчик WebSocket-соединений пользователя (лимит 5) | по SYS-05-R27 | SYS-04-R14, SYS-05-R27 |
| `<module>:cb:<name>` | состояние `RedisCircuitBreaker` (ключ в префиксе модуля-владельца) | 60 с (окно) | SYS-08-R16 |
| канал `ws:channel:<channel>` | доставка сообщений канала на все инстансы | pub/sub, не хранится | SYS-04-R13 |
| канал `ws:user:<user_id>` | доставка сообщений пользователю и закрытие его соединений | pub/sub, не хранится | SYS-04-R13 |

### 5.3. MinIO

Не применимо: ядро не владеет бакетами; `FileStorage` работает с бакетом `flt-<module>` модуля-владельца, бакеты создаёт `cli storage-init` роли `migrate` по декларациям модулей (ADR-007).

### 5.4. OpenSearch

Не применимо: ядро не владеет поисковыми индексами; индексы логов `flt-logs-*` создаёт Fluent Bit по шаблонам `deploy/config/opensearch/` (ADR-010), индексы модулей — роль `migrate` по декларациям модулей (ADR-014).

### 5.5. Qdrant

Не применимо: коллекции объявляют модули (ADR-014); ядро даёт клиент с обязательным `owner_id` для приватных коллекций.

## 6. События Kafka

Контракт общих схем: `Analytics/Specs/_system/asyncapi-common.yaml` (`EventEnvelope`, `WsEnvelope`, типы ядра; создаётся на этапе 1 Г.3, SDD_plan.md 1.2).

### 6.1. Публикуемые топики

Не применимо: ядро не публикует доменных событий. DLQ-топики `<topic>.dlq` создаются автоматически для каждого объявленного топика модуля (SYS-04-R21, R27).

### 6.2. Потребляемые топики

Не применимо: ядро не подписывается на топики модулей. Тестовые задания `core.heartbeat_probe` и `core.slow_probe` (SYS-05) существуют только на стенде тестов.

## 7. REST-роутер и WebSocket-обработчики

### 7.1. REST

- Префикс: ядро не имеет роутера `/api/v1/<module>`. Оно обслуживает служебные эндпоинты вне `/api`: `GET /v1/health`, `GET /v1/ready`, `GET /v1/metrics` (роль `api` — порт 8000, роли `worker` и `media_agent` — порт 8001), `GET /asyncapi/kafka` (порт воркера), документацию `/api/docs`, `/api/redoc`, `/api/openapi.json` (ADR-004, ADR-010, ADR-012, OQ-62).
- Контракт общих компонентов REST: `Analytics/Specs/_system/openapi-common.yaml` (`ErrorResponseV1`, `ErrorMessage`, `CoreJobAcceptedResponse`, `CoreOffsetPage`, схемы безопасности; создаётся на этапе 1 Г.3, SYS-03, пример 3).

| Роутер | Ресурсы | Описан в ТЗ |
|---|---|---|
| `health_router` | `/v1/health`, `/v1/ready`, `/v1/metrics` | ADR-010; SYS-05-R41; SYS-11-R11 |
| `asyncapi_router` (роль `worker`) | `/asyncapi/kafka` | ADR-004 |

### 7.2. WebSocket

Ядро владеет эндпоинтами `/ws` (фронтенд) и `/ws/agent` (локальный агент; аутентификацию выполняет обработчик `local_runtime`) и служебными типами сообщений `ws.*` (SYS-04-R1–R14).

| Тип сообщения | Направление | Схема | Канал Redis pub/sub | Описан в ТЗ |
|---|---|---|---|---|
| `ws.subscribe`, `ws.unsubscribe` | клиент → сервер | `WsSubscribePayload` | — | SYS-04-R6 |
| `ws.ack`, `ws.error` | сервер → клиент | `WsAckPayload`, `WsErrorPayload` | — | SYS-04-R6 |
| `ws.ping`, `ws.pong` | клиент ↔ сервер | `WsPingPayload` | — | SYS-04-R11 |
| сообщения каналов модулей | сервер → клиент | схемы модулей | `ws:channel:<channel>`, `ws:user:<user_id>` | SYS-04-R13 |

Коды закрытия: `1012` (остановка инстанса), `1013` (переполнение очереди), `4401` (нет аутентификации или сессия отозвана), `4429` (лимит соединений).

## 8. Секция настроек

Общие настройки ядра читаются классами `configs/` без префикса модуля; секреты — `SecretStr` без значения по умолчанию, только из переменных окружения (ADR-013). Таблица всех секретов ведётся в SYS-11.

| Переменная | Тип | По умолчанию | Секрет | Назначение |
|---|---|---|---|---|
| `STAND_NAME` | str (`local`, `dev`, `test`, `prod`) | `local` | нет | стенд и набор `envs/<стенд>/` (SYS-11-R3) |
| `APP_ROLE` | str (`api`, `worker`, `all`, `migrate`, `media_agent`) | `all` | нет | роль запуска (ADR-004) |
| `APP_VERSION` | str | тег образа | нет | метка `flt_instance_info` (SYS-12-R21) |
| `APP_PUBLIC_URL` | str | `http://flt.localhost` | нет | внешний адрес; проверка `Origin` WebSocket (ADR-006, раздел 3.7) |
| `WORKER_HTTP_PORT` | int | `8001` | нет | служебный порт ролей `worker` и `media_agent` |
| `FORWARDED_ALLOW_IPS` | str | сеть compose | нет | доверие `X-Forwarded-*` от HAProxy (ADR-012) |
| `FLT_EXPOSE_DOCS` | bool | `false` (`true` на local и dev) | нет | открыть документацию API и не снимать `X-Instance-Id` (SYS-05-R5) |
| `DEBUG_MODE` | bool | `false` | нет | детали ответа `500` только на local (ADR-013) |
| `SHUTDOWN_GRACE_SECONDS` | int | `30` | нет | время на завершение стримов при остановке |
| `HTTP_MAX_JSON_BODY_BYTES` | int | `1048576` | нет | лимит тела JSON (SYS-03-R26) |
| `PG_HOST`, `PG_PORT`, `PG_DATABASE`, `PG_USERNAME` | str, int | по стенду | нет | подключение к PostgreSQL |
| `PG_PASSWORD` | SecretStr | — | да | пароль PostgreSQL |
| `REDIS_MODE` | str (`standalone`, `sentinel`) | `standalone` | нет | режим Redis (ADR-003) |
| `REDIS_HOST`, `REDIS_SENTINEL_HOSTS`, `REDIS_SENTINEL_MASTER`, `REDIS_DB` | str, int | по стенду | нет | адреса Redis |
| `REDIS_PASSWORD` | SecretStr | — | да | пароль Redis |
| `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_CLIENT_ID` | str | по стенду | нет | брокер Kafka (без SASL, ADR-013) |
| `KAFKA_AUTO_CREATE_TOPICS_ENABLE` | bool | `true` только на local | нет | автосоздание топиков (ADR-004) |
| `WS_OUTBOX_MAX`, `WS_SEND_TIMEOUT_SECONDS`, `WS_MAX_MESSAGE_BYTES` | int | значения SYS-04 | нет | очередь и лимиты соединения WebSocket |
| `S3_ENDPOINT_URL`, `S3_REGION`, `S3_PUBLIC_BASE_URL` | str | по стенду | нет | хранилище (ADR-007) |
| `S3_PRESIGN_TTL_SECONDS`, `S3_UPLOAD_TTL_SECONDS`, `S3_SINGLE_UPLOAD_MAX_BYTES`, `S3_MULTIPART_PART_BYTES` | int | значения ADR-007 | нет | presigned URL и загрузки |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | SecretStr | — | да | учётная запись монолита в хранилище |
| `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_VERIFY_SSL` | str, bool | по стенду | нет | клиент поиска (ADR-014) |
| `OPENSEARCH_PASSWORD` | SecretStr | — | да | пароль пользователя монолита в OpenSearch |
| `QDRANT_URL` | str | по стенду | нет | клиент Qdrant |
| `QDRANT_API_KEY` | SecretStr | — | да | ключ Qdrant |
| `JWT_PUBLIC_KEYS` | str (JSON) | выводится из `JWT_SIGNING_KEYS` | нет | публичные ключи проверки по `kid` (ADR-006, раздел 3.3) |
| `JWT_ISSUER`, `JWT_AUDIENCE` | str | `flt`, `flt-api` | нет | проверка claims |
| `AUTH_CSRF_SECRET` | SecretStr | — | да | HMAC CSRF-токена |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_FROM` | str, int | Mailpit на local, dev, test | нет | SMTP-клиент (OQ-11) |
| `SMTP_PASSWORD` | SecretStr | — | да | пароль SMTP |
| `CAPTCHA_ENABLED`, `CAPTCHA_SITE_KEY` | bool, str | `false` | нет | капча (OQ-10) |
| `CAPTCHA_SERVER_KEY` | SecretStr | — | да (при `CAPTCHA_ENABLED=true`) | серверный ключ Yandex SmartCaptcha |
| `OTLP_EXPORTER_ENDPOINT` | str | пусто | нет | экспорт трейсов выключен до этапа 4 (ADR-010) |
| `LOGS_RETENTION_DAYS` | int | `14` | нет | срок хранения логов (используется развёртыванием) |

## 9. Права и роли

Ядро не объявляет собственных прав. Оно реализует механизм SYS-06: формат кода права `<module>:<resource>:<action>`, закрытый перечень действий `PERMISSION_ACTIONS` (SYS-06-R2), области `own`, `rel`, `any`, признак `L` «доступ к обучению» (SYS-06-R7), маркер `public=True` для анонимных роутов (SYS-06-R10) и обязательное объявление доступа каждым роутом и обработчиком (SYS-06-R5).

| Permission | Роли | Правило |
|---|---|---|
| — | — | Не применимо: права объявляют модули; ядро проверяет их через `auth_user` и `RolePermissionsProvider` |

## 10. Наблюдаемость

### 10.1. Метрики

| Имя | Тип | Метки | Описана в ТЗ |
|---|---|---|---|
| `http_requests_total` | counter | `method`, `endpoint`, `status` | ADR-010 |
| `http_request_duration_seconds` | histogram | `method`, `endpoint` | ADR-010 |
| `flt_ws_connections` | gauge | `endpoint` | ADR-010, SYS-04-R36 |
| `flt_ws_messages_total` | counter | `direction`, `type` | ADR-010 |
| `flt_db_pool_connections` | gauge | `state` | ADR-010 |
| `flt_redis_pool_connections` | gauge | `state` | ADR-010 |
| `flt_redis_up` | gauge | — | ADR-010 |
| `flt_auth_revocation_check_skipped_total` | counter | — | ADR-006, ADR-010 |
| `flt_instance_info` | gauge (info) | `instance_id`, `role`, `version`, `stand` | ADR-010, SYS-12-R21 |
| `flt_outbox_pending` | gauge | `module` | SYS-04-R36 |
| `flt_outbox_publish_latency_seconds` | histogram | `module` | SYS-04-R36 |
| `flt_kafka_retries_total`, `flt_kafka_duplicates_total` | counter | `topic`, `handler` | SYS-04-R36 |
| `flt_jobs_total` | counter | `module`, `kind`, `status` | SYS-04-R36 |
| `flt_schedule_runs_total` | counter | `module`, `task`, `status` | SYS-04-R36 |
| `flt_ws_connections_total`, `flt_ws_dropped_frames_total`, `flt_ws_publish_failed_total` | counter | `endpoint` | SYS-04-R36 |
| `flt_ratelimit_bypassed_total` | counter | `module`, `scope` | SYS-05-R15 |
| `flt_kafka_dlq_messages_total` | counter | `topic` | SYS-04-R36 |
| метрики `KafkaPrometheusMiddleware` | counter, histogram | `topic`, `handler`, `status` | ADR-010 |

### 10.2. Логи

- Поле `module`: `core` (логгеры `flt.core.*`).
- Обязательные поля и запреты — CLAUDE.md, «Наблюдаемость»; процессор `redact_sensitive_keys` (ADR-010, SYS-08-R18).
- События: `core.startup`, `core.shutdown`, `core.readiness_failed`, `core.outbox_relay_error`, `core.dlq_message`, `core.revocation_check_skipped`, `core.idempotency_replayed`.

### 10.3. Дашборды и алерты

Дашборды `deploy/config/grafana/dashboards/{instances,http,websocket,kafka,postgresql,redis,haproxy,logs}.json`; алерты `FltInstanceDown`, `FltHigh5xxRate`, `FltKafkaConsumerLag`, `FltDiskSpaceLow`, `FltReadinessFailing`, `FltOpenSearchRed`, `FltRedisDown`, `FltAuthRevocationSkipped` (ADR-010, этап 1 Г.9).

## 11. Frontend-модуль

Не применимо: backend-ядро без frontend-модуля; frontend-инфраструктура — [`app_shell`](../app_shell/_module.md).

### 11.1. Страницы

Не применимо: backend-ядро без frontend-модуля.

### 11.2. API-хуки

Не применимо: backend-ядро без frontend-модуля.

### 11.3. Подписки WebSocket

Не применимо: backend-ядро без frontend-модуля.

### 11.4. Клиентское состояние

Не применимо: backend-ядро без frontend-модуля.

## 12. Готовность к выделению в микросервис

Ядро в отдельный сервис не выделяется: при выделении модуля в микросервис ядро становится его библиотекой (копируется вместе с модулем или выносится в пакет). Чтобы это было возможно без переписывания, ядро не знает о модулях (контракт import-linter `app.core` не импортирует `app.modules`).

| Что потребуется | Описание | Готово сейчас |
|---|---|---|
| Замена вызовов в процессе на сетевые | не применимо к ядру; `RolePermissionsProvider` выделенного сервиса получает права по REST или из кэша событий `identity` | нет: решается ADR при выделении первого модуля |
| Отдельная БД | шаблоны `outbox`, `processed_events`, `jobs` уже живут в схеме модуля | да |
| Конфигурация | раздел 8; секреты выделенного сервиса — только нужные ему (например `JWT_PUBLIC_KEYS` без `JWT_SIGNING_KEYS`) | да |
| Развёртывание | ядро — часть образа каждого сервиса | да |
| Известные препятствия | общий счётчик WebSocket-соединений `shared_kernel:ws:conns` предполагает один эндпоинт `/ws`; при выделении модуля с WebSocket нужен ADR о маршрутизации каналов | нет |

## 13. Вне рамок

- Трейсинг с экспортом (OpenTelemetry Collector, Tempo) — этап 4, новым ADR (OQ-20).
- Нативная шина событий для внешних сервисов и плагинов — этап 7 (SYS-13).
- Шаблоны писем и логика уведомлений — `identity` (транзакционные письма этапа 2) и `notifications` (этап 5).
- PgBouncer — только по порогу SYS-05.
- Frontend-часть инфраструктуры — `app_shell`.

## 14. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-84](../../open-questions.md) | перечень подпакетов `app/core` в SYS-01-R10 | нет | resolved: добавлены `i18n`, `resilience`, `extensions` (SYS-01 2.0) |
| [OQ-77](../../open-questions.md) | анонимная сессия `flt_anon_session` — субъект `Idempotent()` и лимитов анонима | нет | open: рабочее решение утверждено |
| [OQ-20](../../open-questions.md) | экспорт трейсов | нет | resolved: выключен до этапа 4 |
| [OQ-62](../../open-questions.md) | путь метрик `/v1/metrics` | нет | resolved |

## 15. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-11 | Claude | Черновик | draft |
| 0.1 | 2026-10-11 | Claude | Передан на гейт G1 (PR блока В) | review |
| 1.0 | 2026-10-11 | пользователь | Утверждена на гейте G1 блока В (PR #4) | approved |
| 1.1 | 2026-10-11 | Claude | Раздел 8: удалена `MIGRATE_ON_START` (SYS-05-R33, реализация Г.1); на утверждение в PR Г.1 | review |
| 1.1 | 2026-10-11 | пользователь | Утверждена (PR #5) | approved |
