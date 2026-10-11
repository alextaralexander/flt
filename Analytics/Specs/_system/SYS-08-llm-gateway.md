# SYS-08 — LLM-шлюз

| Поле | Значение |
|---|---|
| Статус | draft |
| Версия | 0.2 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | VIS-03, STU-01 (STU-01.1–STU-01.4), STU-02, STU-03, STU-05, STU-12, STU-13, STU-25, STU-27, STU-28, STU-36, TCH-02 |
| Модуль | llm_gateway (владелец); speech (те же интерфейсы для провайдеров речи); local_runtime (транспорт провайдера `local`); все модули, вызывающие LLM (`lessons`, `assessment`, `dictionary`, `learning_plan`, `memorization`, `materials`, `avatar`, `promotion`); shared kernel (`app/core/crypto`, ограничитель, circuit breaker) |
| Зависимости | ADR-002, ADR-003, ADR-004, ADR-006, ADR-008, ADR-009, ADR-013, ADR-014; SYS-04 (конверт стрима) |
| Связанные ADR/SYS | ADR-010, ADR-005; SYS-02, SYS-03, SYS-05, SYS-06, SYS-09, SYS-10, SYS-13 |

## 1. Цель и область действия

- **Цель**: определить LLM-шлюз — единственную точку обращения платформы к языковым моделям: абстракцию провайдера и возможностей модели, реестр провайдеров как точку расширения, хранение подключений и зашифрованных API-ключей учеников, модель платформы и её лимиты, правило выбора модели для запроса, стриминг, учёт расхода токенов (включая оценку при отмене), квоты, версионирование промптов, устойчивость (таймауты, ретраи, circuit breaker), единые коды ошибок, безопасность ключей и детерминированную заглушку для тестов, а также зафиксировать тот же подход для провайдеров речи и границу настроек harness — так, чтобы любая функция работала с любым подключённым провайдером (LLM-агностичность).
- **Область действия**: backend (модуль `llm_gateway`, интерфейсы модуля `speech`, обёртки shared kernel), frontend (экраны подключений и расхода — только в части контрактов), tests (заглушка `stub`, кассеты), deploy (переменные конфигурации и секреты модели платформы и шифрования — одновременно в docker-compose и Helm через SYS-11).
- **Действует с этапа**: 1 (Г.6: интерфейс провайдера, модель платформы, провайдеры `stub` и `openai_compatible`, стриминг по WebSocket, запись расхода); подключения учеников — этап 4 (STU-01, STU-03, STU-05), локальные модели через агента — этапы 4–5, провайдеры речи — этап 5, эмбеддинги — этап 5 (STU-27), harness, MCP и плагины-провайдеры — этап 7.
- **Уточняет**: CLAUDE.md, разделы «Технологический стек» (строка «LLM-интеграция» с пометкой о едином адаптере, которую закрывает эта спецификация; синтез и распознавание речи через провайдеров), «Ключевые архитектурные требования» (LLM-агностичность, API-ключи учеников зашифрованы, модель платформы только в быстром тесте), «О проекте»; ADR-009 (интерфейс провайдера с `stream_completion`, `Delta`, `Usage`, оценка usage, таблица `usage_records`, интерфейсы `STTProvider`/`TTSProvider`), ADR-013 (раздел 3.4: AES-256-GCM, `key_version`, последние 4 символа), ADR-008 (провайдер `local` с транспортом `local_runtime`), ADR-014 (интерфейс `EmbeddingsProvider`), ADR-006 (согласие `foreign_llm_transfer`). Решает OQ-26 (единый адаптер), OQ-45 (модель платформы и модель курса по умолчанию), OQ-73 (оценка usage при отмене); фиксирует место harness в `llm_gateway` (часть OQ-57) и интерфейс эмбеддингов (часть OQ-59).

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| Провайдер LLM, модель, внешняя модель, локальная модель, модель платформы, модель курса по умолчанию, возможности модели, API-ключ ученика, ключ шифрования, LLM-шлюз, провайдер эмбеддингов, стриминг, промпт, версия промпта, токен LLM, учёт токенов, заглушка LLM, провайдер речи, TTS, STT, голос | [глоссарий](../../glossary.md), раздел 5 |
| AI-преподаватель, персонаж платформы | [глоссарий](../../glossary.md), разделы 1 и 6 |
| Harness, MCP-сервер, скил, точка расширения, плагин | [глоссарий](../../glossary.md), раздел 10 |
| Быстрый тест без регистрации, лимит запросов | [глоссарий](../../glossary.md), раздел 11 |
| Локальный агент, локальный runtime (модуль), локальный движок | [глоссарий](../../glossary.md), раздел 5 |
| Подключение провайдера (`provider_binding`) | Запись `llm_gateway.provider_bindings`: вид провайдера, адрес, модель по умолчанию и зашифрованный ключ ученика (или идентификатор агента для `local`); единица, которую ученик создаёт в STU-01/STU-05 и выбирает в STU-03 (SYS-08-R6) |
| Вид провайдера (`provider_kind`) | Код реализации адаптера в реестре провайдеров: `openai_compatible`, `anthropic`, `gigachat`, `yandexgpt`, `local`, `stub`; `plugin.<plugin_id>.<kind>` для плагинов (SYS-08-R4) |
| Запись расхода (`usage_record`) | Строка `llm_gateway.usage_records` об одном вызове модели: кто, провайдер, модель, назначение, токены, признак оценки, версия промпта (SYS-08-R12) |
| Назначение вызова (`purpose`) | Строка `<module>.<purpose>` от вызывающего модуля (`lessons.tutor_reply`, `dictionary.entry`, `assessment.quick_test`), по которой группируется расход (SYS-08-R12) |
| Юрисдикция провайдера (`jurisdiction`) | Признак `ru` или `foreign` у вида провайдера и хоста: передача данных провайдеру `foreign` требует согласия `foreign_llm_transfer` (SYS-08-R10) |
| Кассета (`cassette`) | Файл записанного ответа провайдера для режима replay заглушки (SYS-08-R25) |

## 3. Требования

### SYS-08-R1 Все вызовы моделей — только через LLM-шлюз

- **Формулировка**: модуль платформы не должен обращаться к провайдерам LLM, эмбеддингов и речи напрямую: вызов идёт только через публичный API `LlmGatewayService` (LLM и эмбеддинги) и `SpeechService` (STT и TTS); пакеты `openai`, `anthropic`, `tiktoken`, `litellm`, `langchain`, `gigachat`, `yandexcloud` и `httpx`-клиенты к хостам провайдеров разрешены только внутри `app/modules/llm_gateway` и `app/modules/speech`.
- **Обоснование**: CLAUDE.md «Ключевые архитектурные требования» (не завязываться на API вендора вне слоя адаптеров); глоссарий «LLM-шлюз» (все вызовы LLM идут только через него); OQ-26 (вариант 1: собственный тонкий интерфейс, LiteLLM допустим только как реализация адаптера).
- **Проверка**: контракт import-linter `llm-clients-only-in-gateway` (`type = forbidden`, `source_modules = app.modules` кроме `app.modules.llm_gateway` и `app.modules.speech`, `forbidden_modules` — перечисленные пакеты) в `.importlinter` (ADR-002); AST-тест `test_no_provider_hosts_outside_gateway` (строковые литералы хостов `api.openai.com`, `api.anthropic.com`, `llm.api.cloud.yandex.net`, `gigachat.devices.sberbank.ru` отсутствуют вне двух модулей).
- **Применимость**: backend, tests.

### SYS-08-R2 Интерфейс провайдера LLM

- **Формулировка**: каждый адаптер провайдера должен реализовывать `@runtime_checkable` `Protocol` `LLMProvider` из `app/modules/llm_gateway/public/providers.py` со свойством `kind: str` (вид провайдера из `ProviderKindInfo`) и методами: `async def complete(self, request: CompletionRequest) -> CompletionResult`; `def stream_completion(self, request: CompletionRequest) -> AsyncIterator[Delta]` (async-генератор: `Delta(seq, kind ∈ text | tool_call | reasoning | usage, text, tool_call, usage, finish_reason)`, последняя дельта — `kind="usage"` с `Usage` и `finish_reason`); `async def list_models(self) -> list[ModelInfo]`; `async def capabilities(self, llm_model: str) -> ModelCapabilities`; `async def check_connection(self) -> ConnectionCheck`; `def count_tokens(self, request: CompletionRequest) -> int | None` (`None`, если токенизатор неизвестен — тогда работает оценщик SYS-08-R13); исключения адаптера — только подклассы `ProviderError` с полем `code` из SYS-08-R17; эмбеддинги — отдельный `Protocol` `EmbeddingsProvider` (SYS-08-R21).
- **Обоснование**: ADR-009, разделы 3.3 и 4.3 (интерфейс с `stream_completion`, `Delta`, `Usage`); OQ-26 (единый адаптер для внешних и локальных моделей: вызывающие модули не различают провайдеров); разделение `complete` и `stream_completion` позволяет адаптеру без стриминга (ADR-009: `capabilities.streaming = false`) эмулировать `stream_completion` одной дельтой. Экземпляр адаптера создаётся фабрикой вида провайдера на одно подключение (SYS-08-R4), поэтому методы не принимают параметров подключения; эти сигнатуры — контракт точки расширения `llm_gateway.providers` (SYS-09-R7).
- **Проверка**: архитектурный тест `test_providers_implement_protocol` (каждый класс, зарегистрированный в `ProviderRegistry`, проходит `isinstance(..., LLMProvider)` с `runtime_checkable` и покрыт параметризованным набором тестов `tests/modules/llm_gateway/providers/test_provider_contract.py`: порядок дельт, финальная `usage`, исключения только `ProviderError`); `mypy strict`.
- **Применимость**: backend, tests.

### SYS-08-R3 Возможности модели

- **Формулировка**: `ModelCapabilities` должен содержать поля `streaming: bool`, `tools: bool`, `vision: bool`, `audio_input: bool`, `audio_output: bool`, `json_mode: bool`, `max_context_tokens: int`, `max_output_tokens: int`, `supports_system_role: bool`; шлюз должен проверять запрос против возможностей до вызова провайдера и отклонять его ошибкой `llm_gateway.capability_unsupported` с `details.capability`; источник значений — статический справочник адаптера по известным моделям (`known_models.py` адаптера), ответ провайдера (`/v1/models` для `openai_compatible` и движков агента) и значения по умолчанию адаптера для неизвестной модели (`streaming=true`, остальные булевы `false`, `max_context_tokens=8192`, `max_output_tokens=2048`); вызывающий модуль получает возможности через `LlmGatewayService.capabilities(provider_binding_id, llm_model)` и обязан адаптировать сценарий (например, выключать голосовой ответ без `audio_output`).
- **Обоснование**: SDD_plan.md Б.8 (возможности моделей: стриминг, tools, аудио, изображения); глоссарий «Возможности модели»; LLM-агностичность требует явной деградации, а не падения на неподдерживаемой возможности.
- **Проверка**: unit-тесты `tests/modules/llm_gateway/test_capabilities.py` (отклонение до вызова провайдера — провайдер-заглушка фиксирует отсутствие вызова); контрактный тест схемы `LlmGatewayModelCapabilitiesResponse`.
- **Применимость**: backend, frontend, tests.

