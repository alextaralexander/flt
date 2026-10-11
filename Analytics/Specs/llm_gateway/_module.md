# llm_gateway — LLM-шлюз

| Поле | Значение |
|---|---|
| Статус | review |
| Версия | 0.1 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | VIS-03 (модель платформы), STU-01, STU-03, STU-05 (подключение моделей), STU-25 (harness), STU-36 (версии промптов персонажа) |
| Модуль | llm_gateway |
| Зависимости | shared kernel; `identity` (согласие `foreign_llm_transfer`); `local_runtime` (провайдер `local`, этап 4); `audit` (этап 3) |
| Связанные ADR/SYS | ADR-002, ADR-004, ADR-008, ADR-009, ADR-013, ADR-014; SYS-01, SYS-02, SYS-03, SYS-04, SYS-05, SYS-06, SYS-07, SYS-08, SYS-09, SYS-10, SYS-11 |

## 1. Назначение и границы

- **Отвечает за**: единственную точку обращения платформы к языковым моделям, эмбеддингам и хранение учётных данных всех внешних AI-провайдеров (SYS-08-R1, SYS-01): реестр видов провайдеров (`ProviderKindInfo`, точка расширения `llm_gateway.providers`), адаптеры (`stub`, `openai_compatible`; позже `anthropic`, `gigachat`, `yandexgpt`, `local`), подключения провайдеров (`provider_binding`) с зашифрованными ключами для LLM и речи, модель платформы (`platform_model`) и её суточный бюджет, предпочтения модели ученика (`model_preferences`), настройки harness (`harness_settings`), стрим `stream_completion` по WebSocket, учёт расхода (`usage_record`), оценку токенов, лимиты и предохранитель провайдеров, провайдер эмбеддингов (`EmbeddingsProvider`), выдачу учётных данных модулю `speech` (`ProviderCredentialsService`).
- **Появляется на этапе**: 1 (базовая часть, ADR-009, раздел 3.8; SDD_plan.md, Г.6); дополняется на этапах 2 (модель платформы в быстром тесте), 4 (подключения учеников, модели, `local`), 5 (эмбеддинги `platform`, учётные данные речи), 7 (harness: MCP, скилы).
- **Объём этапа 1 (Г.6)**: интерфейс `LLMProvider` с `stream_completion`, `Delta`, `Usage`; реестр видов и точки расширения; провайдеры `stub` (режимы `scripted`, `replay`, `record`) и `openai_compatible`; модель платформы по конфигурации (российский провайдер через OpenAI-совместимый адаптер, OQ-09); вид `local` — только зарезервированное значение и ветка `auth_mode = agent`; канал WebSocket и команды `llm_gateway.completion.request`/`cancel`, события `start`/`delta`/`end`/`error`; коалесценция дельт, таймауты, отмена, лимит стримов на соединение и пользователя; `instance_shutdown` при `SIGTERM`; запись `usage_records`; `SecretBox` для ключей (ввод ключей — этап 4); таблицы модуля и контракт REST целиком с `x-flt-stage`, реализация `GET /provider-kinds` и `POST /provider-bindings/{provider_binding_id}/test` (SYS-08-R7, R27).
- **Не отвечает за**:
  - тексты промптов и семантику диалога занятия — модули-потребители (`lessons`, `dictionary`, `assessment`, `learning_plan`, `memorization`, `avatar`, `promotion`; SYS-08-R15);
  - транспорт до локального агента, реестр агентов и сопряжение — это модуль `local_runtime` (ADR-008);
  - адаптеры синтеза и распознавания речи и голосовые сессии — это модуль `speech` (SYS-08-R22); `llm_gateway` хранит только их подключения и ключи (OQ-81);
  - модель курса по умолчанию `course_default_model` — атрибут курса в модуле `courses`; шлюз только предзаполняет по ней `model_preferences` (команда `prefill_model_preferences`);
  - согласия — модуль `identity` (шлюз проверяет `has_consent`);
  - состояние анонимной сессии быстрого теста — модуль `assessment` (OQ-77).

## 2. Пункты BRD и ТЗ модуля

