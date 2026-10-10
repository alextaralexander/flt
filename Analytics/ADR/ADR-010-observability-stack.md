# ADR-010 — Наблюдаемость: метрики, логи, трейсы, health-эндпоинты

| Поле | Значение |
|---|---|
| Статус | proposed |
| Версия | 0.2 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | все |
| Модуль | все; код — shared kernel (`app/core`) |
| Зависимости | нет |
| Связанные ADR/SYS | ADR-003 (readiness не зависит от Redis, `flt_redis_up`), ADR-004 (роли монолита, порты 8000/8001, заголовок `request_id` в Kafka), ADR-006 (метрика пропущенной проверки отзыва), ADR-011 (CI), ADR-012 (HAProxy), ADR-013 (секреты), ADR-014 (общий кластер OpenSearch, настройки `OPENSEARCH_*`), SYS-02, SYS-04, SYS-05, SYS-10, SYS-11, SYS-12; OQ-60 (канал алертов) |

## 1. Контекст

- **Проблема**: монолит работает в N инстансах за HAProxy, и ни один инстанс не хранит состояние. Без единого сбора метрик со всех инстансов, централизованных логов с ID запроса и ID инстанса и без корректных health-эндпоинтов невозможно ни отладить сценарий, шаги которого попали на разные инстансы, ни выполнить критерий выхода этапа 1 («метрики всех инстансов видны в Prometheus, логи запросов — в OpenSearch и видны в Grafana», SDD_plan.md, этап 1 Г.11). Boilerplate даёт заготовки (`PrometheusMiddleware`, structlog, OpenTelemetry, `/v1/health`, `/v1/ready`), но они рассчитаны на один микросервис в чужой инфраструктуре: логи отправляются в OpenSearch из процесса, readiness всегда отвечает `ready`, трейсы экспортируются в несуществующий коллектор, нет ID запроса и ID инстанса.
- **Почему сейчас**: этап 1, пункты Г.8 (развёртывание с Prometheus, Grafana, OpenSearch, Fluent Bit), Г.9 (наблюдаемость) и Г.11 (E2E «ходячего скелета»). Решение нужно до спецификации shared kernel (этап 1 В) и SYS-11.
- **Ограничения**:
  - CLAUDE.md, «Наблюдаемость»: метрики Prometheus на `/metrics`, health-эндпоинты, JSON-логи в stdout с полями время, уровень, модуль, ID инстанса, ID запроса; логи собирает Fluent Bit в OpenSearch, просмотр в Grafana; дашборды и алерты — как код; секреты и персональные данные в логи не пишутся;
  - CLAUDE.md, «Отличия проекта от boilerplate», п. 3 (встроенная отправка логов в OpenSearch выключена) и п. 5 (экспорт трейсов: коллектор или отключение — OQ-20);
  - OQ-21 (решён): пути `/v1/health` и `/v1/ready` из boilerplate сохраняются;
  - OQ-07 (решён): prod — docker-compose на VPS в РФ, Helm проверяется в kind в CI — стек наблюдаемости должен умещаться на одном VPS и работать в обоих вариантах развёртывания в паритете (CLAUDE.md, «Развёртывание»);
  - OQ-11 (решён): dev-only сервисы включаются профилем compose и `values-dev.yaml`;
  - CLAUDE.md, «Масштабирование и состояние»: периодические задачи не дублируются на инстансах; состояние — только PostgreSQL, Redis, MinIO;
  - boilerplate: `prometheus-client`, `structlog`, `opentelemetry-sdk` с инструментацией FastAPI, aiokafka, asyncpg, redis, SQLAlchemy уже в `pyproject.toml`; `PrometheusMiddleware` и `/v1/metrics` (роутер `metrics_router` подключён под префиксом `/v1`), `logging_middleware` с access-логом, `opensearch_sink.py`, `telemetry.py`, `KafkaOpenTelemetryMiddleware`.
- **Если не решить**: каждый модуль начнёт логировать и измерять по-своему, логи останутся в stdout контейнеров без корреляции между инстансами, HAProxy будет слать трафик на инстанс без соединения с PostgreSQL, тесты на N инстансах нельзя будет диагностировать.
- **Ссылки**: CLAUDE.md «Наблюдаемость», «Состав контейнеров», «Отличия проекта от boilerplate»; SDD_plan.md этап 1 А.10, Г.8, Г.9, Г.11; OQ-20, OQ-21, OQ-29; ADR-012, ADR-013, ADR-014.

## 2. Рассматриваемые варианты

Решение состоит из пяти частей: сбор метрик, доставка логов, трейсы, health-эндпоинты, дашборды и алерты. Варианты сравниваются по частям, где выбор нетривиален: обнаружение инстансов для Prometheus, доставка логов и трейсы. Для остальных частей вариант один, он описан в разделе 3.

### Вариант A. Prometheus через DNS-обнаружение реплик, Fluent Bit через log driver `fluentd`, трейсы отключены на этапе 1

- **Описание**:
  - Prometheus в docker-compose находит инстансы монолита через `dns_sd_configs` по имени сервиса compose (встроенный DNS Docker `127.0.0.11` возвращает A-записи всех контейнеров сервиса при `deploy.replicas: 3` или `--scale`); в Kubernetes — `kubernetes_sd_configs` (role `pod`) по аннотациям `prometheus.io/scrape`, `prometheus.io/path`, `prometheus.io/port`.
  - Контейнеры compose пишут логи через logging driver `fluentd` (`fluentd-async: "true"`, `tag: "{{.Name}}"`) в Fluent Bit (input `forward` на `24224`), в Kubernetes Fluent Bit — DaemonSet с input `tail` по `/var/log/containers/*.log` и фильтром `kubernetes`. Output в обоих случаях один — OpenSearch, индекс `flt-logs-YYYY.MM.DD`.
  - Экспорт трейсов OpenTelemetry выключен (`OTLP_EXPORTER_ENDPOINT` пустой), инструментирование в коде сохраняется; корреляция — по `request_id`.