### SYS-08-R4 Реестр провайдеров

- **Формулировка**: виды провайдеров должны регистрироваться в `ProviderRegistry` shared-части модуля вызовом `registry.register(ProviderKindInfo(kind, factory, jurisdiction, auth_mode ∈ api_key | agent | none, display_name_key, default_base_url, stage))`, где `factory: Callable[[ProviderBindingConfig, ProviderCredentials | None], LLMProvider]` создаёт адаптер на одно подключение (`ProviderBindingConfig` — `provider_binding_id`, `base_url`, `default_model`, `extra_headers`, `agent_id`; `ProviderCredentials` — SYS-08-R31); `ProviderKindInfo` — контракт вклада в точку расширения `llm_gateway.providers` (SYS-09-R7); на этапе 1 регистрируются `openai_compatible` (`jurisdiction` зависит от хоста — SYS-08-R10) и `stub` (только при `LLM_STUB_ENABLED=true`, недоступен на стенде prod — валидатор настроек); на этапе 4 — `anthropic`, `gigachat`, `yandexgpt` (последний — тонкая настройка `openai_compatible` с `base_url` и заголовками Yandex Cloud), `local` (ADR-008); реестр — точка расширения для плагинов (SYS-09): плагин регистрирует вид `plugin.<plugin_id>.<kind>` через тот же вызов, а изоляция и права — SYS-13 (этап 7); неизвестный `kind` при создании подключения — `422 core.validation_failed`; `GET /api/v1/llm-gateway/provider-kinds` отдаёт зарегистрированные виды, доступные текущему стенду и роли.
- **Обоснование**: CLAUDE.md «Расширяемость» (реестр провайдеров — точка расширения, закладывается в каркас); SDD_plan.md Г.6 (один OpenAI-совместимый провайдер на этапе 1), этап 4 STU-01.1–STU-01.4; ADR-009 (`stub`); ADR-008 (`local`); OQ-09 (российский провайдер через OpenAI-совместимый адаптер).
- **Проверка**: unit-тест `tests/modules/llm_gateway/test_provider_registry.py` (регистрация, дубликат → ошибка, `stub` скрыт без флага); архитектурный тест `test_registry_is_only_provider_source` (AST: экземпляры адаптеров создаются только через `ProviderRegistry.create`); тест настроек `test_stub_disabled_on_prod`.
- **Применимость**: backend, tests.

### SYS-08-R5 Адаптер `openai_compatible`

- **Формулировка**: адаптер `openai_compatible` должен использовать `POST {base_url}/chat/completions` (при `stream=true` — SSE `data: {...}`, `data: [DONE]`, `stream_options: {"include_usage": true}`), `GET {base_url}/models`, `POST {base_url}/embeddings` (для `EmbeddingsProvider` на том же подключении), поддерживать `tools`, `response_format: {"type": "json_object"}`, изображения в `content` частями `image_url`; принимать конфигурацию `base_url` (HTTPS обязателен, кроме `http://127.0.0.1` и `http://localhost` внутри агента), `api_key`, `extra_headers` (не более 5, без `Authorization`), `default_model`; этим же адаптером шлюз формирует тело запроса для локальных движков (агент тело не изменяет — ADR-008, раздел 3.4) и для модели платформы (OQ-09).
- **Обоснование**: ADR-009, раздел 3.3 (SSE-парсер OpenAI-совместимого формата, `include_usage`); ADR-008, раздел 3.4 (LM Studio и `llama-server` — OpenAI-совместимый API); OQ-09 (YandexGPT и GigaChat через OpenAI-совместимый адаптер; GigaChat на этапе 4 получает собственный адаптер из-за OAuth-токена доступа и самоподписанного сертификата — STU-01.4).
- **Проверка**: тесты адаптера на `respx`-моках `tests/modules/llm_gateway/providers/test_openai_compatible.py` (SSE-поток, `[DONE]`, usage в последнем чанке, ошибки 401/429/5xx → коды SYS-08-R17, запрет `http://` для внешних хостов).
- **Применимость**: backend, tests.

### SYS-08-R6 Подключение провайдера и хранение ключа

- **Формулировка**: подключение провайдера (LLM и речи) должно храниться в таблице `llm_gateway.provider_bindings` с колонками `id`, `service` ∈ `llm | speech` (вид из `ProviderRegistry` или `SpeechProviderRegistry` соответственно, OQ-81), `user_id` (UUID без FK; `NULL` только у подключения модели платформы, которое не хранится в таблице, а задаётся конфигурацией — SYS-08-R8), `kind`, `name` (до 64 символов, уникально в паре с `user_id`), `base_url`, `default_model`, `extra_headers jsonb`, `agent_id` (только для `local`), `api_key_ciphertext bytea`, `api_key_nonce bytea(12)`, `key_version text`, `api_key_last4 text`, `jurisdiction`, `status` ∈ `active | invalid | revoked`, `last_checked_at`, `last_error_code`, `created_at`, `updated_at`, `version`; ключ шифруется в `SecretBox` shared kernel (`app/core/crypto/secret_box.py`) алгоритмом AES-256-GCM со случайным nonce 12 байт, AAD = `user_id || connection_id` и ключом `LLM_KEYS_ENCRYPTION_KEYS[LLM_KEYS_ENCRYPTION_ACTIVE_VERSION]`; открытый ключ существует только в памяти процесса на время запроса к провайдеру, в ответах API возвращаются только `api_key_last4` и `has_api_key`; `PATCH` с новым ключом перешифровывает; смена активной версии ключа шифрования и перешифровка фоновым заданием — по ADR-013, раздел 3.4; ключ длиной до 512 символов, пробелы по краям отсекаются.
- **Обоснование**: CLAUDE.md «Ключевые архитектурные требования» (API-ключи учеников зашифрованы, ключ шифрования в Vault или `.env`); ADR-013, раздел 3.4 (AES-256-GCM, nonce, AAD, `key_version`, последние 4 символа, ротация); ADR-003 (`bytea` только для криптоматериала до 4 КиБ; `version` и базовые колонки).
- **Проверка**: unit-тесты `tests/core/crypto/test_secret_box.py` (расшифровка с чужим AAD падает, ротация версий); интеграционный тест `tests/modules/llm_gateway/test_provider_bindings.py` (ключ не возвращается ни одним эндпоинтом — проверка всех ответов регулярным выражением на введённый ключ; `last4` корректен); архитектурный тест `test_no_plain_api_key_columns` (в метаданных модуля нет колонок с именами `api_key`, `token`, `secret` типа `text`).
- **Применимость**: backend, tests.

### SYS-08-R7 Проверка подключения

- **Формулировка**: `POST /api/v1/llm-gateway/provider-bindings/{provider_binding_id}/test` должен выполнять `check_connection()` адаптера синхронно с общим таймаутом 10 с (`list_models`, а при его отсутствии у провайдера — `complete` с одним сообщением `ping` и `max_tokens=1`), записывать `last_checked_at`, `last_error_code` и `status` (`active` при успехе, `invalid` при `provider_auth`), возвращать `200` с `{"ok": bool, "code": "<код SYS-08-R17 или null>", "models_count": <int или null>, "latency_ms": <int>}`; проверка при создании подключения выполняется автоматически; это единственная операция REST с синхронным вызовом провайдера (исключение SYS-03-R27).
- **Обоснование**: STU-01 («проверить соединение» — ADR-009, раздел 3.1); результат нужен пользователю немедленно; ограничение таймаутом укладывается в `timeout server 60s` HAProxy (ADR-012).
- **Проверка**: интеграционный тест с `respx` (успех, 401 → `invalid`, таймаут → `provider_unavailable`, `latency_ms`); лимит `llm_gateway:ratelimit:connection_test:<user_id>` — 10 в минуту (SYS-08-R14).
- **Применимость**: backend, tests.

### SYS-08-R8 Модель платформы (решает OQ-45)

- **Формулировка**: термины должны различаться так: **модель платформы** (`platform_model`) — модель, подключённая платформой по её ключу из конфигурации (`PLATFORM_LLM_PROVIDER_KIND=openai_compatible`, `PLATFORM_LLM_BASE_URL`, `PLATFORM_LLM_MODEL`, секрет `PLATFORM_LLM_API_KEY`); это и есть «модель по умолчанию» из SDD_plan.md Г.6; **модель курса по умолчанию** (`course_default_model`) — атрибут курса в модуле `courses` (вид провайдера и имя модели), который только предзаполняет выбор ученика при записи на курс и никогда не даёт доступа к ключу платформы. Модель платформы должна быть доступна только анонимному вызову из быстрого теста (`actor.kind = anonymous`, `purpose = assessment.quick_test` или `lessons.demo_lesson`); вызов от аутентифицированного пользователя или с иным `purpose` отклоняется ошибкой `llm_gateway.platform_model_forbidden`, в том числе как запасной вариант при отказе ключа ученика; посетитель может вместо модели платформы ввести свой ключ — он держится только в Redis `assessment:quick_test:<session_id>` (TTL 24 ч, шифруется `SecretBox` с AAD = `session_id`) и в PostgreSQL не сохраняется.
- **Обоснование**: CLAUDE.md «О проекте» (модель платформы — только быстрый тест без регистрации); OQ-45 (подтвердить тождество, запретить доступ зарегистрированным, развести с моделью курса); OQ-09 (российский провайдер через OpenAI-совместимый адаптер, ключ не сохраняется); ADR-013 (`PLATFORM_LLM_API_KEY`).
- **Проверка**: unit-тесты `tests/modules/llm_gateway/test_platform_model.py` (аутентифицированный актор → `platform_model_forbidden`; `purpose` вне списка → отказ; аноним с `quick_test` → вызов провайдера); архитектурный тест `test_platform_key_not_in_db` (ни одна модель SQLAlchemy не хранит `PLATFORM_LLM_API_KEY`); правка SDD_plan.md Г.6 на термин «модель платформы» — оркестратор после утверждения.
- **Применимость**: backend, tests.

### SYS-08-R9 Лимиты модели платформы