| ID | Пункт BRD | ТЗ | Этап | Статус ТЗ |
|---|---|---|---|---|
| — | Каркас: стрим ответа модели на заглушке и OpenAI-совместимом провайдере | нет ТЗ фичи: объём — SDD_plan.md, этап 1, Г.6; требования — ADR-009, SYS-08 | 1 | не начато |
| VIS-03 | Быстрый тест без регистрации (модель платформы) | ТЗ в модуле `assessment` (этап 2) | 2 | не начато |
| STU-01 | Подключение внешних моделей по ключу | STU-01-provider-bindings.md (имя уточняется в ТЗ этапа 4) | 4 | не начато |
| STU-03 | Выбор модели | STU-03-model-selection.md (этап 4) | 4 | не начато |
| STU-05 | Подключение локальной модели через агента | ТЗ в модуле `local_runtime` (этап 4); часть `llm_gateway` — провайдер `local` (SYS-08-R20) | 4 | не начато |
| STU-25 | MCP-серверы, скилы и настройки harness | STU-25-harness.md (этап 7) | 7 | не начато |
| STU-36 | Персонаж платформы (версии промптов) | ТЗ в модуле `avatar` (этап 5); шлюз записывает `prompt_name`, `prompt_version` | 5 | не начато |

## 3. Публичный API

Подпакет `app/modules/llm_gateway/public/`: `providers.py`, `interfaces.py`, `schemas.py`, `events.py`, `errors.py`, `ws_messages.py`, `topics.py`, `extension_points.py` (SYS-08, раздел 4).

### 3.1. Сервисные интерфейсы

| Интерфейс | Метод | Назначение | Кто вызывает |
|---|---|---|---|
| `LlmGatewayService` | `stream_completion(actor, request, *, purpose, prompt_ref=None) -> AsyncIterator[Delta]` | интерактивный стрим (SYS-08-R26) | обработчики WebSocket модулей (`lessons`, `dictionary`, `assessment`); собственный канал `llm_gateway.stream` |
| `LlmGatewayService` | `complete(actor, request, *, purpose, prompt_ref=None) -> CompletionResult` | непотоковый вызов, в том числе из фоновых заданий роли `worker` (ADR-009, раздел 3.2) | `learning_plan`, `dictionary`, `memorization`, `materials`, `promotion` |
| `LlmGatewayService` | `resolve_model(actor, context) -> ModelSelection` | выбор модели: явный выбор → курс → умолчание ученика (SYS-08-R11) | модули-потребители |
| `LlmGatewayService` | `capabilities(provider_binding_id, llm_model) -> ModelCapabilities` | возможности модели (SYS-08-R3) | модули-потребители |
| `LlmGatewayService` | `embed(actor, texts, *, purpose) -> EmbeddingsResult` | эмбеддинги (SYS-08-R21) | `materials`, `dictionary`, `social` |
| `LlmGatewayService` | `estimate_tokens(request) -> int` | оценка размера запроса (SYS-08-R13, R29) | модули-потребители |
| `LlmGatewayService` | `get_usage_summary(user_id, period) -> UsageSummary` | агрегаты расхода | `progress` (этап 4, экран профиля) |
| `ProviderCredentialsService` | `async get_credentials(provider_binding_id, *, owner_user_id, consumer_module) -> ProviderCredentials` | учётные данные провайдера речи на время вызова (SYS-08-R31, OQ-81) | `speech` (этап 5) |
| `LLMProvider` (контракт адаптера) | `kind`; `complete`; `stream_completion`; `list_models`; `capabilities(llm_model)`; `check_connection`; `count_tokens` | адаптер на одно подключение (SYS-08-R2) | реализации в `providers/`; вклад `local` модуля `local_runtime` (этап 4) |
| `ProviderKindInfo` (контракт вклада) | `kind`, `factory`, `jurisdiction`, `auth_mode`, `display_name_key`, `default_base_url`, `stage` | вклад в точку `llm_gateway.providers` (SYS-08-R4, SYS-09-R7) | реестр провайдеров, `local_runtime`, плагины (этап 7) |
| `EmbeddingsProvider` (контракт) | `embed(texts, *, model=None) -> EmbeddingsResult` | вклад в точку `llm_gateway.embeddings_providers` (SYS-08-R21) | реализации `stub` (этап 1), `platform` (этап 5) |

### 3.2. Pydantic-схемы