- **Плюсы**:
  - новые инстансы попадают в Prometheus без правки конфигурации — и при `--scale`, и при HPA;
  - log driver `fluentd` передаёт имя контейнера и его ID в теге без доступа Fluent Bit к Docker-сокету и к `/var/lib/docker/containers`; `docker logs` продолжает работать (dual logging в Docker Engine 20.10 и новее);
  - в стеке нет ни одного нового контейнера сверх «Состава контейнеров» CLAUDE.md;
  - один `prometheus.yml` с общими правилами и алертами, отличается только блок обнаружения.
- **Минусы**:
  - `dns_sd_configs` даёт только IP инстанса — метка `instance` в Prometheus не читаема; ID инстанса приходится брать из самого монолита (info-метрика);
  - при недоступности Fluent Bit контейнеры с `fluentd-async` буферизуют логи в памяти (лимит `fluentd-buffer-limit`, по умолчанию 1 МБ) и теряют излишек;
  - без трейсов нет дерева вызовов внутри запроса: цепочки REST → Kafka → LLM видны только по совпадению `request_id` в логах.
- **Масштабирование на N инстансах**: каждый инстанс отдаёт свои метрики, Prometheus хранит их по инстансам; счётчики не агрегируются в процессе (нет общего состояния); остановка инстанса — его серия помечается `up == 0` и исчезает из обнаружения; Redis не участвует.
- **Выделение модулей в микросервисы**: нейтрально — новый сервис получает тот же `PrometheusMiddleware`, те же процессоры логов и тот же log driver; меняется только имя сервиса в обнаружении.
- **Трудоёмкость и риски**: низкая; риск — поведение DNS compose при `--scale` проверяется smoke-тестом в Г.8.

### Вариант B. Статический список инстансов `api-1..api-3`, Fluent Bit через `tail` файлов json-file, OpenTelemetry Collector и Tempo сразу

- **Описание**: в compose три явных сервиса `api-1`, `api-2`, `api-3` с одинаковой конфигурацией; Prometheus — `static_configs` с тремя адресами; Fluent Bit монтирует `/var/lib/docker/containers` и читает `*-json.log` парсером `docker`; дополнительно контейнеры `otel-collector` и `tempo`, монолит экспортирует трейсы по OTLP, Grafana получает источник данных Tempo.
- **Плюсы**:
  - имена инстансов (`api-1`) видны в метке `instance` без info-метрики;
  - сквозные трейсы REST → Kafka → PostgreSQL с первого дня.
- **Минусы**:
  - масштабирование — правка compose в трёх местах (сервисы, Prometheus, HAProxy) вместо `--scale`; в Kubernetes статический список не работает вовсе, конфигурации расходятся;
  - `tail` файлов Docker даёт только ID контейнера в пути файла, имя сервиса нужно восстанавливать отдельным фильтром или доступом к Docker-сокету;
  - два дополнительных контейнера в обоих вариантах развёртывания и ещё одно хранилище (Tempo) на VPS; ценность трейсов на этапах 1–3 (CRUD, вход, статические страницы) низкая;
  - OpenTelemetry-инструментация в boilerplate неполная: `FastAPIInstrumentor` упомянут в docstring `processors.py`, но нигде не вызывается — для REST нет span-ов, трейсы без доработки будут неполными.
- **Масштабирование на N инстансах**: работает при фиксированном N; при N > 3 требует правки конфигураций; состояние не затрагивается.
- **Выделение модулей в микросервисы**: статический список растёт на каждый сервис; Tempo помогает при появлении сетевых вызовов между сервисами — но это не раньше выделения первого модуля.
- **Трудоёмкость и риски**: средняя; риск — расхождение compose и Helm, лишняя нагрузка на VPS.

### Вариант C. Ничего не менять: boilerplate как есть

- **Описание**: оставить отправку логов из процесса в OpenSearch (`OPEN_SEARCH_LOGS_ENABLED`), readiness без проверок зависимостей, экспорт трейсов на `http://127.0.0.1:4317`, без Prometheus и Grafana в compose.
- **Плюсы**: нулевая трудоёмкость.
- **Минусы**: противоречит CLAUDE.md («Отличия проекта от boilerplate», п. 3 и п. 5; «Наблюдаемость»); логи HAProxy, Nginx, PostgreSQL, Kafka не собираются вовсе; процесс монолита держит буфер логов и фоновый поток отправки (`opensearch_sink.py`) — при остановке инстанса последние записи теряются; HAProxy не может исключить инстанс без соединения с PostgreSQL.
- **Масштабирование на N инстансах**: не обеспечивает ни одного пункта проверки из «Тестов масштабируемости» CLAUDE.md.
- **Выделение модулей в микросервисы**: нейтрально.
- **Трудоёмкость и риски**: нулевая трудоёмкость, неприемлемый результат.

## 3. Решение

