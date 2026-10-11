# CLAUDE.md — Foreign Language Trainer (FLT)

Инструкции для Claude при работе с этим репозиторием.

## О проекте

FLT — платформа для изучения иностранных языков с помощью LLM (внешних: OpenAI, Claude, YandexGPT, GigaChat и др.; локальных: llama.cpp, LM Studio).
Модель платформы используется только в быстром тесте без регистрации (какая LLM пишет публикации персонажа в каналах продвижения — OQ-58, решается в ТЗ ADM-06). Для обучения ученик подключает свою внешнюю или локальную модель.
Модель платформы — российский провайдер (YandexGPT или GigaChat) через OpenAI-совместимый адаптер; лимиты быстрого теста — параметры конфигурации (стартово: сессия до 20 сообщений и 15 минут, 3 теста в сутки с одного IP, 2 млн токенов в сутки на всю платформу; значения уточняются после запуска), состояние теста — в Redis с TTL 24 ч, при исчерпании лимита предлагается ввести свой ключ, который не сохраняется (OQ-09).
Все курсы бесплатные, платежей на платформе нет. Ученик может состоять в нескольких классах и курсах.
Название в коде, именах сервисов, префиксах и ключах i18n — `flt` навсегда; отображаемое название — параметр конфигурации `APP_NAME` и ключ i18n; домен — параметр конфигурации, в dev — `flt.localhost`; бренд и домен выбираются до начала этапа 2 (OQ-08).
Полные бизнес-требования: [Analytics/BRD/FLT_BRD.md](Analytics/BRD/FLT_BRD.md) — источник истины по функциональности.
План работы (порядок ТЗ, тестов и кода по этапам): [Analytics/BRD/SDD_plan.md](Analytics/BRD/SDD_plan.md).
Репозиторий: https://github.com/alextaralexander/flt

Роли пользователей: Посетитель портала, Ученик, Администратор преподавателя/класса, Администратор платформы.

## Текущий этап

<!-- Обновлять при переходе между этапами -->
Этап 0 «Подготовка SDD-инфраструктуры» выполнен 2026-10-10. Артефакты: ID пунктов в `Analytics/BRD/FLT_BRD.md`, глоссарий `Analytics/glossary.md`, реестр открытых вопросов `Analytics/open-questions.md`, шаблоны `Analytics/Specs/_templates/`, матрица трассировки `Analytics/traceability.md`; приёмка этапа — в PR ветки `stage-0-sdd-setup`. SDD_plan.md утверждён: версия 1.0 от 2026-10-10, статус `approved`. Boilerplate-ы импортированы: бэкенд — `src/backend/py-monolyth` и `src/backend/py-main-lib`, фронтенд — `src/frontend` (разделы «Backend-сервис (boilerplate)» и «Frontend (boilerplate)»). Бэкенд собирается и запускается вместе с инфраструктурой через `deploy/docker-compose/docker-compose.yml`.