| Схема | Назначение | Кто использует |
|---|---|---|
| `Actor` | `kind` (`user`, `anonymous`, `system`), `user_id`, `anonymous_session_id`, `request_id` | все вызывающие модули |
| `CompletionRequest`, `Message`, `ContentPart` | запрос к модели (сообщения, параметры, `tools`, `response_format`, `metadata`) | все вызывающие модули |
| `Delta`, `Usage`, `CompletionResult` | дельта стрима, расход, результат непотокового вызова (ADR-009) | все вызывающие модули |
| `ModelSelection`, `ModelCapabilities`, `ModelInfo` | выбранная модель и её возможности | модули-потребители, `learner_profile` |
| `HarnessSettings` | настройки harness ученика (SYS-08-R23) | `lessons` (этап 7) |
| `ProviderCredentials` | `provider_binding_id`, `service`, `kind`, `base_url`, `api_key: SecretStr \| None`, `extra_headers`, `jurisdiction`, `api_key_last4` | `speech` |
| `ProviderError`, `ProviderErrorCode` | единые коды ошибок провайдеров (SYS-08-R17) | модули-потребители, frontend через контракт |
| `PromptRef` | `(name, version)` промпта вызывающего модуля (SYS-08-R15) | модули с промптами |

### 3.3. События

Публикуемые события — раздел 6.1.

## 4. Зависимости

### 4.1. От каких модулей зависит

| Модуль | Что используется | Способ | Зачем |
|---|---|---|---|
| shared kernel | `ModuleRedis`, `rate_limiter`, `RedisCircuitBreaker`, `SecretBox`, `OutboxPublisher`, `WsChannelHandler`, `WsPublisher`, `ExtensionPoint`, `auth_user` | вызов в процессе | инфраструктура |
| `identity` | `IdentityService.has_consent(user_id, "foreign_llm_transfer")` | вызов в процессе через интерфейс | запрет вызова зарубежного провайдера без согласия (SYS-08-R10, SYS-02-R40) |
| `identity` | события `flt.identity.consent_revoked.v1`, `flt.identity.user_deleted.v1` | подписка на топики Kafka | перевод подключений в недоступные; удаление подключений и обезличивание расхода (SYS-08-R19) |
| `local_runtime` (этап 4) | `LocalRuntimeService.stream(agent_id, request)`, `engine.list_models` | вызов в процессе через интерфейс | провайдер `local` (SYS-08-R20) |
| `audit` (этап 3) | команда `flt.audit.jobs.record.v1` | команда через outbox | изменение лимитов модели платформы администратором |

### 4.2. Кто зависит от модуля

| Модуль | Что использует | Способ |
|---|---|---|
| `lessons`, `dictionary`, `assessment`, `learning_plan`, `memorization`, `avatar`, `promotion` | `LlmGatewayService` | вызов в процессе |
| `materials`, `social` | `LlmGatewayService.embed` | вызов в процессе |
| `speech` (этап 5) | `ProviderCredentialsService` | вызов в процессе |
| `courses` | команда `flt.llm_gateway.jobs.prefill_model_preferences.v1` | команда через outbox `courses` |
| `learner_profile` | `resolve_model`, `capabilities` (экран профиля и wizard) | вызов в процессе |
| `local_runtime` (этап 4) | вклад `ProviderKindInfo(kind="local")` в точку `llm_gateway.providers` | регистрация в `ModuleDefinition.contributions` |

## 5. Владение данными

### 5.1. PostgreSQL

- Схема: `llm_gateway`.
- Миграции Alembic: `app/modules/llm_gateway/migrations/`, секция `[llm_gateway]` в `alembic.ini` (ADR-002).

| Таблица | Назначение | Описана в ТЗ |
|---|---|---|
| `llm_gateway.provider_bindings` | подключения провайдеров LLM и речи: `service` (`llm`, `speech`), `user_id`, `kind`, `name`, `base_url`, `default_model`, `extra_headers`, `agent_id`, `api_key_ciphertext`, `api_key_nonce`, `key_version`, `api_key_last4`, `jurisdiction`, `status` (`active`, `invalid`, `revoked`), `last_checked_at`, `last_error_code` | SYS-08-R6; этап 1 Г.6 (таблица), STU-01 (ввод ключей) |
| `llm_gateway.model_preferences` | выбор модели ученика: `user_id`, `scope_type` (`default`, `course`), `scope_id`, `provider_binding_id`, `llm_model` | SYS-08-R11; STU-03 |
| `llm_gateway.harness_settings` | настройки harness: `scope_type` (`default`, `course`, `learner_language`), `system_prompt_suffix`, `generation_params`, `mcp_servers`, `skills` | SYS-08-R23; STU-25 |
| `llm_gateway.usage_records` | запись расхода каждого вызова (без текстов); хранение 400 суток, затем удаление, суточные агрегаты без `user_id` — бессрочно (SYS-02) | SYS-08-R12; этап 1 Г.6 |
| `llm_gateway.usage_daily` | суточные агрегаты расхода без `user_id` (имя уточняется в ТЗ STU-01) | SYS-02, таблица категорий ПД |
| `llm_gateway.outbox`, `llm_gateway.processed_events`, `llm_gateway.jobs` | шаблоны ядра | SYS-04-R24, R26, R29 |

