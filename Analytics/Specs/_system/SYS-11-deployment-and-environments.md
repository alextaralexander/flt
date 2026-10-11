# SYS-11 — Развёртывание: структура `deploy/`, стенды, состав контейнеров, паритет docker-compose и Helm

| Поле | Значение |
|---|---|
| Статус | draft |
| Версия | 0.1 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | все |
| Модуль | все; код — `deploy/` (docker-compose, Helm, config, scripts), `src/tools` (`flt-tools deploy`), настройки стендов `src/backend/py-monolyth/envs/` |
| Зависимости | ADR-001 (политика версий образов), ADR-003 (PostgreSQL, Redis, Sentinel), ADR-004 (роли `api`, `worker`, `migrate`, `media_agent`; порты 8000/8001), ADR-007 (MinIO standalone, `minio-init`, бэкап rclone), ADR-010 (наблюдаемость: экспортёры, Fluent Bit, пути `deploy/config/`), ADR-011 (CI, `docker-compose.ci.yml`, `values-ci.yaml`, `deploy-vps.yml`), ADR-012 (HAProxy, TLS, certbot, headless Service), ADR-013 (секреты: `.env`, Vault + ESO), ADR-014 (образ `flt-opensearch`, Qdrant, порог разделения кластеров), ADR-015 (LiveKit, порты, профиль `recording`) |
| Связанные ADR/SYS | ADR-005 (образ `flt-frontend`, `frontend.conf`), ADR-008 (бакет дистрибутивов агента), ADR-009 (`SHUTDOWN_GRACE_SECONDS`), SYS-02 (RPO/RTO, канал VPS, срок хранения логов), SYS-04 (создание топиков ролью `migrate`), SYS-05 (совместимость миграций, N инстансов), SYS-10 (стенд N инстансов в тестах), SYS-12 (job-ы CI); решает OQ-28, OQ-29, OQ-30; учитывает OQ-07, OQ-11, OQ-17, OQ-63, OQ-64, OQ-61, OQ-59 |

## 1. Цель и область действия

- **Цель**: задать единые, проверяемые правила развёртывания платформы в двух вариантах — docker-compose (разработка, CI, продуктив на VPS в РФ до перехода на Kubernetes — OQ-07) и Helm chart (проверяется в kind в CI, продуктив — после перехода), — так чтобы оба варианта содержали одинаковый состав контейнеров с одинаковыми образами и конфигурациями, монолит работал в N инстансах за HAProxy без состояния, миграции выполнялись отдельным шагом, секреты не попадали в репозиторий, обновление проходило без простоя, а данные резервировались и восстанавливались по известной процедуре.
- **Область действия**: `deploy/` целиком (docker-compose, Helm, общие конфигурации, скрипты), стенды и переменные окружения монолита (`envs/`, `STAND_NAME`), продуктивный VPS (чек-лист подготовки, systemd, межсетевой экран, бэкапы), CI в части smoke-тестов развёртывания и проверки паритета (`flt-tools deploy`), требования к кластеру Kubernetes при переходе. Не затрагивает код модулей, кроме переменных окружения, которые они читают.
- **Действует с этапа**: 1 (п. Г.8 «Развёртывание», Г.3 «стенд из N инстансов», Г.9 «Наблюдаемость», Г.10 «CI»); продуктивный VPS — с этапа 2 (OQ-07, OQ-64).
- **Уточняет**: CLAUDE.md, разделы «Развёртывание», «Состав контейнеров», «Маршрутизация через HAProxy», «Масштабирование и состояние», «Команды»; ADR-004 §3.5, ADR-007 §3.8–3.9, ADR-010 §3.1–3.2 и §3.5, ADR-011 §3.1–3.2, ADR-012 §3.3 и §3.6, ADR-013 §3.2–3.3, ADR-014 §2.3, ADR-015 §3.1–3.2.

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| Инстанс монолита (`instance`), N инстансов (`n_instances`) | [глоссарий](../../glossary.md), раздел 12 |
| Стенд (`stand`) | [глоссарий](../../glossary.md), раздел 12; значения — таблица R3 |
| Роль монолита (`runtime_role`) | ADR-004 §3.5: `api`, `worker`, `all`, `migrate`, `media_agent` |
| Окружение (`environment`) | Назначение установки: разработка, тесты, продуктив. Окружение выбирает стенд (R3) и набор профилей или `values` (R5, R6) |
| Профиль compose (`compose_profile`) | Именованная группа сервисов `docker compose --profile <name>`, которая не запускается без явного указания: `dev`, `ci`, `prod`, `recording`, `full` (R5) |
| Базовый состав | Сервисы compose без поля `profiles` и компоненты Helm с `enabled: true` по умолчанию; одинаков в обоих вариантах (R4) |
| Паритет (`parity`) | Свойство: множества компонентов, образы с тегами, имена переменных окружения монолита, порты, конфигурационные файлы и тома совпадают между docker-compose и Helm с точностью до записей файла исключений `deploy/parity-exceptions.yaml` (R8) |
| Umbrella chart | Helm chart `flt`, который содержит собственные шаблоны компонентов FLT и объявляет публичные chart-ы инфраструктуры зависимостями в `Chart.yaml` (R6) |
| Тег образа (`image_tag`) | Для образов FLT (`flt-backend`, `flt-frontend`) — тег `stage-N`, `main` или `sha-<7>` (ADR-011), на VPS — переменная `FLT_IMAGE_TAG` в `/opt/flt/.image-tag.env`; для инфраструктурных образов — минорный тег по ADR-001 (R7) |
| RPO, RTO | Recovery Point Objective — допустимая потеря данных по времени; Recovery Time Objective — допустимое время восстановления. Значения — R18, согласуются с SYS-02 |

## 3. Требования

### SYS-11-R1 Структура каталога `deploy/`

- **Формулировка**: каталог `deploy/` должен иметь структуру ниже; новые файлы развёртывания должны размещаться только в ней (скрипты развёртывания — `deploy/scripts/`, репозиторные инструменты проверки — `src/tools/`, ADR-011).

  ```
  deploy/
    docker-compose/
      docker-compose.yml          # базовый состав + сервисы профилей dev, ci, prod, recording (R4, R5)
      docker-compose.ci.yml       # оверлей CI: уменьшенные ресурсы, тяжёлые сервисы в профиль full, json-file логи (ADR-011)
      .env.template               # имена всех переменных и несекретные значения по умолчанию (ADR-013)
      README.md                   # чек-лист подготовки VPS (R23), порядок обновления и отката (R19, R20), восстановление (R18), журнал проверок восстановления
      postgres/init/*.sql         # создание расширений (citext, pg_trgm, pg_stat_statements)
      certbot/Dockerfile          # образ flt-certbot: certbot + socat для runtime API HAProxy (ADR-012 §3.3)
      backup/Dockerfile           # образ flt-backup: postgresql18-client, rclone, age, supercronic (R18)
    helm/flt/
      Chart.yaml  Chart.lock  values.yaml  values-ci.yaml  values-dev.yaml  values-prod.example.yaml
      files/config/               # копия deploy/config/, синхронизируется flt-tools deploy sync-config (R2)
      templates/                  # собственные шаблоны компонентов (R6)
    config/
      haproxy/haproxy.cfg                               # ADR-012
      nginx/frontend.conf                               # ADR-005 §3.8 (копируется в образ flt-frontend)
      prometheus/{prometheus.yml, scrape/compose.yml, scrape/kubernetes.yml, rules/*.yml}   # ADR-010
      grafana/{provisioning/{datasources,dashboards,alerting}/*.yml, dashboards/*.json}      # ADR-010
      fluent-bit/{parsers.conf, filters.conf, output.conf, input-compose.conf, input-kubernetes.conf}  # ADR-010
      opensearch/{Dockerfile, opensearch.yml, internal_users.yml, index-template-logs.json, ism-policy-logs.json}  # ADR-010, ADR-014
      redis/redis.conf                                  # ADR-003
      postgres/postgresql.conf                          # ADR-003
      kafka/server.properties.env                       # переменные KAFKA_* общие для compose и Helm
      livekit/livekit.yaml                              # ADR-015, создаётся на этапе 6
    scripts/
      gen-secrets.sh              # ADR-013 §3.2 (режим --ci)
      deploy.sh                   # обновление без простоя на VPS (R19); вызывается deploy-vps.yml и вручную
      rollback.sh                 # откат на предыдущий тег (R20)
      tls-bootstrap.sh            # первый выпуск сертификата (ADR-012 §3.3)
      backup.sh  restore.sh       # R18
      flt-compose.sh              # обёртка docker compose для пользователя flt-deploy (R23)
      vault-seed-dev.sh           # ADR-013 §3.3
      vps-prepare.sh              # идемпотентная подготовка VPS по чек-листу R23
    parity-exceptions.yaml        # допустимые различия compose и Helm (R8)
  ```
- **Обоснование**: CLAUDE.md «Структура репозитория» (каталоги `deploy/helm` и `deploy/config` там ещё не описаны); ADR-010, ADR-012, ADR-015 уже называют конкретные пути в `deploy/config/`; ADR-011 размещает скрипты развёртывания в `deploy/scripts/`, инструменты — в `src/tools/`. Единая структура нужна, чтобы Claude находил и правил файлы развёртывания без устных пояснений.
- **Проверка**: тест `src/tools/tests/test_deploy_layout.py` (`<будет создан>`, этап 1 Г.8): наличие всех файлов из дерева, отсутствие файлов `*.yml`, `*.yaml`, `*.cfg`, `*.conf` в `deploy/` вне перечисленных каталогов; job `docs`/`helm` CI.
- **Применимость**: deploy, CI.

### SYS-11-R2 Общие конфигурации: один источник, копия в chart с проверкой (решает OQ-29)

- **Формулировка**: конфигурации HAProxy, Nginx, Prometheus, Grafana, Fluent Bit, OpenSearch, Redis, PostgreSQL, Kafka и LiveKit должны храниться только в `deploy/config/`; docker-compose монтирует их bind-mount-ом (только чтение), Helm читает их через `.Files.Get` и `.Files.Glob` из `deploy/helm/flt/files/config/`, который является побайтовой копией `deploy/config/`, обновляемой командой `uv run flt-tools deploy sync-config` (из `src/tools`) и проверяемой командой `flt-tools deploy check-config` в CI (падает при расхождении); различия между вариантами развёртывания должны выражаться переменными окружения (HAProxy — `${API_HOST}`, `${FRONTEND_HOST}`, `${MINIO_HOST}`, `${LIVEKIT_HOST}`; Fluent Bit — `${OPENSEARCH_HOST}`; Grafana — `${PROMETHEUS_URL}`, `${OPENSEARCH_URL}`), отдельными файлами с суффиксом варианта (`scrape/compose.yml` и `scrape/kubernetes.yml`, `input-compose.conf` и `input-kubernetes.conf`) или функцией `tpl` Helm только для подстановки имён Service; ручная правка `files/config/` запрещена.
- **Обоснование**: OQ-29 (planned → SYS-11): вариант 1 «файлы в `deploy/config/` с подстановкой переменных» принят; способ доставки в chart — копирование скриптом, а не символическая ссылка: Helm не читает файлы вне корня chart-а, символические ссылки, выходящие за корень, игнорируются `helm package`, и они ненадёжны в git на Windows (среда разработки проекта); проверка в CI повторяет паттерн `api:check` ADR-005.
- **Проверка**: шаг `flt-tools deploy check-config` в job `helm` (ADR-011, SYS-12); тест `src/tools/tests/test_sync_config.py`; `helm template` рендерит ConfigMap из `files/config/` — `kubeconform` в job `helm`; `haproxy -c -f deploy/config/haproxy/haproxy.cfg` для обоих наборов переменных (ADR-012 §3.3).
- **Применимость**: deploy, CI.

### SYS-11-R3 Стенды и окружения

- **Формулировка**: переменная `STAND_NAME` должна принимать ровно четыре значения, каждому соответствует каталог `src/backend/py-monolyth/envs/<stand>/` с несекретными параметрами (ADR-013 §3.2) и назначение из таблицы; окружения разработки, тестов и продуктива выбираются стендом, профилями compose (R5) и файлами `values-*.yaml` (R6); иные стенды не создаются без `changed`-версии этой спецификации.

  | `STAND_NAME` | Где работает | Как запускается | Назначение | `APP_ROLE` | `FLT_EXPOSE_DOCS` | `DEBUG_MODE` |
  |---|---|---|---|---|---|---|
  | `local` | машина разработчика, процесс на хосте | `make dev` + `make compose-up` (только инфраструктурные сервисы compose: `postgres`, `redis`, `kafka`, `minio`, `minio-init`, `opensearch`, `qdrant`, `mailpit`) | разработка, pytest (оверлей `envs/.test.env`, разведение БД — SYS-10, OQ-31) | `all` (по умолчанию только здесь) | `1` | `true` |
  | `dev` | машина разработчика или общий dev-VPS, всё в контейнерах | `docker compose --profile dev up -d --wait`, адрес `http://flt.localhost`, без TLS | ручная проверка полной системы, локальные E2E, Storybook против реального бэкенда | `api` / `worker` / `migrate` | `1` | `false` |
  | `test` | CI: compose `stand-n3` и kind (ADR-011); после перехода на Kubernetes — namespace `flt-test` | `docker compose -f docker-compose.yml -f docker-compose.ci.yml --profile ci up -d --wait --scale api=3`; `helm install -f values-ci.yaml` | автотесты на N инстансах, E2E, smoke Helm, нагрузочные тесты (SYS-10) | `api` / `worker` / `migrate` | `0` | `false` |
  | `prod` | VPS в РФ (OQ-07); после перехода — namespace `flt-prod` | `systemd` unit `flt.service` → `flt-compose --profile prod up -d --wait`; `helm upgrade -f values-prod.yaml` | продуктив | `api` / `worker` / `migrate` (`media_agent` с этапа 6) | `0` | `false` |