- **Формулировка**: шлюз должен вести глобальный суточный бюджет модели платформы в Redis (`llm_gateway:budget:platform:<YYYY-MM-DD UTC>`, счётчик токенов с TTL 48 ч; значение по умолчанию `PLATFORM_LLM_DAILY_TOKEN_BUDGET=2000000`, помечено «уточняется после запуска») и отклонять вызов при исчерпании ошибкой `llm_gateway.platform_budget_exhausted` с предложением ввести свой ключ (ключ i18n в `message_key`); в бюджет засчитываются фактические токены, а при оценке — оценённые с коэффициентом 1,2 (SYS-08-R13); при недоступности Redis вызов модели платформы отклоняется `503 core.service_unavailable` с `Retry-After: 30` (fail-closed); лимиты сессии быстрого теста (`QUICK_TEST_MAX_MESSAGES=20`, `QUICK_TEST_MAX_MINUTES=15`) и на IP (`QUICK_TEST_PER_IP_PER_DAY=3`) принадлежат модулю `assessment` (ТЗ VIS-03) и проверяются до обращения к шлюзу; все значения — параметры конфигурации.
- **Обоснование**: OQ-09 (стартовые лимиты как параметры конфигурации; «уточняются после запуска»); ADR-003, таблица отказа Redis (лимиты модели платформы — fail-closed: платформа не тратит токены без учёта); разделение владения: сессия и IP — свойства быстрого теста, бюджет — свойство ключа платформы.
- **Проверка**: интеграционный тест `tests/modules/llm_gateway/test_platform_budget.py` (исчерпание, учёт оценённых токенов ×1,2, отказ без Redis); тест на N инстансах `tests/n_instances/llm_gateway/test_platform_budget_global.py` (бюджет расходуется запросами через разные инстансы — SYS-05).
- **Применимость**: backend, deploy, tests.

### SYS-08-R10 Юрисдикция провайдера и согласие на передачу данных

- **Формулировка**: каждому виду провайдера и хосту должна присваиваться юрисдикция: `ru` для хостов из конфигурируемого списка `LLM_RU_PROVIDER_HOSTS` (по умолчанию `llm.api.cloud.yandex.net`, `gigachat.devices.sberbank.ru`) и для `local` (данные не покидают компьютер ученика и платформу), `foreign` для всех остальных, включая произвольный `base_url` `openai_compatible`; создание или использование подключения с `jurisdiction = foreign` аутентифицированным пользователем без действующего согласия `foreign_llm_transfer` (ADR-006, таблица `consents`; проверка через `IdentityService.has_consent(user_id, "foreign_llm_transfer")`) отклоняется ошибкой `403 llm_gateway.consent_required` с `details.consent_kind`; отзыв согласия переводит подключения `foreign` в `status = revoked` по событию `identity.consent_revoked`; модель платформы — `ru` (OQ-09), иной выбор провайдера платформы требует экрана согласия посетителя (SYS-02).
- **Обоснование**: CLAUDE.md «Персональные данные» (отдельное согласие на передачу данных зарубежным LLM-провайдерам, 152-ФЗ); ADR-006 (`consents.kind = foreign_llm_transfer`); ADR-009, раздел 3.7 (то же согласие для провайдеров речи); OQ-09 (российский провайдер платформы снимает согласие посетителя).
- **Проверка**: интеграционные тесты `tests/modules/llm_gateway/test_jurisdiction.py` (хосты списка → `ru`; произвольный → `foreign`; без согласия → 403; событие отзыва → `revoked`); тексты согласия и экран — SYS-02 и ТЗ VIS-04.
- **Применимость**: backend, tests.

### SYS-08-R11 Выбор модели для запроса

- **Формулировка**: `LlmGatewayService.resolve_model(actor, context) -> ModelSelection(provider_binding_id, llm_model)` должен выбирать модель в порядке приоритета: (1) явный выбор в запросе (`provider_binding_id` и `llm_model`, переданные вызывающим модулем из действия пользователя); (2) выбор ученика для курса из `llm_gateway.model_preferences` со `scope_type = course` и `scope_id = course_id` (при записи на курс предзаполняется из `course_default_model`, но всегда ссылается на подключение самого ученика); (3) выбор ученика по умолчанию (`scope_type = default`); при отсутствии всех трёх — ошибка `llm_gateway.no_model_configured` (UI ведёт в настройку модели, STU-03); подключение может использоваться только своим владельцем: `provider_bindings.user_id` обязан совпадать с `actor.user_id`, иначе `404 core.not_found` (SYS-03-R22); модель платформы в приоритет не входит (SYS-08-R8); таблица `llm_gateway.model_preferences` (`id`, `user_id`, `scope_type` ∈ `default | course`, `scope_id`, `provider_binding_id`, `llm_model`, базовые колонки; уникальность `(user_id, scope_type, scope_id)`) принадлежит `llm_gateway`, модуль `learner_profile` читает её через публичный API для экрана профиля.
- **Обоснование**: STU-03 (выбор внешней или локальной модели), TCH-02 (LLM по умолчанию курса — рекомендация преподавателя), OQ-45 (модель курса не даёт доступа к чужому ключу); политика «ключ ученика — только для ученика» (задание оркестратора; использование ключей в групповых занятиях — OQ-67, вне рамок).
- **Проверка**: unit-тесты `tests/modules/llm_gateway/test_resolve_model.py` (все ветки приоритета, чужое подключение → 404, отсутствие → `no_model_configured`); владение таблицей — SYS-01 (замечание в отчёте).
- **Применимость**: backend, tests.

### SYS-08-R12 Запись расхода токенов

- **Формулировка**: каждый вызов модели (успешный, отменённый, завершившийся ошибкой после начала генерации, проверка подключения, эмбеддинги) должен порождать строку `llm_gateway.usage_records`: `id`, `user_id` (UUID или `NULL`), `anonymous_session_id` (для быстрого теста), `provider_binding_id` (`NULL` для модели платформы), `provider_kind`, `jurisdiction`, `llm_model`, `purpose` (`<module>.<purpose>`, передаётся вызывающим модулем обязательно), `operation` ∈ `completion | stream | embedding | connection_test`, `prompt_name`, `prompt_version` (`NULL` для вызовов без шаблона), `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated bool`, `finish_reason`, `duration_ms`, `ttft_ms`, `correlation_id`, `request_id`, `created_at`; для интерактивного стрима запись выполняется синхронно до отправки `end` клиенту, для фонового задания — воркером по завершении (ADR-009, раздел 3.2); содержимое промптов и ответов в таблицу не пишется; агрегаты для ученика (`GET /api/v1/llm-gateway/usage?period=day|week|month`) считаются по этой таблице; срок хранения строк — SYS-02 (предлагается 400 суток, затем агрегирование по суткам).
- **Обоснование**: SDD_plan.md Б.8 (учёт расхода токенов); ADR-009 (структура `usage_records` — SYS-08; `usage` в `end`); глоссарий «Учёт токенов» (по ученику, модели и задаче — основа лимитов модели платформы).
- **Проверка**: интеграционные тесты `tests/modules/llm_gateway/test_usage_records.py` (запись при `stop`, `cancelled`, `error`, `connection_test`, `embedding`; `purpose` обязателен — `ValueError` без него); архитектурный тест `test_usage_has_no_text_columns` (в модели `UsageRecord` нет колонок `text`, `jsonb` с промптами); контракт `LlmGatewayUsageSummaryResponse`.
- **Применимость**: backend, tests.

### SYS-08-R13 Оценка расхода при отмене и ошибке (решает OQ-73)

- **Формулировка**: если провайдер не вернул `usage` (отмена, разрыв, ошибка после первого токена, провайдер без `usage`), шлюз должен оценить расход и записать его с `estimated = true`: `prompt_tokens` — `count_tokens()` адаптера, а при `None` — оценщиком shared-части модуля `TokenEstimator`: `tiktoken` с кодировкой `o200k_base` для моделей, у которых адаптер объявил `tokenizer = "tiktoken:o200k_base"`, иначе по символам с коэффициентами по письменности текста (латиница — 4,0 символа на токен, кириллица — 3,0, арабская вязь — 2,5, иероглифы — 1,2; смешанный текст — взвешенно по доле символов); `completion_tokens` — тем же оценщиком по накопленному тексту дельт (при отмене до первого токена — 0); оценка идёт в лимиты модели платформы с коэффициентом 1,2 (SYS-08-R9) и в статистику ученика с пометкой «оценка» (`estimated` в ответе `usage`); коэффициенты — параметры конфигурации `LLM_TOKEN_ESTIMATE_CHARS_PER_TOKEN_<SCRIPT>` и уточняются после запуска по расхождению с фактическим `usage` (метрика `flt_llm_gateway_usage_estimate_ratio`).
- **Обоснование**: OQ-73 (рекомендация: оценивать; `prompt_tokens` — по предыдущему подтверждённому usage той же модели или оценщиком; `completion_tokens` — по тексту; консервативно в лимиты; флаг `estimated`); ADR-009, раздел 3.1 (`end` всегда содержит `usage`, при `cancelled`/`error` — оценка); вариант «по предыдущему usage той же модели» из OQ-73 не принят: он требует хранить промпты или их длины и даёт ошибку при разной длине контекста — оценщик по тексту проще и воспроизводим.
- **Проверка**: unit-тесты `tests/modules/llm_gateway/test_token_estimator.py` (четыре письменности, смешанный текст, `tiktoken` при объявленном токенизаторе); интеграционный тест отмены стрима (запись с `estimated = true`, `completion_tokens > 0` после дельт, 0 до первой дельты); метрика в `tests/core/metrics`.
- **Применимость**: backend, tests.

### SYS-08-R14 Квоты и лимиты запросов

- **Формулировка**: шлюз должен применять ограничитель shared kernel (скользящее окно в Redis, ADR-003) с ключами `llm_gateway:ratelimit:<scope>:<subject>` и значениями по умолчанию: `user_requests` — `LLM_USER_REQUESTS_PER_MINUTE=60` на пользователя; `user_streams` — `LLM_MAX_CONCURRENT_STREAMS_PER_USER=5` одновременных стримов на пользователя (счётчик `llm_gateway:streams:<user_id>` с TTL 180 с, продлевается дельтами) поверх `LLM_MAX_CONCURRENT_STREAMS_PER_CONNECTION=3` на соединение (ADR-009); `connection_test` — 10 в минуту на пользователя; `embeddings` — `LLM_USER_EMBEDDING_TEXTS_PER_MINUTE=2000` текстов; превышение — ошибка `rate_limited` (`retryable: true`, `retry_after_ms`) в стриме или `429 core.rate_limited` в REST; для зарегистрированных пользователей лимиты fail-open без Redis (метрика `flt_ratelimit_bypassed_total`), для модели платформы — fail-closed (SYS-08-R9); значения — конфигурация модуля.
- **Обоснование**: ADR-003, раздел 2.7 (ограничитель) и таблица отказа Redis; ADR-009 (лимит стримов на соединение); OQ-13 (50 одновременных стримов на платформу); расход токенов ученика с его собственного ключа платформой не ограничивается — лимиты защищают инфраструктуру, а не бюджет ученика.
- **Проверка**: интеграционные тесты `tests/modules/llm_gateway/test_rate_limits.py`; тест на N инстансах `tests/n_instances/llm_gateway/test_llm_stream_limit_global.py` (шестой стрим одного пользователя через другой инстанс → `rate_limited`).
- **Применимость**: backend, deploy, tests.