Идёт этап 1 «Каркас платформы» (SDD_plan.md §7). Блок А — архитектурные решения ADR-001…ADR-015 — завершён 2026-10-10: все 15 ADR в статусе `accepted` (PR #2, ветка `spec/stage-1-adr`). Их решения обязательны для SYS, ТЗ и кода; ниже они отражены кратко со ссылками на ADR, подробности — в самих ADR. Блок Б — системные спецификации SYS-01…SYS-12 (`Analytics/Specs/_system/`) — завершён 2026-10-11: все 12 SYS в статусе `approved` 1.0 (PR #3); их требования `SYS-NN-R<M>` обязательны для ТЗ и кода, при расхождении с этим файлом действует SYS. Блок В — спецификации модулей этапа 1 (`Analytics/Specs/{shared_kernel,identity,llm_gateway,app_shell}/_module.md`) — утверждён 2026-10-11 (PR #4). Идёт блок Г (доработка boilerplate-ов и код по принятым решениям): каждая часть сразу проверяется тестами на стенде из N = 3 инстансов. До завершения блока Г код в репозитории — импортированные boilerplate-ы; команды, пути и имена из ADR, которых в коде ещё нет, помечены ниже как «этап 1 Г».

Порядок реализации (из BRD):
1. Каркас платформы, основные технологические моменты
2. Кейсы Посетителя портала
3. Кейсы Администратора платформы
4. Кейсы Ученика — часть 1 (наиболее важные)
5. Кейсы Ученика — часть 2 (средняя важность); сюда входит STU-36 — живой персонаж-ведущий платформы (добавлен в BRD 2026-10-10)
6. Кейсы Администратора преподавателя/класса
7. Кейсы Ученика — часть 3 (плагины, вайбкодинг, социальные возможности); сюда же ADM-06 — продвижение платформы от имени персонажа-ведущего в новом модуле `promotion` (добавлен в BRD 2026-10-10)

## Процесс разработки: спецификации + TDD

Проект разрабатывается **полностью через вайбкодинг на основе спецификаций** (spec-driven development) и по **TDD**. Код пишет Claude, человек формулирует требования, утверждает спецификации и принимает результат. Структура репозитория, документация и процессы строятся так, чтобы Claude мог работать по ним самостоятельно и предсказуемо.

### Источник истины

Цепочка: **BRD → спецификация → тесты → код**.
- Спецификация — главный артефакт. Код и тесты вторичны и должны ей соответствовать.
- Сначала меняется спецификация, потом тесты, потом код. Код без спецификации не пишется.
- Если в ходе реализации выяснилось, что спецификация неполна или противоречива, нужно остановиться, предложить правку спецификации и дождаться утверждения.

### Спецификации

- Расположение: `Analytics/Specs/<модуль>/<ID>-<slug>.md`, где ID — идентификатор пункта BRD (см. SDD_plan.md). Одна спецификация на фичу, модуль совпадает с модулем backend/frontend. Спецификация модуля — `Analytics/Specs/<модуль>/_module.md`; недоменные модули этапа 1 описываются по тому же шаблону: `Analytics/Specs/shared_kernel/_module.md` (shared kernel, код — `app/core`) и `Analytics/Specs/app_shell/_module.md` (frontend app-shell и shared-слой) (OQ-32). Системные спецификации — `Analytics/Specs/_system/`, ADR — `Analytics/ADR/`.
- Шаблоны: `Analytics/Specs/_templates/` — ТЗ фичи, спецификация модуля, системная спецификация, ADR; утверждены 2026-10-10. Правила имён файлов, идентификаторов, версий и статусов — в [Analytics/Specs/_templates/README.md](Analytics/Specs/_templates/README.md). Обязательные разделы ТЗ фичи:
  - цель и ссылка на пункт BRD;
  - роли и пользовательские сценарии;
  - **критерии приёмки** в формате Given / When / Then, у каждого свой ID (например `STU-12.1-AC3`); требования системной спецификации нумеруются как `SYS-NN-R<M>` (например `SYS-05-R2`);
  - контракты: OpenAPI для REST, AsyncAPI для WebSocket и Kafka;
  - модель данных модуля;
  - состояние и масштабируемость: что хранится в PostgreSQL, что в Redis, как фича ведёт себя при одновременных запросах к разным инстансам;
  - UI: экраны, состояния, i18n/RTL;
  - нефункциональные требования и граничные случаи;
  - вне рамок (что сознательно не делается);
  - статус: `draft` → `review` → `approved` → `in-progress` → `implemented`; при изменении требований после утверждения — `changed` и повторный цикл (SDD_plan.md §4). Статусы ADR: `proposed` → `accepted` → `superseded` или `rejected`.
- Контракты API — spec-first: код и клиенты генерируются/проверяются по контракту, а не наоборот.
- Спецификации пишутся так, чтобы их можно было реализовать без устных пояснений: однозначно, с примерами, без «и т.д.».
- Термины и их английские имена для кода — из [Analytics/glossary.md](Analytics/glossary.md); они обязательны в ТЗ, коде, тестах и ключах i18n. Нового термина в глоссарии нет — сначала добавить его туда.
- Неясности и противоречия требований не додумываются, а записываются в [Analytics/open-questions.md](Analytics/open-questions.md) (ID `OQ-NN`) со ссылкой из раздела «Открытые вопросы» документа; принятые там решения обязательны для ADR, SYS и ТЗ.
- Матрица трассировки [Analytics/traceability.md](Analytics/traceability.md) (BRD ↔ ТЗ ↔ тесты ↔ статус) обновляется на шаге 14 конвейера (SDD_plan.md §5) вместе с `_module.md` затронутых модулей.

### TDD

Для каждого функционала автотесты создаются **сразу, до или вместе с кодом**. Фича без тестов не считается готовой.

Цикл:
1. **Red** — по критериям приёмки из спецификации пишутся тесты, они падают.
2. **Green** — минимальный код, чтобы тесты прошли.
3. **Refactor** — улучшение кода при зелёных тестах.

Правила:
- Каждый критерий приёмки покрыт минимум одним тестом. Тест ссылается на ID критерия (в имени или аннотации/тэге), чтобы прослеживалась связь спецификация ↔ тест.
- Нельзя ослаблять, удалять или отключать тесты, чтобы «пройти» сборку. Если тест неверен — сначала исправить спецификацию/тест с объяснением причины.
- Исправление бага начинается с теста, который его воспроизводит.
- LLM-провайдеры, TTS/STT и прочие внешние сервисы в тестах подменяются заглушками/моками; тесты детерминированы и не требуют сети или ключей.

Уровни тестов:
- **Backend**: unit-тесты; интеграционные тесты модуля через его публичный API (с реальными PostgreSQL, Redis, Kafka и, если фича их использует, MinIO, OpenSearch, Qdrant в контейнерах); контрактные тесты REST, WebSocket и Kafka; архитектурные тесты границ модулей (`tests/architecture/`, маркер требования `@pytest.mark.req("SYS-NN-R<M>")`). Инструменты — из boilerplate (pytest, pytest-asyncio, pytest-cov, `TestKafkaBroker`), для границ модулей — import-linter (ADR-002). LLM в тестах — провайдер `stub` с детерминированными фикстурами (ADR-009).
- **Frontend**: unit-тесты и тесты компонентов; тесты модулей с моками REST и WebSocket по контракту (MSW-моки генерирует orval, WebSocket — `msw` `ws.link`). Инструменты — из boilerplate: Vitest, Testing Library, MSW.
- **E2E**: ключевые пользовательские сценарии из спецификаций, в т.ч. RTL-языки. Инструмент — Playwright из boilerplate фронтенда; проекты `chromium-desktop`, `chromium-mobile`, `ar` (ADR-005).
- **Масштабируемость**: тесты каждой фичи на стенде из N инстансов монолита (раздел «Масштабирование и состояние»). Интеграционные backend-тесты и E2E по умолчанию выполняются на этом стенде.
- Порог покрытия backend — не ниже 75% (`fail_under` в `src/backend/py-monolyth/pyproject.toml`), повышать можно, понижать нельзя. Порог frontend (ADR-005) — 70% `lines`, `functions`, `statements` и 60% `branches` для `src/features`, `src/lib`, `src/components`, `src/hooks`, `src/utils` (`src/app/routes` покрывают E2E), тоже только повышается. Все тесты запускаются в CI, красная сборка блокирует слияние (обязательные проверки — ADR-011).

### Определение готовности (Definition of Done)

- [ ] Спецификация в статусе `approved`, после реализации — `implemented`
- [ ] Все критерии приёмки покрыты тестами, все тесты зелёные
- [ ] Границы модулей не нарушены (архитектурные тесты зелёные)
- [ ] Контракт API соответствует реализации
- [ ] Тесты на N инстансах зелёные, состояние хранится только в PostgreSQL, MinIO и Redis
- [ ] Добавлены метрики и логи, нужные для эксплуатации фичи
- [ ] Строки UI вынесены в i18n
- [ ] docker-compose и Helm charts обновлены (если затронуто развёртывание)
- [ ] Документация модуля обновлена

## Структура репозитория

```text
Analytics/          # аналитика и требования
  BRD/FLT_BRD.md    # бизнес-требования
  BRD/SDD_plan.md   # план работы по спецификациям
  glossary.md       # глоссарий: термины и их английские имена для кода и UI
  open-questions.md # реестр открытых вопросов (OQ-NN) и принятых по ним решений
  traceability.md   # матрица трассировки BRD ↔ ТЗ ↔ тесты ↔ статус
  ADR/              # архитектурные решения ADR-001…ADR-015 (accepted 2026-10-10) — обязательны для SYS, ТЗ и кода
  Specs/            # спецификации фич по модулям (источник истины для кода и тестов)
  Specs/_templates/ # шаблоны ТЗ фичи, спецификации модуля, системной спецификации и ADR; правила имён и статусов — README.md
src/                # все исходники
  backend/
    py-monolyth/    # Python-монолит (FastAPI) на основе boilerplate, свои правила — src/backend/py-monolyth/CLAUDE.md; раскладка app/core (shared kernel) + app/modules/<module> — ADR-002
    py-main-lib/    # внутренняя библиотека монолита; правится свободно в этом репозитории и подключается как path-зависимость uv (ADR-001, OQ-69; этап 1 Г.1)
  frontend/         # React-приложение на основе bulletproof-react (react-vite); правила архитектуры — src/frontend/docs/; стек, pnpm, i18n, генерация клиента — ADR-005
  agent/            # локальный агент flt-agent: Python 3.14, трей-приложение, сборка PyInstaller onedir (ADR-008); код появляется на этапе 4
  protocol/         # пакет flt-protocol: общие Pydantic-схемы протокола агент ↔ платформа (ADR-008); заготовка — этап 1 Г.1, наполнение — этап 4
  tools/            # пакет flt_tools: репозиторные скрипты (матрица трассировки, правила контрактов Spectral) с тестами и линтерами бэкенда (ADR-011); этап 1 Г.10
deploy/
  docker-compose/   # docker-compose.yml, docker-compose.ci.yml, .env.template; сейчас бэкенд и его инфраструктура, полный состав — этап 1 Г.8
  helm/flt/         # Helm chart: Deployment flt-api и flt-worker, Job flt-migrate, HAProxy, инфраструктура, values-ci.yaml и values-dev.yaml (ADR-004, ADR-011, ADR-012, ADR-013); этап 1 Г.8
  config/           # конфигурации, общие для compose и Helm: haproxy/, nginx/, prometheus/, grafana/, fluent-bit/, opensearch/ (этап 1 Г.8), livekit/ (этап 6) — ADR-010, ADR-012, ADR-014, ADR-015
  scripts/          # скрипты развёртывания: gen-secrets.sh, tls-bootstrap.sh, vault-seed-dev.sh (ADR-011, ADR-012, ADR-013)
.github/workflows/  # ci.yml, release.yml, deploy-vps.yml (ADR-011); agent-release.yml — с этапа 4 (ADR-008)
.pre-commit-config.yaml  # единый pre-commit для backend, frontend и Analytics (ADR-011); переносится из src/backend/py-monolyth на этапе 1 Г.1
renovate.json       # Renovate на уровне репозитория (ADR-001); переносится из src/backend/py-monolyth на этапе 1 Г.1
# дополнять по мере появления
```

## Технологический стек

- **Backend**: Python 3.14 и FastAPI (ADR-001: совместимость стека с 3.14 подтверждена полным `make check`; переход boilerplate с 3.13 — этап 1 Г.1). Сейчас на бэкенде **только один сервис — модульный монолит** (см. «Модульный монолит»); монолит, локальный агент, `src/protocol` и `src/tools` — один интерпретатор и одна политика версий. Другие языки на бэкенде не используются.
- **База данных**: PostgreSQL — одна база `flt`, схема на модуль (ADR-003). ORM — SQLAlchemy 2.0 (async, asyncpg), миграции — Alembic с секцией `alembic.ini` и каталогом ревизий на модуль (ADR-002).
- **In-memory хранилище**: Redis — модули работают только через обёртку shared kernel `ModuleRedis` с префиксом модуля и обязательным TTL (ADR-003).
- **Файловое хранилище**: S3-совместимое, MinIO; бакет на модуль `flt-<module>`, клиент загружает и читает файлы напрямую через HAProxy по presigned URL, байты через монолит не проходят (ADR-007). На этапе 1 — зафиксированный образ MinIO, сервер хранилища для prod — OQ-64 (до этапа 2).
- **Поиск** — три уровня (ADR-014): точные выборки и фильтры — PostgreSQL; многоязычный полнотекстовый — OpenSearch (один кластер с логами, разделение по индексам и пользователям); семантический и гибридный — Qdrant. Индекс или коллекция заводятся только по требованию ТЗ.
- **Балансировщик**: HAProxy в отдельном контейнере (поде), один `haproxy.cfg` для compose и Helm (ADR-012).
- **Раздача frontend**: Nginx со статикой — образ `flt-frontend`, порт 8080, CSP задаёт Nginx (ADR-005).
- **Мониторинг**: Prometheus и Grafana; алерты — в Telegram (OQ-60). **Логи**: JSON в stdout → Fluent Bit → OpenSearch, просмотр в Grafana. Экспорт трейсов выключен до этапа 4 (ADR-010).
- **Секреты**: только переменные окружения (ADR-013): в docker-compose — файл `.env` на VPS, который создаёт `deploy/scripts/gen-secrets.sh`; в Kubernetes — Vault, из которого External Secrets Operator создаёт Kubernetes Secret. Клиент Vault из boilerplate удаляется.
- **Масштабирование**: горизонтальное, запуском новых инстансов монолита. Монолит запускается из одного образа в ролях `api`, `worker`, `all`, `migrate`, `media_agent` (переменная `APP_ROLE`, ADR-004). Постоянное состояние — в PostgreSQL (файлы — в MinIO), in-memory — в Redis (раздел «Масштабирование и состояние»).
- Полный состав контейнеров — в разделе «Развёртывание».
- **Локальный агент** (ADR-008): `src/agent` — трей-приложение `flt-agent` на Python 3.14, собирается PyInstaller (onedir) под Windows, macOS и Linux; скачивает и запускает `llama-server`, подключается к LM Studio, собирает характеристики железа; связывается с платформой единственным исходящим WebSocket `/ws/agent` через HAProxy с токеном агента `flta_…`, полученным потоком авторизации устройства; схемы сообщений — общий пакет `src/protocol` (`flt-protocol`). Реализация — этапы 4–5.
- **Аутентификация** (ADR-006): собственная реализация в модуле `identity`, без внешнего IdP: email и пароль (argon2id), вход через Google, Яндекс ID и VK ID (`authlib`, за флагами конфигурации); access JWT EdDSA на 10 минут с `kid` плюс ротируемые refresh-токены в PostgreSQL; браузер получает httpOnly-cookie с signed double-submit CSRF, мобильные клиенты — `Authorization: Bearer`; проверка токена — на любом инстансе по публичному ключу и списку отозванных сессий в Redis.
- **Взаимодействие** (ADR-004, подробнее в разделе «Взаимодействие»):
  - REST — синхронное, роутер модуля с префиксом `/api/v1/<module>`;
  - WebSocket — асинхронное с фронтендом, один эндпоинт `/ws` с каналами модулей;
  - Kafka — асинхронное между модулями монолита и с другими сервисами (события, очереди заданий), топики `flt.<module>.<event>.v<N>`, публикация через outbox.
- **Frontend** (ADR-005): React 19+ и TypeScript на основе bulletproof-react (react-vite), раздел «Frontend (boilerplate)»; Node.js 24 LTS, pnpm 10. Модульный монолит по аналогии с бэкендом.
- **Развёртывание**: с первого дня два варианта — docker-compose и Kubernetes (Helm charts); продуктив до появления нагрузки — docker-compose на VPS в РФ (OQ-07, раздел «Развёртывание»).
- **CI/CD**: GitHub Actions (OQ-06, ADR-011): `ci.yml` с двумя ступенями проверок, `release.yml` по тегу `stage-N`, `deploy-vps.yml` — ручной деплой с подтверждением.
- **Основа backend-сервиса**: boilerplate пользователя в `src/backend/py-monolyth` (раздел «Backend-сервис (boilerplate)»).
- **Сборка и инструменты frontend** (ADR-005): Vite 7+, pnpm (через Corepack), ESLint 9 flat config и Prettier, Vitest 3 и Testing Library, MSW, Playwright, Storybook 9; orval — генерация клиента, zod-схем и MSW-моков из OpenAPI; i18next.
- **LLM-интеграция** (ADR-009, детали — SYS-08): модуль `llm_gateway` с единым интерфейсом провайдера и async-генератором `stream_completion`; реализации — внешние OpenAI-совместимые провайдеры, локальные модели через агента (провайдер `local`, транспорт — модуль `local_runtime`) и детерминированная заглушка `stub` для тестов. Интерактивные ответы стримятся по WebSocket с инстанса соединения, долгие генерации — задание Kafka в роли `worker`.
- **Синтез и распознавание речи**: через провайдеров модуля `speech` по аналогии с LLM — облачные сервисы по ключу ученика или локальные модели через агента. Голос один на один с AI-преподавателем — бинарные кадры по тому же WebSocket `/ws`; LiveKit — только для групповых занятий (ADR-009, этап 5).
- **Медиасервер**: LiveKit (`livekit-server`, при включённой записи — `livekit-egress`) для видеосвязи на групповых занятиях, AI-преподаватель в звонке — роль монолита `media_agent` на `livekit-agents` (ADR-015); с этапа 6.
- **Аватар преподавателя**: 2D/3D-рендер в браузере, мимика синхронизируется с синтезированной речью.
- Плагинная система: TODO (точки расширения — SYS-09, архитектура плагинов — SYS-13 на этапе 7).

Конкретные версии Python, React и зависимостей фиксируются в `pyproject.toml` и `package.json` (диапазоны) и в `uv.lock` и `pnpm-lock.yaml` (точные версии), а не в этом документе. Политика версий — ADR-001 §3.2: Renovate на уровне репозитория еженедельно обновляет lock-файлы и минорные версии одним PR, мажорные — отдельными PR вручную через `make check` и CI; новая линия CPython или Node принимается после выхода `X.Y.1`; образы инфраструктуры закреплены на минорных тегах одинаково в docker-compose и Helm (исключение — MinIO, OQ-64).

## Backend-сервис (boilerplate)

Бэкенд построен на boilerplate пользователя: `src/backend/py-monolyth` — основной код монолита, копия `python-boilerplate`; `src/backend/py-main-lib` — внутренняя библиотека, которая ему нужна (private registry недоступен). Библиотека правится свободно в репозитории FLT (ADR-001, OQ-69): на этапе 1 Г.1 `setup.py` с жёсткими пинами заменяется на `pyproject.toml` с диапазонами, class-based `Config` — на `ConfigDict`, неиспользуемые адаптеры (S3, NATS) и `.gitlab-ci.yaml` удаляются, библиотека подключается как `path`-зависимость uv.

- Правила самого boilerplate — в [src/backend/py-monolyth/CLAUDE.md](src/backend/py-monolyth/CLAUDE.md): слои и направление импортов, docstring-и, формат ошибок, анти-паттерны, скаффолдер. Они обязательны для кода бэкенда. Если они противоречат этому файлу, действует этот файл (см. «Отличия проекта от boilerplate»). Файл обновляется под раскладку по модулям на этапе 1 Г.1 (ADR-002).
- Стек: Python 3.14 (ADR-001; в boilerplate сейчас 3.13, переход — Г.1), uv, FastAPI и Pydantic v2, SQLAlchemy 2.0 (async) и Alembic, FastStream 0.7 (Kafka) с автоматической AsyncAPI, Redis, собственная проверка JWT и permissions, Prometheus, OpenTelemetry, structlog. Добавляются на этапе 1: import-linter (ADR-002), `aioboto3` (ADR-007), `qdrant-client` (ADR-014), `argon2-cffi`, `authlib`, `PyJWT[crypto]` (ADR-006).
- Качество кода: ruff (линт, импорты, формат, длина строки 120), mypy strict, bandit, detect-secrets, pre-commit, import-linter (`make arch`, ADR-002). Полная проверка — `make check`.
- Тесты: pytest, pytest-asyncio, pytest-cov, `TestKafkaBroker` из FastStream. Покрытие `app/` — не ниже 75% (`fail_under` в `pyproject.toml`). Архитектурные тесты — `tests/architecture/`, тесты модулей зеркалят `app/modules/<module>/` (ADR-002).
- Конфигурация по стендам: `envs/<стенд>/`, стенд выбирает переменная `STAND_NAME` в файле `.env` (образец — `.env.template`). pytest работает на стенде local с оверлеем `envs/.test.env`. В `envs/` — только несекретные параметры; секреты — `SecretStr` без значения по умолчанию, отсутствие секрета останавливает старт (ADR-013). Настройки модуля — класс с префиксом `<MODULE>_` и файлом `envs/<стенд>/<module>_<стенд>.env` (ADR-002).
- Служебные эндпоинты (ADR-010, OQ-62): `/v1/health` (liveness), `/v1/ready` (readiness по роли), `/v1/metrics`; роль `api` — порт 8000, роли `worker` и `media_agent` — служебный порт 8001; OpenAPI — `/api/docs` и `/api/openapi.json` (ADR-004, ADR-012; снаружи закрыты, на local и dev открываются `FLT_EXPOSE_DOCS`); AsyncAPI — `/asyncapi/kafka` на порту воркера. В boilerplate сейчас `/metrics` и `/docs` — меняется на этапе 1 Г.1; `/v1/info` и `/v1/system-metrics` удаляются.
- Ошибки HTTP отдаются в едином конверте `ErrorResponseV1`.
- Новый код сначала генерируется скаффолдером, затем дорабатывается. После этапа 1 Г.1 (ADR-002): `make scaffold-module name=…`, `make scaffold-entity module=… name=…`, `make scaffold-subscriber module=… topic=… value=…`; сгенерированный код обязан проходить `make check` без правок.
- Проверка при импорте (2026-09-21): 55 тестов проходят, ruff без замечаний. Две ошибки mypy (лишние `type: ignore` в `app/core/broker_middlewares.py`) исправлены 2026-09-22.
- Проверка запуска (2026-09-22, после удаления NATS): сервис стартует с PostgreSQL, Redis и Kafka — миграции применяются, `/v1/health` и `/v1/ready` отвечают 200, CRUD `my_entity` пишет в PostgreSQL и кэш в Redis, сообщение из входящего Kafka-топика обрабатывается и ответ уходит в исходящий топик. 48 тестов проходят, покрытие 77%, ruff, mypy и bandit без замечаний. Проверялось без Docker (Docker Hub был недоступен): вместо Kafka — совместимый с ней брокер Tansu. `docker compose` проверен только на корректность конфигурации.

### Отличия проекта от boilerplate

Boilerplate рассчитан на небольшой микросервис. В FLT действуют следующие отличия. Решения по ним приняты в ADR-001…ADR-015 (accepted 2026-10-10); реализация — этап 1 Г (Г.1 — скелет репозитория, Г.2 — архитектурные тесты, Г.4 — shared kernel, Г.5 — `identity`, Г.9 — наблюдаемость).

1. **Доменные модули вместо слоёв на весь сервис** (ADR-002). Boilerplate раскладывает весь код по слоям (`app/api/controllers`, `services`, `dao`, `schemas`). В FLT каждый доменный модуль — пакет `app/modules/<module>/` со слоями boilerplate внутри и подпакетом `public/` (единственное, что импортируют другие модули); `app/core` — shared kernel без бизнес-логики; модули регистрируются через `app/modules/registry.py` и `ModuleDefinition` в `module.py`; у модуля своя схема PostgreSQL, секция `alembic.ini`, префикс Redis и настройки с префиксом `<MODULE>_`. Границы проверяют import-linter (`.importlinter`) и `tests/architecture/`. Скаффолдер получает `add-module` и `--module`. Пример `my_entity` удаляется. Г.1, Г.2.
2. **Только Kafka.** Сделано 2026-09-22: NATS удалён полностью — код и тесты, настройки и env-файлы, зависимость `nats-py`, контейнер в docker-compose, NATS-функции в `src/backend/py-main-lib` (`auth_user_nats`, `UserTopicViolationError`). Пример Kafka-обработчика теперь отвечает в исходящий Kafka-топик.
3. **Логи** (ADR-010). Встроенная отправка логов в OpenSearch удаляется вместе с `app/core/logging/opensearch_sink.py` и настройками `OPEN_SEARCH_*` (зависимость `opensearch-py` остаётся для клиента поиска, ADR-014). Приложение пишет JSON-логи в stdout с полями из раздела «Наблюдаемость», их собирает Fluent Bit. Г.1, Г.9.
4. **Секреты** (ADR-013). Клиент Vault boilerplate (`configs/vault_config.py`, `hvac`, `default_factory=vault_secret`), стабы `KafkaSettingsStub` и `RedisSettingsStub` удаляются; секреты — обязательные поля `SecretStr`, читаются только из переменных окружения; в Kubernetes их подаёт External Secrets Operator из Vault, в docker-compose — `.env`. `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ROLE_PERMISSIONS` заменяются на `JWT_SIGNING_KEYS`/`JWT_ACTIVE_KID` (секция `identity`), `JWT_PUBLIC_KEYS`, `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_CSRF_SECRET` (ADR-006). Г.1.
5. **Трейсы** (ADR-010, OQ-20). Экспорт OpenTelemetry выключен до этапа 4 (`OTLP_EXPORTER_ENDPOINT` пустой во всех `envs/`), инструментирование сохраняется и дополняется `FastAPIInstrumentor`; корреляция — `request_id`. Коллектор и Grafana Tempo — новым ADR при появлении многошаговых цепочек LLM. Г.1.
6. **Выпуск токенов** (ADR-006). Boilerplate только проверяет JWT. Токены выпускает `TokenIssuer` модуля `identity`; `AuthService` shared kernel заменяется на `TokenVerifier` (EdDSA, несколько публичных ключей по `kid`, cookie и Bearer, async-проверка отзыва в Redis), добавляются `auth_user_optional` и `auth_websocket`; `cli issue-token` переводится на `TokenIssuer`. Г.4, Г.5; экраны регистрации и входа — этап 2 (VIS-04, VIS-05).
7. **Инфраструктура и сборка.** Сделано 2026-09-22: `make compose-up` поднимает инфраструктуру из `deploy/docker-compose/docker-compose.yml`, `Dockerfile` берёт py-main-lib из build-context-а (`make docker-build`). Осталось (Г.1): `.pre-commit-config.yaml` и `renovate.json` переносятся в корень репозитория (ADR-011, ADR-001); py-main-lib становится `path`-зависимостью uv, `make install` и `Dockerfile` упрощаются (ADR-001); второй build-context `flt-protocol` — этап 4 (ADR-008).
8. **Имя сервиса.** `python-boilerplate` переименовать в `flt-backend` (pyproject, Makefile, env-файлы, `SERVICE_NAME` в `telemetry.py` — ADR-010). Г.1.
9. `BOILERPLATE.md` — манифест для другого процесса разработки, в FLT не используется.
10. **Тестовая БД.** pytest и стенд local используют одну базу и схему (`flt` / `ms_py_test`), а тесты пересоздают таблицы: запуск тестов стирает локальные данные, а локальные данные могут ломать тесты. Развести на этапе 1 с учётом схем модулей — SYS-10 (OQ-31), Г.3.
11. **Топики Kafka** (ADR-004). Сервис подписывается на топики при старте. Локальная Kafka создаёт их автоматически (`KAFKA_AUTO_CREATE_TOPICS_ENABLE`) — только на стенде local; на остальных стендах топики создаёт роль `migrate` по декларациям модулей (`topics.py` в публичном API). Callback-топики (`KAFKA_ERROR_TOPIC_BY_SOURCE`), шаблонные `some_service.*` и единый `KAFKA_GROUP_ID` удаляются; `KafkaRouter` из `faststream.kafka.fastapi` заменяется поддерживаемой интеграцией (ADR-001). Г.1.
12. **Базовая модель и обёртка Redis shared kernel** (ADR-003). Вместо `BaseEntityModel` py-main-lib — `EntityBase` (`id` UUID v7 через `new_id()`, `created_at`, `updated_at`, `version` для оптимистической блокировки, `SoftDeleteMixin` по решению ТЗ) и `Clock`; вместо `RedisDAO` и сырого клиента `redis_conn` — `ModuleRedis(prefix)` с обязательным TTL, `locks`, `rate_limiter`; `PG_SCHEMA` удаляется, добавляются `REDIS_MODE`, `REDIS_SENTINEL_*`; настройки `MIGRATE_ON_START` нет (SYS-05-R33). Г.1, Г.4.
13. **Роли запуска и точка входа** (ADR-004, ADR-012). `uvi_run.py` и `MIGRATE_ON_START` удаляются; точка входа образа — `python -m app` с `APP_ROLE`; uvicorn запускается с `proxy_headers=True` и `FORWARDED_ALLOW_IPS`; `ROOT_PATH` удаляется, OpenAPI переезжает на `/api/docs`; `MetricsService` переписывается на readiness по роли с ответом 503 (ADR-010). Г.1, Г.4, Г.9.

## Frontend (boilerplate)

Фронтенд построен на [bulletproof-react](https://github.com/alan2207/bulletproof-react), приложение `apps/react-vite` (лицензия MIT, `src/frontend/LICENSE`). Импортирован 2026-09-21 из коммита `9506629` от 2026-05-14.

- Правила архитектуры — в [src/frontend/docs](src/frontend/docs): структура проекта, API-слой, состояние, стили, тесты, обработка ошибок, безопасность. Они обязательны для кода фронтенда. Если они противоречат этому файлу или ADR-005, действует этот файл.
- Структура `src/frontend/src`: `app` — роуты, провайдеры, роутер, регистрация namespaces i18n модулей (`i18n-resources.ts`); `features/<модуль>` — доменные модули (внутри `api/generated/`, `locales/`, `ws/generated/`, компоненты); `components`, `hooks`, `lib` (в том числе `lib/i18n`, `lib/ws`, `lib/auth.tsx`), `utils`, `types`, `config` — общий код; `testing` — моки MSW и утилиты тестов, `testing/architecture` — архитектурные тесты.
- Стек (целевые версии — ADR-005 §3.1, миграция — этап 1 Г.1): React 19, TypeScript 5.9 (strict), Vite 7, React Router 7 (library mode), TanStack Query 5, axios (один общий API-клиент), react-hook-form и zod 4, zustand 5, Tailwind 4 (CSS-first конфигурация) и Radix UI; Node.js 24 LTS, pnpm 10 через Corepack (`packageManager`, `.nvmrc`, `.npmrc`).
- Тесты: Vitest 3 и Testing Library, моки API — MSW с `@mswjs/data`, E2E — Playwright (проекты `chromium-desktop`, `chromium-mobile`, `ar`) на mock-сервере и на стенде из N инстансов, Storybook 9 для компонентов. Порог покрытия (ADR-005): 70 % `lines`, `functions`, `statements` и 60 % `branches` для `src/features`, `src/lib`, `src/components`, `src/hooks`, `src/utils`; `src/app/routes` исключены и покрываются E2E; порог только повышается.
- Качество: ESLint 9 flat config (`eslint.config.js`): зоны границ модулей строятся автоматически из `src/features/*`, `import-x/no-cycle`, имена файлов и папок в kebab-case, запрет barrel-файлов, локальное правило `flt/no-physical-direction-classes`, `react/jsx-no-literals`; Prettier отдельно (`pnpm format:check`); `tsc`; `pnpm i18n:check` и `pnpm api:check` в CI.
- Переменные окружения — `VITE_APP_*` (образец — `.env.example`), они встраиваются в сборку; адреса бэкенда относительные (`/api/v1`, `/ws`), поэтому одна сборка работает на всех стендах.
- Генератор компонентов — plop (`pnpm generate`).
- Проверка при импорте (2026-09-21, ещё на yarn): `yarn install`, `yarn lint`, `yarn check-types`, `yarn build` проходят, 21 тест проходит, E2E не запускались. В `yarn.lock` один пакет (`eslint-plugin-check-file`) скачивался с зеркала `registry.npmmirror.com` — адрес заменён на стандартный реестр. Переход на pnpm (`pnpm import`, удаление `yarn.lock`) — первый шаг Г.1.

### Отличия проекта от boilerplate

Решения приняты в ADR-005 (accepted 2026-10-10); порядок миграции — ADR-005 §3.2: 11 шагов, каждый — отдельный коммит при зелёных `pnpm lint`, `pnpm check-types`, `pnpm test`, `pnpm build`; шаги 1–10 — этап 1 Г.1, шаг 11 — Г.7.

1. **Версии и менеджер пакетов.** В boilerplate React 18, Vite 5, Tailwind 3, ESLint 8 со старым форматом конфига, TypeScript 5.4, Vitest 2, Storybook 8, yarn 1. Обновляются до версий из ADR-005 §3.1 (не ниже; мажорная версия моложе 60 дней не берётся), ESLint — на flat config, Tailwind — на 4 с `@theme` в CSS, `react-helmet-async` удаляется; менеджер пакетов — pnpm.
2. **Демо-фичи.** `auth`, `comments`, `discussions`, `teams`, `users` — примеры стиля. Остаются как образец до появления app-shell, затем удаляются в Г.7 вместе с их моками, тестами, роутами и `src/types/api.ts`.
3. **Модули.** `src/features/<модуль>` соответствуют модулям бэкенда. Зоны `import-x/no-restricted-paths` строятся автоматически из списка каталогов `src/features/*` — новый модуль получает зону без правки конфига; негативный тест `src/testing/architecture/eslint-boundaries.test.ts` доказывает, что нарушение границы ломает `eslint` (критерий выхода этапа 1).
4. **i18n и RTL.** i18next + react-i18next + `i18next-browser-languagedetector` + `i18next-resources-to-backend`; языки `ru`, `en`, `ar`; namespace `common` в `src/lib/i18n/locales/`, namespace модуля — `src/features/<module>/locales/{ru,en,ar}.json` с ленивой загрузкой; ключи английские, типизированы из `ru`; полнота — `i18next-cli` (`pnpm i18n:check`). Направление задаётся для всего документа (`dir` и `lang` на `<html>`), Radix — через `DirectionProvider`; в стилях только логические классы Tailwind (`ms-*`, `pe-*`, `start-*`, `text-start`), варианты `rtl:`/`ltr:` — только для зеркалирования иконок в `src/components/ui`; физические классы запрещены правилом `flt/no-physical-direction-classes` и архитектурным тестом для `.css`. Строки UI вне `t()` запрещены (`react/jsx-no-literals`). Порядок определения языка, шрифты, форматы — SYS-07.
5. **API.** orval генерирует из `Analytics/Specs/<module>/api/openapi.yaml` TanStack Query-хуки, zod-схемы и MSW-моки в `src/features/<module>/api/generated/` (коммитится, исключён из lint и покрытия); `pnpm api:generate` после изменения контракта, `pnpm api:check` в CI. Типы и zod-схемы WebSocket-сообщений генерируются из `asyncapi.yaml` в `src/features/<module>/ws/generated/`. Базовые адреса относительные: `/api/v1` и `/ws` через HAProxy, пути не переписываются. Dev-сервер Vite проксирует `/api`, `/ws` и `/flt-*` (path-style запросы к хранилищу, ADR-007) на бэкенд без `rewrite`; маршруты приложения не начинаются с `/api`, `/ws` и `/flt-` (архитектурный тест).
6. **WebSocket.** Общий клиент shared-слоя `src/lib/ws/`: `WsClient`, хук `useWsSubscription`, zod-схема конверта из ADR-004, экспоненциальная задержка переподключения; одно соединение на вкладку, после переподключения — переподписка и перечитывание состояния каналов по REST; моки — `msw` `ws.link` (ADR-004, ADR-005).
7. **Аутентификация** (ADR-006). Браузер работает на httpOnly-cookie: axios с `withCredentials`, интерсептор добавляет `X-CSRF-Token` из cookie `__Host-flt_csrf` для изменяющих методов, при `401` — один single-flight `POST /auth/refresh` и повтор. `react-query-auth` заменяется на `src/lib/auth.tsx` поверх сгенерированного клиента `identity` с теми же именами хуков.
8. **Сборка и раздача.** Многоступенчатый `src/frontend/Dockerfile` (`node:24-alpine` → `nginxinc/nginx-unprivileged`), образ `flt-frontend`, порт 8080, healthcheck `/healthz`; в сборку выполняется `pnpm api:check`. Конфигурация Nginx — `deploy/config/nginx/frontend.conf`: только статика, SPA fallback и CSP (ADR-005 §3.8); `/api` и `/ws` Nginx не проксирует. Этап 1 Г.1.
9. **Порог покрытия** — 70 % lines/functions/statements, 60 % branches (ADR-005, см. выше), проверяется `pnpm test:cov` в CI.
10. **Git-хуки.** husky и lint-staged из `src/frontend` удаляются; единый `.pre-commit-config.yaml` в корне репозитория вызывает `pnpm --dir src/frontend lint-staged` (ADR-011). Этап 1 Г.1.

## Взаимодействие

| Тип | Технология | Где используется |
|---|---|---|
| Синхронное | REST (FastAPI) | запросы фронтенда к бэкенду, внешние клиенты |
| Асинхронное с фронтендом | WebSocket (FastAPI) | стриминг ответов LLM, прогресс длительных задач, уведомления, чат и события класса |
| Асинхронное внутри монолита и с другими сервисами | Kafka | доменные события между модулями, очереди фоновых заданий, интеграция с другими сервисами |

Решение по транспорту, форматам и ролям — ADR-004 (детализируют SYS-03, SYS-04); стриминг LLM и голос — ADR-009; протокол агента — ADR-008.

Правила:
- Контракты описываются заранее, в ТЗ: REST — OpenAPI, WebSocket и Kafka — AsyncAPI. FastAPI генерирует OpenAPI из кода, контрактные тесты сверяют его с контрактом из ТЗ; AsyncAPI, который генерирует FastStream, сверяется с `asyncapi.yaml` модуля.
- REST: каждый модуль подключает `APIRouter(prefix="/api/v1/<module>")`; монолит обслуживает путь `/api/v1/...` сам, HAProxy его не переписывает, поэтому OpenAPI совпадает с внешними URL. Единственное исключение из правила «префикс = имя модуля» — `/api/v1/auth/*` у модуля `identity` (OQ-12). Служебные пути `/v1/health`, `/v1/ready`, `/v1/metrics`, `/asyncapi/kafka` лежат вне `/api` и снаружи недоступны.
- Правило выбора транспорта (ADR-004 §3.1): клиент ждёт ответ — REST; сервер доставляет данные без запроса (стрим LLM, прогресс задания, уведомление, событие класса) — WebSocket; модулю нужны чужие данные прямо сейчас (чтение, проверка) — прямой вызов публичного API в процессе; свершившийся факт — доменное событие через outbox; нужно, чтобы другой модуль изменил свои данные, — событие или команда в топик заданий модуля-владельца, прямой вызов на запись запрещён; задача длинная (> 2 с) или не требует немедленного ответа — фоновое задание; по расписанию — планировщик роли `worker` под распределённой блокировкой; HTTP между модулями внутри монолита запрещён.
- Синхронный вызов между модулями монолита — через `typing.Protocol` из `public/` модуля и контейнер зависимостей shared kernel (`Depends(provide(IdentityService))` в контроллерах, `container.resolve` в консьюмерах и планировщике), не HTTP; вызываемый открывает собственную транзакцию. При выделении модуля реализация `Protocol` заменяется REST- или Kafka-клиентом без изменения вызывающих.
- Сейчас Kafka используется только внутри монолита. Внешние участники появятся при выделении модулей в микросервисы. Локальный агент связывается с платформой по WebSocket `/ws/agent` через HAProxy, Kafka наружу не публикуется.
- Kafka используется, где нужна асинхронность: не нужен немедленный ответ, задача долгая (генерация программы обучения, обработка загруженных материалов, скачивание моделей) или модули нужно развязать. Фоновое задание — запись в `<module>.jobs` плюс команда через outbox в топик `flt.<module>.jobs.<job>.v<N>`; прогресс — WebSocket.
- LLM (ADR-009 §3.2): интерактивный запрос (пользователь ждёт на экране, ≤ 120 с) исполняется прямым стримом от провайдера на инстансе, держащем WebSocket; долгая или многошаговая генерация (программа обучения, обработка материалов) — задание Kafka в роли `worker` с грубыми событиями прогресса через Redis pub/sub и результатом в PostgreSQL. Токены ответа через Redis pub/sub никогда не идут. Каждое ТЗ с LLM указывает выбранный путь.
- Модуль публикует только свои события и только в свои топики. Именование топиков (ADR-004, детализирует SYS-04): события — `flt.<module>.<event>.v<N>` (прошедшее время, snake_case), команды заданий — `flt.<module>.jobs.<job>.v<N>`, dead letter topic — `<topic>.dlq`; группы консьюмеров — `flt.<module>.<handler>`. Топики создаёт роль `migrate` по декларациям модулей; автосоздание — только на стенде local.
- События, связанные с изменением данных, публикуются через transactional outbox: таблица `<module>.outbox` в схеме модуля, запись только через `OutboxPublisher` shared kernel в транзакции с данными, relay — в роли `worker` под распределённой блокировкой (один на модуль), ключ сообщения — `aggregate_id`. Прямой `broker.publish` из модулей запрещён import-linter.
- Консьюмеры Kafka идемпотентны через inbox — таблицу `<module>.processed_events` (`INSERT … ON CONFLICT DO NOTHING` в транзакции обработчика, ack после commit). Ретраи в процессе (1 с, 5 с, 25 с), затем сообщение уходит в `<topic>.dlq` с заголовками ошибки; ошибки валидации — в DLQ без ретраев; разбор — команда `python -m app dlq replay`.
- Схемы сообщений версионируются: конверт события содержит `event_id`, `event_type`, `event_version`, `occurred_at`, `producer`, `aggregate_id`, `correlation_id`, `causation_id`, `payload`; совместимые изменения увеличивают `event_version`, несовместимые — новый топик `.v<N+1>`.
- WebSocket обслуживает сам монолит (роль `api`): один эндпоинт `/ws` с мультиплексированием каналов `<module>.<channel>[:<id>]`; модуль регистрирует обработчик канала (проверка права подписки, входящие команды), транспорт — shared kernel. Отдельный эндпоинт `/ws/agent` — для локального агента с тем же конвертом. События между инстансами доставляются через Redis pub/sub (`ws:channel:<channel>`, `ws:user:<user_id>`). Отдельный брокер (NATS и т.п.) для этого не нужен и не используется.
- WebSocket: аутентификация при handshake (cookie или `Authorization: Bearer`, токен в query запрещён — ADR-006); единый конверт `{type, correlation_id, channel, seq, ts, payload}`; бинарные кадры (аудио) — 9-байтовый заголовок (тип, `stream_id`, `seq`); heartbeat `ping` каждые 30 с; лимит 5 соединений на пользователя; коды закрытия `1012` (остановка инстанса), `1013` (переполнение очереди), `4401` (нет аутентификации или сессия отозвана), `4429` (лимит соединений). Переподключение с восстановлением состояния, в том числе к другому инстансу: у каждого канала есть REST-эндпоинт текущего состояния; незавершённый стрим LLM не возобновляется — модуль-владелец сохраняет частичный ответ с `interrupted = true`.

## Масштабирование и состояние

Монолит масштабируется горизонтально: при росте нагрузки поднимаются новые инстансы. Это свойство поддерживается **постоянно**: любая фича должна корректно работать на N инстансах.

Где хранится состояние:

| Состояние | Где | Примеры |
|---|---|---|
| Постоянное | PostgreSQL — одна база `flt`, схема на модуль (ADR-003) | пользователи, курсы, программы обучения, прогресс, словари, настройки, refresh-токены, outbox и inbox модулей, задания |
| Файлы | MinIO — бакет на модуль `flt-<module>` (ADR-007) | материалы учеников, медиа, демо-видео, записи занятий, дистрибутивы агента. Метаданные файлов — в PostgreSQL модуля-владельца |
| Поисковые индексы (производные) | OpenSearch (`flt-<module>-<entity>`), Qdrant (`flt_<module>_<entity>`) (ADR-014) | полнотекстовый и семантический поиск по словарям, материалам, страницам учеников |
| In-memory (временное, общее для всех инстансов) | Redis — только через `ModuleRedis(prefix)` с обязательным TTL (ADR-003) | отзывы сессий и кэш активности, кэш, лимиты запросов, распределённые блокировки, присутствие онлайн, состояние анонимного быстрого теста, реестр агентов, доставка WebSocket-событий между инстансами |
| В памяти процесса или на диске инстанса | **запрещено** | — |

Правила (детализируются в SYS-05; решения — ADR-003, ADR-004, ADR-007, ADR-014):
- Инстанс не хранит состояние между запросами: ни в глобальных переменных, ни в локальных кэшах, ни в файлах на диске. Любой запрос может попасть на любой инстанс.
- Кэш в памяти процесса допустим только для неизменяемых данных, одинаковых на всех инстансах (настройки, реестр модулей, скомпилированные Lua-скрипты, результат readiness на 5 с). `functools.lru_cache` и `cache` на функциях, читающих PostgreSQL или Redis, запрещены и проверяются архитектурным тестом.
- Sticky-сессии не используются. Корректность не зависит от того, на какой инстанс попал клиент.
- PostgreSQL (ADR-003): первичные ключи — UUID v7 через `new_id()` shared kernel; у каждой сущности `created_at`, `updated_at` и `version` (оптимистическая блокировка: `StaleDataError` → HTTP 409); физическое удаление по умолчанию, soft delete через `deleted_at` только по решению ТЗ; все времена — `timestamptz` в UTC через `Clock`. «Одна транзакция — один модуль»: сессия SQLAlchemy не передаётся через границу модуля, согласованность между модулями — через события outbox. Пул соединений на инстанс с размером по роли, PgBouncer — только по порогу из SYS-05.
- Redis (ADR-003): модуль получает `ModuleRedis(prefix="<module>")`, у всех ключей есть TTL (методов без TTL нет; фикстура pytest падает на ключе с `TTL == -1`); ключи — `<module>:<entity>:<id>`. Распределённые блокировки — `SET NX PX` с токеном владельца и Lua-освобождением (`locks.acquire(name, ttl, wait)`), лимиты — скользящее окно на `ZSET` в Lua (`rate_limiter`). Блокировки защищают только идемпотентные операции; корректность обеспечивают инварианты PostgreSQL. Потеря Redis не приводит к потере постоянных данных: refresh-токены — в PostgreSQL, поэтому сбой Redis не разлогинивает пользователей; допустимо потерять кэш, лимиты, блокировки и незавершённый быстрый тест. `/v1/ready` от Redis не зависит; поведение каждой функции при недоступном Redis (fail-open или fail-closed — таблица ADR-003 §3 п. 8) — обязательная часть ТЗ. В Kubernetes Redis работает с репликой и Sentinel (`REDIS_MODE=sentinel`), в docker-compose — один экземпляр без персистентности.
- Конкурентные изменения с разных инстансов не теряются и не дублируются: оптимистические блокировки (`version`), уникальные ограничения в PostgreSQL, распределённые блокировки в Redis для критических секций.
- WebSocket-событие доставляется клиенту, к какому бы инстансу он ни был подключён (через Redis pub/sub, каналы `ws:channel:*` и `ws:user:*`; pub/sub не хранит сообщения). После переподключения к другому инстансу клиент восстанавливает состояние по REST-эндпоинту канала из PostgreSQL. Запросы к локальному агенту с другого инстанса пересылаются через каналы `local_runtime:agent:<id>:inbox` и `local_runtime:reply:<request_id>` по реестру «агент → инстанс» в Redis (ADR-008).
- События публикуются через outbox в схеме модуля, relay — в роли `worker` под блокировкой; задания из Kafka распределяются между воркерами через consumer group и выполняются один раз благодаря inbox `processed_events`. Периодические задачи — планировщик роли `worker` под распределённой блокировкой `shared_kernel:lock:schedule:<module>.<task>`, задача обязана быть идемпотентной (ADR-004).
- Миграции Alembic выполняются один раз отдельным шагом ролью `migrate` (`make migrate` — `alembic -n <module> upgrade head` по каждому модулю реестра), а не каждым инстансом при старте (настройки `MIGRATE_ON_START` нет, SYS-05-R33). Миграции совместимы с предыдущей версией кода по правилам expand/contract (ADR-003 §2.5): новая колонка — только `NULL` или с `DEFAULT`; переименование и удаление — в два релиза; `NOT NULL` — после backfill через `CHECK … NOT VALID`; индексы — `CONCURRENTLY`; миграции данных свыше 10 000 строк — фоновым заданием роли `worker`; один файл меняет только схему своего модуля.
- Инстанс можно остановить в любой момент: readiness отвечает 503, активным стримам даётся `SHUTDOWN_GRACE_SECONDS=30`, WebSocket закрываются кодом 1012, незавершённые задания Kafka доставятся повторно, клиенты переподключатся к другим инстансам.
- Файлы не хранятся на диске инстанса и не проходят через него (ADR-007): клиент загружает файл напрямую в хранилище по presigned POST или multipart PUT через HAProxy по пути `/flt-<module>/…` и подтверждает загрузку в монолите; публичные медиа читаются по постоянным URL из префикса `public/` бакета `flt-cms`, приватные — по presigned GET на 15 минут после проверки прав; метаданные (`StoredFileMixin`, статусы `pending → uploaded → processing → ready → deleted`) — в PostgreSQL модуля-владельца; версионирование бакетов выключено, объекты пользователя лежат под `u/<owner_user_id>/` для удаления по 152-ФЗ.
- Источник истины — PostgreSQL и MinIO. Индексы OpenSearch и коллекции Qdrant производные (ADR-014): заводятся только по требованию ТЗ, обновляет их консьюмер модуля-владельца по его собственным событиям outbox (читая запись из PostgreSQL по `source_id`), при потере перестраиваются командой `python -m app search reindex` через алиас без простоя; отказ движков не влияет на readiness; приватные коллекции требуют `owner_id` в запросе.

**Тесты масштабируемости.** Каждая фича проверяется на стенде из N инстансов монолита (N = 3) за HAProxy с той же конфигурацией, что и при развёртывании (запросы распределяются по кругу), с общими PostgreSQL, Redis, Kafka и остальными контейнерами, которые использует фича. Проверяется, что:
- шаги одного сценария, попавшие на разные инстансы, дают согласованный результат;
- одновременные запросы к одним и тем же данным через разные инстансы не теряют и не дублируют изменения;
- WebSocket-клиент получает события, возникшие на другом инстансе;
- задание выполняется один раз при N потребителях;
- лимиты и блокировки действуют глобально, а не на каждом инстансе отдельно;
- остановка инстанса посреди сценария не ломает сценарий.

## Модульный монолит

Главное правило: **каждый модуль должен быть готов к выделению в отдельный микросервис** без переписывания. Помнить об этом при любом изменении.

### Backend (Python)

Раскладка, регистрация модулей и контроль границ — ADR-002 (реализация — этап 1 Г.1, Г.2).

- Модули выделяются по бизнес-доменам (bounded contexts), а не по техническим слоям. Предварительная карта модулей — Приложение В в SDD_plan.md, утверждается в SYS-01; порядок зависимостей между модулями из SYS-01 закрепляется контрактом import-linter `modules-dependency-order`.
- Каждый модуль — пакет `app/modules/<module>/` со слоями boilerplate внутри (`api`, `services`, `dao`, `models`, `schemas`, `brokers`, `migrations`, `settings.py`, `permissions.py`) и файлом `module.py` с `ModuleDefinition` (роутер, Kafka-роутер, обработчики WebSocket, метаданные, настройки, права); модули перечислены в `app/modules/registry.py`, `create_app()` подключает их по реестру. Публичный API модуля — подпакет `public/`: `Protocol` сервисов и фабрики для `Depends()`, Pydantic-схемы, события, ошибки, декларации топиков и индексов. Другие модули импортируют **только** `app.modules.<other>.public` и никогда не импортируют внутренние пакеты, модели SQLAlchemy или репозитории чужого модуля; `public/` не реэкспортирует модели и репозитории.
- Каждый модуль владеет своими данными: своя схема PostgreSQL `<module>` (`Base = make_module_base("<module>")`), свои модели SQLAlchemy, свои миграции Alembic (каталог `migrations/` и секция `[<module>]` в `alembic.ini`, своя таблица `alembic_version` в своей схеме). Никаких JOIN'ов, `relationship` и внешних ключей между таблицами разных модулей; схема `public` таблиц не содержит. Ссылки между модулями — по идентификаторам (`UUID` без `ForeignKey`). В Redis модуль использует только ключи со своим префиксом `<module>:` через `ModuleRedis(prefix)`. Также модуль владеет своими бакетами MinIO (`flt-<module>`), индексами OpenSearch (`flt-<module>-*`) и коллекциями Qdrant (`flt_<module>_*`).
- Каждый модуль подключает свой FastAPI-роутер с префиксом `/api/v1/<module>`, свой Kafka-роутер, свои обработчики каналов WebSocket и свой класс настроек с префиксом `<MODULE>_`; права модуля — коды `<module>:<resource>:<action>` с областью `own`/`rel`/`any` в `permissions.py` (SYS-06).
- Никаких циклических зависимостей между модулями.
- Границы модулей проверяются автоматически: import-linter по контрактам `.importlinter` (независимость модулей кроме `public`, порядок зависимостей по SYS-01, слои внутри модуля `api | brokers → public → services → dao → models`, `app.core` и `configs` не импортируют `app.modules`, модули не импортируют `redis`, брокер Kafka, `aioboto3`, `botocore`, `opensearchpy`, `qdrant_client` напрямую — только обёртки shared kernel) и pytest-тесты `tests/architecture/` (нет FK между схемами, таблицы в схеме модуля, префиксы настроек и Redis, префикс роутера, нет прямого `broker.publish`). Запуск — `make arch` в составе `make check`, pre-commit и job `architecture` в CI. Нарушение границы ломает сборку — доказывает негативный тест `test_boundary_violation_breaks_build`.
- Общий код — shared kernel `app/core` — минимален: реестр модулей, конверт ошибок, Kafka (брокер, outbox, inbox, DLQ, планировщик), WebSocket-инфраструктура, контейнер зависимостей, база SQLAlchemy и общий `env.py` Alembic, `ModuleRedis`, блокировки и лимиты, `FileStorage`, клиенты поиска, проверка JWT и permissions, логи, метрики, идентификаторы, время. Код, который знает о пользователях, курсах, моделях LLM или другой предметной области, в `app/core` не допускается.
- Конфигурация модуля изолирована (`<Module>Settings`, файл `envs/<стенд>/<module>_<стенд>.env`, секреты — переменные окружения), чтобы его можно было вынести в отдельный сервис.

### Логичность разбиения

Разбиение на модули поддерживается **постоянно** в ходе разработки, а не только на старте:
- в каждом ТЗ определять, к какому модулю относится новая логика. Если не подходит ни один, предложить новый модуль;
- если модуль разрастается и берёт чужую ответственность или два модуля слишком часто обращаются друг к другу, предложить перенос логики, разделение или объединение модулей;
- изменение разбиения сначала фиксируется в SYS-01 (карта модулей), затем выполняется рефакторинг при зелёных тестах;
- в конце каждого этапа проводится ревью разбиения (SDD_plan.md, раздел 8).

### Frontend

Правила границ и структуры модулей — ADR-005 §3.6 (реализация — этап 1 Г.1, Г.2).

- Модули (feature-модули) повторяют доменное разбиение бэкенда.
- Модули не импортируют друг друга. Связываются они только на уровне `src/app` (роуты, страницы, `i18n-resources.ts`). Контроль — правило ESLint `import-x/no-restricted-paths`, зоны которого строятся автоматически из списка каталогов `src/features/*` (новый модуль получает зону без правки конфига), и `import-x/no-cycle`; shared-слой (`components`, `hooks`, `lib`, `types`, `utils`, `config`) не импортирует `features` и `app`. Негативный тест `src/testing/architecture/eslint-boundaries.test.ts` доказывает, что нарушение границы ломает `eslint`.
- Barrel-файлы (`index.ts` с реэкспортом) не используются: запрет закреплён правилом `check-file/filename-blocklist` на `index.ts(x)` в модулях и shared-слое (единственный допустимый — `src/app/index.tsx`); импорт идёт напрямую из файлов через `@/`.
- Модуль владеет своими компонентами, сгенерированным API-клиентом к соответствующему backend-модулю (`api/generated/` из `openapi.yaml`), ресурсами i18n (`locales/{ru,en,ar}.json`, namespace = имя модуля), схемами WebSocket-сообщений (`ws/generated/` из `asyncapi.yaml`), состоянием и WebSocket-подписками. Роуты страниц лежат в `src/app/routes`.
- Общие UI-компоненты, i18n (`src/lib/i18n`), тема, утилиты, WebSocket-соединение (`src/lib/ws`), аутентификация (`src/lib/auth.tsx`) — в отдельном shared-слое без бизнес-логики. Если двум модулям нужен один компонент, он переезжает в `src/components` без бизнес-логики или дублируется.
- Физические классы направления (`ml-*`, `pr-*`, `left-*`, `text-left` и подобные) запрещены правилом `flt/no-physical-direction-classes` — только логические (`ms-*`, `pe-*`, `start-*`, `text-start`); `rtl:`/`ltr:` — только для зеркалирования иконок в `src/components/ui`. Строки UI вне `t()` запрещены (`react/jsx-no-literals`).
- Структура должна позволять позже вынести модуль в микрофронтенд.
- Интерфейс адаптивный: телефон, планшет, десктоп. Нативных мобильных приложений пока нет, но API и аутентификация проектируются так, чтобы добавить их без переделки.
- Собранная статика раздаётся Nginx. К бэкенду frontend обращается только через HAProxy по относительным путям (`/api/v1`, `/ws`, файлы хранилища — `/flt-*`); маршруты приложения с этими префиксами запрещены.

## Развёртывание

С самого начала поддерживаем **оба** варианта, и они должны оставаться в синхронизированном состоянии:

1. **docker-compose** — локальная разработка, простые установки и продуктив до появления нагрузки.
2. **Kubernetes (Helm charts)** — масштабируемые установки; целевой вариант продуктива при росте нагрузки.

Продуктивная среда (OQ-07): до появления нагрузки продуктив разворачивается docker-compose на VPS в РФ (152-ФЗ). Helm chart поддерживается с первого дня и проверяется в CI в локальном Kubernetes (kind); переход продуктива на Kubernetes — отдельным решением при росте нагрузки. Правило «оба варианта» действует независимо от того, где сейчас продуктив.

CI/CD — GitHub Actions (OQ-06, ADR-011): `ci.yml` — быстрая ступень (линтеры, типы, безопасность, архитектура, unit- и интеграционные тесты, сборка frontend, линт контрактов, матрица трассировки) на каждый push и тяжёлая ступень (образы, стенд из N = 3 инстансов за HAProxy через `docker-compose.ci.yml`, Playwright E2E, Helm в kind) для PR вне draft, PR с меткой `ci:full`, `main` и тегов; `release.yml` по тегу `stage-N` публикует образы `ghcr.io/alextaralexander/flt/{backend,frontend}` и Helm chart; `deploy-vps.yml` — ручной деплой на VPS с подтверждением в окружении `prod` (`docker compose run --rm migrate`, затем `up -d`, откат — тот же workflow с предыдущим тегом). При расходе 80 % бесплатных минут — self-hosted runner на отдельном VPS (переменная `CI_HEAVY_RUNNER`).

Правила:
- Любое изменение, затрагивающее развёртывание (новый сервис, переменная окружения, порт, volume, секрет, зависимость, топик Kafka), вносится **одновременно** в docker-compose и в Helm charts.
- Оба варианта содержат одинаковый состав контейнеров (см. «Состав контейнеров»). Отличия: Vault, External Secrets Operator и Reloader есть только в Kubernetes; Redis в Kubernetes работает с репликой и Sentinel, в docker-compose — один экземпляр. Конфигурации HAProxy, Nginx, Prometheus, Grafana, Fluent Bit, OpenSearch — одни и те же файлы в `deploy/config/` (bind mount в compose, ConfigMap в Helm; OQ-29). Паритет тегов образов между compose и Helm проверяет тест (SYS-11).
- Dev-only сервисы (сейчас — Mailpit; mock OIDC-провайдер для тестов, Vault в dev-режиме) включаются профилем docker-compose и файлом `values-dev.yaml` Helm и в продуктив не попадают (OQ-11; правило фиксируется в SYS-11).
- Монолит запускается из одного образа `flt-backend` в ролях (ADR-004, `APP_ROLE`): `api` — uvicorn с REST, WebSocket и служебными эндпоинтами на порту 8000, без Kafka; `worker` — консьюмеры Kafka, relay outbox и планировщик со служебным HTTP на порту 8001; `all` — обе роли в одном процессе (local и pytest); `migrate` — одноразовый шаг инициализации; `media_agent` — AI-преподаватель в LiveKit (этап 6). Роль `api` — N = 3 экземпляра за HAProxy (`deploy.replicas: 3` или `--scale api=3` в compose, Deployment `flt-api` за headless Service в Helm, не меньше 2 реплик), `worker` — 2 реплики (сервис `worker`, Deployment `flt-worker`); автомасштабирование по ролям — HPA, OQ-30 (SYS-11). Sticky-сессии не используются.
- Миграции и инициализация инфраструктуры выполняются ролью `migrate` отдельным шагом до запуска новых инстансов: `make migrate` по всем модулям реестра (ADR-002), создание топиков Kafka по декларациям модулей (ADR-004), `cli storage-init` — бакеты `flt-*`, политики и lifecycle (ADR-007), шаблоны индексов OpenSearch и коллекции Qdrant (ADR-014). В docker-compose — сервис `migrate` с `restart: "no"`, от которого `api` и `worker` зависят через `service_completed_successfully`; в Helm — Job `flt-migrate` с hook `pre-install,pre-upgrade`. Инстансы при старте миграции не выполняют (настройки `MIGRATE_ON_START` нет, SYS-05-R33).
- Конфигурация и секреты передаются монолиту и всем контейнерам только через переменные окружения (ADR-013). В docker-compose секреты берутся из файла `.env` на VPS (`/opt/flt/.env`, права `600`, не коммитится; шаблон — `deploy/docker-compose/.env.template`, начальные значения создаёт `deploy/scripts/gen-secrets.sh`, режим `--ci` — для стендов CI). В Kubernetes источник — Vault (kv v2, пути `flt/<stand>/infra/<компонент>` и `flt/<stand>/app/<модуль>`), из которого External Secrets Operator создаёт Kubernetes Secret на компонент, Helm подключает их через `envFrom`, перезапуск при смене — Reloader; в kind (CI) Vault выключен, ESO работает с провайдером `fake` и тестовыми значениями из `values-ci.yaml`. Клиент Vault в коде монолита не используется, поэтому код в обоих вариантах одинаковый. Ключи с ротацией (подпись JWT, шифрование ключей учеников) версионируются в данных (`kid`, `key_version`); остальные секреты ротируются поочерёдным перезапуском. Таблица всех секретов — ADR-013 §3.1, ведётся в SYS-11.
- Структуру Helm charts закладывать с учётом будущего разделения на микросервисы: `deploy/helm/flt/` с Deployment `flt-api` (headless Service `flt-api`), `flt-worker`, Job `flt-migrate`, Deployment и Service LoadBalancer HAProxy (в kind — NodePort 30080/30443 с `extraPortMappings`), ConfigMap из `deploy/config/`, `ExternalSecret` на компонент, subchart-зависимости для инфраструктуры (правило выбора chart-ов — SYS-11, OQ-28; MinIO — собственный standalone StatefulSet), `values-ci.yaml` (2 `flt-api`, 1 `flt-worker`, Vault выключен) и `values-dev.yaml`.
- docker-compose — `deploy/docker-compose/docker-compose.yml` (сейчас бэкенд и его инфраструктура; полный состав — этап 1 Г.8) плюс `docker-compose.ci.yml` (профиль `ci`, имя проекта `flt`); тег образа на VPS — `FLT_IMAGE_TAG` в `.image-tag.env`. Helm — `deploy/helm/flt/` (этап 1 Г.8).

### Состав контейнеров

Минимальный состав; решения — ADR-004, ADR-007, ADR-010, ADR-012, ADR-013, ADR-014, ADR-015. Вспомогательные контейнеры: `migrate` (роль монолита), `minio-init` (учётная запись и политика хранилища, ADR-007), `certbot` (TLS на prod, ADR-012), `backup` (резервное копирование prod, SYS-11-R18), `postgres-exporter`, `redis-exporter`, `kafka-exporter`, `node-exporter`, `cadvisor` (только compose), `blackbox-exporter` (prod) (ADR-010, SYS-11-R4, этап 1 Г.9). Контейнер `embeddings` (модель эмбеддингов платформы) — OQ-59, решается до этапа 5 (ADR-014).

| Контейнер | Назначение | docker-compose | Kubernetes |
|---|---|---|---|
| HAProxy | единая точка входа и балансировщик (ADR-012): завершает TLS, распределяет запросы по инстансам роли `api` по кругу без sticky-сессий, обнаруживает инстансы через DNS (`server-template`), исключает их по `/v1/ready`, проксирует WebSocket и файлы хранилища, генерирует `X-Request-ID`, первый рубеж лимитов по IP, метрики на внутреннем порту 8404; один `deploy/config/haproxy/haproxy.cfg` | да (порты 80, 443) | да, Deployment (2 реплики) за Service типа LoadBalancer; в kind — NodePort |
| Python-монолит | backend (FastAPI), образ `flt-backend` в ролях `api` (N = 3, порт 8000 только во внутренней сети), `worker` (2 реплики, служебный порт 8001), `migrate` (одноразово), `media_agent` (этап 6) — ADR-004 | да | да: `flt-api`, `flt-worker`, Job `flt-migrate`, `flt-media-agent` |
| Redis | in-memory состояние; один экземпляр `redis:8-alpine` с `maxmemory`, `volatile-lru`, без персистентности, пароль из `.env` (ADR-003) | да | да, мастер + реплика + 3 Sentinel |
| PostgreSQL | постоянное состояние: одна база `flt`, схема на модуль, `max_connections=200` (ADR-003) | да | да |
| Kafka | события между модулями, очереди заданий; listener `PLAINTEXT` только во внутренней сети, без SASL (ADR-013); топики создаёт роль `migrate` | да | да |
| Nginx | раздача статики frontend: образ `flt-frontend`, порт 8080, SPA fallback, CSP, `/healthz`, webroot ACME (ADR-005, ADR-012) | да | да |
| MinIO | S3-хранилище файлов: бакет на модуль `flt-<module>`, SSE-S3, порт 9000 только во внутренней сети, снаружи — через HAProxy по `/flt-*` (ADR-007); на этапе 1 — зафиксированный тег последнего опубликованного образа, сервер для prod — OQ-64 | да | да, собственный standalone StatefulSet |
| Prometheus | сбор метрик со всех инстансов: DNS-обнаружение в compose, Kubernetes SD по аннотациям `prometheus.io/*` в Helm; хранение 30 дней (ADR-010) | да | да |
| Grafana | дашборды и алерты как код (`deploy/config/grafana/`), источники Prometheus и OpenSearch, оповещения в Telegram (OQ-60) | да | да |
| OpenSearch | один кластер: хранение всех логов (индексы `flt-logs-*`, ISM 14 дней) и полнотекстовый поиск (индексы `flt-<module>-*`); образ `flt-opensearch` с плагинами анализа (ICU, kuromoji, nori, smartcn), плагин безопасности включён, отдельные пользователи для логов, Grafana и монолита; порог разделения на два кластера — SYS-11 (ADR-010, ADR-014) | да, один узел | да |
| Fluent Bit | сбор логов всех контейнеров и доставка в OpenSearch: в compose — logging driver `fluentd` с input `forward`, файловый буфер 512 МБ; конфигурация `deploy/config/fluent-bit/` (ADR-010) | да | да, DaemonSet с input `tail` |
| Qdrant | семантический и гибридный поиск: коллекция на сущность модуля `flt_<module>_<entity>`, именованные векторы по моделям эмбеддингов, фильтр владельца внутри ANN (ADR-014) | да | да |
| LiveKit | видеосвязь на групповых занятиях (ADR-015): `livekit-server` (SFU, сигнализация через HAProxy `/livekit/*`, встроенный TURN, медиапорты напрямую) и `livekit-egress` для записи (профиль `recording`, только после OQ-35); конфигурация `deploy/config/livekit/livekit.yaml`; с этапа 6 | да (этап 6) | да (этап 6), официальный chart под `livekit.enabled` |
| Mailpit | приёмник SMTP для dev, test и CI: письма платформы читаются в веб-интерфейсе (порт 8025 на loopback) и через HTTP API (E2E); dev-only, в продуктив не попадает (OQ-11) | да, по профилю | да, только `values-dev.yaml` |
| Vault | хранение секретов; секреты в поды подаёт External Secrets Operator, перезапуск при смене — Reloader (ADR-013); в kind выключен, ESO с провайдером `fake` | нет | да |

### Маршрутизация через HAProxy

HAProxy — единственная точка входа снаружи; схема утверждена в ADR-012 (конфигурация — `deploy/config/haproxy/haproxy.cfg`, этап 1 Г.8):
- TLS завершается на HAProxy (TLS 1.2/1.3, HTTP/2, редирект HTTP → HTTPS, HSTS). На prod (compose на VPS) сертификат Let's Encrypt получает контейнер `certbot` через webroot, который Nginx отдаёт по `/.well-known/acme-challenge/`; обновление загружается в HAProxy без перезапуска через runtime API; первый выпуск — `deploy/scripts/tls-bootstrap.sh`. TLS включается при появлении домена (`FLT_TLS_DOMAIN`, OQ-08); на local, dev и в CI HAProxy работает без TLS на `flt.localhost`. В Kubernetes HAProxy публикуется через Service типа LoadBalancer (облачный балансировщик или MetalLB; в kind — NodePort), сертификат — cert-manager; конфигурация та же, что в docker-compose. Единственное исключение из «TLS только на HAProxy» — TURN/TLS LiveKit на порту 5349 (ADR-015);
- `/api/*` → инстансы монолита роли `api` (REST `/api/v1/<module>/...`, путь не переписывается, `ROOT_PATH` не используется); документация `/api/docs`, `/api/redoc`, `/api/openapi.json` снаружи закрыта (404), на local и dev открывается `FLT_EXPOSE_DOCS`; тело запроса — до 25 МБ (файлы идут мимо монолита);
- `/ws/*` → те же инстансы: WebSocket фронтенда `/ws` и локального агента `/ws/agent`, `timeout tunnel 1h` (клиенты шлют ping раз в 30 с);
- `/flt-*` → MinIO без переписывания пути и `Host` (path-style S3, все бакеты `flt-<module>`, подпись SigV4 остаётся валидной): presigned POST/PUT загрузки и presigned GET приватных файлов, публичные объекты `flt-cms/public/*`; ACL — только методы `GET HEAD PUT POST`, на уровне бакета только `POST` (листинг запрещён), таймауты 600 с, запрещающий CSP; admin API и health MinIO снаружи недостижимы (ADR-007);
- `/livekit/*` → сигнализация LiveKit `livekit:7880` со снятием префикса (единственный маршрут с переписыванием пути), `/livekit/twirp/*` снаружи — 403; медиатрафик (UDP 7882, TCP 7881) и TURN (UDP 3478, TLS 5349) публикуются напрямую, мимо HAProxy; зарезервировано до этапа 6 (ADR-015);
- остальные пути → Nginx со статикой frontend (`flt-frontend:8080`, SPA fallback делает Nginx);
- служебные эндпоинты монолита `/v1/health`, `/v1/ready`, `/v1/metrics`, `/asyncapi/kafka` лежат вне `/api` и `/ws`, поэтому снаружи недостижимы (запрос уходит на Nginx); порт 8000 монолита на хост не публикуется; stats и метрики HAProxy (`:8404`) — только во внутренней сети.

HAProxy обнаруживает инстансы роли `api` через DNS (`server-template`, в compose — встроенный DNS Docker при `--scale api=3`, в Kubernetes — headless Service `flt-api`), проверяет их по `GET /v1/ready` каждые 2 с и исключает из балансировки после 3 неудач (ответ 503 readiness — неудача); роль `worker` за HAProxy не стоит. Балансировка `roundrobin` без sticky-сессий; таймауты: `connect 5s`, `client 30s`, `server 60s` для REST. HAProxy генерирует `X-Request-ID` (клиентский перезаписывается), перезаписывает `X-Forwarded-For`/`X-Real-IP` значением `src`, выставляет `X-Forwarded-Proto`; монолит доверяет этим заголовкам (`proxy_headers=True`, `FORWARDED_ALLOW_IPS`). HAProxy выставляет HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`; Content-Security-Policy задаёт Nginx (ADR-005). Первый рубеж лимитов по IP — stick-table для `/api/v1/auth/*` (20 запросов за 10 с) и быстрого теста (30 за 10 с), глобальные лимиты — в Redis. Логи HAProxy — JSON в stdout с `request_id`.

## Наблюдаемость

Решение — ADR-010 (реализация — этап 1 Г.4, Г.8, Г.9; требования — SYS-10, SYS-11).

- **Метрики**: каждый инстанс отдаёт метрики в формате Prometheus на `/v1/metrics` (OQ-62; роль `api` — порт 8000, `worker` и `media_agent` — 8001; роль `migrate` метрик не отдаёт). Технические метрики ядра: `http_requests_total`, `http_request_duration_seconds` (метка `endpoint` — шаблон маршрута), `flt_ws_connections`, `flt_ws_messages_total`, метрики Kafka из `KafkaPrometheusMiddleware`, `flt_db_pool_connections`, `flt_redis_pool_connections`, `flt_redis_up`, `flt_auth_revocation_check_skipped_total`, info-метрика `flt_instance_info{instance_id, role, version, stand}`; лаг консьюмеров Kafka отдаёт `kafka-exporter`. Бизнес-метрики модулей именуются `flt_<module>_<metric>[_<unit>][_total]` и объявляются в пакете модуля; метки с неограниченным множеством значений (`user_id`, `session_id`, сырой путь, текст) запрещены; ТЗ фичи перечисляет её метрики. Prometheus собирает метрики со всех инстансов без правки конфигурации при `--scale` и HPA (DNS-обнаружение в compose, Kubernetes SD по аннотациям в Helm), интервал 15 с, хранение 30 дней; экспортёры PostgreSQL, Redis, Kafka, HAProxy (`:8404`) и node-exporter входят в состав этапа 1.
- **Health-эндпоинты** (аналог actuator, есть в boilerplate): `/v1/health` — liveness, всегда 200, внешние зависимости на код ответа не влияют, в теле — информационные детали `checks.redis`, `checks.opensearch`, `checks.qdrant`; `/v1/ready` — readiness по роли: `api` — PostgreSQL доступен, `worker` — PostgreSQL и Kafka, `media_agent` — PostgreSQL и LiveKit; Redis в readiness **не входит** (иначе его отказ снял бы с балансировки все инстансы сразу); при отказе — 503 с деталями, тело вне конверта `ErrorResponseV1`; результат кэшируется 5 с. Их используют HAProxy (`httpchk` каждые 2 с), probes в Kubernetes (`livenessProbe /v1/health`, `readinessProbe /v1/ready`, `startupProbe`) и healthcheck в docker-compose. `/v1/info` и `/v1/system-metrics` boilerplate удаляются.
- **Логи**: структурированные JSON-логи в stdout (на local — консольный рендер). Обязательные поля: `@timestamp` (ISO 8601 UTC), `level`, `logger`, `message`, `module` (второй сегмент имени логгера `flt.<module>.*`, иначе `core`), `instance_id` (`HOSTNAME`), `role`, `stand`, `request_id` (заголовок `X-Request-ID` от HAProxy, для Kafka — заголовок сообщения `request_id`, возвращается клиенту в ответе), `user_id` (только UUID), `trace_id`/`span_id` при активном span-е, поля access-лога (`http.*`, `network.client.ip`, `duration`), `exception`. Логи всех контейнеров собирает Fluent Bit (compose — logging driver `fluentd`; Kubernetes — DaemonSet) и доставляет в индексы `flt-logs-YYYY.MM.DD` OpenSearch с хранением 14 дней (`LOGS_RETENTION_DAYS`). Просматриваются логи в Grafana через источник данных OpenSearch. **Запрещено логировать**: пароли, JWT и refresh-токены, API-ключи учеников и платформы, заголовки `Authorization` и `Cookie`, тела запросов и ответов, содержимое сообщений ученика и ответов LLM, email, имя, телефон, голос, имена файлов пользователя, presigned URL; защита — процессор `redact_sensitive_keys` shared kernel (маскирует ключи из списка и значения, похожие на JWT и ключи провайдеров), покрыт тестами. IP клиента в access-логе разрешён (срок хранения — SYS-02).
- **Трейсы**: экспорт OpenTelemetry выключен на этапах 1–3 (`OTLP_EXPORTER_ENDPOINT` пустой), инструментирование FastAPI и Kafka сохраняется, корреляция — по `request_id`. Включение (OpenTelemetry Collector и Grafana Tempo) — новым ADR не раньше этапа 4 (OQ-20).
- **Дашборды и алерты** Grafana хранятся в репозитории как код (`deploy/config/grafana/provisioning/`, `deploy/config/grafana/dashboards/`: инстансы, HTTP, WebSocket, Kafka, PostgreSQL, Redis, HAProxy, логи) и разворачиваются в обоих вариантах. Стартовые алерты: `FltInstanceDown`, `FltHigh5xxRate`, `FltKafkaConsumerLag`, `FltDiskSpaceLow`, `FltReadinessFailing`, `FltOpenSearchRed`, `FltRedisDown`, `FltAuthRevocationSkipped`. Канал оповещений — Telegram-бот (OQ-60), токен и `chat_id` — секреты ADR-013; на local и в CI уведомления выключены.

## Команды

Команды ниже — целевые по ADR-001, ADR-002, ADR-004, ADR-005, ADR-011; до завершения этапа 1 Г.1 в репозитории действуют команды boilerplate (`make help`, `yarn`). Строки с пометкой «после Г.1» появляются при доработке boilerplate.

Backend — из папки `src/backend/py-monolyth` (единая точка входа — `make`, полный список — `make help`):

```bash
make install          # зависимости через uv; py-main-lib — path-зависимость (после Г.1), сейчас ставится из ../py-main-lib
make dev              # dev-сервер с автоперезагрузкой (порт 8000); после Г.1 — роль all
make run              # запуск как в Docker; после Г.1 — роль migrate, затем api
make test             # тесты на локальном PostgreSQL
make test-docker      # тесты на одноразовом PostgreSQL в Docker
make test-cov         # тесты с покрытием (порог 75%)
make arch             # после Г.1: import-linter по .importlinter (входит в make check)
make check            # format → lint → mypy → arch (после Г.1) → security → tests (Definition of Done)
make migrate          # применить миграции Alembic; после Г.1 — по каждому модулю реестра (alembic -n <module> upgrade head)
make makemigration name="add_x"                      # создать миграцию; после Г.1: make makemigration module=identity name="add_user"
make migrate-downgrade module=identity rev=base      # после Г.1: откат миграций модуля (тесты, отладка)
make scaffold-module name=identity                   # после Г.1: сгенерировать модуль app/modules/identity (ADR-002)
make scaffold-entity name=Order                      # сгенерировать REST-сущность; после Г.1 обязателен module=<module>
make scaffold-subscriber topic=ORDER_CREATED value="svc.order.created.01"   # сгенерировать Kafka-консьюмер; после Г.1 обязателен module=<module>, значение топика по формату flt.<module>.<event>.v<N>
make compose-up       # поднять PostgreSQL, Redis, Kafka из deploy/docker-compose
make compose-down     # остановить их
make docker-build     # собрать Docker-образ сервиса (flt-backend после Г.1)
uv run python -m cli issue-token 00000000-0000-0000-0000-000000000002 --role ADMIN   # dev-токен для ручных запросов (после Г.5 — через TokenIssuer, ADR-006)
uv run python -m cli list-modules                    # после Г.1: список модулей реестра
uv run python -m cli create-user …                   # после Г.5: тестовый пользователь для E2E (ADR-006)
uv run python -m cli storage-init                    # после Г.4: бакеты, политики и lifecycle хранилища (ADR-007); выполняет роль migrate
APP_ROLE=api|worker|all|migrate|media_agent uv run python -m app   # после Г.1: точка входа образа по ролям (ADR-004)
uv run python -m app dlq replay --topic <topic>      # после Г.4: повторная обработка сообщений из DLQ (ADR-004)
uv run python -m app search reindex --module <m> --entity <e>   # после Г.4: перестроение индекса через алиас (ADR-014)
```

Frontend — из папки `src/frontend` (перед первым запуском `cp .env.example .env`; `corepack enable` включает pnpm нужной версии; до шага 1 Г.1 — `yarn`):

```bash
pnpm install          # зависимости (в CI — pnpm install --frozen-lockfile)
pnpm dev              # dev-сервер на порту 3000 (прокси /api, /ws, /flt-* на бэкенд; моки API через MSW при VITE_APP_ENABLE_API_MOCKING=true)
pnpm build            # production-сборка в dist/
pnpm lint             # ESLint (flat config)
pnpm format:check     # Prettier
pnpm check-types      # проверка типов
pnpm test             # Vitest
pnpm test:cov         # Vitest с порогом покрытия 70/60 (ADR-005)
pnpm test-e2e         # Playwright (проекты chromium-desktop, chromium-mobile, ar) на mock-сервере
pnpm api:generate     # orval: клиент, zod-схемы и MSW-моки из Analytics/Specs/<module>/api/openapi.yaml; типы WebSocket из asyncapi.yaml
pnpm api:check        # то же плюс git diff --exit-code — сгенерированный код не устарел (в CI)
pnpm i18n:extract     # i18next-cli extract: обновить файлы locales
pnpm i18n:check       # i18next-cli extract --ci и status: все ключи извлечены, нет пустых значений в en и ar (в CI)
pnpm generate         # генератор компонентов (plop)
pnpm storybook        # Storybook на порту 6006
pnpm build-storybook  # сборка Storybook (в CI)
```

Репозиторные инструменты — из папки `src/tools` (после Г.10, ADR-011): `uv run flt-tools traceability check|generate` (матрица трассировки из шапок спецификаций и тегов тестов), `uv run flt-tools contracts check` (Spectral по OpenAPI и AsyncAPI). Локальный агент — из папки `src/agent` (с этапа 4, ADR-008): `uv run python -m flt_agent [--headless] [--platform-url URL]`, `make check`.

docker-compose — из корня репозитория (нужен Docker):

```bash
docker compose -f deploy/docker-compose/docker-compose.yml up -d --build   # бэкенд и инфраструктура; сейчас Swagger — http://localhost:8000/docs, после Г.8 — http://flt.localhost/api/docs через HAProxy
docker compose -f deploy/docker-compose/docker-compose.yml logs -f backend  # после Г.8 сервисы называются api, worker, migrate
docker compose -f deploy/docker-compose/docker-compose.yml down            # остановить (с флагом -v — удалить и данные)
# после Г.8: стенд из N инстансов как в CI
docker compose -p flt -f deploy/docker-compose/docker-compose.yml -f deploy/docker-compose/docker-compose.ci.yml --profile ci up -d --wait --scale api=3
docker compose -p flt stop flt-api-2                                       # остановка одного инстанса в тестах масштабируемости
deploy/scripts/gen-secrets.sh [--ci]                                       # создать .env из .env.template (ADR-013)
```

Helm — `deploy/helm/flt/` (после Г.8): `helm lint deploy/helm/flt`, `helm template deploy/helm/flt | kubeconform -strict`, `helm install flt deploy/helm/flt -f deploy/helm/flt/values-ci.yaml --wait` в kind (ADR-011).

Git — единый pre-commit в корне репозитория (`pre-commit install`, после Г.1): ruff, uv-lock, bandit, detect-secrets и lint-imports для backend, `pnpm lint-staged` для frontend, markdownlint для `Analytics/`, actionlint для workflow-ов (ADR-011).

## Ключевые архитектурные требования

- **Архитектурные решения ADR-001…ADR-015** (`Analytics/ADR/`, accepted 2026-10-10) обязательны для SYS, ТЗ и кода; разделы этого файла — их краткое отражение, при расхождении действует ADR. Пересмотр решения — только новым ADR (статус `superseded`).
- **LLM-агностичность**: любая функция должна работать с любым подключённым провайдером (внешним или локальным) через единый интерфейс провайдера `llm_gateway` (ADR-009, SYS-08); локальный агент тело запроса не интерпретирует (ADR-008). Не завязываться на API конкретного вендора вне слоя адаптеров. То же относится к провайдерам синтеза и распознавания речи (`speech`) и к AI-преподавателю в LiveKit (ADR-015: плагины поставщиков `livekit-agents` напрямую не используются).
- **i18n с первого дня**: язык интерфейса и изучаемый язык — разные настройки. Поддержка LTR и RTL, арабской вязи, иероглифов. Не хардкодить строки UI. Языки интерфейса на старте: русский, английский, арабский.
- **Уровни CEFR (A1–C2)**: текущий, рабочий и целевой уровень — отдельные сущности; прогресс ведётся параллельно по каждому изучаемому языку.
- **Расширяемость**: плагины (UI, языки, LLM/серверы), MCP, скилы — закладывать точки расширения в каркас, даже если сами плагины будут на этапе 7.
- **Разграничение ролей**: права проверять на сервере, не только в UI.
- **Персональные данные**: 152-ФЗ — хранение на территории РФ, согласия, удаление по запросу, отдельное согласие на передачу данных зарубежным LLM-провайдерам (и провайдерам речи). Согласия хранятся в таблице `identity.consents` (`kind`: `personal_data`, `age_18plus`, `foreign_llm_transfer`; версия текста, время, отзыв — ADR-006). На старте только пользователи 18+: чекбокс-самодекларация в форме регистрации и при первом входе через OAuth, хранятся факт и время подтверждения, без подтверждения доступ к обучению закрыт, формулировки — в SYS-02 (OQ-14). Удаление аккаунта публикует событие `identity.user_deleted`, по которому модули удаляют файлы (`u/<owner_user_id>/*`, ADR-007) и документы индексов (ADR-014). Секреты, API-ключи и персональные данные не попадают в логи (список и процессор маскирования — раздел «Наблюдаемость»).
- **API-ключи учеников** к внешним LLM хранятся на сервере в зашифрованном виде: AES-256-GCM, случайный nonce, AAD — `user_id` и `provider_id`, в записи — `ciphertext`, `nonce`, `key_version`; клиенту возвращаются только последние 4 символа (ADR-013 §3.4, SYS-08). Ключи шифрования `LLM_KEYS_ENCRYPTION_KEYS` с активной версией — в Vault (Kubernetes) или `.env` (docker-compose); ротация — добавить версию, переключить активную, перешифровать фоновым заданием.
- **Горизонтальное масштабирование**: монолит не хранит состояние в инстансе и масштабируется запуском новых инстансов (раздел «Масштабирование и состояние»).
- **Капча**: Yandex SmartCaptcha за интерфейсом провайдера капчи (заглушка в тестах, включение по конфигурации); показывается только после превышения мягкого лимита — со второго быстрого теста с одного IP за сутки, для регистрации аналогично (OQ-10).
- **Электронная почта**: единый SMTP-клиент в shared kernel, параметры и секреты — из конфигурации; провайдер задаётся конфигурацией: в продуктиве российский транзакционный сервис, в dev, test и CI — Mailpit (OQ-11).
- **Вход через OAuth** (Google, Яндекс ID, VK ID): код за флагами конфигурации — без ключей кнопка провайдера скрыта; автотесты — на mock OIDC-провайдере, ручная проверка с реальными приложениями — к гейту G3 по VIS-05 (OQ-12).
- **Стартовые цифры нагрузки** (рабочие допущения SYS-02, уточняются после запуска): 100 одновременных пользователей, 300 WebSocket-соединений, 50 одновременных LLM-стримов, 10 000 зарегистрированных за первый год, p95 REST ≤ 300 мс без обращения к LLM, класс до 30 человек, до 5 одновременных групповых занятий; нагрузочные тесты — Locust на стенде из N инстансов (OQ-13).

## Соглашения

- Язык (OQ-03): идентификаторы, имена файлов, пути REST API, топики Kafka, ключи i18n, имена тестов, переменные окружения, сообщения коммитов — английский; docstring-и, комментарии в коде, документация и аналитика — русский.
- Стиль кода backend: по правилам boilerplate — ruff, mypy strict, Google-style docstring обязателен для каждого модуля, класса и функции; те же правила — для `src/agent`, `src/protocol` и `src/tools` (ADR-008, ADR-011). Frontend: ESLint flat config и Prettier (ADR-005), имена файлов и папок в kebab-case, абсолютные импорты через `@/`.
- Политика версий (ADR-001 §3.2): «последняя стабильная» для библиотек — без pre-release, для CPython и Node — линия с вышедшей `X.Y.1` (Node — Active LTS), для образов — последняя стабильная минорная линия. Диапазоны — в `pyproject.toml` и `package.json`, точные версии — в `uv.lock` (`make lock`, вручную не правится) и `pnpm-lock.yaml`. Renovate (`renovate.json` в корне, GitHub App) по понедельникам: lock-файлы и минорные обновления — одним PR, мажорные — отдельным PR на пакет с меткой `deps:major` (Claude выполняет как мини-задачу: changelog, миграция, `make check`), runtime и базовые образы — метка `deps:runtime`; автослияние выключено. Явные потолки (`faststream <0.8`, `redis <7`, `SQLAlchemy <2.1`) снимаются только мажорным PR с обоснованием. Ревью отложенных обновлений — на гейте GS каждого этапа.
- CI (ADR-011, SYS-12-R4): слияние в `main` только при успехе обязательных проверок `ci-ok`, `backend-quality`, `architecture`, `backend-tests`, `frontend`, `tools`, `contracts`, `docs`, `commits`, `dependency-audit`, `images`, `stand-n3`, `e2e`, `helm`; тяжёлая ступень выполняется для PR вне draft, с меткой `ci:full`, на `main` и по тегам; secrets CI — только в GitHub Secrets и Environments; деплой на VPS — вручную через `workflow_dispatch` (`deploy-vps.yml`) с подтверждением в окружении `prod`; release по тегу `stage-N` публикует образы и chart в GHCR; branch protection и tag protection настраивает пользователь.
- Ветвление и коммиты (OQ-05), действует с этапа 1:
  - `main` защищён: прямые коммиты запрещены, слияние только через PR с зелёным CI.
  - На каждое ТЗ — ветка `feat/<id>-<slug>` от `main`, ID строчными: `feat/vis-04-registration`. Один шаг конвейера (SDD_plan.md §5) — один коммит. PR-черновик открывается на шаге 2 (черновик ТЗ); на шаге «код backend green» (SDD_plan.md §5, шаг 9) PR переводится из draft в ready, что запускает тяжёлую ступень CI (стенд из N инстансов, E2E, Helm), и её полный прогон ждётся до рефакторинга (ADR-011, OQ-70); слияние — merge-коммитом без squash на гейте G3.
  - ADR и системные спецификации этапа N пишутся в ветках `spec/stage-N-adr` и `spec/stage-N-sys` (на этапе 1 — `spec/stage-1-adr` и `spec/stage-1-sys`); PR открывается при утверждении блока.
  - Сообщения коммитов — Conventional Commits на английском: `<type>(<scope>): <subject>`, где type — один из `spec`, `test`, `feat`, `fix`, `refactor`, `deploy`, `docs`, `ci`; scope — модуль; subject начинается с ID ТЗ. Пример: `test(identity): VIS-04 add red backend tests for registration`.
  - Конец каждого этапа помечается тегом релиза `stage-N` (`stage-1`).
- Новые требования и изменения фиксировать в `Analytics/`, а не только в коде.

## Правила для Claude

- Решения ADR-001…ADR-015 обязательны: перед SYS, ТЗ и кодом сверяться с ними и с разделами этого файла; расхождение с ADR не додумывать, а остановиться и предложить правку (новый ADR или `changed`-версия документа).
- Backend пишется только на Python 3.14 (FastAPI, SQLAlchemy, Alembic). Другие языки на бэкенде не предлагать и не использовать. Локальный агент (`src/agent`), протокол (`src/protocol`) и репозиторные инструменты (`src/tools`) — тоже Python с теми же линтерами.
- Бэкенд развивается из boilerplate в `src/backend/py-monolyth`: соблюдать `src/backend/py-monolyth/CLAUDE.md` с учётом «Отличий проекта от boilerplate», новый код сначала генерировать скаффолдером (после Г.1 — в модуль: `make scaffold-module`, `--module`), перед коммитом прогонять `make check` (включая `make arch`).
- Фронтенд развивается из boilerplate в `src/frontend`: соблюдать `src/frontend/docs` с учётом «Отличий проекта от boilerplate» фронтенда и ADR-005, перед коммитом прогонять `pnpm lint`, `pnpm check-types`, `pnpm test` (до шага 1 Г.1 — `yarn`); после изменения `openapi.yaml` или `asyncapi.yaml` выполнять `pnpm api:generate`.
- Все исходники — только внутри `src/` в подпапках по компонентам: `src/backend`, `src/frontend`, `src/agent`, `src/protocol`, `src/tools`. Репозиторные скрипты (матрица трассировки, правила контрактов и подобное) — только в пакете `src/tools/` (`flt_tools`) с тестами и линтерами бэкенда, не в корне и не в `Analytics/`; скрипты развёртывания — в `deploy/scripts/` (ADR-011).
- Тип взаимодействия выбирать по разделу «Взаимодействие»: REST, WebSocket или Kafka.
- Метрики, логи и health-эндпоинты делать по разделу «Наблюдаемость».
- Новые контейнеры добавлять одновременно в docker-compose и Helm и отражать в таблице «Состав контейнеров».
- Никогда не хранить состояние в памяти процесса или на диске инстанса: постоянное — в PostgreSQL, in-memory — в Redis. Для каждой фичи писать тесты на N инстансах монолита.
- При каждой задаче проверять логичность разбиения на модули и предлагать исправление, если оно нарушается.
- Работать только по утверждённой спецификации. Нет спецификации — сначала предложить её черновик по шаблону.
- Порядок работы над фичей: спецификация → тесты (red) → код (green) → рефакторинг → проверка по Definition of Done.
- Никогда не выдавать функционал без автотестов и не отключать/ослаблять тесты ради зелёной сборки.
- Перед реализацией фичи сверяться с BRD и текущим этапом; не реализовывать функциональность более поздних этапов без запроса.
- При неоднозначности требований — спрашивать или заводить вопрос в `Analytics/open-questions.md` (OQ-NN), а не додумывать.
- Всегда соблюдать границы модулей (backend и frontend). Если задача требует нарушить границу — остановиться и предложить изменение публичного API модуля.
- Изменения в развёртывании вносить сразу в docker-compose и в Helm charts; общие конфигурации — в `deploy/config/`.
- Не коммитить секреты (API-ключи LLM-провайдеров и т.п.): секреты — только через переменные окружения, которые в docker-compose приходят из `.env`, а в Kubernetes — из Vault через External Secrets Operator (ADR-013). Новый секрет — строка в таблице секретов (SYS-11), имя переменной в `deploy/docker-compose/.env.template` и в `ExternalSecret` Helm, при необходимости генерация в `gen-secrets.sh`; значения вводит пользователь. В `envs/` и `.env.template` — только имена и несекретные локальные значения (тестовые значения стенда local помечаются `# pragma: allowlist secret`).
- Ветки и PR: PR переводить из draft в ready на шаге «код backend green» конвейера и дожидаться полного прогона CI до рефакторинга (ADR-011, OQ-70); метка `ci:full` — полный прогон на draft по требованию.
- Использовать термины и их английские имена из `Analytics/glossary.md` в ТЗ, коде, тестах и ключах i18n. Новый термин — сначала в глоссарий, потом в документ или код.
- Перед написанием ADR, SYS и ТЗ сверяться с решениями в `Analytics/open-questions.md`: принятое решение не пересматривать и не предлагать заново без запроса человека.
- На шаге 14 конвейера (SDD_plan.md §5) обновлять `Analytics/traceability.md` и `_module.md` затронутых модулей и переводить ТЗ в статус `implemented`.
- Ветки, коммиты и PR вести по правилу ветвления из раздела «Соглашения»: ветка на ТЗ, один коммит на шаг конвейера, Conventional Commits, слияние через PR на гейте G3.