Модель платформы в таблицах не хранится: она задаётся конфигурацией `PLATFORM_LLM_*` (SYS-08-R8).

### 5.2. Redis

Префикс ключей: `llm_gateway:`.

| Шаблон ключа | Назначение | TTL | Описан в ТЗ |
|---|---|---|---|
| `llm_gateway:budget:platform:<YYYY-MM-DD>` | суточный бюджет токенов модели платформы | 48 ч | SYS-08-R9 |
| `llm_gateway:ratelimit:<scope>:<subject>` | лимиты `user_requests`, `user_streams`, `connection_test`, `embeddings` | равен окну | SYS-08-R14 |
| `llm_gateway:streams:<user_id>` | счётчик одновременных стримов пользователя | 180 с, продлевается дельтами | SYS-08-R14 |
| `llm_gateway:cb:<kind>:<host>` | состояние предохранителя провайдера | 60 с | SYS-08-R16 |

Поведение без Redis: вызов модели платформы — fail-closed (`503`, бюджет не проверить, SYS-08-R9); лимиты пользователя — fail-open с метрикой `flt_ratelimit_bypassed_total` (SYS-05-R15); предохранитель — работает по локальным ошибкам вызова без общего состояния.

### 5.3. MinIO

Не применимо: модуль не хранит файлов (кассеты заглушки — тестовые фикстуры в репозитории, SYS-08-R25).

### 5.4. OpenSearch

Не применимо: модуль не использует OpenSearch.

### 5.5. Qdrant

Не применимо: коллекции эмбеддингов объявляют модули-потребители (`materials`, `social`); шлюз только вычисляет векторы и возвращает `model_id` (ADR-014).

## 6. События Kafka

Контракт: `api/asyncapi.yaml` (на этапе 1 — первый контракт `asyncapi.yaml` проекта: канал WebSocket и топики модуля; создаётся на шаге 4 конвейера для Г.6).

### 6.1. Публикуемые топики

| Топик | Событие | Схема | Версия | Когда публикуется | Outbox |
|---|---|---|---|---|---|
| `flt.llm_gateway.provider_binding_created.v1` | подключение создано | `ProviderBindingCreated` (`provider_binding_id`, `user_id`, `service`, `kind`, `jurisdiction`) | 1 | этап 4 | да |
| `flt.llm_gateway.provider_binding_invalidated.v1` | подключение стало недействительным (`provider_auth`, отзыв согласия) | `ProviderBindingInvalidated` (`provider_binding_id`, `user_id`, `code`) | 1 | этап 1 (проверка подключения), этап 4 | да |
| `flt.llm_gateway.provider_binding_deleted.v1` | подключение удалено | `ProviderBindingDeleted` | 1 | этап 4 | да |
| `flt.llm_gateway.model_preference_changed.v1` | изменён выбор модели ученика | `ModelPreferenceChanged` (`user_id`, `scope_type`, `scope_id`) | 1 | этап 4 | да |
| `flt.llm_gateway.usage_recorded.v1` | записан расход вызова (агрегируемые поля, без текстов) | `UsageRecorded` | 1 | этап 1 | да |
| `flt.llm_gateway.platform_model_limit_reached.v1` | исчерпан суточный бюджет модели платформы | `PlatformModelLimitReached` (`date`, `budget_tokens`) | 1 | этап 2 | да |
| `flt.llm_gateway.jobs.reencrypt_keys.v1` (команда, `visibility = internal`) | перешифровать ключи новой версией | `ReencryptKeys` | 1 | при ротации ключа (ADR-013, раздел 3.4) | да |
| `flt.llm_gateway.jobs.prefill_model_preferences.v1` (команда, `visibility = internal`; отправитель — `courses`) | предзаполнить выбор модели по модели курса | `PrefillModelPreferences` (`user_id`, `course_id`, `course_default_model`) | 1 | этап 4 | да (outbox `courses`) |