### SYS-08-R15 Версионирование промптов

- **Формулировка**: промпт платформы должен объявляться в коде вызывающего модуля файлом `app/modules/<module>/prompts/<name>.py` объектом `PromptTemplate(name="<module>.<name>", version=<int ≥ 1>, template=<строка Jinja2 без включений файлов>, variables=<перечень имён>, content_hash="<sha256 первых 16 hex текста шаблона>", description)` и собираться в кортеж `PROMPTS` модуля; любое изменение текста шаблона обязано увеличивать `version` (проверяется по `content_hash`); шлюз принимает в `CompletionRequest` поле `prompt_ref = (name, version)` и записывает его в `usage_records`; вызывающий модуль сохраняет `prompt_name` и `prompt_version` в артефактах генерации, для которых ТЗ требует перегенерации (словарная статья STU-12, набор слов STU-34, программа обучения STU-18); промпт рендерится вызывающим модулем, шлюз текст не изменяет, кроме добавления настроек harness (SYS-08-R23).
- **Обоснование**: SDD_plan.md Б.8 (версионирование промптов); глоссарий «Версия промпта» (сохраняется вместе с результатом, чтобы перегенерировать новой версией); STU-12 (словарная статья хранит модель и версию промпта).
- **Проверка**: архитектурный тест `tests/architecture/test_prompt_templates.py` (для каждого `PromptTemplate` всех модулей реестра `sha256(template)[:16] == content_hash`; имена уникальны и начинаются с имени модуля; `version` ≥ 1); тест `tests/modules/llm_gateway/test_usage_records.py::test_prompt_ref_recorded`; при изменении текста без `version` падает архитектурный тест.
- **Применимость**: backend, tests.

### SYS-08-R16 Таймауты, ретраи и circuit breaker

- **Формулировка**: шлюз должен применять таймауты `LLM_CONNECT_TIMEOUT_SECONDS=10`, `LLM_TTFT_TIMEOUT_SECONDS=60` (первая дельта), `LLM_INTER_DELTA_TIMEOUT_SECONDS=30`, `LLM_INTERACTIVE_TIMEOUT_SECONDS=120` (весь интерактивный запрос; для `complete` — общий таймаут), `LLM_BACKGROUND_TIMEOUT_SECONDS=540` (вызов из воркера, меньше `max.poll.interval.ms`); повторять запрос не более 2 раз с задержками 0,5 и 2 с только при ошибках соединения, таймауте соединения, HTTP 5xx и 429 с `Retry-After ≤ 5 с`, и только пока от провайдера не получена ни одна дельта; вести circuit breaker на пару `(provider_kind, host)` в Redis через shared kernel `RedisCircuitBreaker` (`llm_gateway:cb:<kind>:<host>`: окно 60 с, порог 5 ошибок класса `provider_unavailable` или доля ≥ 50 % при ≥ 10 вызовах, состояние `open` 30 с, `half_open` — 3 пробных вызова, 2 успеха закрывают); при `open` — ошибка `provider_unavailable` (`retryable: true`, `retry_after_ms`) без обращения к провайдеру; ошибки `provider_auth`, `context_too_long`, `content_filtered`, `capability_unsupported` breaker не учитывает; класс `py_main_lib.adapters.circuit_breaker.CircuitBreaker` не используется: его состояние живёт в памяти процесса (каждый инстанс учится отдельно — противоречит правилу «лимиты и блокировки действуют глобально»), по умолчанию считает ошибкой любое `Exception`, а ветка `S3CircuitBreaker` не относится к LLM.
- **Обоснование**: ADR-009, раздел 3.3 (таймауты 10 с, 60 с, 30 с; `LLM_INTERACTIVE_TIMEOUT_SECONDS`); ADR-003 (состояние только в Redis, in-memory состояние между запросами запрещено, лимиты глобальны); ретраи после первой дельты запрещены, потому что ответ уже частично доставлен клиенту и повтор удвоил бы расход.
- **Проверка**: unit-тесты `tests/core/resilience/test_redis_circuit_breaker.py` (переходы состояний, ключи с TTL); тесты шлюза с `respx` и `Clock` (ретраи только до первой дельты, учёт только нужных ошибок); тест на N инстансах `tests/n_instances/llm_gateway/test_circuit_breaker_shared.py` (ошибки с инстанса A открывают breaker для инстанса B).
- **Применимость**: backend, tests.

### SYS-08-R17 Единые коды ошибок провайдеров

- **Формулировка**: адаптер должен преобразовывать любой ответ или исключение провайдера в `ProviderError` с одним из кодов таблицы; в стриме код передаётся в `llm_gateway.completion.error.payload.code` без префикса (ADR-009), в REST — как `llm_gateway.<код>` (SYS-03-R8); `message` в стриме — ключ i18n `errors.llm_gateway.<код>`, детали провайдера (текст ответа без ключей, HTTP-статус) — в `details.provider` только для владельца подключения.

| Код | HTTP (REST) | `retryable` | Источник у провайдера | Побочное действие |
|---|---|---|---|---|
| `provider_auth` | 401 → в REST `llm_gateway.provider_auth` со статусом 400 | нет | HTTP 401, 403, недействительный ключ | `provider_bindings.status = invalid`, событие `llm_gateway.provider_binding_invalidated` |
| `model_not_found` | 400 | нет | HTTP 404 модели, модель отсутствует в `/models` | — |
| `rate_limited` | 429 | да | HTTP 429 провайдера или лимит SYS-08-R14 | `retry_after_ms` |
| `context_too_long` | 400 | нет | HTTP 400 с указанием контекста; проверка SYS-08-R29 | `details.prompt_tokens`, `details.max_context_tokens` |
| `content_filtered` | 200 в `end` с `finish_reason = content_filter` или ошибка | нет | фильтр содержимого провайдера | — |
| `capability_unsupported` | 400 | нет | проверка SYS-08-R3 | `details.capability` |
| `consent_required` | 403 | нет | SYS-08-R10 | — |
| `platform_model_forbidden` | 403 | нет | SYS-08-R8 | — |
| `platform_budget_exhausted` | 429 | нет (до следующих суток) | SYS-08-R9 | `details.resets_at` |
| `no_model_configured` | 409 | нет | SYS-08-R11 | — |
| `agent_offline` | 503 | да | агент не подключён, `AGENT_DISCONNECTED`, `AGENT_STREAM_LOST` (ADR-008) | — |
| `provider_unavailable` | 503 | да | HTTP 5xx, таймауты, ошибки соединения, breaker `open` | учёт в breaker |
| `instance_shutdown` | — (только стрим) | да | SIGTERM инстанса (ADR-009) | — |
| `timeout` | 504 | да | `LLM_TTFT_TIMEOUT_SECONDS`, `LLM_INTER_DELTA_TIMEOUT_SECONDS`, общий таймаут после первой дельты | учёт в breaker |
| `internal` | 500 | нет | необработанное исключение адаптера | лог `error` |

- **Обоснование**: ADR-009, раздел 3.1 (коды `provider_unavailable`, `provider_auth`, `rate_limited`, `context_too_long`, `agent_offline`, `instance_shutdown`, `timeout`, `internal`, флаг `retryable`); единые коды нужны UI для одинаковых сообщений при любом провайдере (LLM-агностичность) и метрике `outcome`.
- **Проверка**: параметризованный тест `tests/modules/llm_gateway/providers/test_error_mapping.py` для каждого адаптера; перечисление `ProviderErrorCode` — единственный источник кодов (архитектурный тест: `ProviderError(code=...)` только со значениями перечисления); контракт `asyncapi.yaml` модуля перечисляет коды в `enum`.
- **Применимость**: backend, frontend, tests.

### SYS-08-R18 Безопасность ключей и содержимого в логах и ответах

- **Формулировка**: API-ключ ученика и ключ платформы не должны попадать в логи, метрики, трассы, ответы API, сообщения WebSocket, события Kafka и тексты ошибок: процессор `redact_sensitive_keys` (ADR-010) дополняется ключами `api_key`, `authorization`, `x-api-key`, `api_key_ciphertext`, `extra_headers` и регулярными выражениями префиксов ключей (`sk-[A-Za-z0-9_-]{16,}`, `AQVN[A-Za-z0-9_-]{20,}`, `y0_[A-Za-z0-9_-]{20,}`, `flta_[A-Za-z0-9_-]{20,}`); `httpx`-клиент адаптеров создаётся с event hook, который логирует только метод, хост, путь, статус и длительность; тексты промптов и ответов не пишутся в логи и события (разрешены длина в символах и `sha256`); исключения провайдера очищаются от заголовков запроса до записи в лог; `DEBUG_MODE=false` на всех стендах, кроме local (ADR-013).
- **Обоснование**: CLAUDE.md «Персональные данные» (секреты, API-ключи и персональные данные не попадают в логи); ADR-010 (маскирование); ADR-013, раздел 3.5; ADR-008, раздел 3.7 (в логах — идентификаторы и размеры, никогда — промпты и ответы).
- **Проверка**: тест `tests/modules/llm_gateway/test_no_secrets_in_logs.py` (перехват structlog и `caplog` на всех путях: успех, 401 провайдера, исключение `httpx`; введённый ключ `sk-test…` и текст промпта отсутствуют в выводе); тест `test_no_secrets_in_events` для `TestKafkaBroker`; правило detect-secrets для кассет (SYS-08-R25).
- **Применимость**: backend, tests.

### SYS-08-R19 Жизненный цикл подключения и персональные данные

- **Формулировка**: удаление подключения (`DELETE /api/v1/llm-gateway/provider-bindings/{provider_binding_id}`) должно физически удалять строку (ключ уничтожается), сохраняя `usage_records` с `provider_binding_id = NULL` (`ON DELETE SET NULL` внутри схемы модуля); по событию `identity.user_deleted` шлюз удаляет все подключения и предпочтения пользователя и обезличивает его `usage_records` (`user_id = NULL`); события шлюза: `llm_gateway.provider_binding_created.v1`, `llm_gateway.provider_binding_invalidated.v1`, `llm_gateway.provider_binding_deleted.v1` (payload без ключей и `last4`).
- **Обоснование**: CLAUDE.md «Персональные данные» (удаление по запросу); ADR-003 (удаление физическое по умолчанию); ADR-013 (утрата ключа шифрования — ученик вводит ключ заново).
- **Проверка**: интеграционные тесты `tests/modules/llm_gateway/test_connection_lifecycle.py`; `TestKafkaBroker`-тест обработчика `identity.user_deleted`.
- **Применимость**: backend, tests.

### SYS-08-R20 Провайдер `local` через локальный агент