- **Обоснование**: CLAUDE.md «Backend-сервис (boilerplate)»: конфигурация по стендам через `STAND_NAME`; OQ-07: dev и test на текущей схеме — машина разработчика и CI, prod — VPS; `DEBUG_MODE=false` вне `local` — ADR-013 §3.5; `FLT_EXPOSE_DOCS` — ADR-012.
- **Проверка**: тест `tests/core/test_stands.py` (`<будет создан>`): перечисление стендов в `configs/stands.py` равно таблице, для каждого есть каталог `envs/<stand>/`, в файлах `envs/*` нет значений переменных из таблицы секретов ADR-013 §3.1 (кроме `local` с `# pragma: allowlist secret`); `detect-secrets` в CI; smoke `helm` и `stand-n3` передают `STAND_NAME=test`.
- **Применимость**: backend, deploy, CI.

### SYS-11-R4 Полный состав контейнеров — одинаковый в docker-compose и Helm

- **Формулировка**: оба варианта развёртывания должны содержать контейнеры из таблицы ниже с указанными образами (линия «не ниже» — минимальная минорная линия на 2026-10-10; точный минорный тег фиксируется при добавлении в п. Г.8 одинаково в `docker-compose.yml` и `values.yaml` и далее обновляется Renovate — ADR-001 §3.2), портами и томами; строки с этапом больше 1 добавляются в обоих вариантах одновременно на указанном этапе; контейнер, которого нет в таблице, не добавляется без `changed`-версии этой спецификации и строки в CLAUDE.md «Состав контейнеров».

  | Контейнер (сервис compose / компонент Helm) | Образ и линия (не ниже) | Порты (контейнер) | Том | Профиль compose / условие Helm | Этап |
  |---|---|---|---|---|---|
  | `haproxy` / `haproxy` | `haproxy:3.2-alpine` (ADR-012) | 80, 443 наружу; 8080 (без TLS, dev и test); 8404 внутр. | `haproxy-certs`, `haproxy-socket` | базовый / всегда; реплик в Helm 2, в CI 1 | 1 |
  | `frontend` / `frontend` | `ghcr.io/alextaralexander/flt/frontend:${FLT_IMAGE_TAG}` (база `nginxinc/nginx-unprivileged:1.28-alpine`, ADR-005) | 8080 внутр. | `acme-webroot` (только чтение) | базовый / всегда | 1 |
  | `api` / `api` | `ghcr.io/alextaralexander/flt/backend:${FLT_IMAGE_TAG}`, `APP_ROLE=api` | 8000 внутр. | нет | базовый, `deploy.replicas: 3` / Deployment `flt-api`, headless Service, `replicas: 2` | 1 |
  | `worker` / `worker` | тот же образ, `APP_ROLE=worker` | 8001 внутр. | нет | базовый, `deploy.replicas: 2` / Deployment `flt-worker`, `replicas: 2` | 1 |
  | `migrate` / `migrate` | тот же образ, `APP_ROLE=migrate` | — | нет | базовый, `restart: "no"` / Job `flt-migrate` с hook-ами `pre-install,pre-upgrade` | 1 |
  | `media-agent` / `media-agent` | тот же образ, `APP_ROLE=media_agent` | 8001 внутр. | нет | базовый с этапа 6 / `livekit.enabled` | 6 |
  | `postgres` / `postgres` | `postgres:18-alpine` | 5432 внутр. | `postgres-data` | базовый / всегда (собственный StatefulSet) | 1 |
  | `redis` / `redis` | `redis:8-alpine` | 6379 внутр. | нет (без персистентности, ADR-003) | базовый / собственные StatefulSet `master` + `replica` и Deployment `sentinel` ×3 (ADR-003) | 1 |
  | `kafka` / `kafka` | `apache/kafka:4.1.0` (KRaft, один узел; в Kubernetes prod — 3 брокера) | 29092 внутр.; 9092 только на `127.0.0.1` хоста для стенда `local` | `kafka-data` | базовый / собственный StatefulSet | 1 |
  | `minio` / `minio` | `minio/minio:RELEASE.2025-10-15T17-29-55Z` (зафиксирован, OQ-64; ADR-007 §3.10) | 9000 внутр. | `minio-data` | базовый / собственный StatefulSet standalone (ADR-007 §3.9) | 1 |
  | `minio-init` / `minio-init` | `minio/mc` — последний опубликованный образ, тег фиксируется в Г.8 вместе с образом сервера (OQ-64) | — | нет | базовый, `restart: "no"` / Job с hook `post-install,post-upgrade` | 1 |
  | `opensearch` / `opensearch` | `flt-opensearch` — собственный образ из `deploy/config/opensearch/Dockerfile` на базе `opensearchproject/opensearch:3.2` с плагинами анализа (ADR-014) | 9200, 9600 внутр. | `opensearch-data` | базовый / chart `opensearch-project/opensearch` с образом `flt-opensearch`, 1 реплика в CI, 3 в prod-Kubernetes | 1 |
  | `qdrant` / `qdrant` | `qdrant/qdrant:v1.15` | 6333, 6334 внутр. | `qdrant-data` | базовый / chart `qdrant/qdrant` | 1 |
  | `prometheus` / `prometheus` | `prom/prometheus:v3.5` | 9090 внутр. | `prometheus-data` | базовый / chart `prometheus-community/prometheus` (без Operator, ADR-010) | 1 |
  | `grafana` / `grafana` | `grafana/grafana:12.1` | 3000 внутр. (на VPS — через SSH-туннель) | `grafana-data` | базовый / chart `grafana/grafana` | 1 |
  | `fluent-bit` / `fluent-bit` | `fluent/fluent-bit:4.0` | 24224 на `127.0.0.1` хоста (log driver `fluentd`, ADR-010) | `fluent-bit-buffer` | базовый / chart `fluent/fluent-bit` как DaemonSet | 1 |
  | `postgres-exporter` / `postgres-exporter` | `prometheuscommunity/postgres-exporter:v0.17` | 9187 внутр. | нет | базовый / chart `prometheus-community/prometheus-postgres-exporter` | 1 |
  | `redis-exporter` / `redis-exporter` | `oliver006/redis_exporter:v1.74` | 9121 внутр. | нет | базовый / chart `prometheus-community/prometheus-redis-exporter` | 1 |
  | `kafka-exporter` / `kafka-exporter` | `danielqsj/kafka-exporter:v1.9` | 9308 внутр. | нет | базовый / chart `prometheus-community/prometheus-kafka-exporter` | 1 |
  | `node-exporter` / `node-exporter` | `prom/node-exporter:v1.9` | 9100 внутр. | `/` хоста только чтение | базовый (один на VPS) / chart `prometheus-community/prometheus-node-exporter` (DaemonSet) | 1 |
  | `cadvisor` / — | `gcr.io/cadvisor/cadvisor:v0.52` | 8080 внутр. | сокет и cgroups хоста только чтение | базовый / не нужен: метрики контейнеров отдаёт kubelet (исключение паритета) | 1 |
  | `mailpit` / `mailpit` | `axllent/mailpit:v1.27` | 1025 внутр.; 8025 на `127.0.0.1` хоста | нет | `dev`, `ci` / `dev.mailpit.enabled` (OQ-11) | 1 |
  | `mock-oidc` / `mock-oidc` | `ghcr.io/navikt/mock-oauth2-server:2.2` | 8080 внутр. | нет | `dev`, `ci` / `dev.mockOidc.enabled` (OQ-12: автотесты OAuth) | 1 |
  | `certbot` / — | `flt-certbot` из `deploy/docker-compose/certbot/Dockerfile` (база `certbot/certbot:v4.0`) | — | `acme-webroot`, `haproxy-certs`, `haproxy-socket`, `letsencrypt` | `prod` / не нужен: cert-manager (ADR-012 §3.3; исключение паритета) | 1 (включается с появлением домена, OQ-08) |
  | `backup` / `backup` | `flt-backup` из `deploy/docker-compose/backup/Dockerfile` (база `alpine:3.22`) | — | `backups` (локальная копия), `postgres-data` не монтируется (дамп по сети) | `prod` / CronJob `flt-backup` под `backup.enabled` | 2 (с продуктивом) |
  | `embeddings` / `embeddings` | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` с моделью по OQ-59 | 80 внутр. | `embeddings-models` | базовый с этапа 5 / `embeddings.enabled` | 5 (при решении OQ-59 в пользу контейнера) |
  | `livekit` / `livekit` | `livekit/livekit-server:v1.9` | 7880 внутр.; 7881/tcp, 7882/udp, 3478/udp, 5349/tcp наружу | `haproxy-certs` только чтение | базовый с этапа 6 / chart `livekit/livekit-server` под `livekit.enabled` | 6 |
  | `livekit-egress` / `livekit-egress` | `livekit/egress:v1.9` | — | нет | `recording` / `livekit.egress.enabled` (ADR-015, OQ-35) | 6 |
  | — / `vault` | chart `hashicorp/vault` 0.30 | — | PVC | только Helm, `vault.enabled` (выключен в CI; `dev`-режим в `values-dev.yaml`) | при переходе на Kubernetes |
  | — / `external-secrets` | chart `external-secrets/external-secrets` 0.18 | — | нет | только Helm, всегда (в CI — `ClusterSecretStore` `fake`) | 1 (в kind) |
  | — / `reloader` | chart `stakater/reloader` 2.1 | — | нет | только Helm, всегда | 1 (в kind) |

- **Обоснование**: CLAUDE.md «Состав контейнеров» и правило «одинаковый состав контейнеров» с оговорками (Vault только в Kubernetes, Redis с Sentinel в Kubernetes); вспомогательные контейнеры (экспортёры, `minio-init`, `certbot`, `backup`, `cadvisor`) добавлены по ADR-007, ADR-010, ADR-012; dev-only и CI-only — по OQ-11, OQ-12; этапы — по ADR-014 (`embeddings`), ADR-015 (LiveKit). Образ `cadvisor` нужен для дашборда `flt-instances.json` (CPU и память контейнеров в compose, ADR-010 §3.5).
- **Проверка**: `flt-tools deploy parity` (R8) сверяет таблицу компонентов и образы между `docker compose config` и `helm template`; тест `src/tools/tests/test_container_table.py` (`<будет создан>`) сверяет эту таблицу спецификации (разбор Markdown) с `docker-compose.yml` и `values.yaml` — имя, образ, этап; smoke `up -d --wait` всего базового состава в ночном job `schedule` (ADR-011 §4.2) и `helm install --wait` в kind.
- **Применимость**: deploy, CI.

### SYS-11-R5 Профили docker-compose: базовый состав без профиля, остальное — по профилям (решает OQ-11)

- **Формулировка**: `docker-compose.yml` должен запускать без профилей ровно базовый состав R4; сервисы с полем `profiles` распределяются так: `dev` — `mailpit`, `mock-oidc`; `ci` — `mailpit`, `mock-oidc` (один сервис может принадлежать обоим профилям); `prod` — `certbot`, `backup`; `recording` — `livekit-egress` (этап 6); оверлей `docker-compose.ci.yml` переводит `opensearch`, `qdrant`, `grafana`, `prometheus`, `fluent-bit`, `postgres-exporter`, `redis-exporter`, `kafka-exporter`, `node-exporter`, `cadvisor` в профиль `full` и заменяет log driver на `json-file`, чтобы job `stand-n3` (ADR-011) поднимал только нужные тестам сервисы, а ночной job `schedule` запускал `--profile ci --profile full`; dev-only сервис не должен иметь побочных эффектов для базового состава (например, монолит в базовом составе получает `SMTP_HOST` из `.env`, а профиль `dev` задаёт `SMTP_HOST=mailpit` через `env_file` стенда, не через `environment` базового сервиса).
- **Обоснование**: OQ-11 (resolved): «dev-only сервисы включаются профилем docker-compose и `values-dev.yaml` Helm — принцип фиксируется в SYS-11»; ADR-011 §4.2: hosted runner не вмещает полный состав для тестов масштабируемости; ADR-012: certbot — профиль `prod`; ADR-015: egress — профиль `recording`.
- **Проверка**: тест `src/tools/tests/test_compose_profiles.py` (`<будет создан>`): `docker compose config --format json` без профилей даёт ровно базовый состав R4; с `--profile dev` добавляются только `mailpit`, `mock-oidc`; `docker compose -f ... -f docker-compose.ci.yml config` без `--profile full` не содержит перечисленных тяжёлых сервисов; `make compose-up` для стенда `local` запускает только инфраструктурные сервисы (проверка цели Makefile).
- **Применимость**: deploy, CI.

### SYS-11-R6 Структура Helm chart и правило выбора chart-ов (решает OQ-28)

- **Формулировка**: Helm chart должен быть одним umbrella chart-ом `deploy/helm/flt` (`apiVersion: v2`, `name: flt`, версия `0.<N>.0` для `stage-N`, `appVersion` — тег образов, ADR-011 §3.2) с собственными шаблонами в `templates/<component>/` для компонентов FLT и для инфраструктуры, у которой нет официального chart-а поставщика с тем же официальным образом, что в compose; публичный chart допускается как зависимость `Chart.yaml` только если его публикует сам проект-поставщик компонента и он позволяет задать тот же образ и тег, что в `docker-compose.yml`; chart-ы Bitnami не используются (с 2025 года их образы платные и отличаются от официальных); операторы (CloudNativePG, Strimzi, MinIO Operator, Prometheus Operator) не используются до перехода prod на Kubernetes и вводятся отдельным ADR. Распределение:

  | Компонент | Реализация в chart-е | Причина |
  |---|---|---|
  | `api`, `worker`, `migrate`, `media-agent`, `haproxy`, `frontend`, `mailpit`, `mock-oidc`, `backup`, `embeddings` | собственные шаблоны | компоненты FLT или конфигурация полностью своя (HAProxy — `haproxy.cfg`, Nginx — образ FLT) |
  | `postgres`, `redis` (master, replica, sentinel), `kafka` (KRaft), `minio`, `minio-init` | собственные StatefulSet/Job | официальные образы без официального chart-а поставщика с нужной конфигурацией; MinIO — ADR-007 §3.9 |
  | `opensearch` | `opensearch-project/opensearch` | официальный chart, образ переопределяется на `flt-opensearch` (ADR-014) |
  | `prometheus`, `node-exporter`, `postgres-exporter`, `redis-exporter`, `kafka-exporter` | `prometheus-community/*` | официальные chart-ы сообщества Prometheus (ADR-010) |
  | `grafana` | `grafana/grafana` | официальный chart |
  | `fluent-bit` | `fluent/fluent-bit` | официальный chart (ADR-010) |
  | `qdrant` | `qdrant/qdrant` | официальный chart |
  | `vault`, `external-secrets`, `reloader` | `hashicorp/vault`, `external-secrets/external-secrets`, `stakater/reloader` | ADR-013 |
  | `livekit`, `livekit-egress` | `livekit/livekit-server`, `livekit/egress` | ADR-015 |
  | cert-manager, MetalLB или облачный LoadBalancer, metrics-server, StorageClass | не входят в chart — требования к кластеру (R27) | компоненты уровня кластера |

  Каждая зависимость объявляется с `condition: <component>.enabled`, `Chart.lock` коммитится, `charts/` — нет (`helm dependency build` в CI); файлы значений: `values.yaml` (базовый состав, prod-подобные значения без секретов), `values-ci.yaml` (R22), `values-dev.yaml` (Mailpit, mock OIDC, Vault dev), `values-prod.example.yaml` (шаблон для перехода, копируется вне репозитория).
- **Обоснование**: OQ-28 (planned → SYS-11): вариант 1 «umbrella chart с собственными subchart-ами для компонентов FLT и публичными chart-ами для инфраструктуры» принят с уточнением из ADR-007 (MinIO — собственный StatefulSet) и распространён на PostgreSQL, Redis и Kafka, для которых публичные chart-ы с официальными образами в 2026 году отсутствуют; собственные шаблоны держат паритет образов с compose, который требует ADR-001; переход к операторам отложен по OQ-07.
- **Проверка**: job `helm` CI (ADR-011): `helm dependency build`, `helm lint`, `helm template | kubeconform -strict`, `helm install -f values-ci.yaml --wait`, `helm test`; тест `src/tools/tests/test_chart_dependencies.py` (`<будет создан>`): репозитории зависимостей `Chart.yaml` входят в белый список таблицы, Bitnami отсутствует; `flt-tools deploy parity` (R8) подтверждает образы.
- **Применимость**: deploy, CI.

### SYS-11-R7 Теги образов задаются один раз на вариант и совпадают

- **Формулировка**: тег каждого инфраструктурного образа должен быть записан ровно один раз в `docker-compose.yml` (поле `image:`) и ровно один раз в `values.yaml` (`<component>.image.repository` и `.tag`, либо `image` зависимости), совпадать между ними и соответствовать политике ADR-001 §3.2 (минорный тег последней стабильной линии; исключение — MinIO и `mc` с зафиксированными тегами до решения OQ-64); образы FLT используют переменную `FLT_IMAGE_TAG` (compose, значение по умолчанию `local` для локальной сборки через `build:`) и `global.imageTag` (Helm); тег `latest` запрещён; Renovate обновляет оба файла одним PR (менеджеры `docker-compose` и `helm-values`, ADR-001).
- **Обоснование**: ADR-001 §3.2 п. 2 и 7: «образы инфраструктуры — минорный тег, одинаковый в docker-compose и Helm (паритет проверяет тест в SYS-11)»; версия, работающая в CI на compose, должна быть той же, что в kind.
- **Проверка**: `flt-tools deploy parity` сравнивает `repository:tag` всех контейнеров; тест `src/tools/tests/test_image_tags.py` (`<будет создан>`): нет `:latest`, нет образов без тега, у MinIO и `mc` — зафиксированные теги из R4; `renovate.json` содержит оба менеджера.
- **Применимость**: deploy, CI.

### SYS-11-R8 Паритет docker-compose и Helm проверяется в CI

- **Формулировка**: команда `uv run flt-tools deploy parity` (пакет `src/tools`, ADR-011) должна строить модель обоих вариантов — из `docker compose -f docker-compose.yml --profile dev --profile prod --profile recording config --format json` и из `helm template flt deploy/helm/flt -f values-prod.example.yaml` с включением всех компонентов — и сравнивать: (а) множество компонентов (имя сервиса compose ↔ метка `app.kubernetes.io/component`); (б) образ с тегом каждого компонента; (в) множество имён переменных окружения контейнеров монолита (`api`, `worker`, `migrate`, `media-agent`) и значение `APP_ROLE`; (г) порты контейнеров; (д) имена файлов конфигурации, смонтированных в контейнер (bind-mount ↔ ключи ConfigMap); (е) имена томов (compose) ↔ имена PVC; (ж) число реплик `worker` и минимальное число реплик `api`; расхождение допускается только при наличии записи в `deploy/parity-exceptions.yaml` с полями `component`, `aspect`, `reason`, `adr`; команда должна входить в job `helm` CI и падать при любом неучтённом расхождении.
- **Обоснование**: CLAUDE.md «Развёртывание»: «любое изменение, затрагивающее развёртывание, вносится одновременно в docker-compose и в Helm charts» — правило без автоматической проверки не выполняется; стартовые исключения: `vault`, `external-secrets`, `reloader`, `redis-replica`, `redis-sentinel` (CLAUDE.md: Vault и Sentinel только в Kubernetes), `certbot` (cert-manager), `cadvisor` (kubelet), `node-exporter` как DaemonSet, `fluent-bit` input (`forward` против `tail`), `kafka` число брокеров (1 против 3 в prod-Kubernetes).
- **Проверка**: тест `src/tools/tests/test_parity.py` (`<будет создан>`): на фикстурах с внесённым расхождением (другой тег, лишняя переменная) команда возвращает ненулевой код; job `helm` CI; негативный smoke в Г.8 — PR с изменением только compose падает на `parity`.
- **Применимость**: deploy, CI.

### SYS-11-R9 Роли монолита и число реплик по стендам (закрывает OQ-17 в части развёртывания)

- **Формулировка**: монолит должен запускаться из одного образа в ролях ADR-004 §3.5 с числом реплик по таблице; роль `all` используется только на стенде `local`; `api` и `worker` — отдельные сервисы compose и Deployment-ы Helm с одинаковым `env_file`/`envFrom` и разным `APP_ROLE`; служебный HTTP `worker` и `media_agent` — порт 8001 (`WORKER_HTTP_PORT`).

  | Стенд | `api` | `worker` | `media_agent` (этап 6) | Способ |
  |---|---|---|---|---|
  | `local` | 1 процесс `all` на хосте | — | — | `make dev` |
  | `dev` (compose) | 3 | 2 | 1 | `deploy.replicas` в `docker-compose.yml` |
  | `test` (compose `stand-n3`) | 3 (`--scale api=3`) | 2 | 1 (с этапа 6, без медиатрафика) | `docker-compose.ci.yml` |
  | `test` (kind) | 2 | 1 | 0 (`livekit.enabled=false`; `true` в отдельном smoke) | `values-ci.yaml` |
  | `prod` (compose на VPS) | 3 | 2 | 1 | `deploy.replicas`, `deploy.sh` (R19) |
  | `prod` (Kubernetes) | не менее 2, HPA до 6 (R21) | 2 | 1 | `values-prod.yaml` |

- **Обоснование**: ADR-004 §3.5 (имена сервисов, порты, роли); CLAUDE.md «Развёртывание»: «N экземпляров за HAProxy… в Helm не меньше 2»; тесты масштабируемости — N = 3 (SDD_plan.md, Приложение Г).
- **Проверка**: `flt-tools deploy parity` (аспект ж); smoke `stand-n3`: три сервера `be_api` в состоянии `UP` на `haproxy:8404/stats;csv` и две цели `flt-worker` в Prometheus (ADR-010, ADR-012); `helm` job: `kubectl get deploy flt-api -o jsonpath='{.spec.replicas}'` = 2.
- **Применимость**: deploy, tests.

### SYS-11-R10 Порядок запуска: инфраструктура → `migrate` → `api`, `worker`

- **Формулировка**: сервисы `api`, `worker` и `media-agent` должны зависеть от `migrate` через `depends_on: { migrate: { condition: service_completed_successfully } }`, а `migrate` — от `postgres`, `kafka`, `minio`, `minio-init`, `opensearch`, `qdrant` через `condition: service_healthy` (для `minio-init` — `service_completed_successfully`); `fluent-bit` должен стартовать первым (все сервисы с драйвером `fluentd` зависят от него); `haproxy` зависит от `api` и `frontend` (`service_healthy`); в Helm шаг миграций — Job `flt-migrate` с аннотациями `helm.sh/hook: pre-install,pre-upgrade`, `helm.sh/hook-weight: "10"`, `helm.sh/hook-delete-policy: before-hook-creation`, `backoffLimit: 0`, `activeDeadlineSeconds: 900`, а инициализация MinIO — Job `flt-minio-init` с `pre-install,pre-upgrade` и весом `"5"`; `MIGRATE_ON_START=false` на всех стендах, кроме `local`.
- **Обоснование**: CLAUDE.md «Масштабирование и состояние»: «миграции выполняются один раз отдельным шагом, а не каждым инстансом при старте»; ADR-004 §3.5 (роль `migrate` создаёт топики, бакеты, шаблоны индексов — поэтому зависит от Kafka, MinIO, OpenSearch, Qdrant); ADR-010 (Fluent Bit первым).
- **Проверка**: тест `src/tools/tests/test_compose_dependencies.py` (`<будет создан>`): граф `depends_on` из `docker compose config` содержит перечисленные рёбра с нужными условиями; `helm template` содержит Job с указанными аннотациями (`kubeconform` + проверка аннотаций в `src/tools/tests/test_helm_hooks.py`); smoke Г.8: `docker compose up -d --wait` завершается успешно, `docker compose ps` показывает `migrate` в состоянии `exited (0)`; негативный smoke — `migrate` с ошибкой не даёт стартовать `api`.
- **Применимость**: deploy, tests.

### SYS-11-R11 Health-проверки и probes

- **Формулировка**: каждый сервис compose должен иметь `healthcheck`, а каждый контейнер Helm — probes по таблице; `api` и `worker` проверяются по `/v1/ready` (ADR-010 §3.4), `start_period` учитывает инициализацию приложения; HAProxy исключает инстанс по собственной проверке `/v1/ready` (ADR-012) независимо от compose.

  | Контейнер | compose `healthcheck.test` | interval / timeout / retries / start_period | Helm liveness / readiness / startup |
  |---|---|---|---|
  | `api` | `wget -qO- http://127.0.0.1:8000/v1/ready` | 10s / 3s / 3 / 30s | `GET /v1/health` 10s, `failureThreshold 3` / `GET /v1/ready` 5s / `GET /v1/health` 2s, `failureThreshold 30` |
  | `worker`, `media-agent` | `wget -qO- http://127.0.0.1:8001/v1/ready` | 10s / 3s / 3 / 30s | как `api` на порту 8001 |
  | `haproxy` | `wget -qO- http://127.0.0.1:8404/stats;csv` | 5s / 3s / 3 / 5s | tcp 8404 / `GET /healthz` на 80 (ADR-012) |
  | `frontend` | `wget -qO- http://127.0.0.1:8080/healthz` | 10s / 3s / 3 / 5s | `GET /healthz` / `GET /healthz` |
  | `postgres` | `pg_isready -U $POSTGRES_USER -d flt` | 5s / 5s / 20 / 10s | `exec pg_isready` / то же |
  | `redis` | `redis-cli -a $REDIS_PASSWORD ping` | 5s / 5s / 20 / 5s | `exec redis-cli ping` / то же; sentinel — `redis-cli -p 26379 ping` |
  | `kafka` | `/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:29092` | 10s / 10s / 20 / 20s | tcp 29092 / `exec` та же команда |
  | `minio` | `mc ready local` или `curl -f http://127.0.0.1:9000/minio/health/live` | 10s / 5s / 10 / 10s | `GET /minio/health/live` / `GET /minio/health/ready` |
  | `opensearch` | `curl -fsu admin:$OPENSEARCH_ADMIN_PASSWORD http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=5s` | 15s / 10s / 20 / 60s | значения chart-а |
  | `qdrant` | `curl -f http://127.0.0.1:6333/readyz` | 10s / 5s / 10 / 10s | `GET /livez` / `GET /readyz` |
  | `prometheus`, `grafana`, `fluent-bit`, экспортёры, `mailpit`, `mock-oidc`, `livekit`, `embeddings` | `GET /-/healthy`, `GET /api/health`, `GET /api/v1/health` (порт 2020), `GET /metrics`, `GET /livez`, `GET /isalive`, `GET /` (7880), `GET /health` | 10s / 5s / 5 / 10s | значения chart-ов или те же пути |

- **Обоснование**: CLAUDE.md «Наблюдаемость»: health-эндпоинты используют HAProxy, probes и healthcheck compose; ADR-010 §3.4 задаёт параметры probes монолита; `depends_on: service_healthy` (R10) работает только при наличии `healthcheck`.
- **Проверка**: тест `src/tools/tests/test_healthchecks.py` (`<будет создан>`): у каждого сервиса `docker compose config` есть `healthcheck`; `helm template`: у каждого контейнера есть `readinessProbe` и `livenessProbe` (проверка через `kubeconform` не покрывает — отдельный разбор YAML); smoke: `docker compose up -d --wait` без таймаута 300 с.
- **Применимость**: deploy, tests.

### SYS-11-R12 Конфигурация и секреты по ADR-013

- **Формулировка**: монолит и все контейнеры должны получать конфигурацию и секреты только через переменные окружения: в compose — `env_file: [/opt/flt/.env, /opt/flt/.image-tag.env]` у сервисов монолита и `env_file: [/opt/flt/.env]` у инфраструктурных (на машине разработчика — `deploy/docker-compose/.env`, создаваемый `gen-secrets.sh`), без значений секретов в `environment:`; шаблон `deploy/docker-compose/.env.template` перечисляет все переменные таблицы ADR-013 §3.1 и несекретные параметры с комментариями; в Helm — `ExternalSecret` на компонент (`flt-backend`, `flt-postgres`, `flt-redis`, `flt-minio`, `flt-opensearch`, `flt-grafana`, `flt-qdrant`, `flt-livekit`) и `envFrom.secretRef` с аннотацией `reloader.stakater.com/auto: "true"`; новый секрет добавляется одновременно в таблицу ADR-013 §3.1 (через ТЗ, которое его вводит), `.env.template`, `values.yaml` (только имя) и `ExternalSecret`; файл `.env` на VPS — `/opt/flt/.env`, владелец `flt-deploy`, права `600`, в репозитории отсутствует (`.gitignore`), в образы и `docker compose config` в CI не попадает.
- **Обоснование**: ADR-013 (решение A: только env; `.env` на VPS; ESO в Kubernetes; `fake`-провайдер в kind); CLAUDE.md «Правила для Claude»: не коммитить секреты.
- **Проверка**: тест `src/tools/tests/test_env_template.py` (`<будет создан>`): множество переменных `.env.template` ⊇ переменных, читаемых `Settings` монолита (экспорт `python -m cli list-settings`) и перечисленных в таблице ADR-013; `docker compose config` не содержит строк, совпадающих с паттернами секретов `detect-secrets`; `helm template -f values-ci.yaml` содержит `ExternalSecret` для каждого компонента из перечня; `detect-secrets` и `.gitignore` (`.env`, `*.pem`, `*.key`, `deploy/**/certs/`) — ADR-011.
- **Применимость**: deploy, backend, CI.

### SYS-11-R13 Сеть и публикация портов

- **Формулировка**: наружу (на интерфейсы хоста VPS, кроме loopback) должны публиковаться только порты HAProxy `80/tcp`, `443/tcp` и с этапа 6 порты LiveKit `7881/tcp`, `7882/udp`, `3478/udp`, `5349/tcp`; на `127.0.0.1` хоста — `24224/tcp` (Fluent Bit), `8025/tcp` (Mailpit, профили `dev`, `ci`), а на стенде `local` дополнительно `5432`, `6379`, `9092`, `9000`, `9200`, `6333` для процесса на хосте (отдельный файл `docker-compose.local-ports.yml`, который `make compose-up` подключает только на `local`); все остальные порты (8000, 8001, 8404, 9090, 3000, 9187, 9121, 9308, 9100, 7880, 6789) доступны только внутри сети compose `flt` или кластера; Kafka работает без SASL (`PLAINTEXT`) только потому, что брокер недоступен за пределами сети контейнеров — порт 29092 не публикуется, в Kubernetes `NetworkPolicy` разрешает доступ к `kafka` только подам `flt-worker`, `flt-migrate`, `flt-api` (роль `api` Kafka не использует — ADR-004 — но получает доступ для `all` на `dev`), `kafka-exporter`; при первой публикации Kafka за пределы сети или появлении потребителя вне монолита включается SASL/SCRAM отдельным ADR (OQ-63); в Kubernetes namespace получает `NetworkPolicy` «default deny ingress» и явные разрешения по компонентам.
- **Обоснование**: ADR-012 §3.1 (служебные пути и порт 8000 наружу не публикуются), ADR-013 §3.1 и OQ-63 (Kafka без SASL — при условии изоляции сети, требование должно быть в SYS-11), ADR-015 §3.2 (порты LiveKit), ADR-010 (Fluent Bit на loopback), ADR-012 §3.1 (Mailpit на loopback).
- **Проверка**: тест `src/tools/tests/test_published_ports.py` (`<будет создан>`): в `docker compose config` без `docker-compose.local-ports.yml` опубликованы только порты из перечня, а loopback-порты привязаны к `127.0.0.1`; `helm template`: Service типа `LoadBalancer`/`NodePort` только у `haproxy` (и `livekit` при `enabled`), `NetworkPolicy` присутствует; smoke на VPS (чек-лист R23): `ss -tulpn` показывает только разрешённые порты; smoke `stand-n3`: `GET http://haproxy/v1/ready` не достигает монолита (ADR-012).
- **Применимость**: deploy, tests.