### 6.2. Потребляемые топики

| Топик | Модуль-владелец | Обработчик | Идемпотентность | Ретраи и DLT |
|---|---|---|---|---|
| `flt.identity.user_deleted.v1` | identity | `on_user_deleted` (группа `flt.llm_gateway.on_user_deleted`) | inbox `llm_gateway.processed_events` по `event_id`; удаление идемпотентно | 1 с, 5 с, 25 с, затем `flt.identity.user_deleted.v1.dlq` |
| `flt.identity.consent_revoked.v1` | identity | `on_consent_revoked` (группа `flt.llm_gateway.on_consent_revoked`) | inbox по `event_id` | то же |
| `flt.llm_gateway.jobs.reencrypt_keys.v1` | llm_gateway | `reencrypt_keys` | inbox по `event_id`; перешифровка пачками по `key_version` | то же |
| `flt.llm_gateway.jobs.prefill_model_preferences.v1` | llm_gateway | `prefill_model_preferences` | inbox по `event_id`; `unique(user_id, scope_type, scope_id)` | то же |

## 7. REST-роутер и WebSocket-обработчики

### 7.1. REST

- Префикс: `/api/v1/llm-gateway` (SYS-03-R1).
- Контракт: `api/openapi.yaml` (создаётся на шаге 4 конвейера для Г.6 целиком; операции этапа 4 помечены `x-flt-stage: 4`, SYS-08-R27).
- REST-эндпоинта генерации нет: стрим — только WebSocket (ADR-009).

| Роутер | Ресурсы | Описан в ТЗ |
|---|---|---|
| `llm_gateway_router` (этап 1) | `GET /provider-kinds`; `POST /provider-bindings/{provider_binding_id}/test` (единственный синхронный вызов провайдера по REST, SYS-03-R27, раздел 6) | SYS-08-R7, R27; этап 1 Г.6 |
| `llm_gateway_router` (этап 4) | `GET`, `POST /provider-bindings`; `GET`, `PATCH`, `DELETE /provider-bindings/{provider_binding_id}`; `GET /provider-bindings/{provider_binding_id}/models`; `GET`, `PUT /model-preferences`; `GET /usage` | ТЗ STU-01, STU-03 |
| `llm_gateway_router` (этап 7) | настройки harness | ТЗ STU-25 |

Коды ошибок: `llm_gateway.<код SYS-08-R17>` (`provider_auth`, `model_not_found`, `rate_limited`, `context_too_long`, `capability_unsupported`, `consent_required`, `platform_model_forbidden`, `platform_budget_exhausted`, `no_model_configured`, `agent_offline`, `provider_unavailable`, `timeout`, `internal`) в конверте `ErrorResponseV1`.

### 7.2. WebSocket

Канал `llm_gateway.stream:<correlation_id>`; обработчик `api/ws.py` — первый `WsChannelHandler` проекта (SYS-04, раздел 4). Токены ответа через Redis pub/sub не идут: стрим исполняется на инстансе соединения (ADR-009, раздел 3.2), отмена `llm_gateway.completion.cancel` приходит по тому же соединению; при обрыве соединения стрим отменяется, при переподключении к другому инстансу клиент повторяет запрос (ADR-009).

| Тип сообщения | Направление | Схема | Канал Redis pub/sub | Описан в ТЗ |
|---|---|---|---|---|
| `llm_gateway.completion.request` | клиент → сервер | `CompletionRequestMessage` | — | ADR-009, раздел 3.1; этап 1 Г.6 |
| `llm_gateway.completion.cancel` | клиент → сервер | `CompletionCancelMessage` | — | ADR-009; этап 1 Г.6 |
| `llm_gateway.completion.start` | сервер → клиент | `CompletionStartMessage` | — (инстанс соединения) | ADR-009; этап 1 Г.6 |
| `llm_gateway.completion.delta` | сервер → клиент | `CompletionDeltaMessage` (`seq`, `text`, коалесценция `LLM_DELTA_FLUSH_MS`) | — | ADR-009; этап 1 Г.6 |
| `llm_gateway.completion.end` | сервер → клиент | `CompletionEndMessage` (`usage`, `finish_reason`) | — | ADR-009; этап 1 Г.6 |
| `llm_gateway.completion.error` | сервер → клиент | `CompletionErrorMessage` (`code` без префикса, `message` — ключ i18n, `retryable`, `retry_after_ms`, `partial_seq`) | — | ADR-009; SYS-08-R17; этап 1 Г.6 |