- **Формулировка**: вид `local` должен реализовывать тот же `LLMProvider`: подключение хранит `agent_id` и `engine` (`lm_studio | llama_cpp`) вместо ключа; `list_models` → команда `engine.list_models` через `LocalRuntimeService` (публичный API `local_runtime`); `stream`/`complete` → `LocalRuntimeService.stream(agent_id, request)` с OpenAI-совместимым телом, сформированным адаптером `openai_compatible`, и трансляцией `llm.chunk`/`llm.done`/`llm.error` агента в `Delta` (ADR-008, раздел 3.7; ADR-009, раздел 3.6); таймауты: первая дельта 120 с (загрузка модели), простой между дельтами 60 с; отсутствие агента в реестре → `agent_offline`; `capabilities` — из ответа движка `/v1/models`, при отсутствии — значения по умолчанию адаптера; `jurisdiction = ru`; реализация — этап 4 (STU-05), на этапе 1 резервируется значение `kind` и ветка `auth_mode = agent` в реестре.
- **Обоснование**: ADR-008 (один OpenAI-совместимый адаптер для внешних и локальных моделей — LLM-агностичность; агент тело не меняет); ADR-009, раздел 3.6 (цепочка браузер ⇄ инстанс A ⇄ Redis ⇄ инстанс B ⇄ агент); OQ-26.
- **Проверка**: этап 4 — тесты `tests/modules/llm_gateway/providers/test_local.py` на заглушке `LocalRuntimeService`; тесты масштабируемости из ADR-008, раздел 3.7.
- **Применимость**: backend, tests.

### SYS-08-R21 Провайдер эмбеддингов

- **Формулировка**: `EmbeddingsProvider` должен быть отдельным `Protocol` в `public/providers.py`: `async def embed(self, texts: Sequence[str], *, model: str | None = None) -> EmbeddingsResult(vectors: list[list[float]], model_id: str, dimensions: int, usage: Usage)` с батчем до `LLM_EMBEDDINGS_BATCH_SIZE=64` текстов и длиной текста до 8 000 символов (больше — вызывающий модуль режет на чанки); реализации: `platform` — контейнер `embeddings` (TEI с `multilingual-e5-small` — рекомендация ADR-014, решение OQ-59 в ТЗ STU-27; `EMBEDDINGS_URL`, `EMBEDDINGS_MODEL`), `stub` — детерминированные векторы из `sha256` текста заданной размерности; реализация `learner` (эмбеддинги у провайдера ученика) на этапах 1–5 не реализуется; `model_id` возвращается вызывающему модулю и записывается в payload точки Qdrant (ADR-014); расход пишется в `usage_records` с `operation = embedding`; вызов — только через `LlmGatewayService.embed(actor, texts, purpose)`.
- **Обоснование**: ADR-014, раздел 3, правило 6 (вызов только через `EmbeddingsProvider` модуля `llm_gateway`, `model_id` в payload точки, заглушка в тестах); глоссарий «Провайдер эмбеддингов»; OQ-59 (модель и контейнер — ТЗ STU-27).
- **Проверка**: тесты `tests/modules/llm_gateway/providers/test_embeddings_stub.py` (детерминизм, размерность, батчи); контракт `platform` — этап 5 (STU-27) с `respx`.
- **Применимость**: backend, tests.

### SYS-08-R22 Провайдеры речи — тот же подход (интерфейсы на этапе 1)

- **Формулировка**: модуль `speech` должен объявить в `app/modules/speech/public/providers.py` `@runtime_checkable` `Protocol` `STTProvider` (свойство `kind: str`; `def stream_transcribe(self, frames: AsyncIterator[AudioFrame], *, language: str, sample_rate: int) -> AsyncIterator[Transcript]`, где `Transcript(kind ∈ partial | final, text, confidence)`; `def capabilities(self) -> SpeechCapabilities`; `async def check_connection(self) -> ConnectionCheck`) и `TTSProvider` (свойство `kind: str`; `def stream_synthesize(self, text: str, *, voice: Voice, language: str, sample_rate: int) -> AsyncIterator[AudioFrame]`; `async def list_voices(self, language: str | None = None) -> list[Voice]`; `def capabilities(self) -> SpeechCapabilities`; `async def check_connection(self) -> ConnectionCheck`), `SpeechCapabilities` (`streaming_stt`, `streaming_tts`, `visemes`, `languages`, `sample_rates`), собственный реестр `SpeechProviderRegistry` с `SpeechProviderKindInfo` (поля `ProviderKindInfo`, `factory: Callable[[ProviderBindingConfig, ProviderCredentials | None], STTProvider | TTSProvider]`, `services ∈ stt | tts`) — эти сигнатуры являются контрактами точек расширения `speech.stt_providers` и `speech.tts_providers` (SYS-09-R9); ключи провайдеров речи `speech` не хранит: подключение к провайдеру речи — строка `llm_gateway.provider_bindings` с `service = speech` (SYS-08-R6), а `speech` хранит только `provider_binding_id` и получает учётные данные на время вызова через `ProviderCredentialsService` (SYS-08-R31, OQ-81); результат проверки подключения речи (`POST /api/v1/speech/provider-bindings/{provider_binding_id}/test`) `speech` хранит у себя (`speech.connection_checks`), не записывая в `llm_gateway`; запись расхода в `speech.usage_records` (секунды аудио и символы вместо токенов), те же правила юрисдикции и согласия (SYS-08-R10), коды ошибок SYS-08-R17 с префиксом `speech.`; на этапе 1 создаются только интерфейсы и заглушки `stub` (без таблиц), реализации — этап 5 (STU-13, STU-28); локальные провайдеры речи через агента — позже (ADR-008, раздел 3.9).
- **Обоснование**: CLAUDE.md «Технологический стек» (синтез и распознавание речи через провайдеров по аналогии с LLM); SDD_plan.md Б.8; ADR-009, разделы 3.7 и 4.3 (`STTProvider`/`TTSProvider` — SYS-08); хранение всех ключей провайдеров в `llm_gateway` даёт одну таблицу, один `SecretBox`, одну процедуру ротации (ADR-013, раздел 3.4) и один экран управления ключами; зависимость `speech → llm_gateway` совпадает с порядком SYS-01, обратной зависимости нет (OQ-81: рабочее решение, окончательно — ТЗ STU-28 этапа 5).
- **Проверка**: архитектурный тест `test_speech_providers_protocol` (наличие `Protocol` и `stub`, `mypy strict`); этап 5 — тесты адаптеров на заглушках провайдеров.
- **Применимость**: backend, tests.

### SYS-08-R23 Harness — граница ответственности (часть OQ-57)

- **Формулировка**: настройки harness должны принадлежать модулю `llm_gateway`: таблица `llm_gateway.harness_settings` (`user_id`, `scope_type` ∈ `default | course | learner_language`, `scope_id`, `system_prompt_suffix` (до 2 000 символов), `generation_params jsonb` (`temperature` 0–1,5, `top_p` 0–1, `max_tokens` ≤ `max_output_tokens` модели — значения вне диапазона отсекаются до границы), `mcp_servers jsonb`, `skills jsonb`, базовые колонки) и публичная схема `HarnessSettings`; шлюз применяет настройки при каждом вызове: `system_prompt_suffix` **добавляется** после системного промпта платформы и не заменяет его, параметры генерации подставляются с ограничением диапазонов, инструменты MCP-серверов и скилы добавляются в `tools` и исполняются циклом tool-use внутри шлюза; настройки курса (TCH-02) — значения по умолчанию для учеников курса; на этапе 1 создаются схема `HarnessSettings` со значениями по умолчанию и точка применения в конвейере вызова, таблица, UI, MCP и скилы — этап 7 (STU-25); перечень настроек, доступных ученику, — ТЗ STU-25.
- **Обоснование**: OQ-57 (рекомендация: harness — слой `llm_gateway`; настройки ученика дополняют промпт платформы, диапазоны ограничены; настройки курса — значения по умолчанию); глоссарий «Harness», «MCP-сервер», «Скил»; персонаж платформы (STU-36) — слой промптов модулей `avatar` и `lessons`, не harness.
- **Проверка**: unit-тесты `tests/modules/llm_gateway/test_harness_apply.py` (суффикс после системного промпта, отсечение диапазонов, значения по умолчанию); архитектурный тест `test_harness_tables_in_llm_gateway` (таблица с именем `harness_settings` существует только в схеме `llm_gateway`).
- **Применимость**: backend, tests.

### SYS-08-R24 Точка расширения для плагинов-провайдеров

- **Формулировка**: `ProviderRegistry` и `SpeechProviderRegistry` должны принимать регистрацию из плагинов только через интерфейс `ProviderPlugin` (`kind`, `factory`, `manifest_ref`) с префиксом `plugin.<plugin_id>.`, юрисдикцией из манифеста и обязательным прохождением тех же контрактных тестов адаптера (SYS-08-R2), выполняемых при модерации плагина (ADM-04); плагин-провайдер не получает доступа к `SecretBox`, ключам других подключений и `usage_records` — ему передаётся расшифрованный ключ своего подключения на время вызова; на этапе 1 фиксируется только интерфейс `ProviderPlugin` в `public/providers.py` и правило префикса; песочница и права — SYS-13.
- **Обоснование**: CLAUDE.md «Расширяемость» (реестр провайдеров — точка расширения); SYS-09 (только интерфейсы на этапе 1); глоссарий «Точка расширения» (реестр провайдеров LLM).
- **Проверка**: архитектурный тест `test_plugin_provider_prefix` (виды с `plugin.` зарегистрированы только через `ProviderPlugin`); контрактный набор тестов адаптера переиспользуется для плагинов (этап 7).
- **Применимость**: backend.

### SYS-08-R25 Детерминированная заглушка и кассеты

- **Формулировка**: провайдер `stub` должен работать в режимах `LLM_STUB_MODE`: `scripted` (по умолчанию в pytest и на стенде local: текст из фикстуры `tests/fixtures/llm_stub/<scenario>.txt`, выбираемый по `metadata.scenario` запроса или по хэшу первого сообщения; дельты по словам с задержкой `LLM_STUB_DELTA_DELAY_MS=20`; `usage` считается оценщиком с `estimated = false`), `replay` (ответ из кассеты по `request_hash`; отсутствие кассеты — исключение `CassetteMissingError`, в CI тест падает), `record` (только на машине разработчика с реальным ключом; CI — запрещён валидатором `CI=true`): кассета — YAML `tests/fixtures/llm_cassettes/<module>/<name>.yaml` с полями `provider_kind`, `llm_model`, `request_hash` (`sha256` канонического JSON: `messages`, `llm_model`, `params`, `tools`, `response_format`), `recorded_at`, `deltas[]` (`kind`, `text`), `usage`, `finish_reason`; кассеты не содержат ключей и заголовков (`detect-secrets` в pre-commit и тест-сканер), а запрос нормализуется без `user_id` и временных меток; `stub` поддерживает сценарии ошибок (`scenario = error:<код>`) и задержек; формат кассет и расположение согласуются с SYS-10 как общие для LLM, эмбеддингов и речи.
- **Обоснование**: CLAUDE.md «TDD» (внешние сервисы подменяются заглушками, тесты детерминированы, без сети и ключей); ADR-009, раздел 3.3 (`stub` с фикстурой и `LLM_STUB_DELTA_DELAY_MS`, на нём идут Г.6, Г.11 и тесты на N инстансах); глоссарий «Заглушка LLM» (record/replay); SYS-10 (детерминированная заглушка LLM).
- **Проверка**: тесты `tests/modules/llm_gateway/providers/test_stub.py` (детерминизм, режимы, отсутствие кассеты в CI, сценарии ошибок); тест-сканер `tests/fixtures/test_cassettes_have_no_secrets.py`; E2E Г.11 на `stub`.
- **Применимость**: backend, tests, CI.

