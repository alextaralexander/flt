# ADR-013 — Секреты: `.env` в docker-compose, Vault через External Secrets Operator в Kubernetes

| Поле | Значение |
|---|---|
| Статус | accepted |
| Версия | 1.0 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-10 (PR #2) |
| Пункт(ы) BRD | все; прямо — STU-01, STU-03 (ключи учеников), VIS-03 (ключ модели платформы), VIS-04, VIS-05 (OAuth, SMTP, капча) |
| Модуль | все; код — shared kernel (`configs/`), `identity`, `llm_gateway` |
| Зависимости | нет |
| Связанные ADR/SYS | ADR-006 (ключи подписи JWT, `AUTH_CSRF_SECRET`), ADR-007 (ключи хранилища и SSE), ADR-010 (запрет секретов в логах, пароли OpenSearch и Grafana, токен Telegram), ADR-011 (секреты CI и деплоя), ADR-012 (приватный ключ TLS), ADR-014 (`OPENSEARCH_PASSWORD`, `QDRANT_API_KEY`), ADR-015 (ключи LiveKit), SYS-02, SYS-08, SYS-11, SYS-12; OQ-28 |

## 1. Контекст

- **Проблема**: платформа хранит и использует секреты нескольких классов — пароли инфраструктуры, ключи подписи и шифрования, учётные данные внешних сервисов, зашифрованные API-ключи учеников. CLAUDE.md требует: Vault в Kubernetes, `.env` в docker-compose, одинаковый код монолита в обоих вариантах, секреты не в репозитории и не в логах, ключ шифрования API-ключей учеников — в Vault или `.env`. Boilerplate читает секреты сам: `configs/vault_config.py` при старте один раз (`lru_cache`) читает kv v1 из Vault по статическому `VAULT_TOKEN` из переменной окружения, а если Vault не сконфигурирован — берёт значения из env; для Kafka и Redis при отсутствии секретов молча переходит на `KafkaSettingsStub` и `RedisSettingsStub` без учётных данных. Нужно решить, оставлять ли чтение Vault в коде или подавать секреты в под извне, как генерировать и хранить `.env` на VPS, как ротировать ключи, что делать в CI и в kind.
- **Почему сейчас**: этап 1 — Г.1 (доработка boilerplate, `pyproject.toml`, `envs/`), Г.5 (`identity`: ключ подписи JWT), Г.6 (`llm_gateway`: шифрование ключей), Г.8 (compose и Helm), SYS-08 и SYS-11 ссылаются на это решение.
- **Ограничения**:
  - CLAUDE.md, «Технологический стек» и «Развёртывание»: Vault только в Kubernetes, в docker-compose — `.env` (не коммитится), код монолита одинаков; «Ключевые архитектурные требования»: API-ключи учеников шифруются на сервере, ключ шифрования — Vault или `.env`; «Правила для Claude»: не коммитить секреты, в `envs/` и `.env.template` — только несекретные локальные значения;
  - CLAUDE.md, «Отличия проекта от boilerplate», п. 4: как получать секреты в Kubernetes — этот ADR;
  - OQ-07 (решён): prod пока docker-compose на VPS в РФ, Helm — в kind в CI; значит основной рабочий путь — `.env`, а Vault должен быть готов, но не обязателен для запуска;
  - OQ-06 (решён): CI — GitHub Actions; OQ-12 (решён): OAuth-секреты — в `.env` и Vault, имена переменных — в `.env.template`; OQ-10, OQ-11: SmartCaptcha и SMTP — ключи в секретах;
  - CLAUDE.md, «Масштабирование и состояние»: секрет читается каждым инстансом одинаково, инстанс не хранит ничего на диске;
  - boilerplate: `hvac`, `vault_config.py`, `VaultSettings` (`VAULT_TOKEN`, `VAULT_URL`, `VAULT_PATH`, `VAULT_MOUNT_POINT`), `detect-secrets` с `.secrets.baseline`, bandit, pre-commit.
- **Если не решить**: секреты разъедутся между `envs/*.env`, `.env`, Vault и values Helm; статический `VAULT_TOKEN` в окружении пода сведёт Vault к ещё одному env-файлу; ротация ключа шифрования ключей учеников без версии в записи потребует перешифровки «всё или ничего».
- **Ссылки**: CLAUDE.md «Развёртывание», «Ключевые архитектурные требования», «Отличия проекта от boilerplate» п. 4; SDD_plan.md этап 1 А.13, Г.1, Г.5, Г.6, Г.8; OQ-06, OQ-07, OQ-10, OQ-11, OQ-12, OQ-39; ADR-006, ADR-010, ADR-011, ADR-012.

## 2. Рассматриваемые варианты

Общая часть всех вариантов: в docker-compose секреты приходят из файла `.env` на VPS. Варианты различаются способом подачи секретов в Kubernetes и тем, остаётся ли в коде монолита клиент Vault.

### Вариант A. Монолит читает только переменные окружения; в Kubernetes секреты подаёт External Secrets Operator из Vault

- **Описание**: `configs/vault_config.py`, зависимость `hvac` и `default_factory=vault_secret(...)` удаляются; все секреты — обязательные поля `Settings` без значений по умолчанию (fail-fast при старте, если секрет не задан). docker-compose: `env_file: .env` для сервисов. Kubernetes: Vault (chart `hashicorp/vault`) + External Secrets Operator (ESO, chart `external-secrets/external-secrets`): `ClusterSecretStore` с провайдером `vault` (kv v2, аутентификация Kubernetes auth по ServiceAccount), `ExternalSecret` на каждый компонент (`flt-backend`, `flt-postgres`, `flt-opensearch`, `flt-grafana`) создаёт Kubernetes Secret, который Helm подключает через `envFrom.secretRef`. ESO обновляет Secret по `refreshInterval: 1h`; перезапуск подов при изменении — аннотация stakater Reloader. В kind (CI) Vault не ставится: `ClusterSecretStore` с провайдером `fake` ESO отдаёт тестовые значения из `values-ci.yaml`, манифесты `ExternalSecret` — те же.
- **Плюсы**:
  - один код чтения конфигурации в compose и Kubernetes: `Settings` из env; нет ветки «Vault доступен / недоступен» и молчаливых стабов;
  - в поде нет токена Vault: ESO аутентифицируется ServiceAccount-ом, права — политика Vault на путь `flt/<stand>/*`;
  - секреты инфраструктурных chart-ов (PostgreSQL, OpenSearch, Grafana, MinIO) подаются тем же механизмом — им Vault-клиент в коде недоступен в принципе;
  - `fake`-провайдер ESO позволяет проверить Helm-манифесты в kind без Vault;
  - ротация пароля — изменение в Vault, ESO обновляет Secret, Reloader перезапускает поды по очереди.
- **Минусы**:
  - два оператора в кластере (ESO, Reloader) и Vault — три компонента сверх приложения; актуально только при переходе prod на Kubernetes (OQ-07);
  - секреты лежат в Kubernetes Secret (base64 в etcd): требуется шифрование etcd at rest на уровне кластера — фиксируется в SYS-11 при переходе;
  - изменение секрета применяется с задержкой `refreshInterval` и перезапуском пода, а не «на лету».
- **Масштабирование на N инстансах**: все инстансы получают одинаковый Secret; при ротации Reloader перезапускает поды по одному (RollingUpdate), старые и новые инстансы работают одновременно — поэтому ключи с версиями (JWT `kid`, `key_version` шифрования) обязаны принимать и старое, и новое значение в окне обновления. Инстанс ничего не пишет на диск; Redis не участвует.
- **Выделение модулей в микросервисы**: помогает — новый сервис получает свой `ExternalSecret` и свою политику Vault на свой путь; в compose — свой набор переменных в том же `.env`.
- **Трудоёмкость и риски**: низкая на этапе 1 (удаление кода, `.env.template`, скрипт генерации); средняя при переходе на Kubernetes (Vault, ESO, Reloader, политика бэкапа и unseal — новый OQ).

### Вариант B. Оставить чтение Vault в монолите (boilerplate как есть)

- **Описание**: `vault_config.py` остаётся; в Kubernetes под получает `VAULT_URL`, `VAULT_PATH`, `VAULT_MOUNT_POINT` и `VAULT_TOKEN` (из Kubernetes Secret или через Vault Agent Injector, который кладёт токен в файл, откуда entrypoint читает его в env); при недоступности Vault — значения из env.
- **Плюсы**:
  - нулевая доработка кода конфигурации;
  - секреты не материализуются в Kubernetes Secret (при чтении напрямую из Vault).
- **Минусы**:
  - статический `VAULT_TOKEN` в окружении пода — долгоживущий токен, который нужно выпускать, хранить и ротировать отдельно; для его доставки всё равно нужен Kubernetes Secret или Injector, то есть внешний механизм появляется в любом случае;
  - кэш `lru_cache` читает секрет один раз за процесс: ротация требует перезапуска, как и в варианте A, но без оператора, который это делает;
  - две ветки поведения (`Vault` / `env` / стабы `KafkaSettingsStub`, `RedisSettingsStub` без учётных данных) — на prod ошибка конфигурации приводит к подключению без пароля с одним `warning` в логе вместо отказа старта;
  - инфраструктурные контейнеры (PostgreSQL, OpenSearch, MinIO, Grafana) Vault читать не умеют — им нужен отдельный путь подачи, то есть в кластере будет два механизма;
  - `hvac` без типов (`ignore_missing_imports` в `pyproject.toml`) — исключение из mypy strict.
- **Масштабирование на N инстансах**: каждый инстанс читает Vault при старте; при недоступности Vault новые инстансы (HPA, перезапуск) не стартуют или молча падают в стаб — зависимость старта от Vault.
- **Выделение модулей в микросервисы**: нейтрально — каждый новый сервис копирует `vault_config.py`.
- **Трудоёмкость и риски**: нулевая на этапе 1; риск — молчаливые стабы на prod и статический токен.

### Вариант C. Vault Agent Injector с рендером env-файла в под

- **Описание**: sidecar `vault-agent` (аннотации `vault.hashicorp.com/agent-inject`) аутентифицируется Kubernetes auth, рендерит шаблон в файл `/vault/secrets/env`, entrypoint монолита выполняет `source` этого файла перед uvicorn; код читает env.
- **Плюсы**: код — только env (как в A); секреты не попадают в etcd; агент обновляет файл при ротации и может послать сигнал процессу.
- **Минусы**: sidecar в каждом поде монолита (память, время старта); entrypoint с `source` — нестандартный запуск, отличается от compose (там env приходит напрямую); инфраструктурные chart-ы (PostgreSQL, OpenSearch, Grafana) ожидают Kubernetes Secret, а не файл в поде — для них всё равно нужен ESO или ручные Secret; в kind нужен работающий Vault для проверки инъекции.
- **Масштабирование на N инстансах**: как A, плюс sidecar на инстанс.
- **Выделение модулей в микросервисы**: помогает, но каждому сервису — свой sidecar и шаблон.
- **Трудоёмкость и риски**: средняя; два механизма (Injector для приложения, Secret для инфраструктуры).

## 3. Решение

- **Выбран**: Вариант A.
- **Решение**: монолит и все контейнеры получают секреты только через переменные окружения; в docker-compose источник — файл `.env` на VPS (права `600`, вне git, шаблон `deploy/docker-compose/.env.template`, начальные значения генерирует `deploy/scripts/gen-secrets.sh`); в Kubernetes источник — Vault, из которого External Secrets Operator создаёт Kubernetes Secret для каждого компонента, а Helm подключает их через `envFrom`; клиент Vault из boilerplate (`configs/vault_config.py`, `hvac`) удаляется, секреты без значения по умолчанию останавливают старт инстанса; ключи с ротацией (подпись JWT, шифрование ключей учеников) версионируются в данных, остальные секреты ротируются перезапуском.
- **Обоснование**: вариант A единственный даёт один механизм для приложения и инфраструктуры в каждом варианте развёртывания и один код конфигурации; он убирает статический токен Vault и молчаливые стабы boilerplate, а `fake`-провайдер ESO позволяет проверять Helm в kind без Vault (OQ-07). Поскольку prod сейчас docker-compose, стоимость Kubernetes-части откладывается до перехода, не влияя на код.
- **Отвергнуты**:
  - Вариант B — статический `VAULT_TOKEN`, стабы без учётных данных на prod, второй механизм для инфраструктурных контейнеров.
  - Вариант C — sidecar и `source` в entrypoint расходятся с compose; инфраструктуре всё равно нужен Secret.
- **Границы решения**: ADR не выбирает алгоритм и срок жизни JWT (ADR-006), не описывает модель данных ключей учеников целиком (SYS-08, ТЗ STU-01), не задаёт структуру Helm chart (SYS-11), не решает, где хранятся unseal-ключи Vault (новый OQ), не решает шифрование etcd (SYS-11 при переходе на Kubernetes).

### 3.1. Перечень секретов

| Переменная (env) | Что это | Кто использует | Compose (`.env`) | Kubernetes (путь Vault `flt/<stand>/…`) | Ротация |
|---|---|---|---|---|---|
| `PG_PASSWORD` (и `PG_USERNAME`) | пароль PostgreSQL для монолита | монолит, миграции, postgres-exporter | генерируется | `infra/postgres` | смена в PostgreSQL и Vault, перезапуск монолита по очереди |
| `POSTGRES_PASSWORD` | пароль суперпользователя PostgreSQL | контейнер PostgreSQL (init) | генерируется | `infra/postgres` | вручную, редко |
| `REDIS_PASSWORD` | `requirepass` Redis | монолит, redis-exporter | генерируется | `infra/redis` | смена в Redis (`CONFIG SET requirepass`) и Vault, перезапуск монолита |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | корневые учётные данные MinIO | только контейнер MinIO и одноразовый `minio-init` (ADR-007); монолит их не использует | генерируется | `infra/minio` | смена в MinIO и Vault, перезапуск |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | ключи учётной записи хранилища `flt-backend` (ADR-007) | монолит (все роли), роль `migrate` (`storage-init`), egress LiveKit — отдельная учётная запись с правами на `flt-classroom/recordings/*` (ADR-015, этап 6) | генерируется | `infra/minio` | смена в хранилище и Vault, перезапуск монолита |
| `MINIO_KMS_SECRET_KEY` | ключ SSE-S3 шифрования объектов (ADR-007) | контейнер MinIO | генерируется (32 байта base64) | `infra/minio` | процедура ротации SYS-11; утрата = утрата объектов |
| `OPENSEARCH_ADMIN_PASSWORD` (`admin`), `OPENSEARCH_LOGS_PASSWORD` (`fluent-bit`), `OPENSEARCH_GRAFANA_PASSWORD` (`grafana`), `OPENSEARCH_PASSWORD` (`flt-backend`, клиент поиска монолита: `OPENSEARCH_URL`, `OPENSEARCH_USERNAME=flt-backend` — конфигурация, ADR-014) | internal users OpenSearch (ADR-010) | OpenSearch, Fluent Bit, Grafana, монолит | генерируется | `infra/opensearch` | `securityadmin` или API, перезапуск потребителей |
| `QDRANT_API_KEY` | ключ API Qdrant (ADR-014) | Qdrant (`QDRANT__SERVICE__API_KEY`), монолит | генерируется | `infra/qdrant` | смена в Qdrant и Vault, перезапуск монолита |
| `GRAFANA_ADMIN_PASSWORD` | администратор Grafana | Grafana | генерируется | `infra/grafana` | смена в Grafana и Vault |
| Kafka SASL | учётные данные брокера | — | **не используется на старте**: Kafka доступна только во внутренней сети compose / кластера, listener `PLAINTEXT`, порт наружу не публикуется; SASL/SCRAM вводится новым ADR при публикации Kafka за пределы сети (выделение модуля в отдельный сервис). `KafkaSettings` теряет поля `KAFKA_USERNAME`, `KAFKA_PASSWORD` до этого момента | — | — |
| `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID` | приватные ключи подписи access JWT: JSON `{"<kid>": "<PEM приватного ключа Ed25519>"}` и активный `kid` (ADR-006) | `identity` (выпуск); shared kernel выводит из них публичные ключи, если не задана несекретная `JWT_PUBLIC_KEYS` (JSON `{"<kid>": "<PEM публичного ключа>"}` — конфигурация, не секрет; нужна выделенным сервисам) | генерируется (Ed25519-пара, `kid` = `k1`) | `app/identity` | добавить `k2` на всех инстансах (поочерёдный перезапуск), переключить `JWT_ACTIVE_KID`; старые access-токены проверяются по `kid` до истечения; удалить `k1` через срок access-токена (600 с) + leeway после того, как все инстансы перестали им подписывать — refresh-токены не JWT, ждать их срока не нужно (ADR-006) |
| `AUTH_CSRF_SECRET` | ключ HMAC signed double-submit CSRF-токена (ADR-006) | shared kernel `app/core/security` (все инстансы роли `api` — одно значение) | генерируется (32 байта) | `app/identity` | смена инвалидирует CSRF-cookie: клиенты получают новый токен при следующем refresh; раскатка одним шагом с перезапуском |
| `LLM_KEYS_ENCRYPTION_KEYS`, `LLM_KEYS_ENCRYPTION_ACTIVE_VERSION` | ключи AES-256-GCM шифрования API-ключей учеников: `{"v1": "<base64 32 байта>"}`, активная версия | `llm_gateway` | генерируется (`v1`) | `app/llm_gateway` | см. 3.4 |
| `OAUTH_GOOGLE_CLIENT_SECRET`, `OAUTH_YANDEX_CLIENT_SECRET`, `OAUTH_VK_CLIENT_SECRET` (client id — не секрет, в конфигурации) | OAuth-приложения (OQ-12) | `identity` | пользователь вносит вручную | `app/identity` | смена у провайдера и в источнике, перезапуск |
| `SMTP_PASSWORD` (`SMTP_USERNAME`, хост и порт — конфигурация) | транзакционная почта (OQ-11) | shared kernel (SMTP-клиент) | вручную; в профиле `dev` — пусто (Mailpit) | `app/smtp` | смена у провайдера, перезапуск |
| `SMARTCAPTCHA_SERVER_KEY` (client key — не секрет) | Yandex SmartCaptcha (OQ-10) | `assessment`, `identity` | вручную | `app/captcha` | смена у провайдера, перезапуск |
| `PLATFORM_LLM_API_KEY` | ключ модели платформы для быстрого теста (OQ-09) | `llm_gateway` | вручную | `app/llm_gateway` | смена у провайдера, перезапуск |
| `TELEGRAM_ALERT_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID` | оповещения Grafana через Telegram-бота (ADR-010, OQ-60 — подтверждено пользователем 2026-10-10); `chat_id` хранится как секрет, чтобы не раскрывать канал | Grafana | вручную | `infra/grafana` | смена у BotFather, перезапуск Grafana |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | ключ и секрет API LiveKit (ADR-015, этап 6) | `livekit-server`, `livekit-egress`, монолит (`classroom`, роль `media_agent`) | генерируется | `infra/livekit` | смена в `livekit.yaml` (через переменные) и Vault, перезапуск LiveKit и монолита |
| Приватный ключ TLS | сертификат домена (ADR-012) | HAProxy | **не в `.env`**: файл на volume `haproxy-certs`, пишет certbot | Secret `flt-tls` от cert-manager | автоматически (ADR-012) |
| `GHCR_PULL_TOKEN` | чтение образов из GHCR на VPS, если репозиторий приватный (OQ-39) | Docker на VPS (`docker login`) | вручную, `docker login` один раз; в `.env` не хранится | — | смена в GitHub |

Правило для новых секретов: ТЗ фичи добавляет строку в эту таблицу (через новый ADR или `changed`-версию SYS-11, которая наследует таблицу) и переменную в `.env.template`, `values.yaml` (только имя) и `ExternalSecret`.

### 3.2. docker-compose: файл `.env` на VPS

- Расположение: `/opt/flt/.env`, владелец — пользователь деплоя, права `600`; `docker compose --env-file /opt/flt/.env -f deploy/docker-compose/docker-compose.yml up -d`. Один файл служит и для подстановки в `docker-compose.yml`, и как `env_file:` сервисов (монолит, миграции, экспортёры, Fluent Bit, Grafana). Файл в `.gitignore` (`.env`, `*.env.local`), в репозитории — только `deploy/docker-compose/.env.template` с именами переменных, комментариями и пустыми значениями для секретов.
- Генерация: `deploy/scripts/gen-secrets.sh` создаёт `.env` из шаблона, заполняя генерируемые секреты (`openssl rand -base64 32`; для `LLM_KEYS_ENCRYPTION_KEYS` — 32 случайных байта в base64; для `JWT_SIGNING_KEYS` — Ed25519-пара `openssl genpkey -algorithm ed25519` в PEM с `kid` `k1`, ADR-006; для `AUTH_CSRF_SECRET` — 32 байта), оставляя ручные пустыми и печатая список того, что нужно внести. Режим `--ci` генерирует те же значения для стендов CI (ADR-011). Скрипт идемпотентен: существующие значения не перезаписывает.
- Разделение с env-файлами boilerplate: `src/backend/py-monolyth/envs/<стенд>/*.env` содержат только несекретные параметры стенда (хосты, порты, пулы, флаги); из них удаляются `PG_USERNAME`, `PG_PASSWORD`, `JWT_SECRET_KEY`, `OPEN_SEARCH_PASSWORD`. Исключение — стенд `local` и оверлей `envs/.test.env`: там остаются фиксированные тестовые значения (`ms_py_test`, пароль локального PostgreSQL), помеченные `# pragma: allowlist secret` для detect-secrets, потому что они не защищают ничего, кроме локальной машины. Фиксированного ключа JWT в `envs/local` нет: pytest-фикстура shared kernel генерирует одноразовую Ed25519-пару на сессию тестов (ADR-006), а для `make dev` на хосте пару создаёт `gen-secrets.sh` в локальный `.env`. Текущий `src/backend/py-monolyth/.env.template` (`STAND_NAME=local`) остаётся для запуска на хосте.
- Контейнер монолита в compose получает секреты через `env_file`, а не через `environment:` с подстановкой — так значения не попадают в `docker compose config` и `docker inspect` в открытом виде только частично (в `inspect` они видны в любом случае: доступ к Docker-сокету на VPS равен доступу к секретам — фиксируется в SYS-11, доступ по SSH только по ключу).
- Бэкап `.env`: вместе с бэкапом volume-ов (SYS-11), зашифрованный `age` ключом владельца; без `.env` данные PostgreSQL и зашифрованные ключи учеников не восстанавливаются.

### 3.3. Kubernetes: Vault и External Secrets Operator

- Vault — chart `hashicorp/vault` в namespace `vault` (`values-prod`: 1 реплика с файловым бэкендом на PVC на старте; HA с Raft — при росте), kv v2 на mount `flt`, пути `flt/<stand>/infra/<компонент>` и `flt/<stand>/app/<модуль>`; аутентификация Kubernetes auth, роль `flt-eso` с политикой `read` на `flt/<stand>/*`. Публичные chart-ы Vault, ESO и Reloader здесь — рабочее предположение; итоговое правило выбора chart-ов для инфраструктуры задаёт SYS-11 (OQ-28).
- ESO — chart `external-secrets/external-secrets`; `ClusterSecretStore flt-vault` (провайдер `vault`, `auth.kubernetes`, ServiceAccount `external-secrets`); на каждый компонент — `ExternalSecret` в chart-е FLT:

  ```yaml
  apiVersion: external-secrets.io/v1
  kind: ExternalSecret
  metadata:
    name: flt-backend
  spec:
    refreshInterval: 1h
    secretStoreRef: { kind: ClusterSecretStore, name: {{ .Values.secrets.storeName }} }
    target:
      name: flt-backend
      creationPolicy: Owner
    dataFrom:
      - extract: { key: flt/{{ .Values.stand }}/app/identity }
      - extract: { key: flt/{{ .Values.stand }}/app/llm_gateway }
      - extract: { key: flt/{{ .Values.stand }}/infra/postgres }
      - extract: { key: flt/{{ .Values.stand }}/infra/redis }
  ```

  Deployment монолита: `envFrom: [{ secretRef: { name: flt-backend } }]`, аннотация `reloader.stakater.com/auto: "true"`.
- kind в CI: `values-ci.yaml` выключает subchart Vault и задаёт `secrets.storeName: flt-fake`; chart создаёт `ClusterSecretStore flt-fake` с провайдером `fake` и данными из `values-ci.yaml` (тестовые значения, не секреты); те же `ExternalSecret` и `envFrom` проверяются установкой в kind (`helm install` → поды `Ready`). Так манифесты, отличающиеся между CI и prod, ограничены одним `ClusterSecretStore`.
- Vault в `values-dev.yaml` для разработчика с локальным Kubernetes — `dev`-режим Vault (`server.dev.enabled: true`) с заполнением из `deploy/scripts/vault-seed-dev.sh`; это dev-only компонент по принципу OQ-11.
- Шифрование Kubernetes Secret в etcd (`EncryptionConfiguration`) и RBAC на чтение Secret — требование к кластеру, фиксируется в SYS-11 при переходе (OQ-07).

### 3.4. Ключ шифрования API-ключей учеников

- Алгоритм — AES-256-GCM (`cryptography`, `AESGCM`), случайный nonce 12 байт на запись, AAD — `user_id` и `provider_id` (ключ нельзя переставить между учениками). В PostgreSQL модуля `llm_gateway` хранятся `ciphertext`, `nonce`, `key_version` (`v1`), без открытого ключа. Ключ ученика расшифровывается только в памяти процесса на время запроса к провайдеру и никогда не возвращается клиенту (SYS-08: UI показывает только последние 4 символа, которые хранятся отдельно).
- Ротация: в `LLM_KEYS_ENCRYPTION_KEYS` добавляется `v2`, `LLM_KEYS_ENCRYPTION_ACTIVE_VERSION=v2`; новые записи шифруются `v2`, старые читаются по своему `key_version`; фоновое задание `llm_gateway` (Kafka, роль `worker`, под распределённой блокировкой — SYS-05) перешифровывает записи пачками; когда записей с `v1` нет, `v1` удаляется из переменной. В окне обновления инстансы с разными значениями `ACTIVE_VERSION` корректны, пока у всех есть оба ключа: сначала раскатывается добавление `v2`, затем — смена активной версии (два шага, SYS-11).
- Утрата ключа означает утрату ключей учеников без возможности восстановления: ученик вводит ключ заново. Поэтому `.env` и Vault входят в бэкап (3.2, 3.5).

### 3.5. Эксплуатация: ротация, CI, бэкап, контроль утечек

- **Ротация** (сводно): ключи с версией в данных (JWT `kid`, `key_version`) — без простоя двумя шагами; остальные — смена в источнике (сервис + `.env`/Vault) и поочерёдный перезапуск потребителей (`docker compose up -d` пересоздаёт только изменённые сервисы; в Kubernetes — Reloader). Монолит перечитывает секреты только при старте; горячее перечитывание не реализуется (инстансы заменяемы, перезапуск по очереди не прерывает сервис — CLAUDE.md «Инстанс можно остановить в любой момент»). Плановая периодичность: пароли инфраструктуры и ключи — раз в год и при подозрении на утечку; OAuth и внешние ключи — по требованию провайдера; срок фиксируется в SYS-02.
- **CI (GitHub Actions, OQ-06)**: секреты среды — GitHub Actions Secrets (SSH-ключ деплоя на VPS, при приватном репозитории — токен GHCR; `GITHUB_TOKEN` для публикации образов выдаётся автоматически). Тесты и smoke в CI используют только значения, сгенерированные в job (`gen-secrets.sh` в `--ci` режиме) — реальные секреты в тестовых job не передаются. OIDC-федерация с облаком не нужна, пока деплой идёт по SSH на VPS (ADR-011). Деплой копирует на VPS образы и `docker-compose.yml`, но **не** `.env`: он создаётся на VPS один раз и правится там.
- **Контроль утечек**: `detect-secrets` с `.secrets.baseline` и bandit в pre-commit на уровне репозитория (CLAUDE.md, «Отличия проекта от boilerplate», п. 7 — выполняется в Г.1) и в CI (`detect-secrets scan --baseline .secrets.baseline` падает на новых находках); `.gitignore` — `.env`, `*.pem`, `*.key`, `deploy/**/certs/`; запрет секретов в логах — процессор `redact_sensitive_keys` (ADR-010); `DEBUG_MODE=false` на всех стендах, кроме local (traceback с локальными переменными в ответе 500 раскрывает секреты); `/v1/info` удаляется (ADR-010). Dependabot или `uv lock --upgrade` в CI — ADR-011.
- **Бэкап**: compose — `.env` в зашифрованном бэкупе volume-ов (3.2); Kubernetes — snapshot Raft Vault по расписанию в MinIO-бакет `flt-vault-backup` (отдельная политика доступа) плюс хранение unseal-ключей (Shamir 3 из 5) и root-токена вне кластера. Кто хранит доли ключей и где — новый OQ (решение пользователя; auto-unseal облачным KMS недоступен без провайдера, OQ-07).
- **Доступ людей**: на VPS — только владелец по SSH-ключу; в Vault — политики на пути по ролям (администратор, CI-читатель, ESO); Claude не получает реальные секреты: вносит переменные в `.env.template` и `ExternalSecret`, значения вводит пользователь (как в OQ-12).

### 3.6. Что меняется в boilerplate

| Было | Станет |
|---|---|
| `configs/vault_config.py`, `hvac` в `pyproject.toml`, `ignore_missing_imports` для `hvac.*`, `VAULT_*` в документации | удаляются |
| `default_factory=partial(vault_secret, "PG_PASSWORD")` и аналоги в `settings.py`, `kafka_config.py`, `redis_config.py` | обычные поля: обязательные (`PG_PASSWORD: SecretStr`) или с пустым значением по умолчанию там, где отсутствие допустимо по этому ADR (`REDIS_PASSWORD` на local); тип `SecretStr` — чтобы `repr` настроек и логи не раскрывали значение |
| `KafkaSettingsStub`, `RedisSettingsStub` — молчаливый переход на подключение без учётных данных | удаляются; `KAFKA_USERNAME`/`KAFKA_PASSWORD` убираются до появления SASL; отсутствие `REDIS_PASSWORD` на стендах, кроме local, — ошибка старта (валидатор по `STAND_NAME`) |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ROLE_PERMISSIONS` (один симметричный ключ) | `JWT_SIGNING_KEYS` + `JWT_ACTIVE_KID` (секция `identity`), `JWT_PUBLIC_KEYS` (необязательная, не секрет), `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_CSRF_SECRET` (shared kernel) — формат и имена ADR-006; shared kernel проверяет EdDSA по `kid` |
| `OPEN_SEARCH_USER_NAME`, `OPEN_SEARCH_PASSWORD` в `Settings` и `envs/local/local.env` | удаляются вместе с sink-ом (ADR-010); клиент поиска shared kernel получает `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENSEARCH_VERIFY_SSL`, `QDRANT_URL`, `QDRANT_API_KEY` (ADR-014) |
| `envs/prod/redis_prod.env` с `REDIS_HOST=0.201.225.116` (чужой адрес из шаблона) | заменяется на имя сервиса `redis`; значения стендов — несекретные |
| `.pre-commit-config.yaml` в `src/backend/py-monolyth` | переносится в корень репозитория, `detect-secrets` и bandit — на весь репозиторий, `.secrets.baseline` — в корне |

## 4. Последствия

### 4.1. Положительные

- Один путь чтения конфигурации (`env`) в коде, одинаковый в compose, Kubernetes, pytest и CI; нет сетевых вызовов при импорте `configs` (устраняется исключение из правила «импорт без побочных эффектов» в CLAUDE.md boilerplate).
- Отсутствие секрета останавливает старт инстанса с понятной ошибкой вместо подключения без пароля.
- Ротация ключей подписи и шифрования без простоя и без массовой перешифровки «в один момент».
- Инфраструктурные контейнеры и монолит получают секреты одним механизмом в каждом варианте развёртывания.
- Переход prod на Kubernetes не меняет код: добавляются Vault, ESO, Reloader и `values-prod`.

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Секреты в Kubernetes Secret (etcd) | Шифрование etcd at rest и RBAC — требование SYS-11 к кластеру; на VPS Kubernetes нет |
| Ротация большинства секретов требует перезапуска инстансов | Поочерёдный перезапуск без простоя; ключи с версиями — без перезапуска семантики |
| `.env` на VPS — единая точка компрометации при доступе к хосту | Права `600`, SSH только по ключу, бэкап зашифрован, ротация при подозрении; ключи учеников дополнительно зашифрованы — утечка дампа PostgreSQL без `.env` их не раскрывает |
| Удаление `vault_config.py` и стабов ломает тесты boilerplate и часть `envs/` | Правки в Г.1 вместе с тестами; покрытие проверяется `make test-cov` |
| Три дополнительных компонента в Kubernetes (Vault, ESO, Reloader) | Нужны только при переходе на Kubernetes (OQ-07); в kind — ESO с `fake`-провайдером, без Vault |
| `fake`-провайдер ESO в CI не проверяет интеграцию с Vault | Интеграционная проверка Vault — при переходе prod на Kubernetes, в стенде test (SYS-11) |
| Потеря `.env`/Vault без бэкапа = потеря ключей учеников | Бэкап обязателен (SYS-11); UI позволяет ввести ключ заново (SYS-08) |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Записать решение: секреты только через env; `.env` на VPS (`600`, `gen-secrets.sh`); Kubernetes — Vault + ESO + Reloader; клиент Vault из boilerplate удалён; таблица секретов ведётся в SYS-11; Kafka без SASL во внутренней сети | CLAUDE.md, разделы «Отличия проекта от boilerplate» п. 4 (отметить решение), «Развёртывание» (абзац про секреты), «Технологический стек» (строка «Секреты»), «Правила для Claude» (не коммитить секреты — добавить `.env.template` и `ExternalSecret` как место для имён) | Claude | не начато |
| Удалить `configs/vault_config.py`, `hvac`, стабы Kafka/Redis, `vault_secret*` default factory; ввести `SecretStr`, `JWT_SIGNING_KEYS`/`JWT_ACTIVE_KID`, `LLM_KEYS_ENCRYPTION_KEYS`/`LLM_KEYS_ENCRYPTION_ACTIVE_VERSION`; очистить `envs/*` от секретов и чужих адресов; перенести pre-commit в корень | `src/backend/py-monolyth` (`configs/`, `envs/`, `pyproject.toml`, `.pre-commit-config.yaml` → корень репозитория, `.secrets.baseline`) | Claude, этап 1 Г.1 | не начато |
| Создать `deploy/docker-compose/.env.template` (все переменные таблицы 3.1 с комментариями), `deploy/scripts/gen-secrets.sh` (с режимом `--ci`), `env_file` у сервисов, Redis с `--requirepass`, PostgreSQL/MinIO/OpenSearch/Grafana с паролями из `.env`; `.gitignore` | `deploy/docker-compose/docker-compose.yml`, `deploy/scripts/`, `.gitignore` | Claude, этап 1 Г.8 | не начато |
| Создать в Helm: subchart-зависимости `vault` (выключен в `values-ci.yaml`), `external-secrets`, `reloader`; шаблоны `ClusterSecretStore` (`vault` и `fake`), `ExternalSecret` на компонент, `envFrom` и аннотации Reloader; `values-ci.yaml` с тестовыми значениями `fake`; `deploy/scripts/vault-seed-dev.sh` | `deploy/helm` (одновременно с compose) | Claude, этап 1 Г.8 | не начато |
| Реализовать (тесты, затем код) шифрование ключей учеников AES-256-GCM с `key_version` и задание перешифровки | модуль `llm_gateway` (ТЗ STU-01, спецификация модуля этапа 1 В) | Claude, этап 1 Г.6 и этап 4 | не начато |
| Реализовать (тесты, затем код) проверку JWT по `kid` из `JWT_PUBLIC_KEYS` или публичных частей `JWT_SIGNING_KEYS`; одноразовая Ed25519-пара в фикстуре pytest | shared kernel `app/core/security`, модуль `identity`, `tests/conftest.py` | Claude, этап 1 Г.4, Г.5 | не начато |
| Требования: таблица секретов и правило её пополнения, размещение `.env` на VPS, бэкап `.env` и snapshot Vault, шифрование etcd и RBAC при переходе на Kubernetes, двухшаговая раскатка смены активного ключа | SYS-11 | Claude, этап 1 Б.11 | не начато |
| Требования: периодичность ротации, доступ по SSH-ключу, `DEBUG_MODE=false` вне local, хранение ключей учеников в зашифрованном виде | SYS-02 | Claude, этап 1 Б.2 | не начато |
| Требования: формат хранения ключей учеников (`ciphertext`, `nonce`, `key_version`, последние 4 символа), запрет возврата ключа клиенту | SYS-08 | Claude, этап 1 Б.8 | не начато |
| Требования: `detect-secrets` и bandit в CI на весь репозиторий, GitHub Actions Secrets только для деплоя, генерация тестовых секретов в job | SYS-12, ADR-011 | Claude, этап 1 Б.12, А.11 | не начато |
| ADR-006: формат `JWT_SIGNING_KEYS` (Ed25519 PEM), окно удаления старого `kid` = срок access-токена + leeway, `AUTH_CSRF_SECRET`, `JWT_PUBLIC_KEYS` | `Analytics/ADR/ADR-006-authentication-and-authorization.md` | Claude | сделано в 0.2 обоих ADR |
| Отметить в Г.1: удаление `vault_config.py` и стабов; в Г.8: `gen-secrets.sh`, ESO с `fake` в kind | SDD_plan.md, этап 1 Г.1, Г.8 | Claude | не начато |
| Чек-лист для пользователя: внести вручную `OAUTH_*_CLIENT_SECRET`, `SMTP_PASSWORD`, `SMARTCAPTCHA_SERVER_KEY`, `PLATFORM_LLM_API_KEY`, `TELEGRAM_ALERT_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID` в `.env` на VPS; выполнить `docker login ghcr.io` при приватном репозитории | `deploy/docker-compose/README.md` (вместе с чек-листом OQ-12) | Claude (чек-лист), человек (значения) | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-006](ADR-006-authentication-and-authorization.md) | дополняет | Ключи подписи JWT Ed25519 с `kid`, `JWT_PUBLIC_KEYS`, `AUTH_CSRF_SECRET`; окно удаления старого `kid` — срок access-токена + leeway; одноразовая пара в pytest |
| [ADR-007](ADR-007-file-storage.md) | дополняет | `S3_ACCESS_KEY`/`S3_SECRET_KEY` учётной записи `flt-backend`, `MINIO_ROOT_*` только для инициализации, `MINIO_KMS_SECRET_KEY`; бакет для snapshot Vault |
| [ADR-010](ADR-010-observability-stack.md) | дополняет | Пароли internal users OpenSearch (`admin`, `fluent-bit`, `grafana`, `flt-backend`), Grafana, экспортёров; токен и `chat_id` Telegram; запрет секретов в логах |
| [ADR-011](ADR-011-ci-cd.md) | дополняет | GitHub Actions Secrets, `gen-secrets.sh --ci` для стендов CI, деплой без копирования `.env` |
| [ADR-012](ADR-012-haproxy-entry-point.md) | дополняет | Приватный ключ TLS — на volume, не в `.env` |
| [ADR-014](ADR-014-search-engines.md) | дополняет | `OPENSEARCH_PASSWORD` пользователя `flt-backend`, `QDRANT_API_KEY` |
| [ADR-015](ADR-015-media-server.md) | дополняет | `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`; учётная запись egress для `flt-classroom/recordings/*` |
| [SYS-02](../Specs/_system/SYS-02-non-functional-requirements.md) | дополняет | Периодичность ротации, защита ключей учеников, доступ к VPS |
| [SYS-08](../Specs/_system/SYS-08-llm-gateway.md) | дополняет | Формат зашифрованных ключей учеников и `key_version` |
| [SYS-11](../Specs/_system/SYS-11-deployment-and-environments.md) | дополняет | Таблица секретов, `.env` на VPS, Vault/ESO/Reloader, бэкап, etcd |
| [SYS-12](../Specs/_system/SYS-12-ci-cd-and-quality.md) | дополняет | detect-secrets и bandit в CI |
| OQ-07 | учитывает | Prod на compose: `.env` — основной путь; Kubernetes-часть готова, проверяется в kind без Vault |
| OQ-12 | учитывает | OAuth-секреты вносит пользователь; имена — в `.env.template` |
| OQ-39 | зависит от | Токен GHCR нужен только при приватном репозитории |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Согласование с ADR-006 (Ed25519 PEM в `JWT_SIGNING_KEYS`, окно удаления `kid` = 600 с + leeway, `AUTH_CSRF_SECRET` — секрет, `JWT_PUBLIC_KEYS` — не секрет, без фиксированного ключа JWT в `envs/local`), ADR-007 (`S3_ACCESS_KEY`/`S3_SECRET_KEY`, `MINIO_KMS_SECRET_KEY`), ADR-010 и ADR-014 (`OPENSEARCH_BACKEND_PASSWORD` → `OPENSEARCH_PASSWORD`, `QDRANT_API_KEY`), ADR-015 (`LIVEKIT_API_KEY`/`SECRET`), ADR-010 (`TELEGRAM_ALERT_CHAT_ID`, OQ-60); фраза о правиле выбора chart-ов (SYS-11, OQ-28) | proposed |
| 1.0 | 2026-10-10 | пользователь | Принят без изменений (PR #2, слияние в main) | accepted |
