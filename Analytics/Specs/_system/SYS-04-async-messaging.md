# SYS-04 — Асинхронное взаимодействие (WebSocket и Kafka)

| Поле | Значение |
|---|---|
| Статус | draft |
| Версия | 0.2 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | все |
| Модуль | все backend-модули, shared kernel (`app/core/ws`, `app/core/kafka`), frontend (`src/lib/ws`), `src/protocol` (локальный агент), `src/tools/contracts` |
| Зависимости | ADR-002, ADR-003, ADR-004, ADR-006, ADR-008, ADR-009, ADR-010, ADR-012 |
| Связанные ADR/SYS | ADR-005, ADR-011, ADR-013, ADR-014, ADR-015; SYS-03, SYS-05, SYS-06, SYS-08, SYS-10, SYS-11, SYS-12 |

## 1. Цель и область действия

- **Цель**: зафиксировать протокол WebSocket монолита (эндпоинты, аутентификация, конверт, каналы, подписки, бинарные кадры, коды закрытия, heartbeat, переподключение, доставка между инстансами, лимиты) и правила Kafka (имена топиков, конверт события, заголовки, ключи, партиции и retention, transactional outbox, inbox, ретраи и dead letter topic, фоновые задания и планировщик, версионирование схем, consumer group, создание топиков), а также формат контрактов AsyncAPI и их сверку с реализацией — так, чтобы любая фича работала на N инстансах, не теряла и не дублировала события, а фронтенд и локальный агент использовали один конверт сообщений.
- **Область действия**: backend (shared kernel `app/core/ws` и `app/core/kafka`, обработчики WebSocket и Kafka модулей), frontend (общий WebSocket-клиент `src/lib/ws`, генерация zod-схем из AsyncAPI), локальный агент (`src/protocol`, `src/agent` — этап 4), deploy (создание топиков ролью `migrate`, параметры брокера по стендам — через SYS-11), tests (`TestKafkaBroker`, контрактные тесты AsyncAPI, тесты на N инстансах), CI (job `contracts` для `asyncapi.yaml`).
- **Действует с этапа**: 1 (shared kernel Г.4, стрим заглушки LLM Г.6, E2E Г.11).
- **Уточняет**: CLAUDE.md, разделы «Взаимодействие» (пометка «именование топиков — утвердить в SYS-04» закрывается этой спецификацией; формат сообщений WebSocket) и «Масштабирование и состояние» (доставка WebSocket между инстансами, задания в consumer group); ADR-004 (разделы 3.3 WebSocket, 3.4 Kafka, 3.5 роли), ADR-009 (семантика стрима поверх конверта, бинарные аудиокадры, обратное давление, остановка инстанса), ADR-008 (`/ws/agent`, пространства типов агента), ADR-006 (аутентификация WebSocket при handshake, код 4401), ADR-010 (`request_id` в заголовках Kafka и сообщениях WebSocket, метрики), ADR-012 (`timeout tunnel 1h`, ping раз в 30 с). Решает OQ-24 (именование топиков Kafka).

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| Доменное событие, топик Kafka, transactional outbox, inbox, консьюмер, consumer group, dead letter topic, фоновое задание, распределённая блокировка | [глоссарий](../../glossary.md), раздел 12 |
| Стриминг | [глоссарий](../../glossary.md), раздел 5 |
| Локальный агент, токен агента, версия протокола агента | [глоссарий](../../glossary.md), раздел 5 |
| Контракт API, контрактный тест | [глоссарий](../../glossary.md), раздел 12 |
| ID запроса (`request_id`), роль монолита (`app_role`) | [глоссарий](../../glossary.md), раздел 12 |
| Конверт WebSocket (`WsEnvelope`) | Объект `{type, correlation_id, channel, seq, ts, payload}` — единственная форма текстового сообщения на `/ws` и `/ws/agent` в обе стороны (SYS-04-R3) |
| Канал WebSocket (`channel`) | Именованный поток событий `<module>.<channel>[:<id>]`, на который клиент подписывается и который принадлежит модулю (SYS-04-R5) |
| Обработчик канала (`WsChannelHandler`) | Объект модуля, зарегистрированный в shared kernel: проверяет право подписки и обрабатывает входящие команды своих типов (SYS-04-R6) |
| Команда задания (`job command`) | Сообщение Kafka в топике `flt.<module>.jobs.<job>.v<N>`, которым роль `api` поручает роли `worker` выполнить фоновое задание (SYS-04-R29) |
| Декларация топика (`TopicDeclaration`) | Описание топика в `public/topics.py` модуля: имя, вид (`event` или `job`), видимость (`visibility`: `public` или `internal`), число партиций, retention, схема сообщения, по которому роль `migrate` создаёт топик, а консьюмеры подписываются (SYS-04-R21) |
| Общие схемы AsyncAPI (`asyncapi-common.yaml`) | Файл `Analytics/Specs/_system/asyncapi-common.yaml` со схемами `WsEnvelope`, `EventEnvelope`, типов shared kernel и серверов, на который ссылаются контракты модулей (SYS-04-R33) |

## 3. Требования

### 3.1. WebSocket

### SYS-04-R1 Единственный эндпоинт `/ws` и эндпоинт агента `/ws/agent`

- **Формулировка**: монолит должен обслуживать ровно два WebSocket-маршрута на роли `api`: `/ws` для фронтенда (браузер, будущие мобильные клиенты) и `/ws/agent` для локального агента; оба реализуются shared kernel `app/core/ws`, модули не должны объявлять собственных WebSocket-маршрутов и обязаны подключать каналы и команды только через `ModuleDefinition.ws_handlers`.
- **Обоснование**: ADR-004, раздел 2.1 A (один эндпоинт с мультиплексированием каналов, одна аутентификация и одно переподключение, один маршрут `/ws/*` в HAProxy); ADR-008 (`/ws/agent` с тем же конвертом и собственной аутентификацией); ADR-012 (`path_beg /ws/` → `be_api_ws`).
- **Проверка**: архитектурный тест `tests/architecture/test_route_inventory.py` (SYS-03-R25: WebSocket-маршруты приложения — только `/ws` и `/ws/agent`, оба из `app.core.ws`); AST-тест `test_no_websocket_routes_in_modules` (в `app/modules/**` нет `@router.websocket` и `WebSocketRoute`).
- **Применимость**: backend, tests.

### SYS-04-R2 Аутентификация при handshake

- **Формулировка**: соединение `/ws` должно аутентифицироваться один раз при HTTP-handshake по правилам ADR-006, раздел 3.4: заголовок `Authorization: Bearer <access JWT>` либо cookie `__Host-flt_access` с проверкой заголовка `Origin` против `APP_PUBLIC_URL`; анонимное соединение допускается только с cookie анонимной сессии быстрого теста (имя и выдача — ТЗ VIS-03, права — SYS-06); токен в query-string запрещён; при неуспехе сервер принимает соединение и немедленно закрывает его кодом `4401` с причиной `unauthenticated`, не отправляя сообщений; идентичность соединения (`user_id`, `sid`, роли, permissions) фиксируется на всё время жизни, истечение access-токена соединение не разрывает, отзыв сессии — событием по каналу пользователя (SYS-04-R13) с закрытием `4401` и причиной `session_revoked`; соединение `/ws/agent` аутентифицируется токеном `flta_…` обработчиком модуля `local_runtime` (SYS-04-R17).
- **Обоснование**: ADR-006, разделы 2.4 (аутентификация WebSocket — cookie или Bearer при handshake, токен в query отвергнут) и 3.7; ADR-004 (код 4401; первое сообщение `auth` не нужно, поскольку все клиенты FLT передают cookie или заголовок — поэтому тип `auth` из перечня ADR-004 не вводится, а правило «5 с на аутентификацию» заменяется проверкой при handshake). Закрытие после `accept` вместо HTTP 403 нужно, чтобы браузерный клиент получил код `4401` и запустил `refresh` (ADR-005).
- **Проверка**: интеграционные тесты `tests/core/ws/test_handshake_auth.py` (Bearer — успех; cookie без `Origin` или с чужим `Origin` — 4401; cookie с валидным `Origin` — успех; токен в query — 4401; `flta_`-токен на `/ws` — 4401); тест на N инстансах `tests/n_instances/test_ws_session_revoke.py` (вход на A, соединение к B, `logout-all` на C → B закрывает соединение 4401 — ADR-006, раздел 3.9).
- **Применимость**: backend, frontend, tests.

### SYS-04-R3 Конверт текстового сообщения

- **Формулировка**: каждое текстовое сообщение на `/ws` и `/ws/agent` в обе стороны должно быть JSON-объектом ровно с шестью полями: `type` (строка `<namespace>.<name>` по SYS-04-R4), `correlation_id` (UUID: у команды клиента — генерирует клиент, у ответов и событий сервера — повторяет команду, у событий без команды — `event_id` исходного события или `request_id` вызвавшего запроса), `channel` (строка канала по SYS-04-R5 или `null` для типов shared kernel, адресных событий пользователя и всех сообщений агента), `seq` (целое с 0: у сообщений сервера — счётчик соединения, монотонный по всем исходящим сообщениям независимо от канала; у сообщений клиента — счётчик клиента на соединение), `ts` (время отправителя ISO 8601 UTC с `Z` и миллисекундами), `payload` (объект по схеме типа; пустой объект, если данных нет); размер сериализованного сообщения — не более 64 КиБ (`WS_MAX_MESSAGE_BYTES`), сообщение с лишними или отсутствующими полями отклоняется ответом `ws.error` с кодом `ws.invalid_envelope`.
- **Обоснование**: ADR-004, раздел 3.3 (поля конверта и их семантика); ADR-009 (стрим использует `correlation_id` клиента во всех сообщениях; `seq` внутри `payload.seq` стрима — отдельный счётчик стрима, не путать с `seq` конверта); ADR-010 (`correlation_id` связывает сообщения с `request_id` в логах). Единая форма позволяет сгенерировать один zod-парсер конверта (ADR-005).
- **Проверка**: схема `WsEnvelope` в `asyncapi-common.yaml` (SYS-04-R33) и Pydantic-модель `WsEnvelope` в `app/core/ws/envelope.py` сверяются тестом `tests/contracts/test_ws_envelope_schema.py`; тест `tests/core/ws/test_envelope_validation.py` (лишнее поле, отсутствие `seq`, размер > 64 КиБ); монотонность `seq` — тест `tests/core/ws/test_seq_monotonic.py` при одновременной публикации в два канала.
- **Применимость**: backend, frontend, агент, tests.

### SYS-04-R4 Пространства имён типов сообщений