### SYS-11-R14 Ресурсы контейнеров

- **Формулировка**: каждый контейнер должен иметь лимиты ресурсов (`deploy.resources.limits` и `reservations` в compose, `resources.requests` и `limits` в Helm) не ниже значений таблицы (CPU в millicores, память в МиБ); процессы с управляемой кучей получают явные параметры: OpenSearch `OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g`, Kafka `KAFKA_HEAP_OPTS=-Xms512m -Xmx512m`, Redis `maxmemory 256mb` с `maxmemory-policy volatile-lru` (ADR-003), PostgreSQL `shared_buffers=256MB`, `max_connections=200`, `work_mem=8MB`, `effective_cache_size=768MB`, `shared_preload_libraries=pg_stat_statements`; uvicorn роли `api` — `--limit-concurrency 500` и `--backlog 2048`; HAProxy — `maxconn 1000` на сервер `be_api` (ADR-012 §3.5); `values-ci.yaml` вправе уменьшать requests вдвое, но не limits памяти ниже 50 % таблицы.

  | Контейнер | requests CPU / память | limits CPU / память | Примечание |
  |---|---|---|---|
  | `api` (×3) | 250 / 256 | 1000 / 512 | один процесс uvicorn без воркеров |
  | `worker` (×2) | 250 / 256 | 1000 / 768 | обработка материалов, relay outbox |
  | `migrate` | 100 / 128 | 500 / 512 | одноразовый |
  | `media-agent` (этап 6) | 500 / 512 | 2000 / 2048 | подпроцесс на комнату (ADR-015) |
  | `haproxy` (×1 на VPS, ×2 в Kubernetes) | 100 / 64 | 500 / 128 | |
  | `frontend` | 50 / 32 | 200 / 64 | статика |
  | `postgres` | 500 / 512 | 2000 / 1024 | |
  | `redis` | 100 / 64 | 500 / 320 | `maxmemory 256mb` + накладные |
  | `kafka` | 500 / 768 | 1000 / 1536 | heap 512 МиБ + page cache |
  | `minio` | 250 / 256 | 1000 / 512 | |
  | `minio-init` | 50 / 32 | 200 / 64 | одноразовый |
  | `opensearch` | 500 / 1536 | 2000 / 2048 | heap 1 ГиБ; `vm.max_map_count=262144` на хосте (R23) |
  | `qdrant` | 100 / 128 | 1000 / 512 | |
  | `prometheus` | 100 / 256 | 1000 / 512 | retention 30 d |
  | `grafana` | 50 / 128 | 500 / 256 | |
  | `fluent-bit` | 50 / 64 | 200 / 128 | файловый буфер 512 МиБ на томе |
  | `postgres-exporter`, `redis-exporter`, `kafka-exporter`, `node-exporter` | 20 / 32 каждый | 100 / 64 каждый | |
  | `cadvisor` | 50 / 64 | 200 / 128 | |
  | `mailpit`, `mock-oidc` | 20 / 32 | 200 / 128 | dev и CI |
  | `certbot`, `backup` | 50 / 64 | 500 / 256 | `backup` — на время `pg_dump` |
  | `embeddings` (этап 5) | 500 / 1024 | 2000 / 1536 | модель `multilingual-e5-small` на CPU (OQ-59) |
  | `livekit` (этап 6) | 500 / 512 | 2000 / 1024 | медиа; канал — SYS-02 |
  | `livekit-egress` (этап 6, профиль `recording`) | 1000 / 2048 | 2000 / 4096 | headless Chrome на запись (ADR-015 §3.5) |