### SYS-08-R26 Публичный API модуля

- **Формулировка**: `app/modules/llm_gateway/public/` должен экспортировать `Protocol` `LlmGatewayService` с методами `stream_completion(actor, request, *, purpose, prompt_ref=None) -> AsyncIterator[Delta]`, `complete(actor, request, *, purpose, prompt_ref=None) -> CompletionResult`, `resolve_model(actor, context) -> ModelSelection`, `capabilities(provider_binding_id, llm_model) -> ModelCapabilities`, `embed(actor, texts, *, purpose) -> EmbeddingsResult`, `estimate_tokens(request) -> int`, `get_usage_summary(user_id, period) -> UsageSummary`, схемы `Actor` (`kind ∈ user | anonymous | system`, `user_id`, `anonymous_session_id`, `request_id`), `CompletionRequest`, `Message`, `ContentPart`, `Delta`, `Usage`, `CompletionResult`, `ModelSelection`, `HarnessSettings`, события из SYS-08-R19, ошибки `ProviderError` и коды; реализация внедряется через контейнер shared kernel (ADR-004, 2.6); обработчик WebSocket `llm_gateway.completion.*` (SYS-04) — тонкая обёртка над `stream_completion`; вызов `complete` из REST-контроллеров других модулей запрещён (SYS-03-R27) — только из воркеров и из `stream_completion`-обработчиков.
- **Обоснование**: ADR-002 (публичный API — `Protocol`, схемы, события, ошибки); ADR-004 (прямой вызов для чтения, контейнер); ADR-009, раздел 3.2 (оба пути — прямой стрим и задание — используют один `stream_completion`).
- **Проверка**: архитектурные тесты ADR-002 (`test_module_public_exports_only_contracts`); `mypy strict`; спецификация `Analytics/Specs/llm_gateway/_module.md` (этап 1 В) перечисляет этот API.
- **Применимость**: backend.

### SYS-08-R27 REST-эндпоинты модуля

- **Формулировка**: модуль должен предоставлять по правилам SYS-03 (контракт `Analytics/Specs/llm_gateway/api/openapi.yaml`): `GET /api/v1/llm-gateway/provider-kinds`; `GET`, `POST /api/v1/llm-gateway/provider-bindings` (POST с `Idempotency-Key`, ключ в теле, ответ без ключа); `GET`, `PATCH`, `DELETE /api/v1/llm-gateway/provider-bindings/{provider_binding_id}`; `POST …/{provider_binding_id}/test`; `GET …/{provider_binding_id}/models`; `GET`, `PUT /api/v1/llm-gateway/model-preferences` (список предпочтений по областям); `GET /api/v1/llm-gateway/usage?period=day|week|month`; на этапе 1 реализуются `GET /provider-kinds` и контракт целиком (остальные операции — STU-01, STU-03, STU-05 этапа 4; до реализации операции отсутствуют в коде и помечены в контракте `x-flt-stage: 4`); стрим — только по WebSocket (`llm_gateway.completion.request`), REST-эндпоинта генерации нет.
- **Обоснование**: STU-01, STU-03, STU-05 (подключения и выбор модели); ADR-009 (интерактивная генерация — WebSocket); SYS-03 (конвенции, исключение для `/test`).
- **Проверка**: контрактный тест `tests/contracts/test_openapi_llm_gateway.py` (операции с `x-flt-stage` выше текущего этапа исключаются из сверки по флагу `FLT_STAGE`); Spectral.
- **Применимость**: backend, frontend.

### SYS-08-R28 Метрики и логи шлюза

- **Формулировка**: шлюз должен отдавать метрики `flt_llm_gateway_requests_total{provider_kind, llm_model, operation, outcome}`, `flt_llm_gateway_tokens_total{provider_kind, llm_model, kind="prompt|completion", estimated}`, `flt_llm_gateway_ttft_seconds{provider_kind}` (гистограмма), `flt_llm_gateway_duration_seconds{provider_kind, operation}`, `flt_llm_gateway_active_streams` (gauge), `flt_llm_gateway_circuit_state{provider_kind, host}` (0 closed, 1 half_open, 2 open), `flt_llm_gateway_platform_budget_used_tokens` (gauge за текущие сутки), `flt_llm_gateway_usage_estimate_ratio` (гистограмма отношения оценки к факту на вызовах, где известны оба); метка `llm_model` ограничена значениями из справочников адаптеров, иное — `other`; метки `user_id`, `purpose` с произвольным текстом запрещены (`purpose` допускается, так как множество значений — конечный список модулей); логи вызова: `request_id`, `correlation_id`, `provider_kind`, `host`, `llm_model`, `purpose`, `prompt_name`, `prompt_version`, размеры, `outcome`, `code` — без текстов.
- **Обоснование**: ADR-010, раздел 3.1 (соглашение имён, примеры `flt_llm_gateway_requests_total`, `flt_llm_gateway_tokens_total`, запрет неограниченных меток).
- **Проверка**: тест `tests/modules/llm_gateway/test_metrics.py` (регистрация, метки, `other` для неизвестной модели); дашборд `flt-llm-gateway.json` и алерты (`FltLlmProviderCircuitOpen`, `FltPlatformBudgetNearLimit` при 80 %) — SYS-11.
- **Применимость**: backend, deploy, tests.

### SYS-08-R29 Контроль размера контекста

- **Формулировка**: до вызова провайдера шлюз должен оценить `prompt_tokens` (`count_tokens` или оценщик SYS-08-R13) и отклонить запрос ошибкой `context_too_long` с `details {prompt_tokens, max_context_tokens, max_output_tokens}`, если `prompt_tokens + max_tokens > max_context_tokens` модели; шлюз не усекает и не переупорядочивает сообщения — стратегия сокращения контекста (суммаризация истории, окно последних реплик) принадлежит вызывающему модулю и описывается в его ТЗ.
- **Обоснование**: LLM-агностичность — у моделей разный контекст; молчаливое усечение меняло бы смысл занятия и ломало воспроизводимость кассет.
- **Проверка**: unit-тест `tests/modules/llm_gateway/test_context_check.py`; раздел «Нефункциональные требования» ТЗ с вызовом LLM указывает стратегию сокращения (раздел 4.2).
- **Применимость**: backend, tests.

### SYS-08-R30 Конфигурация модуля

- **Формулировка**: настройки модуля должны объявляться классом `LlmGatewaySettings` с `env_prefix="LLM_GATEWAY_"` (ADR-002), при этом переменные, поименованные в принятых ADR, принимаются через `validation_alias` без префикса модуля: `LLM_INTERACTIVE_TIMEOUT_SECONDS`, `LLM_TTFT_TIMEOUT_SECONDS`, `LLM_DELTA_FLUSH_MS`, `LLM_MAX_CONCURRENT_STREAMS_PER_CONNECTION`, `LLM_STUB_DELTA_DELAY_MS` (ADR-009), `LLM_KEYS_ENCRYPTION_KEYS`, `LLM_KEYS_ENCRYPTION_ACTIVE_VERSION`, `PLATFORM_LLM_API_KEY` (ADR-013), а также введённые здесь `PLATFORM_LLM_PROVIDER_KIND`, `PLATFORM_LLM_BASE_URL`, `PLATFORM_LLM_MODEL`, `PLATFORM_LLM_DAILY_TOKEN_BUDGET`, `LLM_RU_PROVIDER_HOSTS`, `LLM_STUB_ENABLED`, `LLM_STUB_MODE`, `LLM_USER_REQUESTS_PER_MINUTE`, `LLM_MAX_CONCURRENT_STREAMS_PER_USER`, `LLM_USER_EMBEDDING_TEXTS_PER_MINUTE`, `LLM_EMBEDDINGS_BATCH_SIZE`, `LLM_CONNECT_TIMEOUT_SECONDS`, `LLM_INTER_DELTA_TIMEOUT_SECONDS`, `LLM_BACKGROUND_TIMEOUT_SECONDS`, `LLM_TOKEN_ESTIMATE_CHARS_PER_TOKEN_<SCRIPT>`, `EMBEDDINGS_URL`, `EMBEDDINGS_MODEL`; секреты — `SecretStr` без значения по умолчанию; значения стендов — `envs/<stand>/llm_gateway_<stand>.env`, секреты — `.env` и `ExternalSecret` одновременно (ADR-013).
- **Обоснование**: ADR-002 (префикс `<MODULE>_`), ADR-009 и ADR-013 задают имена без префикса модуля — переименование принятых ADR не допускается, поэтому имена принимаются как псевдонимы; исключение фиксируется в разделе 6.
- **Проверка**: архитектурный тест `test_module_settings_prefix` (ADR-002) с allowlist псевдонимов из раздела 6; тест старта без секретов (`test_missing_platform_key_fails_fast`); паритет переменных compose и Helm — тест конфигурации SYS-11.
- **Применимость**: backend, deploy, tests.

### SYS-08-R31 Учётные данные провайдера для других модулей