- **Формулировка**: значение `type` должно иметь вид `<namespace>.<object>.<event>` или `<namespace>.<event>` в snake_case, где `<namespace>` — имя модуля-владельца (`llm_gateway.completion.delta`, `classroom.presence.changed`, `<module>.job.progress`) или зарезервированное пространство: `ws` — типы shared kernel на `/ws` (`ws.subscribe`, `ws.unsubscribe`, `ws.ping` от клиента; `ws.ack`, `ws.error`, `ws.pong` от сервера); `agent`, `engine`, `llm`, `model`, `hardware` — типы протокола агента на `/ws/agent` (ADR-008, раздел 3.5); тип модуля обрабатывается только зарегистрированным обработчиком этого модуля; неизвестный тип на `/ws` → `ws.error` с кодом `ws.unknown_type` без разрыва соединения; типы `auth` и `event` из перечня ADR-004 не вводятся (аутентификация — при handshake, SYS-04-R2; события несут тип модуля напрямую).
- **Обоснование**: ADR-004 (типы shared kernel и `<module>.<name>` модулей; `job.progress`/`completed`/`failed`); ADR-009, раздел 3.1 (`<модуль>.<объект>.<событие>`); ADR-008 (пространства агента и белый список). Префикс `ws.` у типов shared kernel делает правило «первый сегмент — владелец» единым, что проверяется автоматически.
- **Проверка**: правило Spectral `flt-ws-message-name` (имя каждого `message` с `x-flt-transport: websocket` соответствует `^(ws|<module>)\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$`, где `<module>` — имя модуля контракта; для `local_runtime` разрешены пространства агента); архитектурный тест `test_ws_handlers_own_their_types` (у каждого `WsChannelHandler` модуля все `command_types` начинаются с `<module>.`); тест `tests/core/ws/test_unknown_type.py`.
- **Применимость**: backend, CI, tests.

### SYS-04-R5 Имена каналов и владение

- **Формулировка**: имя канала должно соответствовать `^<module>\.[a-z][a-z0-9_]*(:[A-Za-z0-9_-]{1,64})?$`, где `<module>` — модуль-владелец, необязательный суффикс после `:` — идентификатор сущности (UUID или код); канал объявляется в `asyncapi.yaml` модуля (SYS-04-R33) с REST-эндпоинтом состояния (`x-flt-state-endpoint`, SYS-03-R27 и ADR-004: «у каждого канала есть REST-эндпоинт текущего состояния»); публиковать в канал может только модуль-владелец, подписка проверяется его обработчиком (SYS-04-R6, SYS-04-R7); каналы без владельца (`ws.*`) не существуют — адресные события пользователя доставляются с `channel: null` (SYS-04-R13).
- **Обоснование**: ADR-004, раздел 2.1 A (`<module>.<channel>[:<id>]`, права проверяет модуль-владелец, транспорт — shared kernel) и 3.3 (восстановление состояния через REST после переподключения).
- **Проверка**: правило Spectral `flt-ws-channel-address` (адрес канала с `x-flt-transport: websocket` соответствует шаблону и начинается с имени модуля контракта; `x-flt-state-endpoint` обязателен и указывает на операцию `get` из `openapi.yaml` того же модуля — проверяет `flt-tools contracts check`); архитектурный тест `test_ws_publish_only_own_channels` (AST: аргумент `channel` в вызовах `WsPublisher.publish` в `app/modules/<module>` начинается с литерала `<module>.`); runtime-проверка в `WsPublisher` поднимает `ChannelOwnershipError`.
- **Применимость**: backend, CI, tests.

### SYS-04-R6 Подписка и отписка

- **Формулировка**: клиент подписывается сообщением `ws.subscribe` с `payload: {"channel": "<channel>"}` и получает `ws.ack` с `payload: {"op": "subscribe", "channel": "<channel>", "state_url": "<REST-путь состояния или null>"}` либо `ws.error` с `payload: {"code": "ws.forbidden" | "ws.unknown_channel" | "ws.subscription_limit" | "ws.invalid_channel", "message": "<англ.>", "channel": "<channel>"}`; отписка — `ws.unsubscribe` с тем же `payload` и `ws.ack` с `op: "unsubscribe"`; повторная подписка на уже подписанный канал — `ws.ack` без побочных эффектов; сообщения канала доставляются только после `ws.ack`; при закрытии соединения все подписки снимаются сервером.
- **Обоснование**: ADR-004, раздел 3.3 (подписка через `can_subscribe`, при отказе `error` с `forbidden`); явный `ack` даёт клиенту точку, после которой он читает состояние по REST (`state_url`) и не пропускает событий между чтением и подпиской.
- **Проверка**: тесты `tests/core/ws/test_subscribe.py` (все коды ошибок, идемпотентность повторной подписки, снятие подписок при закрытии); схемы `ws.subscribe`, `ws.ack`, `ws.error` — в `asyncapi-common.yaml`.
- **Применимость**: backend, frontend, tests.

### SYS-04-R7 Право на канал проверяется на сервере

- **Формулировка**: shared kernel должен перед подпиской вызывать `await handler.can_subscribe(principal, channel) -> bool` обработчика модуля-владельца, передавая `UserSecuritySchema` соединения (для анонима — `anonymous` с идентификатором анонимной сессии); обработчик обязан проверять право через permissions SYS-06 и принадлежность сущности из суффикса канала (например, `lessons.lesson:<lesson_id>` — ученик занятия или преподаватель его класса); отсутствие обработчика для канала → `ws.unknown_channel`; обработчик, вернувший `True` без проверки, — нарушение, ловимое тестом ТЗ.
- **Обоснование**: CLAUDE.md «Ключевые архитектурные требования» (права проверять на сервере, не только в UI); ADR-004 (проверка права подписки — ответственность модуля-владельца).
- **Проверка**: архитектурный тест `test_ws_handlers_implement_can_subscribe` (каждый обработчик реализует метод, и его тело не является `return True`); шаблон ТЗ требует критерий «подписка без права → `ws.forbidden`» для каждого канала (раздел 4.2).
- **Применимость**: backend, tests.

### SYS-04-R8 Входящие команды модулей

- **Формулировка**: входящее сообщение с типом модуля (`llm_gateway.completion.request`, `llm_gateway.completion.cancel`, `speech.session.start`) должно передаваться shared kernel обработчику модуля методом `await handler.on_command(connection, envelope)` без интерпретации `payload`; обработчик валидирует `payload` Pydantic-моделью из `public/ws_messages.py` своего модуля и при ошибке отвечает `ws.error` с кодом `<module>.invalid_payload` и `details.errors` в формате SYS-03-R9; команда без обязательного `correlation_id` отклоняется кодом `ws.invalid_envelope`; обработчик не должен блокировать цикл чтения соединения дольше 100 мс — длительная работа выполняется в задаче `asyncio`, привязанной к соединению и отменяемой при его закрытии.
- **Обоснование**: ADR-004, раздел 3.3 (команды модуля передаются обработчику через контейнер); ADR-009, разделы 3.4 и 3.5 (стрим — задача на инстансе соединения, отмена при разрыве).
- **Проверка**: тест `tests/core/ws/test_command_dispatch.py` (маршрутизация по типу, невалидный `payload`, отмена задач при закрытии); контрактный тест модуля (SYS-04-R34) валидирует примеры из `asyncapi.yaml` моделями `public/ws_messages.py`.
- **Применимость**: backend, tests.

### SYS-04-R9 Бинарные кадры

- **Формулировка**: бинарное WebSocket-сообщение должно начинаться с заголовка из 9 байт: тип кадра (1 байт), `stream_id` (4 байта, big-endian, выдаётся сервером в текстовом сообщении открытия потока, например `speech.session.ready`), `seq` (4 байта, big-endian, с 0 в пределах `stream_id`, без пропусков); далее — данные кадра; типы: `0x01` — аудио клиента, `0x02` — аудио сервера, `0x03`–`0x7F` — резерв для будущих типов фронтенда (назначаются только через изменение SYS-04), `0x80`–`0xFF` — резерв протокола агента (ADR-008); кадр с неизвестным `stream_id`, закрытым потоком или неизвестным типом отбрасывается с увеличением метрики `flt_ws_dropped_frames_total{reason}` и одним `ws.error` с кодом `ws.unknown_stream` на `stream_id`; размер кадра — не более 64 КиБ; поток закрывается текстовым сообщением модуля-владельца или закрытием соединения.
- **Обоснование**: ADR-004 (9-байтовый заголовок, остальные значения резервируются в SYS-04); ADR-009, раздел 3.7 (PCM16-кадры по 20 мс, `speech.session.start`/`ready`, barge-in текстовым сообщением).
- **Проверка**: unit-тесты `tests/core/ws/test_binary_frames.py` (разбор заголовка, отбрасывание, метрика); схема кадра описана в `asyncapi-common.yaml` как `x-flt-binary-frame` (документация, без автоматической валидации).
- **Применимость**: backend, frontend, агент, tests.

### SYS-04-R10 Коды закрытия

- **Формулировка**: сервер должен закрывать соединение только кодами из таблицы, передавая причину (`reason`) из колонки «Причина» (ASCII, до 123 байт); клиент выбирает поведение по коду.

| Код | Причина (`reason`) | Когда | Действие клиента |
|---|---|---|---|
| `1000` | `client_close` | штатное закрытие клиентом | — |
| `1008` | `policy_violation` | три нарушения лимита входящих сообщений за минуту (SYS-04-R14) или три `ws.invalid_envelope` подряд | переподключение с задержкой не менее 30 с |
| `1009` | `message_too_big` | сообщение больше `WS_MAX_MESSAGE_BYTES` | исправить клиент; переподключение |
| `1011` | `send_timeout` или `pong_timeout` или `internal_error` | `send` не завершился за `WS_SEND_TIMEOUT_SECONDS=15`; нет `ws.pong` за 60 с; необработанное исключение | переподключение по backoff (SYS-04-R12) |
| `1012` | `instance_shutdown` | остановка инстанса (SIGTERM) после `SHUTDOWN_GRACE_SECONDS=30` | переподключение немедленно, без задержки |
| `1013` | `outbox_overflow` | исходящая очередь соединения превысила `WS_OUTBOX_MAX=1000` | переподключение по backoff, состояние каналов — по REST |
| `4401` | `unauthenticated` или `session_revoked` | handshake без действительной аутентификации; сессия отозвана | `POST /api/v1/auth/refresh`, затем переподключение; при неуспехе — экран входа |
| `4426` | `agent_update_required` | только `/ws/agent`: `protocol_version` ниже `min_protocol_version` (ADR-008) | агент показывает инструкцию по обновлению, не переподключается |
| `4429` | `too_many_connections` | шестое соединение одного пользователя (SYS-04-R14) | закрыть лишние вкладки; переподключение через 10 с |

- **Обоснование**: ADR-004, раздел 3.3 (коды 1011, 1012, 1013, 4401, 4429, 4426); ADR-009 (`WS_SEND_TIMEOUT_SECONDS`, `WS_OUTBOX_MAX`, `SHUTDOWN_GRACE_SECONDS`); коды 1008 и 1009 — стандарт RFC 6455 для нарушений протокола.
- **Проверка**: тест `tests/core/ws/test_close_codes.py` (каждая строка таблицы воспроизводится; других кодов `WsConnection.close` не принимает — перечисление `WsCloseCode`); клиентский тест `src/lib/ws/client.test.ts` (поведение по каждому коду).
- **Применимость**: backend, frontend, агент, tests.

### SYS-04-R11 Heartbeat