- **Обоснование**: ADR-010 §4.2 («лимиты памяти в compose: OpenSearch 1 ГБ heap, Prometheus 512 МБ; размер VPS фиксируется в SYS-11»), ADR-003 (Redis `maxmemory`, PostgreSQL `max_connections=200`), ADR-012 §3.5 (`--limit-concurrency` задаёт SYS-11), ADR-014 §2.3; без лимитов один контейнер (OpenSearch при всплеске логов) вытесняет остальные на VPS.
- **Проверка**: тест `src/tools/tests/test_resources.py` (`<будет создан>`): у каждого сервиса compose и каждого контейнера `helm template` заданы limits памяти и CPU не ниже таблицы; `values-ci.yaml` не опускает limits памяти ниже 50 %; smoke `stand-n3` в CI проходит на runner-е 4 vCPU / 16 ГиБ с профилем без `full` (ADR-011).
- **Применимость**: deploy, CI.

### SYS-11-R15 Минимальный VPS для prod

- **Формулировка**: продуктивный VPS в РФ должен иметь не менее 6 vCPU, 16 ГиБ ОЗУ, 160 ГиБ NVMe/SSD, канал не ниже 200 Мбит/с на этапах 2–5 и 32 ГиБ ОЗУ, 8 vCPU, 320 ГиБ, канал 1 Гбит/с (SYS-02, ADR-015 §3.6) с этапа 6 (LiveKit) или с этапа 5 при включении `embeddings` и `livekit-egress` одновременно; ОС — Ubuntu Server 24.04 LTS (x86-64); swap-файл 4 ГиБ с `vm.swappiness=10` как страховка от OOM. Расчёт по таблице R14 для этапов 2–5: сумма limits памяти базового состава и профиля `prod` ≈ 10,7 ГиБ (api 1,5 + worker 1,5 + postgres 1 + kafka 1,5 + opensearch 2 + minio 0,5 + qdrant 0,5 + prometheus 0,5 + grafana 0,25 + redis 0,31 + haproxy 0,13 + frontend 0,06 + fluent-bit 0,13 + экспортёры и cadvisor 0,38 + certbot и backup 0,5), сумма requests ≈ 5,6 ГиБ; ОС, Docker и page cache PostgreSQL — ещё 3–4 ГиБ; итого 16 ГиБ с запасом 10 %; CPU: сумма requests ≈ 3,5 vCPU, пиковые limits не достигаются одновременно — 6 vCPU; диск: `postgres-data` 20, `minio-data` 50, `opensearch-data` 20 (14 суток логов по ≈ 1 ГиБ/сутки), `prometheus-data` 10, `kafka-data` 10 (retention 7 суток), образы и слои Docker 15, локальные копии бэкапов 30 — 155 ГиБ.
- **Обоснование**: OQ-07 (prod — один VPS), OQ-13 (100 одновременных пользователей, 300 WebSocket), ADR-010 §4.2 (размер VPS — SYS-11), ADR-014 §2.5 (≈ 1 ГиБ на `embeddings`), ADR-015 §3.5 (2–4 ГиБ на запись).
- **Проверка**: шаг `vps-prepare.sh` (R23) проверяет `nproc ≥ 6`, `MemTotal ≥ 15 GiB`, свободное место на `/var/lib/docker` ≥ 140 GiB и завершается ошибкой иначе; алерт `FltDiskSpaceLow` (ADR-010) при < 15 % свободного места; ревью при переходе на этап 5–6 (чек-лист GS).
- **Применимость**: deploy.