- **Формулировка**: `app/modules/llm_gateway/public/interfaces.py` должен экспортировать `Protocol` `ProviderCredentialsService` с методом `async def get_credentials(self, provider_binding_id: UUID, *, owner_user_id: UUID, consumer_module: str) -> ProviderCredentials`, где `ProviderCredentials(provider_binding_id, service, kind, base_url, api_key: SecretStr | None, extra_headers, jurisdiction, api_key_last4)`; метод должен возвращать данные только если подключение принадлежит `owner_user_id`, его `service` разрешён модулю `consumer_module` по настройке `LLM_GATEWAY_CREDENTIALS_CONSUMERS` (на этапе 1 — `{"speech": ["speech"]}`) и `status = active`, иначе — `ProviderError(code="provider_auth")` для `invalid` и `revoked` и `ProviderBindingNotFound` для чужого или неразрешённого подключения (без различия причин); расшифрованный ключ не кэшируется ни в `llm_gateway`, ни у потребителя, живёт только на время вызова провайдера и не логируется (SYS-08-R18); каждая выдача увеличивает метрику `flt_llm_gateway_credentials_issued_total{consumer_module, service}`.
- **Обоснование**: OQ-81 (рабочее решение: ключи провайдеров речи хранит `llm_gateway`); ADR-013, раздел 3.4 (ключи учеников зашифрованы, один ключ шифрования); ADR-004 (синхронное чтение чужих данных — прямой вызов публичного `Protocol`); SYS-06 (объектная проверка владельца на стороне владельца данных).
- **Проверка**: интеграционные тесты `tests/modules/llm_gateway/test_provider_credentials.py` (`<будет создан>`, этап 5: свой ключ — выдаётся; чужое подключение, `service = llm` для `speech`, `revoked` — отказ; метрика; отсутствие ключа в логах); архитектурный тест `test_credentials_consumers_declared` (каждый модуль из `LLM_GATEWAY_CREDENTIALS_CONSUMERS` есть в реестре и зависит от `llm_gateway` по SYS-01).
- **Применимость**: backend, tests.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| llm_gateway | Пакет по ADR-002: `public/providers.py` (`LLMProvider`, `EmbeddingsProvider`, `ProviderPlugin`, `ModelCapabilities`), `public/interfaces.py` (`LlmGatewayService`), `public/schemas.py`, `public/events.py`, `public/errors.py` (`ProviderError`, коды), `public/ws_messages.py` (`llm_gateway.completion.*`), `providers/` (`openai_compatible`, `stub`, позже остальные), `services/` (выбор модели, конвейер вызова, оценщик, учёт, бюджет, harness), `models/` (`provider_bindings`, `model_preferences`, `usage_records`, `harness_settings`), `api/ws.py`, `api/router.py`, `settings.py`, `prompts/` отсутствует (шлюз промптов не имеет); контракты `api/openapi.yaml`, `api/asyncapi.yaml`; спецификация `_module.md` (этап 1 В) |
| speech | `public/providers.py` (`STTProvider`, `TTSProvider`, `SpeechCapabilities`), реестр, `stub`; ключи провайдеров речи не хранит — `provider_binding_id` и `ProviderCredentialsService` (SYS-08-R31); таблицы и адаптеры — этап 5 |
| local_runtime | публичный API `LocalRuntimeService.stream`, `list_models`, `is_online` для провайдера `local` (этап 4) |
| shared kernel | `app/core/crypto/secret_box.py` (AES-256-GCM с версиями ключей), `app/core/resilience/redis_circuit_breaker.py`, расширение `redact_sensitive_keys`; контракт import-linter `llm-clients-only-in-gateway` |
| identity | публичный метод `IdentityService.has_consent(user_id, kind)`; событие `identity.consent_revoked.v1`; событие `identity.user_deleted.v1` потребляется шлюзом |
| assessment, lessons | быстрый тест и демо-урок вызывают шлюз с `Actor(kind=anonymous)` и `purpose` из списка SYS-08-R8; лимиты сессии и IP — в `assessment` |
| courses | атрибут `course_default_model` (вид провайдера и имя модели) без ссылки на подключение; при записи на курс предзаполняет `model_preferences` ученика через публичный API шлюза |
| learner_profile | читает `model_preferences` и подключения через публичный API для экрана профиля и wizard (STU-03, STU-32.1) |
| модули с промптами (`lessons`, `dictionary`, `learning_plan`, `memorization`, `assessment`, `avatar`, `promotion`) | `prompts/*.py` с `PromptTemplate`, `PROMPTS`; `purpose` в каждом вызове; хранение `prompt_name`/`prompt_version` в артефактах; стратегия сокращения контекста в ТЗ |
| materials | эмбеддинги только через `LlmGatewayService.embed`; `model_id` в payload точки Qdrant |
| frontend | экраны подключений (без отображения ключа, только `last4`), расход токенов с пометкой «оценка», сообщения по кодам `errors.llm_gateway.*` |
| deploy | переменные SYS-08-R30 в `.env.template`, `values.yaml`, `ExternalSecret`; контейнер `embeddings` — по решению OQ-59 (этап 5) |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| 4.4. Изменения публичного API модуля | для фич с вызовом LLM — используемые методы `LlmGatewayService`, значение `purpose`, список `PromptTemplate` (имя, версия) |
| 5. Модель данных модуля | для артефактов генерации — колонки `prompt_name`, `prompt_version`, `llm_model`, `provider_kind` |
| 6. Состояние и масштабируемость | путь исполнения LLM (прямой стрим или задание — ADR-009), поведение при `rate_limited`, `provider_unavailable`, `agent_offline` |
| 7.2. Персональные данные | юрисдикция провайдера и согласие `foreign_llm_transfer`; какие данные уходят провайдеру |
| 10. Нефункциональные требования | стратегия сокращения контекста (SYS-08-R29); требуемые возможности модели (`tools`, `vision`, `audio`) и деградация без них |
| 13. План тестов | сценарии `stub` (`scripted` или кассеты `replay`), тест на N инстансах с остановкой инстанса посреди стрима, если фича стримит |

## 5. Примеры

### Пример 1. `Protocol` провайдера и схемы (SYS-08-R2, R3)

```python
# app/modules/llm_gateway/public/providers.py
from collections.abc import AsyncIterator, Sequence
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel


class ModelCapabilities(BaseModel):
    """Возможности модели, по которым шлюз проверяет запрос до вызова провайдера."""

    streaming: bool = True
    tools: bool = False
    vision: bool = False
    audio_input: bool = False
    audio_output: bool = False
    json_mode: bool = False
    max_context_tokens: int = 8192
    max_output_tokens: int = 2048
    supports_system_role: bool = True


class Usage(BaseModel):
    """Расход токенов одного вызова; `estimated` — значения получены оценщиком, а не от провайдера."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool = False


class Delta(BaseModel):
    """Фрагмент потокового ответа; последняя дельта имеет kind='usage' и finish_reason."""

    seq: int
    kind: Literal["text", "tool_call", "reasoning", "usage"]
    text: str | None = None
    tool_call: dict | None = None
    usage: Usage | None = None
    finish_reason: Literal["stop", "length", "tool_calls", "cancelled", "content_filter"] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Единый интерфейс адаптера провайдера LLM (внешнего, локального через агента, заглушки)."""

    kind: str

    async def complete(self, request: "CompletionRequest") -> "CompletionResult":
        """Выполняет запрос без стриминга и возвращает ответ целиком с usage."""
        ...

    def stream(self, request: "CompletionRequest") -> AsyncIterator[Delta]:
        """Возвращает async-генератор дельт; завершает его дельтой kind='usage'."""
        ...

    async def list_models(self) -> list["ModelInfo"]:
        """Возвращает модели, доступные по данному подключению."""
        ...

    async def capabilities(self, llm_model: str) -> ModelCapabilities:
        """Возвращает возможности модели из справочника адаптера или ответа провайдера."""
        ...

    async def check_connection(self) -> "ConnectionCheck":
        """Проверяет ключ и доступность провайдера не дольше 10 с."""
        ...

    def count_tokens(self, request: "CompletionRequest") -> int | None:
        """Считает токены промпта токенизатором провайдера или возвращает None."""
        ...


@runtime_checkable
class EmbeddingsProvider(Protocol):
    """Интерфейс вычисления эмбеддингов (ADR-014); реализации — platform и stub."""

    async def embed(self, texts: Sequence[str], *, model: str | None = None) -> "EmbeddingsResult":
        """Возвращает векторы для батча текстов и идентификатор модели."""
        ...
```

### Пример 2. Запрос стриминга по WebSocket (SYS-08-R11, R15, R17; конверт — SYS-04)

Клиент → сервер:

```json
{
  "type": "llm_gateway.completion.request",
  "correlation_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "channel": null,
  "seq": 12,
  "ts": "2026-10-10T12:00:00.000Z",
  "payload": {
    "messages": [
      {"role": "system", "content": [{"type": "text", "text": "You are a patient English tutor..."}]},
      {"role": "user", "content": [{"type": "text", "text": "Explain the present perfect."}]}
    ],
    "provider_binding_id": null,
    "llm_model": null,
    "params": {"temperature": 0.7, "max_tokens": 512},
    "purpose": "llm_gateway.diagnostic",
    "prompt_ref": {"name": "llm_gateway.diagnostic", "version": 1},
    "client_ts": "2026-10-10T12:00:00.000Z"
  }
}
```

`provider_binding_id: null` для аутентифицированного пользователя означает выбор по SYS-08-R11 (курс → умолчание); для анонима быстрого теста — модель платформы (SYS-08-R8). Сервер отвечает `llm_gateway.completion.start`, затем `delta`, затем `end`:

```json
{
  "type": "llm_gateway.completion.end",
  "correlation_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "channel": "llm_gateway.stream:01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "seq": 57,
  "ts": "2026-10-10T12:00:04.210Z",
  "payload": {
    "finish_reason": "stop",
    "usage": {"prompt_tokens": 61, "completion_tokens": 188, "total_tokens": 249, "estimated": false},
    "duration_ms": 4180,
    "ttft_ms": 620
  }
}
```

Ошибка с единым кодом:

```json
{
  "type": "llm_gateway.completion.error",
  "correlation_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "channel": "llm_gateway.stream:01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "seq": 58,
  "ts": "2026-10-10T12:00:04.300Z",
  "payload": {"code": "provider_unavailable", "message": "errors.llm_gateway.provider_unavailable", "retryable": true, "retry_after_ms": 30000, "partial_seq": 3}
}
```

### Пример 3. Запись расхода (SYS-08-R12, R13)

Строка `llm_gateway.usage_records` после отмены стрима учеником:

```json
{
  "id": "0199a3f0-0000-7000-8000-000000000001",
  "user_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c56",
  "anonymous_session_id": null,
  "provider_binding_id": "0199a2f0-0000-7000-8000-00000000c0de",
  "provider_kind": "openai_compatible",
  "jurisdiction": "foreign",
  "llm_model": "gpt-4.1-mini",
  "purpose": "lessons.tutor_reply",
  "operation": "stream",
  "prompt_name": "lessons.tutor_reply",
  "prompt_version": 4,
  "prompt_tokens": 1240,
  "completion_tokens": 37,
  "total_tokens": 1277,
  "estimated": true,
  "finish_reason": "cancelled",
  "duration_ms": 1830,
  "ttft_ms": 540,
  "correlation_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "request_id": "0199a1b2-3c4d-7e5f-8a9b-0c1d2e3f4a5b",
  "created_at": "2026-10-10T12:00:06.000Z"
}
```

`estimated = true`: провайдер не вернул `usage`, `prompt_tokens` — `count_tokens` адаптера (`tiktoken`), `completion_tokens` — оценщик по 150 символам латиницы (150 / 4,0 ≈ 37).

### Пример 4. Шаблон промпта (SYS-08-R15)