- **Формулировка**: сервер должен отправлять `ws.ping` с `payload: {"server_ts": "<ISO>"}` каждые `WS_PING_INTERVAL_SECONDS=30` и закрывать соединение кодом `1011` (`pong_timeout`), если за `WS_PONG_TIMEOUT_SECONDS=60` не получено ни `ws.pong`, ни иного сообщения клиента; клиент отвечает `ws.pong` с `payload: {"server_ts": <из ping>, "client_ts": "<ISO>"}`; клиент может отправлять `ws.ping` сам (сервер отвечает `ws.pong`) для измерения RTT; на `/ws/agent` в дополнение используются `agent.heartbeat` каждые 30 с и ping/pong уровня протокола WebSocket (ADR-008); любой трафик сбрасывает `timeout tunnel 1h` HAProxy.
- **Обоснование**: ADR-004 (ping каждые 30 с, закрытие без pong за 60 с); ADR-012, раздел 3.5 (`timeout tunnel 1h`, клиент и агент шлют ping раз в 30 с); браузерный клиент не может отправлять ping-кадры протокола, поэтому heartbeat прикладной.
- **Проверка**: тест `tests/core/ws/test_heartbeat.py` с `Clock` shared kernel (ADR-003); клиентский тест `src/lib/ws/client.test.ts::pong`.
- **Применимость**: backend, frontend, агент, tests.

### SYS-04-R12 Переподключение и восстановление состояния

- **Формулировка**: общий WebSocket-клиент shared-слоя фронтенда (`src/lib/ws`, ADR-005) должен при разрыве переподключаться с экспоненциальной задержкой от 1 до 30 с с полным джиттером (после `1012` — немедленно; после `4401` — после успешного `refresh`; после `1008` — не раньше 30 с), восстанавливать подписки повторной отправкой `ws.subscribe` для каждого активного канала и после каждого `ws.ack` вызывать REST-эндпоинт состояния канала (`state_url`); события WebSocket — уведомления, а не источник истины; незавершённый стрим LLM не возобновляется — клиент читает частичный ответ по REST (`interrupted = true`) и повторяет запрос с новым `correlation_id` (ADR-009, раздел 3.5); пропуск в `seq` конверта клиент трактует как потерю и перечитывает состояние подписанных каналов по REST.
- **Обоснование**: ADR-004, раздел 3.3 (переподключение 1–30 с, переподписка, REST-эндпоинт состояния на канал, стрим не возобновляется); ADR-003 (pub/sub не хранит сообщения); ADR-005 (общий клиент, `refresh` перед переподключением).
- **Проверка**: клиентские тесты `src/lib/ws/reconnect.test.ts` на моках `msw ws.link` (ADR-005); E2E Г.11 на N инстансах: остановка инстанса посреди стрима, переподключение к другому инстансу, чтение частичного ответа, повтор (SYS-10).
- **Применимость**: frontend, tests.

### SYS-04-R13 Доставка между инстансами через Redis pub/sub

- **Формулировка**: публикация события в канал с любого инстанса и любой роли должна выполняться только через `WsPublisher` shared kernel: `publish(channel, type, payload, *, correlation_id)` → `PUBLISH ws:channel:<channel> <JSON без seq>`; адресные события пользователя — `publish_to_user(user_id, type, payload, *, correlation_id)` → `PUBLISH ws:user:<user_id> …` (доставляются во все соединения пользователя без подписки, `channel: null`); инстанс держит таблицу «канал → локальные соединения», выполняет `SUBSCRIBE ws:channel:<channel>` при первой локальной подписке и `UNSUBSCRIBE` при последней, `SUBSCRIBE ws:user:<user_id>` — при первом соединении пользователя; для pub/sub используется отдельное соединение `PubSub`, не из общего пула; `seq` присваивает инстанс-держатель соединения при отправке; размер сообщения pub/sub — не более 64 КиБ; через pub/sub не передаются токены ответа LLM (только события прогресса, завершения и ошибки — ADR-009, раздел 3.2); каналы `ws:*` принадлежат shared kernel, каналы запрос–ответ `<module>:...:inbox` и `<module>:reply:<request_id>` — модулю-владельцу (ADR-008); при недоступности Redis публикация регистрируется в метрике `flt_ws_publish_failed_total` и логе, соединения не рвутся (ADR-003, таблица отказа Redis).
- **Обоснование**: CLAUDE.md «Масштабирование и состояние» (событие доставляется клиенту, к какому бы инстансу он ни был подключён); ADR-004, раздел 3.3; ADR-003, правило 6; ADR-009 (токены не через pub/sub).
- **Проверка**: тест на N инстансах `tests/n_instances/core/test_ws_cross_instance.py` (подписка на инстансе A, публикация с инстанса B и из роли `worker`, доставка на A с корректным `seq`; `publish_to_user` доходит до двух соединений на разных инстансах); архитектурный тест `test_no_direct_redis_publish` (контракт import-linter 5 ADR-002 плюс AST: `PUBLISH` только в `app/core`); тест отключения Redis `tests/core/ws/test_publish_without_redis.py`.
- **Применимость**: backend, tests.

### SYS-04-R14 Лимиты соединений, подписок и сообщений

- **Формулировка**: shared kernel должен применять лимиты: соединений на пользователя — `WS_MAX_CONNECTIONS_PER_USER=5` (счётчик `shared_kernel:ws:conns:<user_id>` в Redis, TTL 60 с с продлением heartbeat-ом; превышение — `4429`); подписок на соединение — `WS_MAX_SUBSCRIPTIONS_PER_CONNECTION=50` (`ws.subscription_limit`); входящих сообщений — `WS_MAX_INBOUND_PER_SECOND=20` на соединение (превышение → `ws.error` с кодом `ws.rate_limited` и `retry_after_ms`, третье превышение за минуту → `1008`); бинарных кадров — `WS_MAX_INBOUND_FRAMES_PER_SECOND=100` на соединение (аудио 20 мс = 50 кадров/с); исходящей очереди — `WS_OUTBOX_MAX=1000` сообщений (`1013`); одновременных стримов LLM на соединение — `LLM_MAX_CONCURRENT_STREAMS_PER_CONNECTION=3` (SYS-08); анонимные соединения быстрого теста — `WS_MAX_ANONYMOUS_CONNECTIONS_PER_IP=3`; все значения — параметры конфигурации shared kernel, одинаковые в docker-compose и Helm.
- **Обоснование**: ADR-004 (лимит 5 соединений, ключ `shared_kernel:ws:conns`); ADR-009 (`WS_OUTBOX_MAX`, 3 стрима на соединение); OQ-13 (300 соединений, 50 стримов); лимит входящих защищает инстанс от злоупотребления без HAProxy-уровня (ADR-012: stick-table не видит сообщения внутри туннеля).
- **Проверка**: тесты `tests/core/ws/test_limits.py`; тест на N инстансах `tests/n_instances/core/test_ws_connection_limit.py` (шесть соединений через HAProxy на разные инстансы → одно закрыто `4429`; лимит глобальный — SYS-05).
- **Применимость**: backend, deploy, tests.

### SYS-04-R15 Корреляция и логи WebSocket

- **Формулировка**: при обработке входящего сообщения shared kernel должен устанавливать контекст лога `request_id = correlation_id` сообщения, `user_id`, `connection_id`, `channel`, `type`; при публикации события из REST-запроса или консьюмера `correlation_id` берётся из текущего `request_id`; в логи не пишутся `payload` сообщений и содержимое бинарных кадров (только `type`, размер, `seq`); ошибки обработки команд пишутся с полем `code`.
- **Обоснование**: ADR-010 (`request_id` — ключ корреляции HAProxy → инстанс → Kafka; запрет секретов и персональных данных в логах); ADR-008 (в логах — идентификаторы и размеры, никогда — промпты и ответы).
- **Проверка**: тест `tests/core/ws/test_log_context.py` с перехватом structlog; процессор `redact_sensitive_keys` (ADR-010) покрывает ключ `payload` в контексте WebSocket.
- **Применимость**: backend, tests.

### SYS-04-R16 Прогресс и завершение фоновых заданий по WebSocket

- **Формулировка**: прогресс фонового задания должен доставляться адресно пользователю-владельцу (`publish_to_user`) сообщениями `<module>.job.progress` с `payload: {"job_id", "stage", "percent", "message_key"}` не чаще одного раза в секунду на задание, завершение — `<module>.job.completed` с `payload: {"job_id", "result_ref"}` или `<module>.job.failed` с `payload: {"job_id", "code", "details"}`; `correlation_id` этих сообщений равен `job_id`; состояние задания всегда доступно по `GET /api/v1/<module>/jobs/{job_id}` (SYS-03-R27).
- **Обоснование**: ADR-004 (типы `job.progress`/`completed`/`failed`, не чаще 1 сообщения в секунду); ADR-009, раздел 3.2 (прогресс через pub/sub, результат — в PostgreSQL и по REST).
- **Проверка**: схемы `JobProgressPayload`, `JobCompletedPayload`, `JobFailedPayload` — в `asyncapi-common.yaml` и `app/core/kafka/jobs.py`; тест `tests/core/kafka/test_job_progress_throttle.py`; E2E Г.11 (тестовое задание через Kafka с прогрессом по WebSocket на другом инстансе).
- **Применимость**: backend, frontend, tests.

### SYS-04-R17 Соединение локального агента `/ws/agent`

- **Формулировка**: соединение `/ws/agent` должно: аутентифицироваться заголовком `Authorization: Bearer flta_<token>`, проверяемым обработчиком модуля `local_runtime` по `sha256` в `local_runtime.agents` (иной токен, в том числе JWT пользователя, → `4401`); использовать конверт SYS-04-R3 с `channel: null` и сквозным `seq`; начинаться кадром `agent.hello` и ответом `agent.hello_ack` (поля — ADR-008, раздел 3.5), при `protocol_version` ниже `min_protocol_version` закрываться кодом `4426`; принимать только типы из белого списка `flt_protocol.agent.enums.MessageType` (пространства `agent`, `engine`, `llm`, `model`, `hardware`; неизвестный тип → `agent.error` с `code: UNSUPPORTED_MESSAGE_TYPE` без разрыва); поддерживать `agent.heartbeat` каждые 30 с с продлением реестра `local_runtime:agent:<agent_id>:instance` (TTL 90 с) и закрытием после двух пропусков; маршрутизировать запросы к агенту с других инстансов через каналы `local_runtime:agent:<agent_id>:inbox` и `local_runtime:reply:<request_id>` (ADR-008, раздел 3.7); контракт — `Analytics/Specs/local_runtime/api/asyncapi.yaml`, схемы — пакет `flt_protocol` (`src/protocol`), общий для монолита и агента. На этапе 1 реализуется только резервирование маршрута и пространств типов; код — этап 4 (STU-05).
- **Обоснование**: ADR-008, разделы 3.5–3.7 и 3.9 (этап 1 — резерв); ADR-006, раздел 3.4 (токен агента — отдельный тип учётных данных, только `/ws/agent`); ADR-004 (канал ответа `<module>:reply:<request_id>`, код 4426).
- **Проверка**: этап 1 — архитектурный тест `test_route_inventory` (маршрут `/ws/agent` зарегистрирован shared kernel и отвечает `4401` на любой токен до появления `local_runtime`); этап 4 — тесты `tests/modules/local_runtime/ws/`, контрактный тест `tests/contracts/test_asyncapi_local_runtime.py`, тесты масштабируемости из ADR-008, раздел 3.7.
- **Применимость**: backend, агент, tests.

### SYS-04-R18 Остановка инстанса