- **Выбран**: Вариант A.
- **Решение**: метрики Prometheus отдаёт каждый инстанс монолита на `/v1/metrics`, Prometheus находит инстансы динамически (DNS в compose, Kubernetes SD в Helm) и получает ID инстанса из info-метрики `flt_instance_info`; логи всех контейнеров — JSON в stdout, собирает Fluent Bit (log driver `fluentd` в compose, DaemonSet в Kubernetes) в индексы `flt-logs-YYYY.MM.DD` единого кластера OpenSearch с хранением 14 дней; экспорт трейсов на этапах 1–3 выключен при сохранении инструментации, корреляция — `request_id` от HAProxy; `/v1/health` — liveness без внешних зависимостей (с информационными деталями о Redis и поисковых движках), `/v1/ready` — readiness по роли (ADR-004: `api` — PostgreSQL; `worker` — PostgreSQL и Kafka; Redis в readiness не входит — ADR-003, правило 8) с ответом 503 при отказе; канал алертов — Telegram-бот (подтверждено пользователем 2026-10-10, OQ-60); дашборды и алерты Grafana — файлы в `deploy/config/grafana/`, одинаковые в compose и Helm.
- **Обоснование**: вариант A единственный одновременно работает при `--scale` в compose и при HPA в Kubernetes с одним набором файлов в `deploy/config/` (OQ-29), не добавляет контейнеров сверх утверждённого состава и умещается на VPS (OQ-07). Недостаток «нечитаемая метка `instance`» закрывается info-метрикой, недостаток «нет трейсов» принимается до появления многошаговых цепочек LLM (условие возврата — ниже).
- **Отвергнуты**:
  - Вариант B — статический список расходится с Kubernetes и ломает `--scale`; трейсы на этапах 1–3 не окупают два контейнера на VPS и доработку инструментации.
  - Вариант C — нарушает CLAUDE.md и не даёт проверить ни один тест масштабируемости.
- **Границы решения**: ADR не задаёт бизнес-метрики конкретных модулей (их задают ТЗ фич по соглашению об именовании ниже), не выбирает медиасервер и его метрики (ADR-015), не описывает полнотекстовый поиск в OpenSearch (ADR-014), не задаёт конфигурацию HAProxy (ADR-012) и способ подачи паролей OpenSearch и токена Telegram (ADR-013).

### 3.1. Метрики

1. **Эндпоинт**: `GET /v1/metrics` на каждом инстансе, формат exposition `prometheus_client`, без аутентификации; снаружи закрыт в HAProxy (ADR-012). Путь остаётся таким, как в boilerplate (роутер `metrics_router` под `/v1`), по той же логике, что и OQ-21 для health-эндпоинтов; CLAUDE.md, «Наблюдаемость» и «Служебные эндпоинты», где написано `/metrics`, исправляется на `/v1/metrics`.
2. **Технические метрики ядра** (shared kernel, имена без префикса — совпадают с распространёнными дашбордами):
   - `http_requests_total{method, endpoint, status_code}` и `http_request_duration_seconds{method, endpoint}` — из `PrometheusMiddleware` boilerplate (метка `endpoint` — шаблон маршрута, не сырой путь);
   - `flt_ws_connections{module}` (gauge) — открытые WebSocket-соединения инстанса, `flt_ws_messages_total{module, direction}` — инфраструктура WebSocket shared kernel (этап 1 Г.4);
   - Kafka: `KafkaPrometheusMiddleware` FastStream (`received_messages_total`, `received_processed_messages_duration_seconds`, `published_messages_total` с метками брокера и топика) подключается в `kafka_router` рядом с `KafkaOpenTelemetryMiddleware`; лаг consumer group инстанс не знает — его отдаёт экспортёр Kafka (п. 5);
   - пулы: `flt_db_pool_connections{state="checked_out|idle|overflow"}` из `engine.pool.status()`, `flt_redis_pool_connections{state}` — gauge-коллбэки shared kernel;
   - `flt_instance_info{instance_id, role, version, stand} 1` — info-метрика; `instance_id` = `HOSTNAME` контейнера (ID контейнера в compose, имя пода в Kubernetes), `role` — из ADR-004 (`api`, `worker`, `all`, `media_agent`; роль `migrate` метрик не отдаёт), `version` — `APP_VERSION`; `flt_redis_up` (gauge 0/1, ADR-003) и `flt_auth_revocation_check_skipped_total` (ADR-006) — метрики shared kernel, по которым строятся алерты на деградацию без Redis. Дашборды связывают серии инстанса с его ID выражением `... * on(instance) group_left(instance_id) flt_instance_info`; в Kubernetes дополнительно relabel `__meta_kubernetes_pod_name → instance`.
3. **Бизнес-метрики модулей**: имя `flt_<module>_<metric>[_<unit>][_total]` по соглашениям Prometheus (`_total` у счётчиков, единицы `_seconds`, `_bytes`), например `flt_llm_gateway_requests_total{provider, model, outcome}`, `flt_llm_gateway_tokens_total{provider, model, kind="prompt|completion"}`, `flt_assessment_quick_tests_started_total`. Запрещены метки с неограниченным множеством значений: `user_id`, `session_id`, сырой путь, текст сообщения. Метрика объявляется в пакете своего модуля, общий реестр `prometheus_client` по умолчанию; ТЗ фичи перечисляет её метрики в разделе о нефункциональных требованиях (Definition of Done: «добавлены метрики и логи»).
4. **Обнаружение инстансов**:
   - compose (`deploy/config/prometheus/scrape/compose.yml`):

     ```yaml
     scrape_configs:
       - job_name: flt-api
         metrics_path: /v1/metrics
         dns_sd_configs:
           - names: ["api"]          # имя сервиса compose (ADR-004: api и worker)
             type: A
             port: 8000
             refresh_interval: 15s
       - job_name: flt-worker
         metrics_path: /v1/metrics
         dns_sd_configs:
           - names: ["worker"]
             type: A
             port: 8001            # служебный HTTP роли worker (ADR-004)
             refresh_interval: 15s
     ```

     Встроенный DNS Docker возвращает все IP контейнеров сервиса (`deploy.replicas` или `--scale api=3`); `tasks.<service>` не используется — он есть только в swarm. Роль `media_agent` (этап 6, ADR-015) получает такой же job `flt-media-agent` на порту 8001. Проверка — smoke-тест Г.8: после `docker compose up --scale api=3` в `GET http://prometheus:9090/api/v1/targets` три цели `flt-api` в состоянии `up`;
   - Kubernetes (`deploy/config/prometheus/scrape/kubernetes.yml`): `kubernetes_sd_configs` с `role: pod`, relabel по аннотациям `prometheus.io/scrape: "true"`, `prometheus.io/path: /v1/metrics`, `prometheus.io/port: "8000"` для `flt-api` и `"8001"` для `flt-worker` и `flt-media-agent`, которые Helm ставит на поды монолита; `__meta_kubernetes_pod_name → instance`, `__meta_kubernetes_pod_label_app_kubernetes_io_component → role`. Prometheus Operator и ServiceMonitor не используются: CRD усложняют smoke в kind, а chart `prometheus-community/prometheus` принимает тот же `prometheus.yml`, что и compose (паритет по OQ-29). Итоговое правило выбора chart-ов для инфраструктуры (Prometheus, Grafana, OpenSearch, Fluent Bit, node-exporter) задаёт SYS-11 (OQ-28); здесь публичные chart-ы указаны как рабочее предположение.