### SYS-11-R16 Тома: инстансы монолита без томов, данные — только в именованных томах

- **Формулировка**: сервисы `api`, `worker`, `migrate`, `media-agent`, `haproxy`, `frontend` не должны иметь томов для записи (compose `read_only: true` с `tmpfs: [/tmp]`; Helm `securityContext.readOnlyRootFilesystem: true` и `emptyDir` для `/tmp`), кроме `haproxy` (`haproxy-certs` только чтение, `haproxy-socket`) и `frontend` (`acme-webroot` только чтение); постоянные данные должны лежать в именованных томах compose / PVC Helm с перечнем: `postgres-data`, `kafka-data`, `minio-data`, `opensearch-data`, `qdrant-data`, `prometheus-data`, `grafana-data`, `fluent-bit-buffer`, `haproxy-certs`, `haproxy-socket`, `acme-webroot`, `letsencrypt`, `backups`, `embeddings-models` (этап 5); bind-mount каталогов хоста допускается только для конфигураций из `deploy/config/` (только чтение), `/opt/flt/.env` и системных путей `node-exporter`/`cadvisor` (только чтение).
- **Обоснование**: CLAUDE.md «Масштабирование и состояние»: «инстанс не хранит состояние… ни в файлах на диске»; `read_only` делает нарушение невозможным, а не только запрещённым; именованные тома нужны бэкапу (R18) и переносу на Kubernetes (R27).
- **Проверка**: тест `src/tools/tests/test_volumes.py` (`<будет создан>`): у перечисленных сервисов `read_only: true`, нет `volumes` с записью; множество именованных томов равно перечню; `helm template`: `readOnlyRootFilesystem: true` у контейнеров монолита, PVC для каждого тома данных; архитектурный тест SYS-05 на запись файлов в коде монолита.
- **Применимость**: deploy, tests.

### SYS-11-R17 Параметры хранилищ по стендам

- **Формулировка**: (а) PostgreSQL: одна база `flt`, схема на модуль (ADR-002), расширения `citext`, `pg_trgm`, `pg_stat_statements` создаются скриптом `deploy/docker-compose/postgres/init/` и Job Helm; роль монолита `flt_backend` (`PG_USERNAME`) с правом DDL в схемах модулей (одна роль DDL/DML — принятый риск ADR-003 с планом разделения при переходе на Kubernetes); (б) Redis: compose — один экземпляр без персистентности (`save ""`, `appendonly no`), `requirepass`; Helm — master + 1 replica + 3 sentinel (CI: 1 replica, 1 sentinel), монолит получает `REDIS_SENTINEL_HOSTS` и `REDIS_MASTER_NAME=flt` вместо `REDIS_HOST` (фабрика клиента ADR-003); LiveKit — логическая база `1` (ADR-015); (в) Kafka: compose и CI — 1 брокер KRaft, `replication.factor=1`; prod-Kubernetes — 3 брокера, `replication.factor=3`, `min.insync.replicas=2`; `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true` только на `local`, на остальных стендах топики создаёт роль `migrate` (ADR-004, SYS-04); retention событий 7 суток, DLQ 30 суток (SYS-04); (г) MinIO: standalone, `MINIO_BROWSER=off`, SSE-S3 (`MINIO_KMS_AUTO_ENCRYPTION=on`), учётная запись `flt-backend` создаётся `minio-init` (ADR-007); (д) OpenSearch: один узел с security plugin, пользователи `admin`, `fluent-bit`, `grafana`, `flt-backend`, ISM `flt-logs-retention` с `LOGS_RETENTION_DAYS=14`, порог разделения на два кластера — объём поисковых индексов > 20 ГиБ или p95 поискового запроса > 200 мс при пиковой записи логов (ADR-014 §2.3; при достижении — второй сервис `opensearch-search` и смена `OPENSEARCH_URL`); (е) Qdrant: `QDRANT__SERVICE__API_KEY` из секретов, один узел; (ж) Prometheus: `--storage.tsdb.retention.time=30d`.
- **Обоснование**: ADR-003 (PostgreSQL, Redis, Sentinel, одна роль БД), ADR-004 (брокеры и репликация), ADR-007, ADR-010 §3.1–3.2, ADR-014 §2.3 (порог разделения — «фиксируется в SYS-11»).
- **Проверка**: тест `src/tools/tests/test_storage_params.py` (`<будет создан>`): переменные и флаги командной строки сервисов в `docker compose config` и `helm template` соответствуют перечню (`KAFKA_AUTO_CREATE_TOPICS_ENABLE` отсутствует или `false` вне `local`, `--save ""`, `requirepass`, `MINIO_BROWSER=off`, `LOGS_RETENTION_DAYS`); алерты ADR-010 на размер индексов (`FltOpenSearchSearchIndicesLarge` — `<будет создан>` в `rules/`) и p95 поиска (`flt_search_latency_seconds`).
- **Применимость**: deploy, tests.

### SYS-11-R18 Резервное копирование и восстановление

- **Формулировка**: на prod должно выполняться резервное копирование контейнером `backup` (профиль `prod`; в Kubernetes — CronJob `flt-backup`) по расписанию `supercronic` ежедневно в 03:00 UTC скриптом `deploy/scripts/backup.sh`: (1) `pg_dumpall --globals-only` и `pg_dump -Fc -d flt` по сети в `/backups/postgres/flt-<YYYYMMDD>.dump`; (2) копия `grafana-data` (`grafana.db`) и файлов `/opt/flt/.env`, `/opt/flt/.image-tag.env`, зашифрованных `age` открытым ключом владельца (`BACKUP_AGE_RECIPIENT`); (3) `rclone sync` каталога `/backups` и всех бакетов `flt-*` MinIO (`rclone sync minio:flt-<bucket> remote:flt-backup/minio/flt-<bucket>`) во второе хранилище на территории РФ — S3-сервис российского облака или отдельный диск второго VPS по SFTP (конкретный `remote` задаётся переменными `RCLONE_CONFIG_REMOTE_*` при настройке VPS); (4) удаление копий старше 30 суток (`rclone delete --min-age 30d`), локальных — старше 7 суток; (5) запись метрики `flt_backup_last_success_timestamp_seconds` и `flt_backup_size_bytes{kind}` в файл textfile-коллектора `node-exporter`. Не резервируются: индексы OpenSearch (производные, перестраиваются `search reindex`), логи `flt-logs-*` (срок 14 суток), Prometheus, Redis (ADR-003), Kafka (события в полёте восстанавливаются из outbox). Целевые показатели: RPO 24 часа, RTO 4 часа; восстановление — `deploy/scripts/restore.sh <YYYYMMDD>` (останавливает `api`, `worker`; `pg_restore --clean --if-exists`; `rclone sync` обратно в MinIO; `search reindex` всех модулей; запуск); проверка восстановления на стенде `dev` — раз в квартал с записью в `deploy/docker-compose/README.md`, раздел «Журнал проверок восстановления».
- **Обоснование**: ADR-007 §3.8 (rclone, 30 суток, тот же интервал для дампа PostgreSQL, проверка раз в квартал), ADR-013 §3.2 и §3.5 (`.env` в зашифрованном бэкапе; без него не восстанавливаются ключи учеников), CLAUDE.md «152-ФЗ: хранение на территории РФ» (вторая копия тоже в РФ); RPO 24 часа и RTO 4 часа — предложение для SYS-02 (один VPS без репликации, OQ-13: нагрузка MVP).
- **Проверка**: алерт `FltBackupStale` (`time() - flt_backup_last_success_timestamp_seconds > 26*3600` — порог SYS-02-R57, `<будет создан>` в `deploy/config/prometheus/rules/`, уведомление в Telegram по ADR-010); тест `src/tools/tests/test_backup_script.py` (`<будет создан>`): `backup.sh` и `restore.sh` проходят `shellcheck`, в `backup.sh` присутствуют все пять шагов (grep по командам); интеграционный smoke в ночном job `schedule` (ADR-011): `backup.sh` в compose с `remote` = локальный каталог, затем `restore.sh` в чистый стенд и `GET /api/v1/auth/.well-known/jwks.json` 200; квартальная проверка — ручная по журналу (автоматизировать невозможно: требуется второе хранилище и человек, подтверждающий целостность).
- **Применимость**: deploy, tests.

### SYS-11-R19 Обновление без простоя

- **Формулировка**: обновление на VPS должно выполняться скриптом `deploy/scripts/deploy.sh <image_tag> [--no-migrate]` (его вызывает `deploy-vps.yml` ADR-011 §3.2 и администратор вручную) в порядке: (1) записать `FLT_IMAGE_TAG=<tag>` в `/opt/flt/.image-tag.env`; (2) `flt-compose pull`; (3) `flt-compose run --rm migrate` (миграции совместимы с предыдущей версией кода — SYS-05; при ошибке — остановка без изменения инстансов); (4) поочерёдная замена инстансов `api`, затем `worker`, затем `media-agent`: для каждого старого контейнера — `flt-compose up -d --no-deps --no-recreate --scale <role>=<N+1> <role>` (создаёт один контейнер с новым образом), ожидание его `healthy` (не дольше 120 с), затем `docker stop -t 40` и `docker rm` одного старого (HAProxy снимает его по `/v1/ready` и DNS, активным стримам даётся `SHUTDOWN_GRACE_SECONDS=30` — ADR-009, ADR-012), повтор до замены всех; (5) `flt-compose --profile prod up -d --remove-orphans --wait` для остальных сервисов (пересоздаются только те, чья конфигурация изменилась); (6) проверка через HAProxy: `GET /healthz` 200, `GET /api/v1/auth/.well-known/jwks.json` 200, три сервера `be_api` `UP`; при неуспехе — ненулевой код и подсказка `rollback.sh`. В Kubernetes: `strategy.rollingUpdate` с `maxSurge: 1`, `maxUnavailable: 0`, `terminationGracePeriodSeconds: 40`, `preStop: sleep 5` у `api`, `PodDisruptionBudget` `minAvailable: 1` для `flt-api` и `haproxy`, `helm upgrade --atomic --timeout 15m`.
- **Обоснование**: CLAUDE.md «Масштабирование и состояние»: «инстанс можно остановить в любой момент», «миграции совместимы с предыдущей версией кода: старые и новые инстансы работают одновременно»; ADR-011 §2.2 (компоновка деплоя); `docker compose up -d` без поочерёдности пересоздаёт все реплики сразу — простой.
- **Проверка**: тест `src/tools/tests/test_deploy_script.py` (`<будет создан>`): `shellcheck`, порядок шагов; smoke в ночном job `schedule`: на стенде compose с образом `A` запустить `deploy.sh B` при фоновом цикле запросов `GET /api/v1/auth/.well-known/jwks.json` через HAProxy раз в 200 мс — доля ошибок 0 % за время обновления (допускаются только повторы соединения HAProxy `retries 2`); `helm` job: `kubectl rollout status` после `helm upgrade` с изменённым `global.imageTag`.
- **Применимость**: deploy, tests.

### SYS-11-R20 Откат

- **Формулировка**: откат должен выполняться скриптом `deploy/scripts/rollback.sh` (или `deploy-vps.yml` с предыдущим `image_tag` и `run_migrations=false`), который повторяет шаги 1, 2, 4–6 R19 с предыдущим тегом из `/opt/flt/.image-tag.history` (скрипт `deploy.sh` дописывает туда каждый применённый тег с меткой времени) без обратных миграций: схема данных предыдущего релиза совместима по правилу expand/contract SYS-05, поэтому код версии N−1 работает на схеме версии N; откат данных (если релиз испортил данные) — восстановление из бэкапа R18 по процедуре RTO; в Kubernetes — `helm rollback <release> <revision>`; откат на два и более релизов назад без восстановления данных запрещён (совместимость схемы гарантируется только с предыдущим релизом).
- **Обоснование**: ADR-011 §2.2 вариант E («откат — повторный запуск с предыдущим тегом»); SYS-05 (совместимость миграций с предыдущей версией); CLAUDE.md «Миграции совместимы с предыдущей версией кода».
- **Проверка**: smoke в ночном job `schedule`: после R19 (`A` → `B`) выполнить `rollback.sh` (→ `A`) под той же фоновой нагрузкой — 0 % ошибок, `GET /v1/ready` всех инстансов 200; тест SYS-05 на совместимость миграций (старый код на новой схеме).
- **Применимость**: deploy, tests.