- **Формулировка**: по `SIGTERM` роль `api` должна перевести `/v1/ready` в `503`, перестать принимать новые соединения и новые стримы (ответ `error` с кодом `instance_shutdown`, `retryable: true` — SYS-08), дать активным стримам `SHUTDOWN_GRACE_SECONDS=30` на завершение, затем закрыть все соединения кодом `1012`; роль `worker` должна прекратить `poll`, завершить обработку текущего сообщения (не дольше `max.poll.interval.ms`), зафиксировать транзакцию и ack, отпустить блокировки relay и планировщика; `terminationGracePeriodSeconds` (Helm) и `stop_grace_period` (compose) — 40 с.
- **Обоснование**: ADR-004, разделы 2.5 A и 3.5; ADR-009, раздел 3.4; ADR-012, раздел 3.5 (readiness 503 снимает инстанс с балансировки); CLAUDE.md «Масштабирование и состояние» (инстанс можно остановить в любой момент).
- **Проверка**: E2E Г.11 на N инстансах (остановка `flt-api-2` и `flt-worker-2` посреди сценария — ADR-011, job `stand-n3`); тест `tests/core/ws/test_graceful_shutdown.py` с `Clock`; проверка значений grace-периода в compose и Helm — тест конфигурации SYS-11.
- **Применимость**: backend, deploy, tests.

### 3.2. Kafka

### SYS-04-R19 Именование топиков (решает OQ-24)

- **Формулировка**: имя топика события должно соответствовать `^flt\.(?P<module>[a-z][a-z0-9_]*)\.(?P<event>[a-z][a-z0-9_]*)\.v(?P<major>[1-9][0-9]*)$`, где `<module>` — модуль-владелец, `<event>` — имя события в прошедшем времени (`user_registered`, `entry_generated`); имя топика команд заданий — `^flt\.(?P<module>[a-z][a-z0-9_]*)\.jobs\.(?P<job>[a-z][a-z0-9_]*)\.v[1-9][0-9]*$`, где `<job>` — глагол в инфинитиве (`extract_text`, `generate_plan`); dead letter topic — `<topic>.dlq`; retry-топики не вводятся (ретраи в процессе — SYS-04-R27); модуль публикует только в топики со своим `<module>`; схема `<модуль>.<событие>` из CLAUDE.md заменяется этой.
- **Обоснование**: ADR-004, разделы 2.2 A и 3.4 (вариант принят, SYS-04 фиксирует как требование и закрывает OQ-24); префикс `flt.` исключает конфликты в общем брокере стендов; версия в имени даёт несовместимым изменениям отдельный топик (SYS-04-R30).
- **Проверка**: архитектурный тест `tests/architecture/test_topic_declarations.py` (каждая `TopicDeclaration` в `app/modules/<module>/public/topics.py` соответствует регулярному выражению и содержит `<module>` своего пакета; имена уникальны в монолите); правило Spectral `flt-kafka-channel-address` (адрес канала с `x-flt-transport: kafka` соответствует шаблону и модулю контракта).
- **Применимость**: backend, CI, tests.

### SYS-04-R20 Конверт события

- **Формулировка**: тело сообщения события должно быть JSON-объектом `EventEnvelope` с полями: `event_id` (UUID v7, равен `outbox.id`), `event_type` (`<module>.<event>`, без префикса `flt.` и версии), `event_version` (целое ≥ 1, минорная версия схемы), `occurred_at` (ISO 8601 UTC `Z`), `producer` (имя модуля), `aggregate_type` (имя сущности в snake_case: `user`, `dictionary_entry`), `aggregate_id` (UUID сущности), `correlation_id` (UUID: `request_id` запроса, вызвавшего изменение, или `event_id` события-причины), `causation_id` (UUID события или команды, непосредственно вызвавшей это событие, либо `null`), `actor_id` (UUID пользователя, совершившего действие, или `null` для системы и анонима), `payload` (объект по схеме события модуля); модель — `app/core/kafka/envelope.py::EventEnvelope[PayloadT]`, события модулей — подклассы `BaseEvent` в `app/modules/<module>/public/events.py` с атрибутами `event_type`, `event_version`, `topic`, `aggregate_type`.
- **Обоснование**: ADR-004, раздел 3.4 (конверт с `event_id`, `event_type`, `event_version`, `occurred_at`, `producer`, `aggregate_id`, `correlation_id`, `causation_id`, `payload`); поля `aggregate_type` и `actor_id` добавлены для журнала аудита (ADM-01–ADM-06: кто и над каким объектом) и для фильтрации консьюмеров без разбора `payload` — добавление полей совместимо (SYS-04-R30).
- **Проверка**: контрактный тест `tests/contracts/test_event_envelope_schema.py` (Pydantic `EventEnvelope` против `asyncapi-common.yaml#/components/schemas/EventEnvelope`); архитектурный тест `test_events_declare_metadata` (у каждого подкласса `BaseEvent` заданы `event_type` = `<module>.<name>`, `topic` из деклараций модуля, `aggregate_type`); `TestKafkaBroker`-тесты модулей валидируют опубликованные сообщения `EventEnvelope`.
- **Применимость**: backend, tests.

### SYS-04-R21 Декларации топиков

- **Формулировка**: каждый топик модуля должен быть объявлен в `app/modules/<module>/public/topics.py` объектом `TopicDeclaration(name, kind="event" | "job", visibility="public" | "internal", partitions, retention, message_model, description)` и собран в кортеж `TOPICS`; `visibility="internal"` (значение по умолчанию) — топик читают только консьюмеры самого модуля; `visibility="public"` — топик могут читать консьюмеры других модулей, а с этапа 7 — плагины (SYS-09-R12), поэтому payload публичного события не содержит персональных данных сверх идентификаторов (SYS-02); `kind="job"` допускает только `internal`: команды заданий `flt.<module>.jobs.*` принимает только модуль-владелец; значения по умолчанию: `partitions=6`, `retention=timedelta(days=7)` для событий и команд, DLQ создаётся автоматически с `retention=timedelta(days=30)`; `brokers/topics.py` как отдельный `StrEnum` не ведётся — имена берутся из деклараций; консьюмер другого модуля импортирует декларацию из `public` модуля-владельца.
- **Обоснование**: ADR-004 (топики создаются ролью `migrate` по декларациям модулей — `topics.py` в публичном API; retention событий 7 суток, DLQ 30 суток, 6 партиций); подписка чужого модуля требует имени топика, поэтому декларация публична: ADR-002 v1.1 перенёс `topics.py` из `brokers/` в `public/`; поле `visibility` отделяет события, на которые можно подписываться, от внутренних команд заданий (правило ADR-004: другой модуль меняет данные владельца только командой в его топик заданий, публикуя её через outbox владельца или через публичный `Protocol`).
- **Проверка**: архитектурный тест `test_topic_declarations.py` (наличие `public/topics.py` у каждого модуля с `kafka_router` или `OutboxPublisher`; у каждого консьюмера модуля топик найден в декларациях модуля-владельца, а консьюмер чужого модуля подписан только на топик с `visibility="public"`; у `kind="job"` — только `visibility="internal"`); скаффолдер `make scaffold-subscriber` создаёт декларацию.
- **Применимость**: backend, tests.

### SYS-04-R22 Заголовки и ключ сообщения

- **Формулировка**: каждое сообщение события или команды должно иметь заголовки Kafka (строки UTF-8): `event_id`, `event_type`, `event_version`, `producer`, `content_type=application/json`, `request_id` (= `correlation_id` конверта), `traceparent` (middleware OpenTelemetry boilerplate; при выключенном экспорте — сгенерированный контекст), `schema` (`<module>.<EventClass>`); ключ сообщения — `aggregate_id` в строковом виде для событий и `job_id` для команд заданий; сообщение без ключа не публикуется (`OutboxPublisher` отклоняет).
- **Обоснование**: ADR-004 (заголовки `event_id`, `event_type`, `content_type`, `request_id`, `traceparent`; ключ — `aggregate_id`); ADR-010 (консьюмер привязывает `request_id` к своим логам); ключ по агрегату сохраняет порядок событий одного агрегата в одной партиции.
- **Проверка**: тест relay `tests/core/kafka/test_outbox_relay.py` (заголовки и ключ опубликованного сообщения); тест консьюмера `tests/core/kafka/test_consumer_context.py` (`request_id` из заголовка попадает в контекст лога).
- **Применимость**: backend, tests.

### SYS-04-R23 Параметры топиков по стендам

- **Формулировка**: роль `migrate` должна создавать топики с параметрами: `partitions` из декларации (на стенде local допускается `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true` с `num.partitions=1`); `replication.factor` — 1 в docker-compose (один брокер) и 3 в Kubernetes при трёх брокерах с `min.insync.replicas=2`; `retention.ms` из декларации; `cleanup.policy=delete`; для DLQ — `retention.ms` 30 суток; изменение `partitions` после создания выполняется только в сторону увеличения отдельной операцией `python -m app topics apply` роли `migrate` и фиксируется в ТЗ (порядок по агрегату для старых ключей при этом не гарантируется — ТЗ указывает, допустимо ли).
- **Обоснование**: ADR-004, раздел 3.4; число брокеров и конфигурация compose и Helm — SYS-11; `min.insync.replicas=2` с `acks=all` (SYS-04-R24) даёт сохранность при потере одного брокера.
- **Проверка**: интеграционный тест стенда N инстансов `tests/n_instances/core/test_topics_created.py` (после `migrate` все декларированные топики и их DLQ существуют с заявленными партициями и retention — через `AdminClient`); тест конфигурации SYS-11 на значения `replication.factor` по стендам.
- **Применимость**: backend, deploy, tests.

### SYS-04-R24 Transactional outbox

- **Формулировка**: событие или команда должны записываться в таблицу `<module>.outbox` (DDL — пример 4) вызовом `await OutboxPublisher.publish(session, event)` shared kernel в той же сессии SQLAlchemy и транзакции, что и изменение данных; прямой `broker.publish` вне shared kernel запрещён; relay выполняется в роли `worker` — один активный на модуль под блокировкой `shared_kernel:lock:outbox:<module>` (TTL 30 с, продление heartbeat-ом каждые 10 с): выборка `SELECT … WHERE published_at IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED`, публикация с `acks=all`, `enable.idempotence=true`, затем `UPDATE published_at = now()`; при ошибке публикации — `attempts += 1`, `last_error`, повтор при следующем проходе; пауза при пустой выборке 200 мс с ростом до 2 с; строки с `published_at` старше 7 суток удаляет периодическая задача shared kernel (регистрируется от имени каждого модуля); без Redis relay не стартует (fail-closed, ADR-003).
- **Обоснование**: CLAUDE.md «Взаимодействие» (события через outbox); ADR-004, раздел 2.3 A (один relay на модуль под блокировкой сохраняет порядок по агрегату; `SKIP LOCKED` страхует от двойной публикации при потере блокировки); ADR-003 (блокировки `SET NX PX` с токеном владельца).
- **Проверка**: контракт import-linter 6 `kafka-publish-only-via-outbox` и AST-тест `test_no_direct_broker_publish` (ADR-002); интеграционные тесты `tests/core/kafka/test_outbox_relay.py` (атомарность с откатом транзакции, порядок по агрегату, повтор при ошибке брокера, уборка); тест на N инстансах `tests/n_instances/test_outbox_failover.py` (два воркера: один relay активен; остановка `flt-worker-2` → второй подхватывает за ≤ 30 с; каждое событие опубликовано ровно один раз по `event_id`).
- **Применимость**: backend, tests.