## 8. Секция настроек

Класс `LlmGatewaySettings`, `env_prefix="LLM_GATEWAY_"`, файл `envs/<стенд>/llm_gateway_<стенд>.env`; переменные, поименованные в ADR и SYS-08, принимаются через `validation_alias` без префикса (SYS-08-R30).

| Переменная | Тип | По умолчанию | Секрет | Назначение |
|---|---|---|---|---|
| `LLM_KEYS_ENCRYPTION_KEYS` | SecretStr (JSON `{"<version>": "<32 байта base64>"}`) | — | да | ключи шифрования API-ключей учеников (ADR-013) |
| `LLM_KEYS_ENCRYPTION_ACTIVE_VERSION` | str | — | нет | активная версия ключа шифрования |
| `PLATFORM_LLM_PROVIDER_KIND` | str | `openai_compatible` | нет | вид провайдера модели платформы |
| `PLATFORM_LLM_BASE_URL` | str | адрес российского провайдера (OQ-09) | нет | адрес модели платформы |
| `PLATFORM_LLM_MODEL` | str | по стенду | нет | имя модели платформы |
| `PLATFORM_LLM_API_KEY` | SecretStr | — | да | ключ платформы (ADR-013) |
| `PLATFORM_LLM_DAILY_TOKEN_BUDGET` | int | `2000000` | нет | суточный бюджет токенов модели платформы (OQ-09) |
| `LLM_RU_PROVIDER_HOSTS` | list[str] | перечень SYS-08-R10 | нет | хосты с юрисдикцией `ru` |
| `LLM_STUB_ENABLED` | bool | `true` на local, dev, test; `false` на prod (валидатор) | нет | регистрация вида `stub` |
| `LLM_STUB_MODE` | str (`scripted`, `replay`, `record`) | `scripted` | нет | режим заглушки (SYS-08-R25) |
| `LLM_STUB_DELTA_DELAY_MS` | int | `20` (в тестах `0`) | нет | задержка дельт заглушки (ADR-009) |
| `LLM_STUB_RECORD_ALLOWED` | bool | `false` | нет | разрешение записи кассет вне CI (SYS-10-R18) |
| `LLM_INTERACTIVE_TIMEOUT_SECONDS` | int | `120` | нет | общий таймаут интерактивного вызова |
| `LLM_TTFT_TIMEOUT_SECONDS` | int | `60` | нет | таймаут первой дельты |
| `LLM_INTER_DELTA_TIMEOUT_SECONDS` | int | `30` | нет | таймаут между дельтами |
| `LLM_CONNECT_TIMEOUT_SECONDS` | int | `10` | нет | таймаут соединения |
| `LLM_BACKGROUND_TIMEOUT_SECONDS` | int | `540` | нет | таймаут вызова из воркера |
| `LLM_DELTA_FLUSH_MS` | int | значение ADR-009 | нет | коалесценция дельт |
| `LLM_MAX_CONCURRENT_STREAMS_PER_CONNECTION` | int | `3` | нет | стримов на соединение (ADR-009) |
| `LLM_MAX_CONCURRENT_STREAMS_PER_USER` | int | `5` | нет | стримов на пользователя (SYS-08-R14) |
| `LLM_USER_REQUESTS_PER_MINUTE` | int | `60` | нет | лимит запросов пользователя |
| `LLM_USER_EMBEDDING_TEXTS_PER_MINUTE` | int | `2000` | нет | лимит текстов эмбеддингов |
| `LLM_EMBEDDINGS_BATCH_SIZE` | int | `64` | нет | размер пачки эмбеддингов |
| `LLM_TOKEN_ESTIMATE_CHARS_PER_TOKEN_<SCRIPT>` | float | значения SYS-08-R13 | нет | коэффициенты оценщика по письменности |
| `EMBEDDINGS_URL`, `EMBEDDINGS_MODEL` | str | пусто до этапа 5 | нет | контейнер эмбеддингов платформы (OQ-59) |
| `LLM_GATEWAY_CREDENTIALS_CONSUMERS` | dict[str, list[str]] | `{"speech": ["speech"]}` | нет | модули, которым выдаются учётные данные (SYS-08-R31) |