### SYS-11-R21 Автомасштабирование роли `api` (решает OQ-30)

- **Формулировка**: chart должен содержать шаблон `templates/api/hpa.yaml` (`autoscaling/v2`), включаемый `api.autoscaling.enabled` (по умолчанию `false`; включается в `values-prod.yaml` при переходе prod на Kubernetes), с параметрами: `minReplicas: 2`, `maxReplicas: 6`, метрика `cpu` `averageUtilization: 70`, `behavior.scaleDown.stabilizationWindowSeconds: 300`, `scaleUp.stabilizationWindowSeconds: 60`; вторая метрика — пользовательская `flt_ws_connections` (среднее на под, порог `200`, ADR-010) через `prometheus-adapter` — зафиксирована в `values-prod.example.yaml` как `api.autoscaling.wsConnectionsPerPod: 200` и включается только после установки `prometheus-adapter` при переходе (R27), до этого в HPA не участвует; роль `worker` масштабируется вручную (`worker.replicas`), KEDA по лагу consumer group — отдельным ADR при переходе; `PodDisruptionBudget` `minAvailable: 1` создаётся всегда; в compose автомасштабирования нет — число реплик фиксировано (R9).
- **Обоснование**: OQ-30 (planned → SYS-11): рекомендация «HPA по CPU для `api` (min 2, max 6), фиксированные реплики `worker`, PDB, пользовательские метрики позже» принята; prod сейчас на compose (OQ-07), поэтому включение отложено, а параметры фиксируются, чтобы шаблон проверялся в kind.
- **Проверка**: `helm template -f values-ci.yaml --set api.autoscaling.enabled=true | kubeconform`; тест `src/tools/tests/test_helm_hpa.py` (`<будет создан>`): параметры HPA равны перечисленным; `helm` job устанавливает `metrics-server` в kind и проверяет `kubectl get hpa flt-api` в состоянии без ошибок при `enabled=true` (отдельный smoke-шаг).
- **Применимость**: deploy, CI.

### SYS-11-R22 Профиль CI в kind: `values-ci.yaml`

- **Формулировка**: файл `values-ci.yaml` должен задавать: `global.stand: test`, `api.replicas: 2`, `worker.replicas: 1`, `haproxy.replicas: 1`, `haproxy.service.type: NodePort` с `nodePorts.http: 30080`, `nodePorts.https: 30443` (kind `extraPortMappings` 80→30080, 443→30443 — ADR-012 §3.6), `tls.enabled: false`, `vault.enabled: false`, `secrets.storeName: flt-fake` с тестовыми значениями `fake`-провайдера ESO (не секреты; генерируются `gen-secrets.sh --ci` в шаге job-а и подставляются `--set-file`), `opensearch.replicas: 1` с `opensearchJavaOpts: -Xms512m -Xmx512m`, `kafka.replicas: 1`, `redis.replica.count: 1`, `redis.sentinel.count: 1`, `livekit.enabled: false`, `embeddings.enabled: false`, `backup.enabled: false`, `dev.mailpit.enabled: true`, `dev.mockOidc.enabled: true`, `persistence.storageClass: standard`, requests вдвое меньше R14; smoke-проверки job `helm` — по ADR-011 §3.1 и ADR-012 §4.3 плюс `helm test` (под `tests/test-ready.yaml`: `GET haproxy/healthz` 200, `GET flt-api:8000/v1/ready` 200, `GET flt-worker:8001/v1/ready` 200).
- **Обоснование**: ADR-011 §3.1 (job `helm`: 2 реплики `flt-api`, 1 `flt-worker`, уменьшенные ресурсы, Vault выключен), ADR-013 §3.3 (`fake`-провайдер), ADR-012 §3.6 (NodePort и `extraPortMappings`).
- **Проверка**: тест `src/tools/tests/test_values_ci.py` (`<будет создан>`) сверяет ключи; job `helm` в CI устанавливает chart за ≤ 10 минут (`--timeout 10m`).
- **Применимость**: deploy, CI.

### SYS-11-R23 Продуктивный VPS: подготовка и защита (учитывает OQ-07)

- **Формулировка**: VPS должен готовиться идемпотентным скриптом `deploy/scripts/vps-prepare.sh` и чек-листом в `deploy/docker-compose/README.md`, включающими: (1) Ubuntu Server 24.04 LTS, часовой пояс хоста `UTC`, `chrony`; (2) Docker Engine последней стабильной линии с плагином Compose v2, `/etc/docker/daemon.json`: `{"live-restore": true, "log-driver": "json-file", "log-opts": {"max-size": "50m", "max-file": "3"}}` (драйвер `fluentd` задаётся в compose; `json-file` — для контейнеров вне compose и dual logging); (3) пользователи: администратор (владелец платформы) с `sudo` и `flt-deploy` без `sudo`, с единственным правилом sudoers `flt-deploy ALL=(root) NOPASSWD: /usr/local/bin/flt-compose` — обёртка `deploy/scripts/flt-compose.sh`, которая выполняет `docker compose --project-name flt --project-directory /opt/flt/deploy/docker-compose --env-file /opt/flt/.env "$@"` и не принимает иных путей (прямое членство `flt-deploy` в группе `docker` запрещено — это эквивалент root); (4) каталоги `/opt/flt/{deploy,backups}` и файлы `/opt/flt/.env` (`600`, владелец `flt-deploy`, создаётся `gen-secrets.sh`), `/opt/flt/.image-tag.env`; (5) SSH: только ключи (`PasswordAuthentication no`, `PermitRootLogin no`, `AllowUsers <admin> flt-deploy`), `fail2ban` с jail `sshd`; (6) `ufw`: `default deny incoming`, `allow 22/tcp`, `allow 80/tcp`, `allow 443/tcp`, с этапа 6 — `7881/tcp`, `7882/udp`, `3478/udp`, `5349/tcp`; Docker публикует порты в обход `ufw`, поэтому R13 обязателен и проверяется `ss -tulpn`; (7) `unattended-upgrades` только для security-обновлений ОС; обновления Docker — вручную в окно обслуживания; (8) `sysctl`: `vm.max_map_count=262144`, `vm.swappiness=10`, `net.core.somaxconn=4096`, `fs.inotify.max_user_instances=512`; swap-файл 4 ГиБ (R15); (9) шифрование диска: зашифрованный том провайдера или LUKS для `/var/lib/docker` и `/opt/flt` (ADR-007 §3.9: «обязанность оператора»); если провайдер не предоставляет ни того, ни другого — запись исключения в раздел 6 этой спецификации с решением пользователя; (10) systemd unit `/etc/systemd/system/flt.service`: `After=docker.service network-online.target`, `Type=oneshot`, `RemainAfterExit=yes`, `ExecStart=/usr/local/bin/flt-compose --profile prod up -d --wait --remove-orphans`, `ExecStop=/usr/local/bin/flt-compose --profile prod stop`, `WantedBy=multi-user.target`; (11) `docker login ghcr.io` при приватном репозитории (OQ-39, ADR-013); (12) первый выпуск сертификата `tls-bootstrap.sh` после появления домена (OQ-08); (13) доступ к Grafana, stats HAProxy и Mailpit — только через SSH-туннель (`ssh -L 3000:127.0.0.1:3000`), на хосте порты не публикуются (R13 — Grafana 3000 во внутренней сети, доступ `docker compose exec`/туннель через `socat`-сервис профиля `prod` на `127.0.0.1:3000`).
- **Обоснование**: OQ-07 (prod — docker-compose на VPS в РФ), ADR-011 §3.2 и §4.3 (пользователь `flt-deploy`, доступ только к `docker compose` в `/opt/flt`, VPS готовит человек по чек-листу SYS-11), ADR-013 §3.2 и §4.2 (`.env` `600`, SSH только по ключу, доступ к Docker-сокету = доступ к секретам), ADR-012 §3.7 (stats через SSH-туннель), ADR-007 §3.9 (шифрование диска), ADR-014 (`vm.max_map_count` для OpenSearch).
- **Проверка**: `vps-prepare.sh --check` возвращает ненулевой код при любом невыполненном пункте (sshd-конфиг, ufw-статус, sudoers, права `.env`, sysctl, наличие unit-а, `ss -tulpn` только разрешённые порты); `shellcheck` в CI; тест `src/tools/tests/test_vps_prepare.py` (`<будет создан>`) на функции разбора; выполнение чек-листа подтверждает пользователь перед первым деплоем (гейт этапа 2, ручной шаг — автоматизация невозможна без доступа CI к VPS с правами администратора).
- **Применимость**: deploy.

### SYS-11-R24 TLS и сертификаты по стендам