```python
# app/modules/dictionary/prompts/entry.py
from app.modules.llm_gateway.public.prompts import PromptTemplate

ENTRY_V3 = PromptTemplate(
    name="dictionary.entry",
    version=3,
    template=(
        "You are a lexicographer. Describe the {{ learning_language }} word or expression "
        "\"{{ headword }}\" for a learner at CEFR level {{ working_level }}: meanings, examples, "
        "idioms and relevant grammar. Answer in {{ explanation_language }} as JSON matching the schema."
    ),
    variables=("learning_language", "headword", "working_level", "explanation_language"),
    content_hash="3f9a1c2e7b8d4a60",
    description="Словарная статья STU-12.1",
)
PROMPTS = (ENTRY_V3,)
```

Изменение текста без увеличения `version` ломает `tests/architecture/test_prompt_templates.py`; словарная статья хранит `prompt_name = "dictionary.entry"`, `prompt_version = 3`.

### Пример 5. Кассета заглушки (SYS-08-R25)

`tests/fixtures/llm_cassettes/dictionary/entry_present_perfect.yaml`:

```yaml
provider_kind: openai_compatible
llm_model: gpt-4.1-mini
request_hash: "4d1f0a9c6b3e2d8f7a5c1b0e9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c"
recorded_at: "2026-10-10T11:00:00Z"
deltas:
  - { kind: text, text: "The present perfect " }
  - { kind: text, text: "links past actions to the present..." }
usage: { prompt_tokens: 61, completion_tokens: 188, total_tokens: 249, estimated: false }
finish_reason: stop
```

### Пример 6. Разведение терминов (SYS-08-R8, R11)

| Понятие | Где хранится | Чей ключ | Кто использует |
|---|---|---|---|
| Модель платформы (`platform_model`) | конфигурация `PLATFORM_LLM_*` | ключ платформы (`PLATFORM_LLM_API_KEY`) | только аноним в быстром тесте и демо-уроке |
| Модель курса по умолчанию (`course_default_model`) | `courses.courses` (вид провайдера, имя модели) | нет ключа | предзаполняет `model_preferences` ученика при записи на курс |
| Предпочтение ученика (`model_preferences`) | `llm_gateway.model_preferences` | подключение ученика (`provider_bindings`) | все вызовы ученика по приоритету SYS-08-R11 |

## 6. Исключения и как их согласовать

Порядок согласования: вопрос в `Analytics/open-questions.md` → решение человека → строка в таблице ниже → исключение в автоматической проверке (allowlist архитектурного теста, контракт import-linter) со ссылкой на эту таблицу.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-08-R1 (пакеты провайдеров только в `llm_gateway` и `speech`) | `app/modules/local_runtime` — нет исключения: агентские тела запросов формирует `llm_gateway`, `local_runtime` только пересылает | — | — | — |
| SYS-08-R30 (префикс `LLM_GATEWAY_`) | псевдонимы `LLM_*`, `PLATFORM_LLM_*`, `EMBEDDINGS_*` из ADR-009, ADR-013 и этой спецификации | имена зафиксированы принятыми ADR; переименование потребовало бы нового ADR без выгоды | до пересмотра ADR-002 (новым ADR) | предлагается SYS-08; утверждается на G1 |
| SYS-08-R8 (модель платформы только анониму) | `purpose = promotion.post` для публикаций персонажа (ADM-06) — не исключение сейчас | источник модели для продвижения — OQ-58 (этап 7); при выборе модели платформы потребуется `changed`-версия SYS-08 | — | — |
| SYS-03-R27 (нет синхронных вызовов провайдеров по REST) | `POST …/provider-bindings/{id}/test` в `llm_gateway` и `speech` | проверка подключения с таймаутом 10 с (SYS-08-R7) | бессрочно | утверждается на G1 SYS-03 и SYS-08 |

## 7. Вне рамок

- Экраны подключения провайдеров, выбора модели, wizard, список устройств агента — ТЗ STU-01, STU-03, STU-05, STU-32.1.
- Семантика занятий и диалога, стратегия сокращения контекста, суммаризация истории — ТЗ модулей `lessons`, `assessment`, `dictionary`.
- Транспорт стрима (конверт, каналы, коды закрытия, переподключение) — SYS-04; семантика `start/delta/end/error`, коалесценция, graceful shutdown — ADR-009.
- Протокол агента, сопряжение, каталоги моделей и сборок, подбор модели под железо — ADR-008, ТЗ STU-02, STU-04, STU-05.
- Модель и контейнер эмбеддингов (OQ-59), разбиение материалов на чанки, RAG — ТЗ STU-27 и ADR-014.
- Голосовая сессия, кодеки, VAD, аватар и визимы — ADR-009, ТЗ STU-28, STU-29, STU-13.
- Перечень настроек harness, доступных ученику, UI MCP и скилов, песочница плагинов — ТЗ STU-25, SYS-13.
- Чьи модель и ключи использует AI-преподаватель в групповом занятии — OQ-67 (спецификация `classroom`, ТЗ TCH-08).
- Какая модель генерирует публикации персонажа платформы — OQ-58 (ТЗ ADM-06).
- Тексты согласий, срок хранения `usage_records` (400 суток, затем удаление; суточные агрегаты без `user_id` — бессрочно), нормативы задержки голоса (OQ-72) — SYS-02.
- Матрица прав на подключения и предпочтения (ученик, преподаватель, администратор) — SYS-06.
- Биллинг и оплата токенов — отсутствуют (все курсы бесплатные, платежей нет).

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-002](../../ADR/ADR-002-module-layout.md) | основан на | раскладка `app/modules/llm_gateway`, `public/`, `settings.py` с префиксом, контракты import-linter, архитектурные тесты |
| [ADR-003](../../ADR/ADR-003-state-storage.md) | основан на | `bytea` для криптоматериала, базовые колонки и `version`, ограничитель в Redis, таблица отказа Redis (лимиты модели платформы fail-closed), запрет состояния в процессе |
| [ADR-004](../../ADR/ADR-004-communication-patterns.md) | основан на | `Protocol` публичного API и контейнер, outbox для событий шлюза, фоновые задания для долгих генераций и перешифровки |
| [ADR-005](../../ADR/ADR-005-frontend-stack.md) | ограничивает | клиент из `openapi.yaml`, zod-схемы сообщений стрима из `asyncapi.yaml` |
| [ADR-006](../../ADR/ADR-006-authentication-and-authorization.md) | основан на | таблица `consents` и вид `foreign_llm_transfer`, `UserSecuritySchema` как актор, событие `identity.user_deleted` |
| [ADR-008](../../ADR/ADR-008-local-agent.md) | основан на | провайдер `local`, транспорт `LocalRuntimeService`, OpenAI-совместимое тело без изменений, таймауты агента |
| [ADR-009](../../ADR/ADR-009-llm-streaming-and-voice.md) | основан на | интерфейс `stream_completion`, `Delta`, `Usage`, коды ошибок стрима, таймауты, `stub`, `usage_records`, `STTProvider`/`TTSProvider` |
| [ADR-010](../../ADR/ADR-010-observability-stack.md) | основан на | имена метрик `flt_llm_gateway_*`, маскирование, запрет текстов в логах |
| [ADR-013](../../ADR/ADR-013-secrets-management.md) | основан на | AES-256-GCM, nonce, AAD, `key_version`, ротация и перешифровка, `PLATFORM_LLM_API_KEY`, `LLM_KEYS_ENCRYPTION_*`, `DEBUG_MODE` |
| [ADR-014](../../ADR/ADR-014-search-engines.md) | основан на | `EmbeddingsProvider`, `model_id` в payload точки Qdrant, заглушка эмбеддингов, контейнер `embeddings` (OQ-59) |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-09](../../open-questions.md) | провайдер и лимиты модели платформы — значения параметров SYS-08-R8, R9 | нет | resolved: российский провайдер через OpenAI-совместимый адаптер; лимиты 20 сообщений / 15 мин / 3 теста с IP / 2 млн токенов в сутки, «уточняются после запуска» |
| [OQ-26](../../open-questions.md) | единый адаптер для внешних и локальных моделей — SYS-08-R2, R5, R20 (решает) | да | planned → SYS-08; закрывается утверждением этой спецификации |
| [OQ-45](../../open-questions.md) | модель платформы и модель курса по умолчанию — SYS-08-R8, R11 (решает) | да | planned → SYS-08; закрывается утверждением этой спецификации; правка SDD_plan.md Г.6 — оркестратор |
| [OQ-57](../../open-questions.md) | harness — место в `llm_gateway` и правило «настройки дополняют промпт платформы» — SYS-08-R23 (решает часть SYS-08); перечень настроек — ТЗ STU-25 | нет | planned → SYS-08 и ТЗ STU-25 |
| [OQ-59](../../open-questions.md) | интерфейс `EmbeddingsProvider` и реализации `platform`/`stub` — SYS-08-R21; модель и контейнер — ТЗ STU-27 | нет | planned → ТЗ STU-27 и SYS-08 |
| [OQ-73](../../open-questions.md) | оценка usage при отмене и ошибке — SYS-08-R13 (решает) | да | planned → SYS-08; закрывается утверждением этой спецификации |
| [OQ-58](../../open-questions.md) | модель для публикаций персонажа — при выборе модели платформы потребуется изменение SYS-08-R8 | нет | planned → ТЗ ADM-06 |
| [OQ-67](../../open-questions.md) | чьи ключи использует AI-преподаватель в групповом занятии — политика «ключ ученика — только для ученика» (SYS-08-R11) потребует отдельного решения | нет | planned → спецификация `classroom`, ТЗ TCH-08 |
| [OQ-72](../../open-questions.md) | нормативы задержки голоса — влияют на таймауты провайдеров речи (SYS-08-R22) | нет | planned → SYS-02, ТЗ STU-28 |
| [OQ-81](../../open-questions.md) | учётные данные провайдеров речи хранит `llm_gateway`, `speech` получает их через `ProviderCredentialsService` (SYS-08-R6, R22, R31) | нет | open (рабочее решение принято; окончательно — ТЗ STU-28) |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
| 0.2 | 2026-10-11 | Claude | Согласование SYS-01…SYS-12: R2 — метод `stream_completion` (ADR-009) и свойство `kind`, сигнатуры — контракт точки SYS-09-R7; R4 — сигнатура `factory` и `ProviderBindingConfig`; R6 — колонка `service` (`llm`/`speech`); R22 — сигнатуры `STTProvider`/`TTSProvider` совпадают с SYS-09-R9, ключи речи хранит `llm_gateway` (OQ-81), исключение раздела 6 для R22 снято; новое R31 `ProviderCredentialsService`; пути тестов N3 — `tests/n_instances/llm_gateway/`; срок хранения `usage_records` 400 суток (SYS-02); раздел 9 — OQ-81; термин и таблица `provider_connection(s)` → `provider_binding(s)` (как в ADR-009 и SYS-01, SYS-06), REST `/api/v1/llm-gateway/provider-bindings` | draft |