### SYS-04-R25 Порядок событий агрегата

- **Формулировка**: все события одного агрегата должны публиковаться с одним `aggregate_id` (ключом) и из одной таблицы outbox, что при одном relay на модуль и `enable.idempotence=true` гарантирует порядок внутри партиции; консьюмер не должен полагаться на порядок между разными агрегатами и разными топиками; ТЗ, которому нужен порядок между агрегатами, обязано выразить его через `causation_id` и проверку состояния по REST или базе.
- **Обоснование**: ADR-004, раздел 2.3 (вариант B отвергнут из-за нарушения порядка); Kafka гарантирует порядок только в партиции.
- **Проверка**: тест `tests/core/kafka/test_outbox_relay.py::test_order_per_aggregate`; ревью раздела «Контракты → Kafka» ТЗ (чек-лист: события агрегата используют один `aggregate_id`).
- **Применимость**: backend, tests.

### SYS-04-R26 Идемпотентность консьюмера (inbox)

- **Формулировка**: обработчик сообщения должен выполняться декоратором `@idempotent_consumer(consumer="<module>.<handler>")` shared kernel в одной транзакции модуля: `INSERT INTO <module>.processed_events (consumer, event_id, processed_at) ON CONFLICT DO NOTHING` → при конфликте сообщение пропускается с ack и метрикой `flt_kafka_duplicates_total{consumer}`; иначе — бизнес-изменение, собственные события в outbox, `COMMIT`, затем ack Kafka (`AckPolicy.REJECT_ON_ERROR`, ack после commit); обработчик не должен вызывать внешние сервисы с побочным эффектом до фиксации записи в `processed_events` без собственной идемпотентности (ключ запроса провайдеру — `event_id`); строки `processed_events` старше 30 суток удаляет периодическая задача.
- **Обоснование**: CLAUDE.md «Взаимодействие» (консьюмеры идемпотентны); ADR-004, раздел 3.4 (таблица `processed_events`, ack после commit); at-least-once доставка Kafka и повтор при остановке воркера (SYS-04-R18).
- **Проверка**: архитектурный тест `test_consumers_are_idempotent` (каждый `@subscriber` в `app/modules/**` обёрнут `@idempotent_consumer`); интеграционный тест `tests/core/kafka/test_inbox.py` (повторная доставка того же `event_id` не меняет данные и не публикует повторных событий); тест на N инстансах `tests/n_instances/test_job_runs_once.py` (команда задания при двух воркерах и принудительном повторе доставки выполняется один раз — SYS-05).
- **Применимость**: backend, tests.

### SYS-04-R27 Ретраи и dead letter topic

- **Формулировка**: при исключении обработчика shared kernel должен повторить обработку в процессе с задержками 1 с, 5 с, 25 с (всего до 4 попыток, включая первую), откатив транзакцию каждой попытки; исключения, наследующие `NonRetryableError` shared kernel, и `pydantic.ValidationError` отправляются в DLQ без ретраев; после исчерпания попыток исходное сообщение публикуется в `<topic>.dlq` с исходными заголовками и дополнительными `error` (строка исключения, до 1 КиБ, без секретов), `error_type` (имя класса), `attempts`, `consumer`, `original_topic`, `original_partition`, `original_offset`, `failed_at`, после чего исходное сообщение подтверждается (партиция не блокируется); каждая запись в DLQ увеличивает `flt_kafka_dlq_messages_total{topic, consumer}` и пишет лог уровня `error` с `event_id`; callback-топики boilerplate (`KAFKA_ERROR_TOPIC_BY_SOURCE`) удаляются.
- **Обоснование**: ADR-004, раздел 3.4 (1/5/25 с, 3 повтора, DLQ с заголовками, ошибки валидации — сразу в DLQ, метрика и алерт — ADR-010); блокировка партиции не дольше 31 с (ADR-004, раздел 4.2).
- **Проверка**: тесты `tests/core/kafka/test_retry_and_dlq.py` с `TestKafkaBroker` и `Clock` (расписание задержек, заголовки DLQ, `NonRetryableError`, `ValidationError`, ack исходного); алерт `FltKafkaDlqGrowing` — ADR-010, проверка файла алертов SYS-11.
- **Применимость**: backend, tests.

### SYS-04-R28 Разбор DLQ и повторная обработка

- **Формулировка**: роль `worker` должна предоставлять команду `python -m app dlq replay --topic <topic> [--event-id <uuid>]... [--consumer <name>] [--dry-run]`, которая читает `<topic>.dlq` с начала, публикует выбранные сообщения обратно в `<topic>` с исходными заголовками и дополнительными `replayed_from=<topic>.dlq`, `replay_count` (+1), `replayed_at`, и команду `python -m app dlq list --topic <topic> [--since <ISO>]` для просмотра (`event_id`, `event_type`, `consumer`, `error_type`, `failed_at`); повтор выполняется администратором вручную; при `replay_count > 3` команда отказывает без флага `--force`; записи inbox не мешают повтору, так как в DLQ попадают только сообщения, чья транзакция откатилась.
- **Обоснование**: ADR-004 (`python -m app dlq replay`, разбор вручную); глоссарий «Dead letter topic» (разбирается вручную).
- **Проверка**: тест `tests/cli/test_dlq_commands.py` на `TestKafkaBroker`; runbook в SYS-11.
- **Применимость**: backend, tests.

### SYS-04-R29 Фоновые задания

- **Формулировка**: фоновое задание должно создаваться ролью `api` записью в таблице `<module>.jobs` (`id`, `kind`, `status` ∈ `queued|running|succeeded|failed|cancelled`, `progress jsonb`, `payload jsonb`, `result jsonb`, `error jsonb`, `run_after timestamptz`, `attempts`, `owner_user_id`, `created_at`, `updated_at`, `version`) и командой в outbox с `aggregate_id = job.id` в топик `flt.<module>.jobs.<job>.v<N>` с телом `JobCommand {job_id, kind, payload, attempt}`; воркер переводит `status` в `running` (оптимистично по `version`), выполняет работу шагами, публикует прогресс (SYS-04-R16), проверяет флаг отмены (`status = cancelled` в PostgreSQL и ключ `<module>:job_cancel:<id>` в Redis, TTL 1 ч) между шагами и не реже раза в 5 с, по завершении записывает `result` или `error` и публикует доменное событие; одно сообщение обрабатывается не дольше `max.poll.interval.ms = 600000` — задания длиннее 5 минут разбиваются на шаги, каждый шаг — отдельная команда; отложенные задания (`run_after` в будущем) ставит в outbox периодическая задача модуля.
- **Обоснование**: ADR-004, разделы 2.4 A и 3.1; ADR-009, раздел 3.2 (отмена через флаг и ключ Redis); SYS-03-R27 (REST-ресурс задания).
- **Проверка**: базовые классы `JobRunner` и миграция таблицы `jobs` из декларации shared kernel; тесты `tests/core/kafka/test_jobs.py` (жизненный цикл, отмена, разбиение на шаги); E2E Г.11 (тестовое задание shared kernel `core.jobs.echo`).
- **Применимость**: backend, tests.

### SYS-04-R30 Версионирование схем событий

- **Формулировка**: совместимое изменение схемы события (добавление необязательного поля в `payload`, добавление нового типа события в тот же топик) должно увеличивать `event_version` на 1 и сопровождаться записью в `asyncapi.yaml`; несовместимое изменение (удаление или переименование поля, изменение типа, перевод поля в обязательное, изменение семантики) должно публиковаться в новый топик `.v<N+1>` с периодом двойной публикации в оба топика не менее одного этапа, пока все консьюмеры старого топика не переведены (список консьюмеров — по декларациям), после чего старый топик помечается `deprecated` в контракте и удаляется ролью `migrate` в следующем этапе; консьюмеры обязаны игнорировать неизвестные поля (`model_config = ConfigDict(extra="ignore")`) и обрабатывать все `event_version` своего топика.
- **Обоснование**: CLAUDE.md «Взаимодействие» (схемы версионируются, изменения обратно совместимы); ADR-004, раздел 2.2 A (минорные изменения — `event_version`, несовместимые — новый топик, старые консьюмеры дочитывают старый).
- **Проверка**: CI job `contracts`: `flt-tools contracts check` сравнивает схемы сообщений `asyncapi.yaml` в PR с `main` и падает при несовместимом изменении без нового топика или при совместимом без увеличения `event_version` (сравнение JSON Schema по правилам `oasdiff`-подобного алгоритма для AsyncAPI — реализуется в `flt_tools`); архитектурный тест `test_event_models_ignore_extra` (`extra="ignore"` у всех подклассов `BaseEvent` и моделей `payload`).
- **Применимость**: backend, CI.

### SYS-04-R31 Consumer group и клиент

- **Формулировка**: каждый обработчик должен подписываться с `group_id = "flt.<module>.<handler>"` (`flt.dictionary.index_entries`), где `<handler>` — имя функции-обработчика в snake_case; единый `KAFKA_GROUP_ID` boilerplate не используется; `client.id = flt-<role>-<instance_id>`; у роли `api` соединения с Kafka нет (публикация — только через outbox); при роли `all` консьюмеры работают в том же процессе (стенд local и pytest).
- **Обоснование**: ADR-004, разделы 3.4 и 3.5 (`group_id` по группе на обработчик, `KAFKA_CLIENT_ID` по роли; `api` без Kafka); отдельная группа на обработчик позволяет повторять и масштабировать обработчики независимо.
- **Проверка**: архитектурный тест `test_consumer_group_naming` (обход подписчиков всех `kafka_router` модулей: `group_id` соответствует `^flt\.<module>\.[a-z][a-z0-9_]*$` и уникален); тест фабрики приложения `tests/core/test_app_roles.py` (роль `api` не создаёт `KafkaBroker`).
- **Применимость**: backend, tests.

### SYS-04-R32 Планировщик периодических задач

- **Формулировка**: периодическая задача модуля должна объявляться в `app/modules/<module>/schedules.py` объектом `ScheduleDeclaration(name, cron, handler, lock_ttl)` и выполняться планировщиком роли `worker`: каждые 10 с проверяется расписание; задача запускается только после захвата блокировки `shared_kernel:lock:schedule:<module>.<name>` с TTL = интервалу задачи (не более 24 ч); отсутствие блокировки — пропуск без ошибки; журнал запусков — таблица `<module>.scheduled_runs` (`id`, `task`, `started_at`, `finished_at`, `status`, `error`); задача обязана быть идемпотентной и укладываться в `lock_ttl`, иначе — разбиение на задания (SYS-04-R29).
- **Обоснование**: ADR-004, раздел 3.4 (планировщик под блокировкой, `schedules.py`, `scheduled_runs` в схеме модуля); CLAUDE.md «Масштабирование и состояние» (периодические задачи не выполняются на всех инстансах сразу).
- **Проверка**: тест `tests/core/kafka/test_scheduler.py`; тест на N инстансах `tests/n_instances/core/test_schedule_runs_once.py` (задача с интервалом 1 мин при двух воркерах выполняется один раз — SYS-05).
- **Применимость**: backend, tests.

### 3.3. Контракты и тесты

### SYS-04-R33 Контракт AsyncAPI модуля и общие схемы