5. **Экспортёры** (вспомогательные контейнеры по CLAUDE.md, «Состав контейнеров»; добавляются на этапе 1 Г.9, потому что базовые дашборды и алерты (п. 3.5) требуют их метрик): `prometheuscommunity/postgres-exporter`, `oliver006/redis_exporter`, `danielqsj/kafka-exporter` (лаг consumer group: `kafka_consumergroup_lag{consumergroup, topic}`), встроенный `prometheus-exporter` HAProxy на порту `8404` (ADR-012), `nginx-prometheus-exporter` — не на этапе 1 (трафик статики виден в HAProxy). Экспортёры публикуются только во внутренней сети, пароли — ADR-013.
6. **Интервал** сбора 15 с, хранение Prometheus 30 дней (`--storage.tsdb.retention.time=30d`), volume `prometheus-data`.

### 3.2. Логи

1. **Формат**: одна JSON-строка на запись в stdout (`LOG_JSON_FORMAT=true` на всех стендах, кроме local; на local — консольный рендер). Процессоры structlog boilerplate сохраняются; меняются: `TimeStamper(fmt="iso", utc=True)` вместо `"%Y-%m-%d %H:%M:%S.%f"` (без часового пояса OpenSearch трактует время неоднозначно), ключ `timestamp` переименовывается в `@timestamp` (ожидание Fluent Bit и Grafana по умолчанию), `rename_event_key` (`event → message`) сохраняется.
2. **Обязательные поля** каждой записи монолита:

   | Поле | Источник | Пример |
   |---|---|---|
   | `@timestamp` | `TimeStamper` | `2026-10-10T12:34:56.789012Z` |
   | `level` | `add_log_level` | `info` |
   | `logger` | `add_logger_name` | `flt.identity.services.registration` |
   | `message` | `rename_event_key` | `user registered` |
   | `module` | процессор `add_module`: второй сегмент имени логгера `flt.<module>.*`; логгеры `app`, `api`, `kafka`, `uvicorn`, `sqlalchemy` → `core` | `identity` |
   | `instance_id` | `HOSTNAME` при старте, bind в `merge_contextvars` через `structlog.contextvars.bind_contextvars` в lifespan | `flt-api-7c9d5b8f4-x2k9q` |
   | `role` | `APP_ROLE` (ADR-004) | `api` |
   | `stand` | `STAND_NAME` | `prod` |
   | `request_id` | middleware: заголовок `X-Request-ID` от HAProxy (ADR-012), иначе `uuid4()`; возвращается клиенту в ответе; для Kafka — заголовок сообщения `request_id`, который публикатор копирует из своего контекста (SYS-04) | `0194a6b3-...` |
   | `user_id` | bind после аутентификации (UUID пользователя; email, имя, телефон — запрещены) | `8f1c...` |
   | `trace_id`, `span_id` | `add_open_telemetry_trace_context` — только при активном span-е (Kafka-обработчики через `KafkaOpenTelemetryMiddleware`; REST — после включения `FastAPIInstrumentor`) | `4bf9...` |
   | `http.method`, `http.url`, `http.status_code`, `network.client.ip`, `duration` | access-лог `logging_middleware` (как в boilerplate) | |
   | `exception` | `format_exc_info` при ошибках | многострочный traceback |

   Пример access-записи:

   ```json
   {"@timestamp":"2026-10-10T12:34:56.789012Z","level":"info","logger":"api","module":"core","message":"200 POST \"/api/v1/auth/login\"","instance_id":"a1b2c3d4e5f6","role":"api","stand":"prod","request_id":"0194a6b3-6c2e-7d3a-9f10-2b4c6d8e0f12","user_id":"8f1c4e2a-0d7b-4c3e-9a1f-5e6d7c8b9a01","http":{"method":"POST","url":"/api/v1/auth/login","status_code":200},"network":{"client":{"ip":"203.0.113.7","port":51234}},"duration":0.0421}
   ```