- **Формулировка**: TLS должен завершаться только на HAProxy (исключение — TURN/TLS 5349 LiveKit с тем же сертификатом с тома только чтение, ADR-015); на `prod` сертификат выпускает контейнер `certbot` (webroot `acme-webroot`, `certbot renew` каждые 12 часов, deploy-hook собирает `.pem` в `haproxy-certs` и загружает через runtime API по сокету `haproxy-socket` — ADR-012 §3.3), переменная `FLT_TLS_DOMAIN` включает ветку `fe_https`; на `dev` и `test` `FLT_TLS_DOMAIN` не задан — HAProxy слушает `:80` и `:8080`, HSTS не выставляется, самоподписанные сертификаты не используются; в Kubernetes — `tls.certManager.enabled` создаёт `Certificate` (`ClusterIssuer` Let's Encrypt HTTP-01, Secret `flt-tls`), который монтируется в под HAProxy, обновление подхватывает Reloader; приватный ключ никогда не попадает в `.env`, `values` и репозиторий.
- **Обоснование**: ADR-012 §3.3, ADR-013 §3.1 (ключ TLS — файл на томе), ADR-015 §3.2.
- **Проверка**: `haproxy -c` с заданным `FLT_TLS_DOMAIN` и тестовым `.pem` в job `helm`/`stand-n3` (ADR-012 §3.3); тест `src/tools/tests/test_tls_layout.py` (`<будет создан>`): `certbot` только в профиле `prod`, тома `haproxy-certs`/`acme-webroot`/`haproxy-socket` смонтированы в нужные сервисы с нужными режимами; алерт на срок действия сертификата — blackbox-exporter добавляется при появлении TLS на prod (ADR-012 §4.2; этап 2; строка в R4 добавляется `changed`-версией).
- **Применимость**: deploy, tests.

### SYS-11-R25 Логи и метрики инфраструктуры

- **Формулировка**: каждый сервис compose должен использовать якорь `x-logging: &flt-logging` (драйвер `fluentd`, `fluentd-address: 127.0.0.1:24224`, `fluentd-async: "true"`, `fluentd-buffer-limit: "8m"`, `tag: "flt.{{.Name}}"` — ADR-010 §3.2) кроме самого `fluent-bit` (`json-file`); Prometheus должен собирать метрики со всех инстансов монолита (`dns_sd_configs` по сервисам `api`, `worker`, `media-agent`; в Kubernetes — аннотации `prometheus.io/scrape|path|port` на подах) и со всех контейнеров таблицы R4, у которых есть эндпоинт метрик (HAProxy 8404, MinIO `/minio/v2/metrics/cluster`, OpenSearch, Qdrant 6333, экспортёры, `cadvisor`, `node-exporter`, LiveKit 6789); параметры `LOGS_RETENTION_DAYS=14`, `PROMETHEUS_RETENTION=30d` задаются в `.env.template` и `values.yaml`; дашборды и алерты из `deploy/config/grafana/` поставляются в оба варианта без изменений (R2).
- **Обоснование**: CLAUDE.md «Наблюдаемость»; ADR-010 §3.1–3.2, §3.5 (контейнеры наблюдаемости, параметр `LOGS_RETENTION_DAYS`, тома).
- **Проверка**: тест `src/tools/tests/test_logging_anchor.py` (`<будет создан>`): у всех сервисов, кроме `fluent-bit`, `logging.driver == fluentd` в `docker compose config`; smoke Г.8/Г.9 (ADR-010 §4.3): после `--scale api=3` три цели `flt-api` и две `flt-worker` в состоянии `up`, запись с `request_id` из E2E находится в OpenSearch через API Grafana; `promtool check config` и `promtool check rules` в job `helm`.
- **Применимость**: deploy, CI.

### SYS-11-R26 Smoke-тесты развёртывания в CI

- **Формулировка**: изменение любого файла в `deploy/` должно запускать job-ы `stand-n3` и `helm` (фильтр путей `deploy` в ADR-011 §3.1), которые выполняют, помимо тестов SYS-10, smoke-проверки развёртывания: `docker compose config` без предупреждений; `up -d --wait` базового состава (CI — без `full`) за ≤ 300 с; `flt-tools deploy parity`, `check-config`, тесты `src/tools/tests/test_*` из этой спецификации; проверки ADR-012 §4.3 (три `UP`, `DOWN` после остановки, служебные пути снаружи недостижимы, `GET /api/docs` 404, `GET /flt-materials/` 403, 429 после лимита, `X-Request-ID`); ADR-007 §3.5 (бакеты созданы, анонимный GET 403); ADR-014 §3 п. 7 (тестовый шаблон индекса и коллекция); ADR-010 §4.3 (цели Prometheus, запись в OpenSearch); `helm lint`, `kubeconform -strict`, `helm install --wait`, `helm test`, `kubectl rollout status`; ночной job `schedule` дополнительно: полный состав `--profile ci --profile full`, `backup.sh`/`restore.sh` (R18), `deploy.sh`/`rollback.sh` под нагрузкой (R19, R20).
- **Обоснование**: критерий выхода этапа 1: «система в полном составе контейнеров разворачивается одной командой обоими способами»; ADR-011 (структура job-ов, фильтры путей, ночной прогон полного состава).
- **Проверка**: `ci.yml` содержит перечисленные шаги (проверка `actionlint` и ревью SYS-12); негативный тест в Г.8: PR, ломающий `healthcheck` сервиса, краснит `stand-n3`.
- **Применимость**: CI, tests.

### SYS-11-R27 Переход prod на Kubernetes: критерии и шаги

- **Формулировка**: переход продуктива с compose на Kubernetes должен инициироваться новым ADR при наступлении любого из условий: (а) средняя загрузка CPU VPS > 70 % или сумма requests памяти > 75 % ОЗУ в течение 7 суток после увеличения VPS до 32 ГиБ; (б) более 300 одновременных WebSocket-соединений (потолок OQ-13) ежедневно дольше часа в течение недели; (в) SYS-02 требует RTO < 1 часа или доступность, недостижимую на одном узле; (г) этап 6 требует отдельный узел для LiveKit по пропускной способности (ADR-015 §3.6); (д) третий инцидент за квартал, вызванный обновлением на одном узле. Кластер должен удовлетворять требованиям: поддерживаемая минорная версия Kubernetes, шифрование Secret в etcd (`EncryptionConfiguration`, ADR-013), RBAC с минимальными правами и отдельными ServiceAccount на компонент, `NetworkPolicy` default-deny (R13), StorageClass RWO на SSD с поддержкой snapshot, LoadBalancer с UDP (LiveKit) или `hostNetwork` для медиапортов, `cert-manager`, `metrics-server` (HPA R21), `prometheus-adapter` (пользовательские метрики R21), процедура unseal и бэкапа Vault (OQ-61), ресурсы узлов не ниже R15 × 1,3; шаги перехода: (1) выбор провайдера и размещения стендов (OQ-07 пункты а, в, г); (2) кластер и предпосылки; (3) `values-prod.yaml` из `values-prod.example.yaml`, Vault с реальными секретами из `/opt/flt/.env`, ESO; (4) стенд `flt-test` в кластере: E2E, тесты N инстансов и нагрузочные через LoadBalancer; (5) окно обслуживания: остановка `worker`, финальный `backup.sh`, `pg_restore` в PostgreSQL кластера, `rclone sync` бакетов, `search reindex`, `migrate`; (6) переключение DNS (TTL заранее снижен до 300 с), compose на VPS сохраняется 7 суток как путь отката; (7) смена `secrets`/`backup` исключений паритета и обновление CLAUDE.md «Развёртывание».
- **Обоснование**: OQ-07 (resolved): «переход на Kubernetes — отдельным решением при росте нагрузки»; ADR-013 §3.3 и §4.2, ADR-012 §3.3 и §3.6, ADR-003 (операторы, PgBouncer — при переходе), OQ-61 (deferred до перехода).
- **Проверка**: критерии (а)–(б) — алерты `FltVpsCpuSaturated` и `FltWsConnectionsHigh` (`<будут созданы>` в `deploy/config/prometheus/rules/` на этапе 2) с длительностью 7 суток; (в)–(д) — решение человека на гейте GS; шаги — чек-лист нового ADR.
- **Применимость**: deploy.

### SYS-11-R28 Имя проекта, сети и контейнеров

- **Формулировка**: проект compose должен называться `flt` (`name: flt` в файле и `--project-name flt` в обёртке), все сервисы — в одной пользовательской сети `flt` (bridge) с включённым внутренним DNS; имена контейнеров — автоматические `flt-<service>-<n>` (поле `container_name` запрещено, иначе `--scale` невозможен); в Kubernetes все ресурсы получают метки `app.kubernetes.io/name: flt`, `app.kubernetes.io/component: <component>`, `app.kubernetes.io/part-of: flt`, `app.kubernetes.io/version: <imageTag>`; все контейнеры работают с `TZ=UTC`.
- **Обоснование**: ADR-011 §3.1 (остановка контейнера `flt-api-2` в тестах), ADR-012 §3.6 (DNS compose для `server-template`), ADR-010 (`instance_id = HOSTNAME`), SYS-07 R21 (время в UTC).
- **Проверка**: тест `src/tools/tests/test_compose_naming.py` (`<будет создан>`): `name: flt`, нет `container_name`, одна сеть; `helm template`: метки на всех ресурсах (`kubeconform` плюс разбор); smoke: `docker compose -p flt stop flt-api-2` в `stand-n3` (SYS-10).
- **Применимость**: deploy, tests.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| все | переменные настроек модуля с префиксом `<MODULE>_` (ADR-002) добавляются в `.env.template` и `values.yaml` одновременно; новый секрет — таблица ADR-013 §3.1 + `.env.template` + `ExternalSecret`; новый топик, бакет, индекс — создаёт роль `migrate`, контейнеры не меняются; новый контейнер — только через `changed`-версию SYS-11 и CLAUDE.md |
| shared kernel | `configs/stands.py` — четыре стенда R3; `APP_ROLE`, `WORKER_HTTP_PORT`, `MIGRATE_ON_START`, `FORWARDED_ALLOW_IPS`, `SHUTDOWN_GRACE_SECONDS`; фабрика Redis standalone/Sentinel (ADR-003); команда `python -m cli list-settings` для теста R12; readiness по ролям (ADR-010) |
| `identity`, `llm_gateway` (этап 1) | переменные `IDENTITY_*`, `LLM_GATEWAY_*` в `envs/<stand>/` и `.env.template`; секреты по ADR-013 |
| `classroom` (этап 6) | `LIVEKIT_HOST`, порты LiveKit в R13, профиль `recording`, Redis база `1` |
| `materials`, `llm_gateway` (этап 5) | контейнер `embeddings` при решении OQ-59, `EMBEDDINGS_URL` |
| `src/tools` (`flt_tools`) | подкоманды `deploy sync-config`, `deploy check-config`, `deploy parity`; тесты `src/tools/tests/test_*` из раздела 3 |
| frontend | образ `flt-frontend` (ADR-005 §3.8), `frontend.conf` из `deploy/config/nginx/`; переменные сборки не зависят от стенда |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| Контракты | новые переменные окружения и секреты фичи перечисляются таблицей «переменная — секрет/конфигурация — стенды — значение по умолчанию»; секреты ссылаются на строку таблицы ADR-013 §3.1 |
| Состояние и масштабируемость | указать, нужны ли фиче новые тома, топики, бакеты, индексы (создаёт `migrate`) и влияет ли она на ресурсы R14 (например, новый тип фонового задания — лимит памяти `worker`) |
| Нефункциональные требования и граничные случаи | поведение фичи при поочерёдном обновлении инстансов (R19): совместимость API между версиями N−1 и N, двухшаговая раскатка смены активного ключа (ADR-013 §3.4) |
| Вне рамок / Definition of Done | пункт «docker-compose и Helm обновлены одновременно, `flt-tools deploy parity` зелёный» обязателен, если фича затрагивает развёртывание |

## 5. Примеры

### Пример 1. Фрагмент `docker-compose.yml`: якоря, роли монолита, профили (SYS-11-R5, SYS-11-R9, SYS-11-R10, SYS-11-R16, SYS-11-R25)

```yaml
name: flt

x-logging: &flt-logging
  driver: fluentd
  options:
    fluentd-address: "127.0.0.1:24224"
    fluentd-async: "true"
    fluentd-buffer-limit: "8m"
    tag: "flt.{{.Name}}"

x-backend: &flt-backend
  image: ghcr.io/alextaralexander/flt/backend:${FLT_IMAGE_TAG:-local}
  build:
    context: ../../src/backend/py-monolyth
    additional_contexts: { py-main-lib: ../../src/backend/py-main-lib }
  env_file: [.env, .image-tag.env]
  environment:
    STAND_NAME: ${STAND_NAME:-dev}
    TZ: UTC
  read_only: true
  tmpfs: [/tmp]
  logging: *flt-logging
  networks: [flt]
  depends_on:
    fluent-bit: { condition: service_started }
    migrate: { condition: service_completed_successfully }

services:
  migrate:
    <<: *flt-backend
    environment: { APP_ROLE: migrate, STAND_NAME: ${STAND_NAME:-dev}, TZ: UTC }
    restart: "no"
    depends_on:
      fluent-bit: { condition: service_started }
      postgres: { condition: service_healthy }
      kafka: { condition: service_healthy }
      minio-init: { condition: service_completed_successfully }
      opensearch: { condition: service_healthy }
      qdrant: { condition: service_healthy }
    deploy: { resources: { limits: { cpus: "0.5", memory: 512M } } }

  api:
    <<: *flt-backend
    environment: { APP_ROLE: api, STAND_NAME: ${STAND_NAME:-dev}, TZ: UTC }
    expose: ["8000"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8000/v1/ready"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 30s
    deploy:
      replicas: 3
      resources: { limits: { cpus: "1", memory: 512M }, reservations: { cpus: "0.25", memory: 256M } }

  worker:
    <<: *flt-backend
    environment: { APP_ROLE: worker, STAND_NAME: ${STAND_NAME:-dev}, TZ: UTC, WORKER_HTTP_PORT: "8001" }
    expose: ["8001"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8001/v1/ready"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 30s
    deploy:
      replicas: 2
      resources: { limits: { cpus: "1", memory: 768M }, reservations: { cpus: "0.25", memory: 256M } }

  haproxy:
    image: haproxy:3.2-alpine
    ports: ["80:80", "443:443"]
    environment: { API_HOST: api, FRONTEND_HOST: frontend, MINIO_HOST: minio, FLT_TLS_DOMAIN: "${FLT_TLS_DOMAIN:-}", TZ: UTC }
    volumes:
      - ../config/haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
      - haproxy-certs:/etc/haproxy/certs:ro
      - haproxy-socket:/var/run/haproxy
    depends_on:
      api: { condition: service_healthy }
      frontend: { condition: service_healthy }
    logging: *flt-logging
    networks: [flt]

  mailpit:
    image: axllent/mailpit:v1.27
    profiles: [dev, ci]
    ports: ["127.0.0.1:8025:8025"]
    logging: *flt-logging
    networks: [flt]

  certbot:
    build: ./certbot
    image: flt-certbot:local
    profiles: [prod]
    volumes:
      - acme-webroot:/var/www/acme
      - letsencrypt:/etc/letsencrypt
      - haproxy-certs:/etc/haproxy/certs
      - haproxy-socket:/var/run/haproxy
    logging: *flt-logging
    networks: [flt]

networks:
  flt: {}

volumes:
  postgres-data: {}
  kafka-data: {}
  minio-data: {}
  opensearch-data: {}
  qdrant-data: {}
  prometheus-data: {}
  grafana-data: {}
  fluent-bit-buffer: {}
  haproxy-certs: {}
  haproxy-socket: {}
  acme-webroot: {}
  letsencrypt: {}
  backups: {}
```

Неправильно: `container_name: flt-api` (ломает `--scale`), `environment: { PG_PASSWORD: secret }` (секрет вне `.env`), `ports: ["8000:8000"]` у `api` (нарушает R13), `volumes: [./uploads:/data]` у `api` (нарушает R16).

### Пример 2. Фрагмент `values.yaml` и `values-ci.yaml` (SYS-11-R6, SYS-11-R7, SYS-11-R21, SYS-11-R22)

```yaml
# deploy/helm/flt/values.yaml (фрагмент)
global:
  stand: prod
  imageTag: stage-1              # теги образов FLT; инфраструктурные — ниже, по одному разу
  imageRegistry: ghcr.io/alextaralexander/flt

api:
  replicas: 2
  image: { repository: backend }     # <imageRegistry>/<repository>:<imageTag>
  resources:
    requests: { cpu: 250m, memory: 256Mi }
    limits: { cpu: 1000m, memory: 512Mi }
  autoscaling:
    enabled: false
    minReplicas: 2
    maxReplicas: 6
    targetCPUUtilizationPercentage: 70
    wsConnectionsPerPod: 200         # используется только при установленном prometheus-adapter (R27)
  pdb: { minAvailable: 1 }
  terminationGracePeriodSeconds: 40

worker:
  replicas: 2
  resources:
    requests: { cpu: 250m, memory: 256Mi }
    limits: { cpu: 1000m, memory: 768Mi }

haproxy:
  replicas: 2
  image: { repository: haproxy, tag: 3.2-alpine }
  service: { type: LoadBalancer }
  pdb: { minAvailable: 1 }

postgres:
  image: { repository: postgres, tag: 18-alpine }
  persistence: { size: 20Gi }
  config: { shared_buffers: 256MB, max_connections: 200 }

redis:
  image: { repository: redis, tag: 8-alpine }
  replica: { count: 1 }
  sentinel: { count: 3, masterName: flt }
  maxmemory: 256mb

kafka:
  image: { repository: apache/kafka, tag: 4.1.0 }
  replicas: 3
  replicationFactor: 3

minio:
  image: { repository: minio/minio, tag: RELEASE.2025-10-15T17-29-55Z }   # OQ-64
  persistence: { size: 50Gi }

opensearch:                        # зависимость opensearch-project/opensearch
  enabled: true
  image: { repository: ghcr.io/alextaralexander/flt/opensearch, tag: 3.2 }
  replicas: 3
  opensearchJavaOpts: "-Xms1g -Xmx1g"

secrets:
  storeName: flt-vault             # ClusterSecretStore (ADR-013)

tls: { enabled: true, certManager: { enabled: true, clusterIssuer: letsencrypt } }
vault: { enabled: true }
livekit: { enabled: false, egress: { enabled: false } }
embeddings: { enabled: false }
backup: { enabled: true, schedule: "0 3 * * *", retentionDays: 30 }
dev: { mailpit: { enabled: false }, mockOidc: { enabled: false } }
logs: { retentionDays: 14 }
prometheus: { retention: 30d }
```

```yaml
# deploy/helm/flt/values-ci.yaml (фрагмент)
global: { stand: test }
api: { replicas: 2, resources: { requests: { cpu: 125m, memory: 128Mi } } }
worker: { replicas: 1 }
haproxy:
  replicas: 1
  service: { type: NodePort, nodePorts: { http: 30080, https: 30443 } }
tls: { enabled: false, certManager: { enabled: false } }
vault: { enabled: false }
secrets: { storeName: flt-fake }   # данные fake-провайдера подставляет job через --set-file
opensearch: { replicas: 1, opensearchJavaOpts: "-Xms512m -Xmx512m" }
kafka: { replicas: 1, replicationFactor: 1 }
redis: { replica: { count: 1 }, sentinel: { count: 1 } }
backup: { enabled: false }
dev: { mailpit: { enabled: true }, mockOidc: { enabled: true } }
persistence: { storageClass: standard }
```

### Пример 3. Файл исключений паритета (SYS-11-R8)

```yaml
# deploy/parity-exceptions.yaml
- component: vault
  aspect: presence
  reason: "Vault только в Kubernetes (CLAUDE.md «Развёртывание»)"
  adr: ADR-013
- component: external-secrets
  aspect: presence
  reason: "В compose секреты из .env"
  adr: ADR-013
- component: reloader
  aspect: presence
  reason: "Перезапуск при смене секрета в compose делает deploy.sh"
  adr: ADR-013
- component: redis
  aspect: replicas
  reason: "Sentinel и реплика только в Kubernetes"
  adr: ADR-003
- component: certbot
  aspect: presence
  reason: "В Kubernetes сертификаты выпускает cert-manager"
  adr: ADR-012
- component: cadvisor
  aspect: presence
  reason: "Метрики контейнеров в Kubernetes отдаёт kubelet"
  adr: ADR-010
- component: fluent-bit
  aspect: config-files
  reason: "input-compose.conf против input-kubernetes.conf"
  adr: ADR-010
- component: kafka
  aspect: replicas
  reason: "1 брокер в compose и CI, 3 в prod-Kubernetes"
  adr: ADR-004
```

### Пример 4. Поочерёдная замена инстансов в `deploy.sh` (SYS-11-R19)

```bash
rolling_replace() {            # $1 — сервис (api|worker|media-agent), $2 — целевое число реплик
  local svc="$1" n="$2" new_image
  new_image="$(flt-compose config --images | grep "^${svc} " | awk '{print $2}')"
  for old in $(docker ps -q --filter "label=com.docker.compose.project=flt" --filter "label=com.docker.compose.service=${svc}"); do
    [ "$(docker inspect -f '{{.Config.Image}}' "$old")" = "$new_image" ] && continue
    flt-compose up -d --no-deps --no-recreate --scale "${svc}=$((n + 1))" "$svc"
    wait_healthy_new "$svc" "$new_image" 120          # ожидание healthy у контейнера с новым образом
    docker stop -t 40 "$old" && docker rm "$old"       # SIGTERM → SHUTDOWN_GRACE_SECONDS=30 → выход
  done
  flt-compose up -d --no-deps --scale "${svc}=${n}" "$svc"
}

flt-compose pull
[ "$NO_MIGRATE" = 1 ] || flt-compose run --rm migrate
rolling_replace api 3
rolling_replace worker 2
flt-compose --profile prod up -d --remove-orphans --wait
verify_through_haproxy        # /healthz 200, jwks 200, 3× be_api UP
```

## 6. Исключения и как их согласовать

Порядок: 1) вопрос в `Analytics/open-questions.md` с обоснованием; 2) решение человека; 3) строка в таблице ниже; 4) запись в `deploy/parity-exceptions.yaml` (для R8) или allowlist теста `src/tools/tests/` со ссылкой на строку. Исключение без записи — нарушение. Стартовые исключения паритета перечислены в примере 3 и вытекают из принятых ADR.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-11-R4, SYS-11-R8 | `vault`, `external-secrets`, `reloader`, `redis` (replica, sentinel), `certbot`, `cadvisor`, `fluent-bit` (input), `kafka` (число брокеров) | различия, предписанные CLAUDE.md «Развёртывание» и ADR-003, ADR-010, ADR-012, ADR-013 | бессрочно | фиксируется при утверждении этой спецификации |
| SYS-11-R7 | образы `minio/minio`, `minio/mc` | образы community-редакции не публикуются; зафиксированный тег до решения OQ-64 | до решения OQ-64 (этап 2) | пользователь, 2026-10-10 (ADR-007 §3.10) |
| SYS-11-R23 п. 9 | шифрование диска VPS | заполняется, если провайдер не даёт зашифрованный том и LUKS невозможен | до смены провайдера | — |