- **Формулировка**: контракт асинхронного взаимодействия модуля должен лежать в `Analytics/Specs/<module>/api/asyncapi.yaml` (AsyncAPI 3.0.0, один документ на модуль) со структурой: `servers` — `ws` (`host: /`, `protocol: wss`, `pathname: /ws`) и `kafka` (`protocol: kafka`), подключаемые ссылкой из `asyncapi-common.yaml`; `channels` — каналы WebSocket модуля (`address: <module>.<channel>:{id}` с `parameters`, `x-flt-transport: websocket`, `x-flt-state-endpoint: <operationId openapi>`) и топики Kafka (`address: flt.<module>.<event>.v1`, `x-flt-transport: kafka`, `x-flt-kind: event | job`, `x-flt-partitions`, `x-flt-retention-days`); `operations` — `send`/`receive` с привязкой к каналу; `components.messages` — сообщения с `payload`, где текстовое сообщение WebSocket описывается как `allOf: [WsEnvelope, {properties: {type: {const: ...}, payload: {$ref: ...}}}]`, а событие Kafka — как `allOf: [EventEnvelope, {properties: {event_type: {const}, payload: {$ref}}}]`; общие схемы (`WsEnvelope`, `EventEnvelope`, `JobCommand`, `JobProgressPayload`, `JobCompletedPayload`, `JobFailedPayload`, сообщения `ws.*`, описание бинарного кадра, серверы) — в `Analytics/Specs/_system/asyncapi-common.yaml`, который создаётся на этапе 1 Г.3 вместе с инфраструктурой контрактов и правится только через изменение SYS-04.
- **Обоснование**: CLAUDE.md «Взаимодействие» (WebSocket и Kafka — AsyncAPI); шаблоны (`_templates/README.md`: `api/asyncapi.yaml` рядом с ТЗ); ADR-005 (zod-схемы сообщений генерируются из `asyncapi.yaml` модуля скриптом `asyncapi-to-zod.ts`); один документ на модуль переезжает с модулем при выделении.
- **Проверка**: CI job `contracts`: Spectral с набором `spectral:asyncapi` и правилами `flt-*` (`flt-ws-message-name`, `flt-ws-channel-address`, `flt-kafka-channel-address`, `flt-asyncapi-version-3`, `flt-envelope-allof` — каждое сообщение построено через `allOf` с конвертом из `asyncapi-common.yaml`, `flt-channel-transport` — у каждого канала задан `x-flt-transport`); `flt-tools contracts check` проверяет наличие контракта у каждого модуля с `ws_handlers` или `kafka_router` и разрешимость `x-flt-state-endpoint`.
- **Применимость**: backend, frontend, CI.

### SYS-04-R34 Контрактные тесты асинхронного взаимодействия

- **Формулировка**: для каждого модуля с `asyncapi.yaml` должен существовать тест `tests/contracts/test_asyncapi_<module>.py`, который: (1) для каждого сообщения WebSocket и события Kafka находит Pydantic-модель в `public/ws_messages.py` или `public/events.py` по `x-flt-model` и сверяет JSON Schema модели (`model_json_schema()`) с `payload` контракта после нормализации (допустимые отличия — как в SYS-03-R23); (2) валидирует все `examples` контракта этими моделями; (3) сверяет перечень топиков и их параметры с `public/topics.py`; (4) сверяет каналы WebSocket с `channels` обработчиков модуля; кроме того, документ AsyncAPI, который генерирует FastStream (`/asyncapi/kafka` роли `worker`), должен содержать все топики деклараций — проверяется тестом `tests/contracts/test_faststream_asyncapi.py`; версия документа FastStream (2.6 или 3.0) к контракту не привязывается — источник истины остаётся `asyncapi.yaml`.
- **Обоснование**: CLAUDE.md «Взаимодействие» (контрактные тесты сверяют реализацию с контрактом); ADR-004 (сверка AsyncAPI FastStream с контрактом); FastStream генерирует только Kafka-часть и не знает о WebSocket, поэтому сверка идёт по Pydantic-моделям.
- **Проверка**: сам контрактный тест (создаётся скаффолдером); архитектурный тест `test_every_async_module_has_contract_test`; CI job `backend-tests`; `pnpm api:check` (zod-схемы из того же контракта — ADR-005).
- **Применимость**: backend, frontend, tests, CI.

### SYS-04-R35 Тесты асинхронного взаимодействия в ТЗ

- **Формулировка**: ТЗ фичи, которая публикует событие, обрабатывает сообщение, запускает задание или использует канал WebSocket, должно включать тесты: unit и интеграционные на `TestKafkaBroker` (публикация через outbox с откатом транзакции, идемпотентность повторной доставки, попадание в DLQ); интеграционные с реальными Kafka и Redis (relay, доставка pub/sub); на N инстансах — задание выполняется один раз при двух воркерах, событие WebSocket, возникшее на другом инстансе или в воркере, доставлено клиенту, остановка воркера или инстанса `api` посреди сценария не ломает сценарий.
- **Обоснование**: CLAUDE.md «Тесты масштабируемости» (задание выполняется один раз при N потребителях, WebSocket-клиент получает события с другого инстанса, остановка инстанса); ADR-004, раздел 4.3 (SYS-10: тесты outbox и inbox).
- **Проверка**: шаблон ТЗ, раздел 6.7 и 13 (раздел 4.2 ниже); CI job `stand-n3` (`pytest -m n_instances`).
- **Применимость**: tests.

### SYS-04-R36 Метрики и логи асинхронного взаимодействия

- **Формулировка**: shared kernel должен отдавать метрики `flt_ws_connections{module}` и `flt_ws_connections_total{result}`, `flt_ws_messages_total{module, direction}`, `flt_ws_dropped_frames_total{reason}`, `flt_ws_publish_failed_total`, `flt_ws_outbox_size` (gauge по соединениям — гистограмма), `flt_outbox_pending{module}`, `flt_outbox_publish_latency_seconds{module}` (от `occurred_at` до публикации), `flt_outbox_relay_active{module}` (0/1 на воркере), `flt_kafka_dlq_messages_total{topic, consumer}`, `flt_kafka_duplicates_total{consumer}`, `flt_kafka_retries_total{consumer, attempt}`, `flt_jobs_total{module, kind, status}`, `flt_schedule_runs_total{module, task, status}` в дополнение к метрикам FastStream (`KafkaPrometheusMiddleware`) и лагу consumer group от экспортёра Kafka; в логах консьюмеров — `request_id`, `event_id`, `event_type`, `consumer`, `attempt`, без `payload`.
- **Обоснование**: ADR-010, раздел 3.1 (метрики WebSocket и Kafka ядра, соглашение имён `flt_<module>_…`, запрет меток неограниченной кардинальности); ADR-004 (метрика DLQ и алерт).
- **Проверка**: тест `tests/core/metrics/test_async_metrics_registered.py` (все перечисленные метрики зарегистрированы и имеют заявленные метки); дашборды `flt-async.json` — SYS-11.
- **Применимость**: backend, deploy, tests.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| все | Каналы WebSocket и команды — через `WsChannelHandler` в `api/ws.py`, регистрируемый в `ModuleDefinition.ws_handlers`; модели `payload` — `public/ws_messages.py`; события — `public/events.py` (подклассы `BaseEvent`); декларации — `public/topics.py` (`TOPICS`), `schedules.py`; публикация только `OutboxPublisher`; консьюмеры — `@idempotent_consumer`, `group_id = flt.<module>.<handler>`; таблицы `outbox`, `processed_events`, при заданиях — `jobs`, при расписаниях — `scheduled_runs` создаются миграцией модуля из деклараций shared kernel; контракт `api/asyncapi.yaml` и тест `tests/contracts/test_asyncapi_<module>.py` |
| shared kernel (`app/core/ws`) | эндпоинты `/ws` и `/ws/agent`, `WsEnvelope`, реестр обработчиков, подписки, лимиты, heartbeat, бинарные кадры, `WsPublisher`, мост Redis pub/sub, коды закрытия, graceful shutdown |
| shared kernel (`app/core/kafka`) | `EventEnvelope`, `BaseEvent`, `TopicDeclaration`, `OutboxPublisher`, relay, `@idempotent_consumer`, ретраи и DLQ, `JobRunner`, `JobCommand`, планировщик, команды `dlq replay`/`dlq list`/`topics apply`, создание топиков в роли `migrate`, метрики |
| identity | события `identity.user_registered`, `identity.user_blocked`, `identity.session_revoked`, `identity.user_deleted` (ADR-006); отзыв сессии → `publish_to_user` с типом `identity.session.revoked` и закрытие `4401` |
| llm_gateway | канал `llm_gateway.stream:<correlation_id>` и команды `llm_gateway.completion.request`/`cancel`, события стрима `start/delta/end/error` (ADR-009, SYS-08); на этапе 1 — первый `WsChannelHandler` и первый контракт `asyncapi.yaml` |
| local_runtime (этап 4) | обработчик `/ws/agent`, белый список типов агента, реестр и каналы `inbox`/`reply`, контракт `Analytics/Specs/local_runtime/api/asyncapi.yaml`, пакет `flt_protocol` |
| frontend (`src/lib/ws`) | клиент: один сокет, конверт, подписки с `state_url`, backoff, обработка кодов закрытия, zod-схемы из `asyncapi.yaml` |
| `src/tools/contracts` | правила Spectral `flt-*` для AsyncAPI, проверка `x-flt-state-endpoint`, сравнение схем событий между `main` и PR |
| deploy | роль `migrate` создаёт топики; `stop_grace_period`/`terminationGracePeriodSeconds` 40 с; параметры брокера по стендам (SYS-11) |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| 3. Критерии приёмки | для каждого канала — «подписка без права → `ws.forbidden`»; для каждого консьюмера — «повторная доставка не меняет результат»; для каждого задания — «отмена между шагами» |
| 4.2. WebSocket | таблица каналов (`<module>.<channel>:<id>`, кто может подписаться, `x-flt-state-endpoint`) и таблица сообщений (тип, направление, модель `public/ws_messages.py`, пример); ссылка на `asyncapi.yaml` |
| 4.3. Kafka | таблица топиков из `public/topics.py` (имя `flt.<module>.<event>.v<N>`, kind, партиции, retention), для каждого события — `event_type`, `event_version`, `aggregate_type`, модель `public/events.py`; потребители топика; для заданий — `kind`, шаги, условие отмены |
| 6. Состояние и масштабируемость | путь исполнения LLM (прямой стрим или задание — ADR-009); что происходит с событиями pub/sub при разрыве (REST-состояние) |
| 6.7. Тесты на N = 3 инстансах | обязательные сценарии SYS-04-R35 |
| 13. План тестов | строки «`tests/contracts/test_asyncapi_<module>.py` обновлён», «`pnpm api:generate` выполнен» |

## 5. Примеры

### Пример 1. Подписка на канал и подтверждение (SYS-04-R3, R6)

Клиент → сервер:

```json
{
  "type": "ws.subscribe",
  "correlation_id": "0199a2a0-1111-7000-8000-000000000001",
  "channel": null,
  "seq": 0,
  "ts": "2026-10-10T12:00:00.000Z",
  "payload": {"channel": "learning_plan.job:0199a1d0-0000-7000-8000-00000000abcd"}
}
```

Сервер → клиент:

```json
{
  "type": "ws.ack",
  "correlation_id": "0199a2a0-1111-7000-8000-000000000001",
  "channel": "learning_plan.job:0199a1d0-0000-7000-8000-00000000abcd",
  "seq": 7,
  "ts": "2026-10-10T12:00:00.012Z",
  "payload": {"op": "subscribe", "channel": "learning_plan.job:0199a1d0-0000-7000-8000-00000000abcd",
              "state_url": "/api/v1/learning-plan/jobs/0199a1d0-0000-7000-8000-00000000abcd"}
}
```

Отказ:

```json
{
  "type": "ws.error",
  "correlation_id": "0199a2a0-1111-7000-8000-000000000001",
  "channel": null,
  "seq": 8,
  "ts": "2026-10-10T12:00:00.013Z",
  "payload": {"code": "ws.forbidden", "message": "Subscription not allowed", "channel": "classroom.lesson:0199a1d0-…"}
}
```

### Пример 2. Дельта стрима LLM (SYS-04-R3, R4; семантика — ADR-009 и SYS-08)

```json
{
  "type": "llm_gateway.completion.delta",
  "correlation_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "channel": "llm_gateway.stream:01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "seq": 42,
  "ts": "2026-10-10T12:00:00.123Z",
  "payload": {"seq": 3, "kind": "text", "text": "Hel"}
}
```

`seq: 42` — счётчик соединения; `payload.seq: 3` — счётчик стрима. Прогресс задания (адресно, без подписки):

```json
{
  "type": "learning_plan.job.progress",
  "correlation_id": "0199a1d0-0000-7000-8000-00000000abcd",
  "channel": null,
  "seq": 43,
  "ts": "2026-10-10T12:00:01.000Z",
  "payload": {"job_id": "0199a1d0-0000-7000-8000-00000000abcd", "stage": "lessons", "percent": 40, "message_key": "learning_plan.job.stage.lessons"}
}
```

### Пример 3. Событие Kafka (SYS-04-R19, R20, R22)

Топик `flt.identity.user_registered.v1`, ключ `01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c56`, заголовки `event_id`, `event_type=identity.user_registered`, `event_version=1`, `producer=identity`, `content_type=application/json`, `request_id=01999d1e-…4c57`, `traceparent=00-…`, `schema=identity.UserRegistered`:

```json
{
  "event_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c55",
  "event_type": "identity.user_registered",
  "event_version": 1,
  "occurred_at": "2026-10-10T12:00:00.000Z",
  "producer": "identity",
  "aggregate_type": "user",
  "aggregate_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c56",
  "correlation_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c57",
  "causation_id": null,
  "actor_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c56",
  "payload": {"user_id": "01999d1e-7c3a-7b2e-9f0a-2b7f1d8e4c56", "ui_language": "ru", "roles": ["learner"]}
}
```

Объявление события и топика в модуле:

```python
# app/modules/identity/public/topics.py
from datetime import timedelta

from app.core.kafka.topics import TopicDeclaration
from app.modules.identity.public.events import UserRegistered

USER_REGISTERED_V1 = TopicDeclaration(
    name="flt.identity.user_registered.v1",
    kind="event",
    visibility="public",
    partitions=6,
    retention=timedelta(days=7),
    message_model=UserRegistered,
    description="Пользователь зарегистрирован (VIS-04).",
)
TOPICS: tuple[TopicDeclaration, ...] = (USER_REGISTERED_V1,)
```

```python
# app/modules/identity/public/events.py
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.kafka.envelope import BaseEvent


class UserRegisteredPayload(BaseModel):
    """Данные события регистрации пользователя."""

    model_config = ConfigDict(extra="ignore")

    user_id: UUID
    ui_language: str
    roles: list[str]


class UserRegistered(BaseEvent[UserRegisteredPayload]):
    """Доменное событие: пользователь зарегистрирован."""

    event_type = "identity.user_registered"
    event_version = 1
    topic = "flt.identity.user_registered.v1"
    aggregate_type = "user"
```

### Пример 4. Outbox и inbox (SYS-04-R24, R26)

DDL таблиц, создаваемых миграцией каждого модуля из декларации shared kernel (ADR-004):

```sql
CREATE TABLE <module>.outbox (
  id             uuid PRIMARY KEY,                  -- UUID v7 = event_id
  topic          text NOT NULL,
  key            text NOT NULL,                     -- aggregate_id или job_id
  event_type     text NOT NULL,
  event_version  integer NOT NULL,
  headers        jsonb NOT NULL DEFAULT '{}'::jsonb,
  body           jsonb NOT NULL,                    -- EventEnvelope или JobCommand целиком
  occurred_at    timestamptz NOT NULL,
  published_at   timestamptz NULL,
  attempts       integer NOT NULL DEFAULT 0,
  last_error     text NULL
);
CREATE INDEX ix_<module>_outbox_unpublished ON <module>.outbox (id) WHERE published_at IS NULL;

CREATE TABLE <module>.processed_events (
  consumer     text NOT NULL,
  event_id     uuid NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, event_id)
);
```

Публикация в сервисе модуля и идемпотентный консьюмер в другом модуле:

```python
# app/modules/identity/services/registration_service.py (фрагмент)
async with self.session.begin():
    user = await self.user_dao.create(session=self.session, **data)
    await self.outbox.publish(
        self.session,
        UserRegistered(aggregate_id=user.id, actor_id=user.id,
                       payload=UserRegisteredPayload(user_id=user.id, ui_language=user.ui_language, roles=["learner"])),
    )
# commit → relay роли worker публикует в Kafka
```

```python
# app/modules/learner_profile/brokers/subscribers.py (фрагмент)
from app.core.kafka.consumer import idempotent_consumer
from app.modules.identity.public.topics import USER_REGISTERED_V1
from app.modules.identity.public.events import UserRegistered

@kafka_router.subscriber(USER_REGISTERED_V1.name, group_id="flt.learner_profile.create_profile")
@idempotent_consumer(consumer="learner_profile.create_profile")
async def create_profile(event: UserRegistered, service: ProfileServiceDep) -> None:
    """Создаёт пустой профиль ученика при регистрации; повторная доставка пропускается по inbox."""
    await service.create_empty_profile(user_id=event.payload.user_id, ui_language=event.payload.ui_language)
```

### Пример 5. Фрагмент `asyncapi.yaml` модуля (SYS-04-R33)

`Analytics/Specs/learning_plan/api/asyncapi.yaml`:

```yaml
asyncapi: 3.0.0
info:
  title: FLT learning_plan async API
  version: 1.0.0
servers:
  ws:
    $ref: "../../_system/asyncapi-common.yaml#/servers/ws"
  kafka:
    $ref: "../../_system/asyncapi-common.yaml#/servers/kafka"
channels:
  jobChannel:
    address: "learning_plan.job:{job_id}"
    x-flt-transport: websocket
    x-flt-state-endpoint: learning_plan_getJob
    parameters:
      job_id: { description: UUID задания }
    messages:
      jobProgress: { $ref: "#/components/messages/jobProgress" }
  planGenerated:
    address: flt.learning_plan.plan_generated.v1
    x-flt-transport: kafka
    x-flt-kind: event
    x-flt-partitions: 6
    x-flt-retention-days: 7
    messages:
      planGenerated: { $ref: "#/components/messages/planGenerated" }
  generatePlanJob:
    address: flt.learning_plan.jobs.generate_plan.v1
    x-flt-transport: kafka
    x-flt-kind: job
    x-flt-partitions: 6
    x-flt-retention-days: 7
    messages:
      jobCommand:
        $ref: "../../_system/asyncapi-common.yaml#/components/messages/jobCommand"
operations:
  sendJobProgress:
    action: send
    channel: { $ref: "#/channels/jobChannel" }
    messages: [{ $ref: "#/channels/jobChannel/messages/jobProgress" }]
  publishPlanGenerated:
    action: send
    channel: { $ref: "#/channels/planGenerated" }
  consumeGeneratePlan:
    action: receive
    channel: { $ref: "#/channels/generatePlanJob" }
    x-flt-consumer-group: flt.learning_plan.generate_plan
components:
  messages:
    jobProgress:
      name: learning_plan.job.progress
      x-flt-model: app.core.kafka.jobs.JobProgressPayload
      payload:
        allOf:
          - $ref: "../../_system/asyncapi-common.yaml#/components/schemas/WsEnvelope"
          - type: object
            properties:
              type: { const: learning_plan.job.progress }
              payload: { $ref: "../../_system/asyncapi-common.yaml#/components/schemas/JobProgressPayload" }
    planGenerated:
      name: learning_plan.plan_generated
      x-flt-model: app.modules.learning_plan.public.events.PlanGenerated
      payload:
        allOf:
          - $ref: "../../_system/asyncapi-common.yaml#/components/schemas/EventEnvelope"
          - type: object
            properties:
              event_type: { const: learning_plan.plan_generated }
              event_version: { const: 1 }
              payload:
                type: object
                required: [plan_id, learner_language_id]
                properties:
                  plan_id: { type: string, format: uuid }
                  learner_language_id: { type: string, format: uuid }
```

### Пример 6. Состав `asyncapi-common.yaml` (SYS-04-R33; создаётся на этапе 1 Г.3)

```yaml
asyncapi: 3.0.0
info: { title: FLT common async schemas, version: 1.0.0 }
servers:
  ws:    { host: "/", pathname: /ws, protocol: wss, description: "WebSocket фронтенда через HAProxy (ADR-012)" }
  kafka: { host: "kafka:9092", protocol: kafka, description: "внутренний брокер; наружу не публикуется" }
channels: {}
operations: {}
components:
  messages:
    wsSubscribe:   { name: ws.subscribe,   payload: { $ref: "#/components/schemas/WsSubscribePayload" } }
    wsUnsubscribe: { name: ws.unsubscribe, payload: { $ref: "#/components/schemas/WsSubscribePayload" } }
    wsAck:         { name: ws.ack,         payload: { $ref: "#/components/schemas/WsAckPayload" } }
    wsError:       { name: ws.error,       payload: { $ref: "#/components/schemas/WsErrorPayload" } }
    wsPing:        { name: ws.ping,        payload: { $ref: "#/components/schemas/WsPingPayload" } }
    wsPong:        { name: ws.pong,        payload: { $ref: "#/components/schemas/WsPongPayload" } }
    jobCommand:    { name: core.job.command, payload: { $ref: "#/components/schemas/JobCommand" } }
  schemas:
    WsEnvelope:
      type: object
      additionalProperties: false
      required: [type, correlation_id, channel, seq, ts, payload]
      properties:
        type: { type: string, pattern: "^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)?$" }
        correlation_id: { type: string, format: uuid }
        channel: { type: [string, "null"], pattern: "^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*(:[A-Za-z0-9_-]{1,64})?$" }
        seq: { type: integer, minimum: 0 }
        ts: { type: string, format: date-time }
        payload: { type: object }
    EventEnvelope:
      type: object
      required: [event_id, event_type, event_version, occurred_at, producer, aggregate_type, aggregate_id, correlation_id, causation_id, actor_id, payload]
      properties:
        event_id: { type: string, format: uuid }
        event_type: { type: string }
        event_version: { type: integer, minimum: 1 }
        occurred_at: { type: string, format: date-time }
        producer: { type: string }
        aggregate_type: { type: string }
        aggregate_id: { type: string, format: uuid }
        correlation_id: { type: string, format: uuid }
        causation_id: { type: [string, "null"], format: uuid }
        actor_id: { type: [string, "null"], format: uuid }
        payload: { type: object }
    JobCommand:
      type: object
      required: [job_id, kind, payload, attempt]
      properties:
        job_id: { type: string, format: uuid }
        kind: { type: string }
        payload: { type: object }
        attempt: { type: integer, minimum: 1 }
    JobProgressPayload:
      type: object
      required: [job_id, stage, percent, message_key]
      properties:
        job_id: { type: string, format: uuid }
        stage: { type: string }
        percent: { type: integer, minimum: 0, maximum: 100 }
        message_key: { type: string }
    JobCompletedPayload: { type: object, required: [job_id, result_ref], properties: { job_id: { type: string, format: uuid }, result_ref: { type: string } } }
    JobFailedPayload: { type: object, required: [job_id, code], properties: { job_id: { type: string, format: uuid }, code: { type: string }, details: { type: object } } }
    WsSubscribePayload: { type: object, required: [channel], properties: { channel: { type: string } } }
    WsAckPayload: { type: object, required: [op, channel, state_url], properties: { op: { enum: [subscribe, unsubscribe] }, channel: { type: string }, state_url: { type: [string, "null"] } } }
    WsErrorPayload: { type: object, required: [code, message], properties: { code: { type: string }, message: { type: string }, channel: { type: [string, "null"] }, retry_after_ms: { type: integer }, details: { type: object } } }
    WsPingPayload: { type: object, required: [server_ts], properties: { server_ts: { type: string, format: date-time } } }
    WsPongPayload: { type: object, required: [server_ts, client_ts], properties: { server_ts: { type: string, format: date-time }, client_ts: { type: string, format: date-time } } }
  x-flt-binary-frame:
    description: "Бинарное сообщение: 1 байт тип (0x01 аудио клиента, 0x02 аудио сервера, 0x03-0x7F резерв фронтенда, 0x80-0xFF резерв агента), 4 байта stream_id big-endian, 4 байта seq big-endian, далее данные; размер ≤ 64 КиБ"
```