3. **Запрещено логировать**: пароли, JWT и refresh-токены, API-ключи учеников и платформы, заголовки `Authorization` и `Cookie`, тела запросов и ответов REST, содержимое сообщений ученика и ответов LLM (персональные данные по 152-ФЗ), email, имя, телефон, голос. Разрешены: UUID пользователя, IP клиента в access-логе (нужен для лимитов и разбора злоупотреблений; срок хранения — 14 дней, фиксируется в SYS-02), числовые характеристики (длина текста, число токенов, длительность). Техническая защита — процессор `redact_sensitive_keys` в shared kernel: ключи из списка (`password`, `token`, `access_token`, `refresh_token`, `authorization`, `cookie`, `api_key`, `secret`, `email`, `phone`, `prompt`, `completion`, `content`) заменяются на `***` на любой глубине словаря; строковые значения, совпадающие с регулярными выражениями JWT (`eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`) и ключей провайдеров (`sk-[A-Za-z0-9]{20,}`, `AQVN[A-Za-z0-9_-]{30,}`), маскируются. Тест shared kernel проверяет каждый пункт списка (SYS-10).
4. **Логи других контейнеров**: HAProxy — `log stdout format raw local0` с JSON `log-format`, содержащим `request_id` (ADR-012); Nginx — `access_log /dev/stdout json_combined`; PostgreSQL, Redis, Kafka, MinIO, OpenSearch, Grafana, Prometheus — штатный текстовый stdout, Fluent Bit кладёт строку в поле `message` без разбора.
5. **Fluent Bit**: образ `fluent/fluent-bit`, конфигурация в `deploy/config/fluent-bit/` — общие `parsers.conf`, `filters.conf` и `output.conf`, разные `input-compose.conf` и `input-kubernetes.conf` (принцип OQ-29).
   - compose: каждому сервису задаётся

     ```yaml
     x-logging: &flt-logging
       driver: fluentd
       options:
         fluentd-address: "127.0.0.1:24224"   # порт Fluent Bit, опубликованный только на loopback хоста
         fluentd-async: "true"
         fluentd-buffer-limit: "8m"
         tag: "flt.{{.Name}}"
     ```

     Fluent Bit стартует первым (`depends_on` у остальных сервисов), input `forward`, фильтр `parser` с парсером `json` для поля `log` (`Reserve_Data On`, `Preserve_Key Off`) — JSON монолита разворачивается в поля верхнего уровня, не-JSON остаётся в `message`; фильтр `modify` добавляет `container` из тега;
   - Kubernetes: chart `fluent/fluent-bit` как DaemonSet, input `tail` по `/var/log/containers/*.log` с парсером `cri`, фильтр `kubernetes` (`Merge_Log On`, `Keep_Log Off`, `K8S-Logging.Parser On`) — те же поля плюс `kubernetes.pod_name`, `kubernetes.namespace_name`;
   - output для обоих:

     ```ini
     [OUTPUT]
         Name              opensearch
         Match             *
         Host              ${OPENSEARCH_HOST}
         Port              9200
         HTTP_User         ${OPENSEARCH_LOGS_USER}
         HTTP_Passwd       ${OPENSEARCH_LOGS_PASSWORD}
         Logstash_Format   On
         Logstash_Prefix   flt-logs
         Logstash_DateFormat %Y.%m.%d
         Time_Key          @timestamp
         Suppress_Type_Name On
         Replace_Dots      On
         Retry_Limit       False
         storage.total_limit_size 512M
     ```

     Буфер Fluent Bit — файловый (`storage.path /var/log/flt-fluent-bit`, volume) — при недоступности OpenSearch логи не теряются до 512 МБ.
6. **OpenSearch**: один кластер для логов и для поиска (ADR-014): на VPS второй кластер не умещается, а разделение по индексам (`flt-logs-*` — логи, `flt-search-*` — индексы ADR-014) и по пользователям с разными правами достаточно; при переходе на Kubernetes и росте нагрузки логи выносятся в отдельный кластер без изменения кода (меняется только `OPENSEARCH_HOST` у Fluent Bit и Grafana). ADR-014 ссылается на это решение и не создаёт свой кластер. Security plugin включён с первого дня: пользователи `fluent-bit` (запись в `flt-logs-*`, пароль `OPENSEARCH_LOGS_PASSWORD`), `grafana` (чтение `flt-logs-*`, `OPENSEARCH_GRAFANA_PASSWORD`), `flt-backend` (ADR-014: поисковые индексы `flt-<module>-*`; настройки клиента монолита `OPENSEARCH_URL`, `OPENSEARCH_USERNAME=flt-backend`, `OPENSEARCH_PASSWORD`) и `admin` (`OPENSEARCH_ADMIN_PASSWORD`); имена секретов — ADR-013. TLS на HTTP-слое внутри частной сети выключен (`plugins.security.ssl.http.enabled: false`), транспортный TLS — демо-сертификаты только на local/dev, на prod — свои (ADR-013). Index template `flt-logs` с явным mapping обязательных полей (п. 2) и `dynamic: true` для остальных; ISM-политика `flt-logs-retention`: удаление индекса через **14 дней** (значение — параметр `LOGS_RETENTION_DAYS` в `.env` и `values.yaml`; выбрано по объёму диска VPS и сроку хранения IP-адресов; пересматривается в SYS-02). Один узел в compose, в Helm — chart `opensearch-project/opensearch` с 1 репликой в `values-ci.yaml` и 3 в prod-values.
7. **Boilerplate**: `app/core/logging/opensearch_sink.py` и настройки `OPEN_SEARCH_LOGS_ENABLED`, `OPEN_SEARCH_URL`, `OPEN_SEARCH_VERIFY_SSL`, `OPEN_SEARCH_USER_NAME`, `OPEN_SEARCH_PASSWORD`, `open_search_index`, `open_search_service_name` удаляются из монолита на этапе 1 Г.1; зависимость `opensearch-py` остаётся — её использует клиент поиска shared kernel по ADR-014 с новыми настройками `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENSEARCH_VERIFY_SSL` (одинаково в ADR-010, ADR-013 и ADR-014). Строка `OPEN_SEARCH_PASSWORD="Local#V9rT2qMx7!"` из `envs/local/local.env` удаляется вместе со старыми настройками.

### 3.3. Трейсы (OQ-20)