## 9. Права и роли

Полная матрица — SYS-06, раздел 3.3, таблица `llm_gateway`.

| Permission | Роли | Правило |
|---|---|---|
| `llm_gateway:providers:read` | аноним (для быстрого теста), `learner`, `platform_admin` | реестр видов провайдеров и моделей; этап 1 |
| `llm_gateway:provider_bindings:test` | `learner` (`own`, признак `L`) | проверка своего подключения; этап 1 |
| `llm_gateway:completions:create` | `learner` (`own`, `L`) | прямой стрим через канал `llm_gateway.stream`; модули вызывают сервис со своими правами |
| `llm_gateway:platform_model:use` | аноним (`own` по анонимной сессии) | только в быстром тесте и демо-уроке (SYS-08-R8); этап 2 |
| `llm_gateway:provider_bindings:create`, `update`, `delete`, `read` | `learner` (`own`, `L`) | этап 4 |
| `llm_gateway:usage:read` | `learner` (`own`), `platform_admin` (`any`, агрегаты без содержимого) | этап 4 |
| `llm_gateway:harness:manage` | `learner` (`own`, `L`) | этап 7 |
| `llm_gateway:platform_model:manage` | `platform_admin` (`any`) | лимиты и статистика модели платформы; этап 2 |

Права на `model-preferences` в матрице SYS-06 отсутствуют: они добавляются `changed`-версией SYS-06 вместе с ТЗ STU-03 (этап 4). Администратор платформы не читает ключи и содержимое запросов учеников (SYS-06-R15).

## 10. Наблюдаемость

### 10.1. Метрики

| Имя | Тип | Метки | Описана в ТЗ |
|---|---|---|---|
| `flt_llm_gateway_requests_total` | counter | `provider_kind`, `llm_model`, `operation`, `outcome` | SYS-08-R28 |
| `flt_llm_gateway_tokens_total` | counter | `provider_kind`, `llm_model`, `kind` (`prompt`, `completion`), `estimated` | SYS-08-R28 |
| `flt_llm_gateway_ttft_seconds` | histogram | `provider_kind` | SYS-08-R28 |
| `flt_llm_gateway_duration_seconds` | histogram | `provider_kind`, `operation` | SYS-08-R28 |
| `flt_llm_gateway_active_streams` | gauge | — | SYS-08-R28 |
| `flt_llm_gateway_circuit_state` | gauge | `provider_kind`, `host` | SYS-08-R28 |
| `flt_llm_gateway_platform_budget_used_tokens` | gauge | — | SYS-08-R28 |
| `flt_llm_gateway_usage_estimate_ratio` | histogram | — | SYS-08-R28 |
| `flt_llm_gateway_credentials_issued_total` | counter | `consumer_module`, `service` | SYS-08-R31 |
| `flt_llm_platform_overhead_seconds` (имя закреплено SYS-02-R2) | histogram | `segment` (`start`, `delta`) | SYS-02-R2 |

### 10.2. Логи

- Поле `module`: `llm_gateway`.
- События: `llm_gateway.call_finished` (`request_id`, `correlation_id`, `provider_kind`, `host`, `llm_model`, `purpose`, `prompt_name`, `prompt_version`, размеры, `outcome`, `code`), `llm_gateway.circuit_opened`, `llm_gateway.platform_budget_exhausted`, `llm_gateway.binding_invalidated`. Тексты запросов и ответов, ключи и `last4` не логируются (SYS-08-R18).

### 10.3. Дашборды и алерты

Дашборд `deploy/config/grafana/dashboards/llm-gateway.json` (запросы, TTFT, ошибки по кодам, активные стримы, бюджет модели платформы, состояние предохранителей; этап 1 Г.9); алерты `FltLlmPlatformBudgetHigh` (использовано больше 80 % суточного бюджета) и `FltLlmCircuitOpen` (предохранитель открыт дольше 5 минут) — этап 2.

## 11. Frontend-модуль

Папка: `src/features/llm-gateway`. Пространство ключей i18n: namespace `llm_gateway` (ключи ошибок `errors.llm_gateway.<код>` — в namespace `common`, SYS-07). На этапе 1 экранов нет: сквозной E2E Г.11 получает стриминговый ответ заглушки через общий `WsClient` (`app_shell`) и минимальную тестовую страницу диагностики стрима.