## 7. Вне рамок

- Состав job-ов CI, обязательные проверки, бюджет минут, self-hosted runner — SYS-12 и ADR-011; здесь — только smoke-проверки развёртывания и инструменты `flt-tools deploy`.
- Методика тестов на N инстансов (маркеры, остановка контейнера, фикстуры) — SYS-10; совместимость миграций и правило expand/contract — SYS-05.
- Конфигурация HAProxy по существу (маршруты, ACL, таймауты) — ADR-012; CSP и `frontend.conf` — ADR-005.
- Перечень секретов и их ротация — ADR-013 (таблица §3.1 наследуется, SYS-11 не копирует её); сроки ротации — SYS-02.
- Нормативы RPO/RTO как бизнес-требование, срок хранения логов и IP-адресов — SYS-02 (здесь предложены значения R18 для согласования).
- Распределённый режим MinIO, операторы PostgreSQL и Kafka, PgBouncer, несколько узлов LiveKit, разделение кластера OpenSearch — отдельные ADR при переходе prod на Kubernetes или достижении порогов (R17 д, R27).
- Выбор провайдера VPS, домена (OQ-08), SMTP-сервиса (OQ-11) и второго хранилища для бэкапов — решения пользователя при настройке VPS.
- Сборка и подпись локального агента — ADR-008, ADR-011 (`agent-release.yml`).

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-001](../../ADR/ADR-001-tech-stack.md) | основан на | минорные теги образов, одинаковые в compose и Helm; Renovate обновляет оба; исключение MinIO |
| [ADR-003](../../ADR/ADR-003-state-storage.md) | основан на | PostgreSQL `max_connections=200`, Redis `maxmemory`/`volatile-lru` без персистентности, Sentinel в Helm, одна роль БД, PgBouncer по порогу |
| [ADR-004](../../ADR/ADR-004-communication-patterns.md) | основан на | роли `api`, `worker`, `all`, `migrate`, `media_agent`; порты 8000/8001; `service_completed_successfully`; Job `pre-install,pre-upgrade`; брокеры и `replication.factor`; `terminationGracePeriodSeconds=40`; закрывает OQ-17 в части развёртывания |
| [ADR-005](../../ADR/ADR-005-frontend-stack.md) | основан на | образ `flt-frontend` на `nginx-unprivileged`, порт 8080, `/healthz`, `frontend.conf` |
| [ADR-007](../../ADR/ADR-007-file-storage.md) | основан на | MinIO standalone и собственный StatefulSet, `minio-init`, SSE-S3, порт 9000 внутри, бэкап `rclone` 30 суток, образ с зафиксированным тегом (OQ-64) |
| [ADR-010](../../ADR/ADR-010-observability-stack.md) | основан на | контейнеры наблюдаемости и экспортёры, log driver `fluentd`, `dns_sd_configs`, пути `deploy/config/`, параметры probes и healthcheck, `LOGS_RETENTION_DAYS`, retention Prometheus |
| [ADR-011](../../ADR/ADR-011-ci-cd.md) | основан на | `docker-compose.ci.yml`, `values-ci.yaml`, job-ы `stand-n3` и `helm`, `deploy-vps.yml`, `.image-tag.env`, пользователь `flt-deploy`, `src/tools` и `deploy/scripts` |
| [ADR-012](../../ADR/ADR-012-haproxy-entry-point.md) | основан на | HAProxy как единственный публичный порт, certbot и runtime API, `FLT_TLS_DOMAIN`, headless Service `flt-api`, NodePort 30080/30443 в kind, stats через SSH-туннель |
| [ADR-013](../../ADR/ADR-013-secrets-management.md) | основан на | `.env` на VPS (`600`, `gen-secrets.sh`), `env_file`, ESO + Vault + Reloader, `fake`-провайдер в CI, бэкап `.env` с `age`, шифрование etcd при переходе |
| [ADR-014](../../ADR/ADR-014-search-engines.md) | основан на | образ `flt-opensearch` с плагинами, один кластер с порогом разделения, Qdrant с API-ключом, контейнер `embeddings` (OQ-59) |
| [ADR-015](../../ADR/ADR-015-media-server.md) | основан на | контейнеры `livekit`, `livekit-egress`, порты 7881/7882/3478/5349, профиль `recording`, `livekit.yaml`, Redis база `1`, роль `media_agent` |
| [ADR-009](../../ADR/ADR-009-llm-streaming-and-voice.md) | уточняет | `SHUTDOWN_GRACE_SECONDS=30` в процедуре поочерёдной замены инстансов |
| [ADR-008](../../ADR/ADR-008-local-agent.md) | уточняет | бакет `flt-local-runtime` создаёт `storage-init`; дистрибутивы агента развёртыванием не затрагиваются |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-28](../../open-questions.md) | Структура Helm charts | да | planned → решает SYS-11 (R6): umbrella chart `flt`, собственные шаблоны для компонентов FLT, PostgreSQL, Redis, Kafka, MinIO; официальные chart-ы поставщиков для остального; без Bitnami и операторов |
| [OQ-29](../../open-questions.md) | Общие конфигурации в `deploy/config/` | да | planned → решает SYS-11 (R2): один источник, переменные окружения для различий, копия в `files/config/` chart-а скриптом `flt-tools deploy sync-config` с проверкой в CI |
| [OQ-30](../../open-questions.md) | Автомасштабирование монолита (HPA) | да | planned → решает SYS-11 (R21): HPA `api` по CPU 70 %, 2–6 реплик, шаблон выключен до перехода prod на Kubernetes; метрика `flt_ws_connections` 200 на под через prometheus-adapter при переходе; `worker` — вручную, KEDA отдельным ADR |
| [OQ-17](../../open-questions.md) | Роли запуска монолита | нет | planned → ADR-004 (принят); SYS-11 R9 закрывает часть «реплики по стендам» |
| [OQ-11](../../open-questions.md) | Mailpit как dev-only сервис | нет | resolved; принцип зафиксирован в R5 |
| [OQ-07](../../open-questions.md) | Среда продуктива | нет | resolved; VPS — R15, R23; переход — R27 |
| [OQ-63](../../open-questions.md) | Kafka без SASL во внутренней сети | нет | planned → ADR-013 (принят: без SASL); требование изоляции сети — R13 |
| [OQ-64](../../open-questions.md) | Сервер хранилища для prod (MinIO) | нет (блокирует prod-VPS, этап 2) | open; R4 и R7 используют зафиксированный тег до решения; замена образа — правка `docker-compose.yml`, `values.yaml`, `minio-init` |
| [OQ-61](../../open-questions.md) | Unseal-ключи и бэкап Vault | нет | deferred до перехода на Kubernetes (R27) |
| [OQ-59](../../open-questions.md) | Контейнер `embeddings` | нет | planned → ТЗ STU-27, SYS-08; строка R4 и лимит R14 зарезервированы |
| [OQ-60](../../open-questions.md) | Канал алертов Grafana | нет | resolved в ADR-010 (Telegram); секреты — ADR-013, provisioning — `deploy/config/grafana/provisioning/alerting/` |
| [OQ-08](../../open-questions.md) | Домен prod | нет | deferred; TLS на prod включается `FLT_TLS_DOMAIN` после выбора (R24) |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