1. На этапах 1–3 экспорт трейсов **выключен**: `OTLP_EXPORTER_ENDPOINT` пустой во всех `envs/<стенд>/*.env`, `setup_telemetry` при пустом endpoint не подключает экспортёр (поведение boilerplate сохраняется). Инструментирование остаётся и расширяется: `FastAPIInstrumentor().instrument_app(app)` добавляется в `create_app()` (сейчас только упомянут в docstring), `KafkaOpenTelemetryMiddleware` сохраняется, чтобы `trace_id` появлялся в логах Kafka-обработчиков и W3C `traceparent` проходил через заголовки Kafka. Так включение экспорта позже не потребует правки кода модулей.
2. **Условие включения**: первый из двух — начало этапа 4 (многошаговые цепочки LLM: программа обучения, урок, словарь) или разбор инцидента, в котором `request_id` не позволил найти причину задержки. Тогда новым ADR добавляются OpenTelemetry Collector и Grafana Tempo (а не Data Prepper в OpenSearch, как предполагалось в OQ-20: Tempo хранит трейсы в MinIO, который уже есть, и даёт переход «лог → трейс» в Grafana по `trace_id` без нового интерфейса). До этого ни `otel-collector`, ни `tempo` в составе контейнеров нет.
3. `SERVICE_NAME = "python_boilerplate"` в `telemetry.py` заменяется на `flt-backend` (CLAUDE.md, «Отличия проекта от boilerplate», п. 8).

### 3.4. Health-эндпоинты

| Эндпоинт | Назначение | Что проверяет | Таймаут | Ответ |
|---|---|---|---|---|
| `GET /v1/health` | liveness: процесс жив и обслуживает HTTP | ничего внешнего не влияет на код ответа; в теле — информационные детали `checks.redis`, `checks.opensearch`, `checks.qdrant` (`ok`/`fail`, ADR-003 и ADR-014) | 1 с на детали | всегда `200 {"status":"healthy","checks":{…}}` |
| `GET /v1/ready` | readiness: инстанс может обрабатывать запросы своей роли (ADR-004) | `api`: PostgreSQL — `SELECT 1` через пул; `worker` и `media_agent`: PostgreSQL и Kafka — `broker.ping(timeout=…)` FastStream (у `media_agent` вместо Kafka — доступность LiveKit); Redis **не проверяется** — иначе отказ Redis снимал бы с балансировки все инстансы сразу (ADR-003, правило 8); проверки параллельно | 2 с на проверку, 3 с на весь ответ | `200 {"status":"ready","checks":{"postgres":"ok","kafka":"ok"}}` или `503` с тем же телом и `"fail"` у отказавших; тело — вне конверта `ErrorResponseV1` (его читают HAProxy и probes, а не клиенты) |

Правила: роль `worker` (ADR-004) отдаёт те же эндпоинты на порту 8001 (без HTTP-трафика HAProxy их опрашивают probes и compose healthcheck); результат readiness кэшируется в памяти процесса на 5 с (допустимый кэш неизменяемых в этом окне данных — защита от шторма проверок, не состояние запросов); `MetricsService` boilerplate, который сейчас всегда отвечает `ready`, переписывается с внедрением проверок через `Depends()`; `/v1/info` и `/v1/system-metrics` boilerplate удаляются (сведения о сборке — в `flt_instance_info`, метрики хоста — у экспортёров). Потребители: HAProxy — `option httpchk GET /v1/ready` каждые 2 с, инстанс исключается после 3 неудач (ADR-012); compose `healthcheck` монолита — `/v1/ready` (`interval: 10s`, `retries: 3`, `start_period: 30s`); Kubernetes — `livenessProbe /v1/health` (`periodSeconds: 10`, `failureThreshold: 3`), `readinessProbe /v1/ready` (`periodSeconds: 5`), `startupProbe /v1/health` (`failureThreshold: 30`, `periodSeconds: 2`). Оба пути исключены из access-лога (как в boilerplate), но считаются в метриках.

### 3.5. Grafana: дашборды и алерты как код

1. **Источники данных** (provisioning `deploy/config/grafana/provisioning/datasources/datasources.yml`, адреса через переменные окружения `PROMETHEUS_URL`, `OPENSEARCH_URL`): `Prometheus` (по умолчанию) и `OpenSearch` (плагин `grafana-opensearch-datasource`, индекс `flt-logs-*`, поле времени `@timestamp`, учётная запись `grafana`). Grafana пишет состояние (пользователи, алерты) в свою SQLite на volume `grafana-data`; в Kubernetes — PostgreSQL платформы, отдельная база `grafana` (при переходе prod на Kubernetes).
2. **Дашборды** — JSON в `deploy/config/grafana/dashboards/`, provisioning с `foldersFromFilesStructure: true`, одинаково в compose (bind mount) и Helm (ConfigMap из `.Files.Glob`): `flt-instances.json` (инстансы: `up`, `flt_instance_info`, CPU и память из cAdvisor или kubelet, перезапуски), `flt-http.json` (RPS, p50/p95/p99 по `endpoint`, доля 5xx, 429), `flt-websocket.json` (`flt_ws_connections` по инстансам и модулям, сообщения), `flt-kafka.json` (сообщения по топикам, длительность обработки, `kafka_consumergroup_lag`), `flt-postgres.json` (соединения, транзакции, размер БД, медленные запросы по `pg_stat_statements`), `flt-redis.json` (память, команды, попадания кэша, `connected_clients`), `flt-haproxy.json` (сессии, коды ответов по backend-ам, статус серверов), `flt-logs.json` (поток логов с фильтрами `module`, `instance_id`, `request_id`, `level`).
3. **Алерты** — Grafana unified alerting, правила в `deploy/config/grafana/provisioning/alerting/rules.yml`:

   | Алерт | Условие | Длительность |
   |---|---|---|
   | `FltInstanceDown` | `up{job=~"flt-api\|flt-worker"} == 0` | 2 мин |
   | `FltHigh5xxRate` | `sum(rate(http_requests_total{status_code=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05` | 5 мин |
   | `FltKafkaConsumerLag` | `max by (consumergroup, topic) (kafka_consumergroup_lag) > 1000` | 10 мин |
   | `FltDiskSpaceLow` | `node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes < 0.15` (node-exporter на VPS; в Kubernetes — kubelet) | 10 мин |
   | `FltReadinessFailing` | `probe` HAProxy: `haproxy_server_check_status{state="DOWN"} == 1` | 3 мин |
   | `FltOpenSearchRed` | `opensearch_cluster_status{color="red"} == 1` (встроенный Prometheus-экспортёр OpenSearch) | 5 мин |

   `node-exporter` добавляется в compose как вспомогательный контейнер (один процесс на VPS), в Helm — через chart `prometheus-node-exporter`.