### 11.1. Страницы

| Страница | Роут | Роли | Описана в ТЗ |
|---|---|---|---|
| Диагностика стрима (только E2E этапа 1; удаляется или переносится в настройки на этапе 4) | `/dev/llm-stream` (только при `VITE_APP_ENABLE_DEV_PAGES=true`) | `learner` | SDD_plan.md, этап 1, Г.11 |
| Подключения моделей | `/settings/models` | `learner` | ТЗ STU-01 (этап 4) |
| Выбор модели | `/settings/models/preferences` | `learner` | ТЗ STU-03 (этап 4) |
| Расход токенов | `/settings/models/usage` | `learner` | ТЗ STU-01 (этап 4) |

### 11.2. API-хуки

| Хук | operationId | Назначение |
|---|---|---|
| `useLlmGatewayListProviderKinds` | `llm_gateway_listProviderKinds` | виды провайдеров (этап 1) |
| `useLlmGatewayTestProviderBinding` | `llm_gateway_testProviderBinding` | проверка подключения (этап 1) |
| `useLlmGatewayListProviderBindings`, `useLlmGatewayCreateProviderBinding` | `llm_gateway_listProviderBindings`, `llm_gateway_createProviderBinding` | подключения (этап 4) |

### 11.3. Подписки WebSocket

| Тип сообщения | Что обновляет |
|---|---|
| `llm_gateway.completion.start`, `delta`, `end`, `error` | вывод ответа модели с `lang` и `dir` (SYS-07); при `error` — сообщение по коду `errors.llm_gateway.<код>` |

### 11.4. Клиентское состояние

Не применимо на этапе 1: текст стрима держит компонент страницы до `end`; подключения и предпочтения — кэш TanStack Query (этап 4).

## 12. Готовность к выделению в микросервис

| Что потребуется | Описание | Готово сейчас |
|---|---|---|
| Замена вызовов в процессе на сетевые | `LlmGatewayService.complete`, `embed`, `resolve_model`, `ProviderCredentialsService` — на REST-клиент; `stream_completion` — на потоковый транспорт (gRPC или WebSocket между сервисами) | частично: интерфейсы есть, транспорт стрима между сервисами требует ADR |
| Отдельная БД | схема `llm_gateway` без FK наружу | да |
| Конфигурация | раздел 8 вместе с ключами шифрования | да |
| Развёртывание | контейнер сервиса; канал WebSocket `llm_gateway.stream` должен обслуживаться инстансом, держащим соединение клиента | нет: нужен ADR о маршрутизации каналов WebSocket |
| Известные препятствия | стрим исполняется на инстансе соединения (ADR-009); вклад `local` использует `LocalRuntimeService` в процессе | нет |

## 13. Вне рамок

- Тексты промптов и их шаблоны — модули-потребители (SYS-08-R15).
- Адаптеры речи и голосовые сессии — `speech` (этап 5).
- Песочница и модерация плагинов-провайдеров — SYS-13 (этап 7).
- Эмбеддинги у провайдера ученика (реализация `learner`) — не реализуется на этапах 1–5 (SYS-08-R21).
- Возобновление прерванного стрима — не делается: модуль-владелец диалога сохраняет частичный ответ с `interrupted = true` (ADR-004).

## 14. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-81](../../open-questions.md) | учётные данные провайдеров речи хранит `llm_gateway` | нет | open: рабочее решение утверждено |
| [OQ-59](../../open-questions.md) | модель и контейнер эмбеддингов платформы | нет | planned → ТЗ STU-27 |
| [OQ-58](../../open-questions.md) | модель для публикаций персонажа (может потребовать изменения SYS-08-R8) | нет | planned → ТЗ ADM-06 |
| [OQ-67](../../open-questions.md) | ключи AI-преподавателя в групповом занятии | нет | planned → спецификация `classroom` |
| [OQ-09](../../open-questions.md) | провайдер и лимиты модели платформы | нет | resolved |
| [OQ-45](../../open-questions.md) | модель платформы и модель курса по умолчанию | нет | resolved |

## 15. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-11 | Claude | Черновик | draft |
| 0.1 | 2026-10-11 | Claude | Передан на гейт G1 (PR блока В) | review |