### Пример 7. Обработчик канала модуля (SYS-04-R5–R8)

```python
# app/modules/llm_gateway/api/ws.py
from app.core.ws.handlers import WsChannelHandler, WsConnection, WsEnvelope
from app.core.security.schemas import UserSecuritySchema
from app.modules.llm_gateway.public.ws_messages import CompletionRequestPayload, CompletionCancelPayload


class CompletionStreamHandler(WsChannelHandler):
    """Канал стрима ответов LLM и команды запуска и отмены стрима (ADR-009)."""

    module = "llm_gateway"
    channels = ("llm_gateway.stream",)
    command_types = {
        "llm_gateway.completion.request": CompletionRequestPayload,
        "llm_gateway.completion.cancel": CompletionCancelPayload,
    }

    async def can_subscribe(self, principal: UserSecuritySchema, channel: str) -> bool:
        """Подписаться на llm_gateway.stream:<correlation_id> может только соединение, открывшее стрим."""
        correlation_id = channel.split(":", 1)[1]
        return await self.streams.is_owner(correlation_id, principal)

    async def on_command(self, connection: WsConnection, envelope: WsEnvelope) -> None:
        """Запускает или отменяет стрим в задаче, привязанной к соединению."""
        ...
```

## 6. Исключения и как их согласовать

Порядок согласования: вопрос в `Analytics/open-questions.md` → решение человека → строка в таблице ниже → исключение в автоматической проверке (allowlist архитектурного теста, расширение `x-flt-*` в контракте) со ссылкой на эту таблицу.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-04-R4 (первый сегмент `type` — модуль) | `/ws/agent`: пространства `agent`, `engine`, `llm`, `model`, `hardware` принадлежат модулю `local_runtime` | протокол агента задан ADR-008 и общим пакетом `flt_protocol`; переименование под `local_runtime.*` удлинило бы каждое сообщение агента без пользы | бессрочно | ADR-008, пользователь, 2026-10-10 |
| SYS-04-R3 (`channel`) | все сообщения `/ws/agent` — `channel: null` | у агента нет подписок: единственный адресат — платформа (ADR-008, раздел 3.5) | бессрочно | ADR-008, пользователь, 2026-10-10 |
| SYS-04-R24 (публикация только через outbox) | тесты (`tests/**`), команда `dlq replay`, relay shared kernel | `TestKafkaBroker` и повтор из DLQ публикуют напрямую по природе; каталог `tests/` вне `root_packages` import-linter (ADR-002) | бессрочно | ADR-002 и ADR-004, пользователь, 2026-10-10 |
| SYS-04-R13 (токены LLM не через pub/sub) | стрим локальной модели через агента: части `llm.chunk` идут через `local_runtime:reply:<request_id>` | ретрансляция между инстансами без связи инстанс–инстанс (ADR-009, вариант G; ADR-008, раздел 3.7); при потере — `agent_offline` и повтор | бессрочно | ADR-009, пользователь, 2026-10-10 |

## 7. Вне рамок

- Семантика стрима LLM (порядок `start → delta* → end | error`, коды ошибок стрима, коалесценция, учёт токенов, оценка usage при отмене) — ADR-009 и SYS-08.
- Семантика голосовой сессии (`speech.*`, кодеки, VAD, аватар) — ADR-009 и ТЗ STU-28, STU-29; SYS-04 задаёт только бинарный кадр и типы кадров `0x01`/`0x02`.
- Матрица прав на каналы и команды — SYS-06; SYS-04 задаёт только точку проверки `can_subscribe`.
- Протокол агента в деталях (поля `agent.hello`, `engine.*`, `model.*`), сопряжение и токен агента — ADR-008 и ТЗ STU-05; схемы — пакет `flt_protocol`.
- Число брокеров, конфигурация Kafka, Redis Sentinel, значения grace-периодов в compose и Helm, runbook DLQ — SYS-11.
- Методика тестов на N инстансах, фикстуры `TestKafkaBroker`, остановка инстанса в тестах — SYS-10 и SYS-05.
- Генерация zod-схем и моков WebSocket на фронтенде — ADR-005 и спецификация `app_shell`.
- Уведомления как доменная сущность (модуль-владелец `notifications`, SYS-01, OQ-49); SYS-04 задаёт только канал доставки `publish_to_user`.
- Видеосвязь групповых занятий (LiveKit, сигнализация `/livekit/*`) — ADR-015 и ТЗ TCH-08.
- Трассировка OpenTelemetry (`traceparent` передаётся, экспорт выключен) — ADR-010.
- Retry-топики с задержкой (вместо ретраев в процессе) не вводятся; при появлении потребности — изменение SYS-04.

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-002](../../ADR/ADR-002-module-layout.md) | основан на | `ModuleDefinition.ws_handlers`, `kafka_router` модуля, пакеты `app/core/ws` и `app/core/kafka`, контракт import-linter «публикация только через outbox», `public/events.py`; уточняется расположение `topics.py` |
| [ADR-003](../../ADR/ADR-003-state-storage.md) | основан на | таблицы `outbox`, `processed_events`, `jobs` в схеме модуля; блокировки `SET NX PX`; отдельное соединение `PubSub`; поведение без Redis; UUID v7 |
| [ADR-004](../../ADR/ADR-004-communication-patterns.md) | основан на | один `/ws`, конверт, каналы, бинарный кадр, коды закрытия, heartbeat, pub/sub, топики `flt.<module>.<event>.v<N>`, конверт события, outbox, inbox, ретраи и DLQ, задания, планировщик, роли |
| [ADR-005](../../ADR/ADR-005-frontend-stack.md) | ограничивает | общий WebSocket-клиент, zod-схемы из `asyncapi.yaml`, моки `msw ws.link` |
| [ADR-006](../../ADR/ADR-006-authentication-and-authorization.md) | основан на | аутентификация при handshake (cookie + `Origin` или Bearer), код 4401, отзыв сессии через канал пользователя, токен агента только на `/ws/agent` |
| [ADR-008](../../ADR/ADR-008-local-agent.md) | основан на | `/ws/agent`, `agent.hello`/`hello_ack`, пространства типов, белый список, heartbeat 30 с, код 4426, реестр и каналы `inbox`/`reply`, `flt_protocol` |
| [ADR-009](../../ADR/ADR-009-llm-streaming-and-voice.md) | основан на | семантика стрима поверх конверта, `payload.seq`, бинарные аудиокадры, обратное давление (`WS_SEND_TIMEOUT_SECONDS`, `WS_OUTBOX_MAX`), `SHUTDOWN_GRACE_SECONDS`, токены не через pub/sub, прогресс заданий |
| [ADR-010](../../ADR/ADR-010-observability-stack.md) | основан на | `request_id` в заголовках Kafka и контексте логов, метрики `flt_ws_*`, `flt_kafka_dlq_messages_total`, запрет `payload` в логах |
| [ADR-011](../../ADR/ADR-011-ci-cd.md) | основан на | job `contracts` (Spectral `spectral:asyncapi`), `stand-n3` с остановкой `flt-api-2` и `flt-worker-2` |
| [ADR-012](../../ADR/ADR-012-haproxy-entry-point.md) | ограничивает | `timeout tunnel 1h`, ping раз в 30 с, readiness 503 при остановке |
| [ADR-013](../../ADR/ADR-013-secrets-management.md) | ограничивает | Kafka без SASL во внутренней сети; `KAFKA_USERNAME`/`KAFKA_PASSWORD` удалены |
| [ADR-014](../../ADR/ADR-014-search-engines.md) | уточняет | индексы обновляются консьюмерами событий по правилам inbox |
| [ADR-015](../../ADR/ADR-015-media-server.md) | ограничивает | сигнализация LiveKit вне `/ws`; события класса — через каналы `classroom.*` |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-24](../../open-questions.md) | именование топиков Kafka — зафиксировано в SYS-04-R19 (решает OQ-24) | да | planned → SYS-04; закрывается утверждением этой спецификации |
| [OQ-17](../../open-questions.md) | роли запуска монолита (`api`, `worker`, `migrate`) — приняты в ADR-004, используются в SYS-04-R18, R24, R31 | нет | resolved (ADR-004) |
| [OQ-49](../../open-questions.md) | модуль-владелец уведомлений — канал доставки задан (`publish_to_user`), владелец типов `notification.*` — модуль `notifications` (SYS-01) | нет | planned → SYS-01 (черновик: модуль `notifications`) |
| [OQ-74](../../open-questions.md) | кодек голоса (PCM16 или Opus) — влияет на размер кадра, не на заголовок | нет | planned → ТЗ STU-28, STU-34.2 |
| [OQ-70](../../open-questions.md) | расположение правил Spectral — путь в разделе «Проверка» | нет | resolved: `src/tools/contracts/.spectral.yaml` |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
| 0.2 | 2026-10-11 | Claude | Согласование SYS-01…SYS-12: R21 — поле `visibility` (`internal` по умолчанию, `public` — для других модулей и плагинов, согласовано с SYS-09-R12) у `TopicDeclaration`, `topics.py` в `public/` по ADR-002 v1.1, исключение раздела 6 для R21 снято; пути тестов N3 — `tests/n_instances/core/`; уведомления — модуль `notifications`; раздел 9 — статусы OQ-17, OQ-49, OQ-70 | draft |