4. **Канал оповещений**: contact point Telegram — бот, токен `TELEGRAM_ALERT_BOT_TOKEN` и `chat_id` — секреты по ADR-013; provisioning `contact-points.yml` и `policies.yml`; на local и в CI уведомления выключены. Канал подтверждён пользователем 2026-10-10 (OQ-60); создание бота и владение им — человек. Алерты, которые обязательно входят в стартовый набор сверх таблицы выше: `FltRedisDown` (`flt_redis_up == 0` 2 мин) и `FltAuthRevocationSkipped` (`increase(flt_auth_revocation_check_skipped_total[5m]) > 0`) — деградация без Redis по ADR-003 и ADR-006.

## 4. Последствия

### 4.1. Положительные

- Любой запрос прослеживается по `request_id` от строки лога HAProxy до строки лога инстанса и Kafka-обработчика независимо от того, на какой инстанс он попал.
- `--scale api=5` и HPA не требуют правок конфигурации наблюдаемости.
- HAProxy и Kubernetes исключают инстанс, потерявший PostgreSQL (а воркер — ещё и Kafka), вместо отдачи 500; отказ Redis не снимает инстансы с балансировки, а виден по `flt_redis_up` и алерту.
- Дашборды и алерты версионируются с кодом, одинаковы в compose и Helm и восстанавливаются вместе с инсталляцией.
- Монолит не держит сетевых соединений для логов: остановка инстанса не теряет записи (их уже забрал Fluent Bit).

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Нет трейсов до этапа 4: дерево вызовов внутри запроса не видно | `request_id` во всех логах; `duration` в access-логе и метриках по `endpoint`; инструментация сохранена, включение — новым ADR по условию п. 3.3 |
| Log driver `fluentd` теряет логи при недоступности Fluent Bit дольше, чем держит буфер 8 МБ | Fluent Bit стартует первым и имеет файловый буфер 512 МБ до OpenSearch; алерт `FltInstanceDown` распространяется на контейнер `fluent-bit` |
| Единый кластер OpenSearch: всплеск логов влияет на поиск ADR-014 | ISM 14 дней, лимит буфера Fluent Bit, отдельные пользователи; вынос логов в отдельный кластер — сменой `OPENSEARCH_HOST` |
| Семь контейнеров наблюдаемости на VPS (Prometheus, Grafana, OpenSearch, Fluent Bit, три экспортёра, node-exporter) | Лимиты памяти в compose (`OpenSearch` 1 ГБ heap, `Prometheus` 512 МБ); OpenSearch один узел; размер VPS фиксируется в SYS-11 |
| Readiness опрашивают HAProxy, compose и Kubernetes — до 3 запросов в 2 с на инстанс | Кэш результата 5 с, проверки параллельны, таймаут 2 с |
| Удаление `opensearch_sink.py` и `/v1/info`, `/v1/system-metrics` ломает тесты boilerplate | Тесты удаляются вместе с кодом в Г.1; покрытие не падает ниже 75% — проверка `make test-cov` |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Исправить `/metrics` → `/v1/metrics` (OQ-62); добавить правила: info-метрика `flt_instance_info`, именование `flt_<module>_<metric>`, обязательные поля лога, список запрещённого к логированию, readiness по ролям без Redis, трейсы выключены до этапа 4 | CLAUDE.md, разделы «Наблюдаемость», «Backend-сервис (boilerplate)» (строка «Служебные эндпоинты»), «Отличия проекта от boilerplate» п. 3 и п. 5 (отметить «сделано» после Г.1), «Состав контейнеров» (строки Fluent Bit, экспортёры, node-exporter) | Claude | не начато |
| Удалить `opensearch_sink.py`, настройки `OPEN_SEARCH_*`, эндпоинты `/v1/info` и `/v1/system-metrics`; `opensearch-py` оставить для клиента поиска с настройками `OPENSEARCH_*` (ADR-014); переименовать `SERVICE_NAME` в `flt-backend`; `OTLP_EXPORTER_ENDPOINT=` во всех `envs/` | `src/backend/py-monolyth` (`app/core/logging`, `app/core/metrics`, `app/core/telemetry.py`, `configs/settings.py`, `envs/*`, `pyproject.toml`) | Claude, этап 1 Г.1 | не начато |
| Реализовать (тесты, затем код): процессоры `add_module`, `redact_sensitive_keys`, bind `instance_id`/`role`/`stand`, middleware `request_id` (`X-Request-ID`), `FastAPIInstrumentor`, `KafkaPrometheusMiddleware`, gauge пулов, `flt_instance_info`, `flt_redis_up`, `flt_ws_*`, readiness по ролям (PostgreSQL; Kafka для `worker`) с 503, детали Redis в `/v1/health` | shared kernel `app/core` (спецификация `Analytics/Specs/shared_kernel/_module.md`, раздел о наблюдаемости) | Claude, этап 1 Г.4 и Г.9 | не начато |
| Добавить контейнеры `prometheus`, `grafana`, `opensearch`, `fluent-bit`, `postgres-exporter`, `redis-exporter`, `kafka-exporter`, `node-exporter`; `x-logging` для всех сервисов; healthcheck монолита по `/v1/ready`; аннотации `prometheus.io/*` и probes в Helm | `deploy/docker-compose/docker-compose.yml` и `deploy/helm` одновременно | Claude, этап 1 Г.8 | не начато |
| Создать конфигурации: `deploy/config/prometheus/{prometheus.yml,scrape/compose.yml,scrape/kubernetes.yml,rules/}`, `deploy/config/fluent-bit/`, `deploy/config/grafana/{provisioning,dashboards}/`, `deploy/config/opensearch/{index-template,ism-policy,internal_users}` | `deploy/config/` (структура — SYS-11, OQ-29) | Claude, этап 1 Г.8 | не начато |
| Smoke-тест: `docker compose up --scale api=3` → три цели `flt-api` (порт 8000) и две `flt-worker` (порт 8001) в Prometheus `up`; запись с `request_id` из E2E Г.11 находится в OpenSearch через API Grafana | SYS-10 (методика), CI (ADR-011) | Claude, этап 1 Г.8, Г.11 | не начато |
| Требования: `request_id` в заголовках Kafka-сообщений и WebSocket-сообщениях | SYS-04, требования о формате сообщений | Claude, этап 1 Б.4 | не начато |
| Требования: срок хранения логов 14 дней и IP-адресов в них; запрет персональных данных в логах | SYS-02, раздел о персональных данных | Claude, этап 1 Б.2 | не начато |
| Требования: тесты процессора редактирования, тест readiness 503 при недоступном PostgreSQL и 200 при недоступном Redis, тест info-метрики | SYS-10 | Claude, этап 1 Б.10 | не начато |
| Требования: лимиты памяти контейнеров наблюдаемости, volume-ы `prometheus-data`, `grafana-data`, `opensearch-data`, `fluent-bit-buffer`, параметр `LOGS_RETENTION_DAYS`, размер VPS | SYS-11 | Claude, этап 1 Б.11 | не начато |
| Отметить в Г.9: экспортёры и node-exporter входят в этап 1; трейсы — не входят | SDD_plan.md, этап 1 Г.9 | Claude | не начато |
| ADR-014: использовать единый кластер OpenSearch с поисковыми индексами `flt-<module>-<entity>` и пользователем `flt-backend` | `Analytics/ADR/ADR-014-search-engines.md` | Claude | сделано в ADR-014 0.2 |
| Добавить в шаблон ТЗ подсказку: раздел НФТ перечисляет метрики `flt_<module>_*` и события логов фичи | `Analytics/Specs/_templates/feature-spec.md` | Claude | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-003](ADR-003-state-storage.md) | зависит от | Readiness не зависит от Redis; метрика `flt_redis_up` и детали Redis в `/v1/health` |
| [ADR-004](ADR-004-communication-patterns.md) | зависит от | Роли `api`/`worker`/`media_agent` дают метки `role`, имена сервисов и порты 8000/8001 для обнаружения; заголовок `request_id` в Kafka |
| [ADR-006](ADR-006-authentication-and-authorization.md) | дополняет | Метрика `flt_auth_revocation_check_skipped_total` и алерт; маскирование токенов в логах |
| [ADR-011](ADR-011-ci-cd.md) | дополняет | Smoke-тесты наблюдаемости выполняются в CI; kind для проверки Helm |
| [ADR-012](ADR-012-haproxy-entry-point.md) | дополняет | HAProxy генерирует `X-Request-ID`, проверяет `/v1/ready`, не пропускает `/v1/*` снаружи, отдаёт метрики на `8404` |
| [ADR-013](ADR-013-secrets-management.md) | зависит от | Пароли OpenSearch (`fluent-bit`, `grafana`, `flt-backend`, `admin`), экспортёров, пароль администратора Grafana, токен бота Telegram |
| [ADR-014](ADR-014-search-engines.md) | ограничивает | ADR-014 использует тот же кластер OpenSearch, свои индексы и пользователя `flt-backend`; настройки клиента `OPENSEARCH_*` |
| [ADR-015](ADR-015-media-server.md) | дополняет | Метрики LiveKit собираются Prometheus; роль `media_agent` — job на порту 8001 |
| [SYS-02](../Specs/_system/SYS-02-non-functional-requirements.md) | дополняет | Срок хранения логов и IP-адресов, запрет персональных данных в логах |
| [SYS-04](../Specs/_system/SYS-04-async-messaging.md) | дополняет | `request_id` и `traceparent` в заголовках Kafka и сообщениях WebSocket |
| [SYS-05](../Specs/_system/SYS-05-state-and-scaling.md) | дополняет | Кэш readiness в процессе на 5 с — разрешённое исключение; метрики по инстансам |
| [SYS-10](../Specs/_system/SYS-10-test-strategy.md) | дополняет | Тесты редактирования логов, readiness, smoke-тесты обнаружения |
| [SYS-11](../Specs/_system/SYS-11-deployment-and-environments.md) | дополняет | Структура `deploy/config/`, лимиты ресурсов, volume-ы, параметры |
| OQ-20 | закрывает | Экспорт трейсов выключен до этапа 4, затем Collector и Tempo новым ADR |
| OQ-21 | учитывает | Пути `/v1/health`, `/v1/ready` сохранены; `/v1/metrics` — по той же логике |
| OQ-29 | учитывает | Конфигурации Prometheus, Grafana, Fluent Bit в `deploy/config/`, общие для compose и Helm |
| OQ-60 | закрывает | Канал алертов — Telegram-бот (подтверждено пользователем 2026-10-10) |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Решение пользователя 2026-10-10: канал алертов — Telegram (OQ-60). Согласование с ADR-004 (scrape воркера `worker:8001/v1/metrics`, роль `media_agent`), ADR-003 (readiness без Redis, `flt_redis_up`, детали в `/v1/health`), ADR-006 (метрика `flt_auth_revocation_check_skipped_total`), ADR-014 (настройки `OPENSEARCH_*`, `opensearch-py` остаётся, пользователь `flt-backend`); фраза о правиле выбора chart-ов (SYS-11, OQ-28) | proposed |
