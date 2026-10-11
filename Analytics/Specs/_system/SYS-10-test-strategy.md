# SYS-10 — Тестовая стратегия

| Поле | Значение |
|---|---|
| Статус | approved |
| Версия | 1.1 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-11 (PR #3) |
| Пункт(ы) BRD | все |
| Модуль | все (backend, frontend, `src/tools`, deploy — в части стендов для тестов) |
| Зависимости | ADR-002, ADR-003, ADR-004, ADR-005, ADR-006, ADR-009, ADR-010, ADR-011, ADR-013 (accepted); SYS-05 (методика тестов на N инстансах), SYS-03 и SYS-04 (контракты для контрактных тестов), SYS-06 (матрица прав для негативных тестов) |
| Связанные ADR/SYS | ADR-001, ADR-007, ADR-012, ADR-014; SYS-02, SYS-08, SYS-11, SYS-12, SYS-13 (этап 7) |

## 1. Цель и область действия

- **Цель**: задать единые правила тестирования FLT на всех уровнях — какие тесты обязательны, какими инструментами пишутся, где лежат, как связываются с критериями приёмки и требованиями, как изолируются от внешних сервисов и от локальных данных, какие пороги покрытия и бюджеты времени действуют и что делать с нестабильными тестами, — чтобы цикл TDD «red → green → refactor» выполнялся Claude без устных пояснений и проверялся человеком на гейте G2.
- **Область действия**: backend (`src/backend/py-monolyth/tests`), frontend (`src/frontend/src/**/*.test.tsx`, `src/frontend/e2e`), репозиторные инструменты (`src/tools`), deploy (контейнеры и профили для тестов), CI (job-ы, запускающие тесты). Локальный агент (`src/agent`, этап 4) наследует правила backend.
- **Действует с этапа**: 1 (п. Г.2 архитектурные тесты, Г.3 тестовая инфраструктура, далее каждая фича).
- **Уточняет**: CLAUDE.md, разделы «Процесс разработки: спецификации + TDD» (подразделы «TDD», «Уровни тестов»), «Определение готовности», «Отличия проекта от boilerplate» п. 10 (тестовая БД — решает OQ-31); SDD_plan.md §5 шаги 5–7, 9–11; ADR-011 (job-ы тестов), ADR-005 (тесты frontend), SYS-05 (тесты на N инстансах).

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| TDD, Критерий приёмки (AC), Гейт, Конвейер фичи, Контрактный тест, Архитектурный тест, Тест масштабируемости, Матрица трассировки | [глоссарий](../../glossary.md), раздел 12 |
| Тег критерия | Пометка теста ID критерия приёмки `<ID ТЗ>-AC<N>` или ID требования `SYS-NN-R<M>`: маркер pytest `ac`/`req`, ID в квадратных скобках в имени теста Vitest, тег Playwright `@<ID>` (R12–R14) |
| Тестовая БД | База PostgreSQL `flt_test`, отдельная от базы стенда local `flt`; её схемы создают и удаляют миграции в сессии pytest (R4) |
| Кассета | Файл `tests/fixtures/llm_cassettes/<module>/<name>.yaml` (LLM) или `tests/fixtures/speech_cassettes/<name>.yaml` (речь) с записанными запросом и ответом внешнего LLM-провайдера, который заглушка воспроизводит в тестах (R18) |
| Режим `record` / `replay` | Режим заглушки LLM: `record` вызывает реальный провайдер и сохраняет кассету (только локально, с реальным ключом); `replay` читает кассету и не ходит в сеть (единственный режим в CI) |
| Карантин | Временное исключение нестабильного теста из блокирующих проверок с обязательной ссылкой на issue и сроком (R29) |
| Смоук-набор (`@smoke`) | Минимальный набор тестов «ходячего скелета» (SDD_plan.md, этап 1 Г.11), которым проверяются стенд N3, kind и прод после деплоя (R31) |
| Фабрика | Генератор тестовых объектов (`polyfactory`) с детерминированным seed; сид — набор данных, загружаемый в БД перед тестом или E2E (R16) |

## 3. Требования

Группы: уровни и расположение (R1–R3), тестовая БД и фикстуры хранилищ (R4–R6), контрактные и архитектурные тесты (R7–R8), frontend и покрытие (R9–R11), теги и трассировка (R12–R15), тестовые данные и время (R16–R17), заглушки внешних сервисов (R18–R23), правила TDD (R24–R27), специальные виды тестов (R28–R36), детерминизм и данные i18n (R37–R38).

### SYS-10-R1 Обязательные уровни тестов

- **Формулировка**: Каждая фича должна быть покрыта тестами уровней из таблицы ниже в соответствии с тем, что она использует; фича без тестов хотя бы одного применимого уровня не должна переходить в статус `implemented`.
- **Обоснование**: CLAUDE.md «TDD»: «Фича без тестов не считается готовой»; «Уровни тестов» CLAUDE.md; SDD_plan.md §5 шаги 5–7.
- **Проверка**: раздел 13 ТЗ («План тестов») заполнен для каждого AC; `flt-tools specs check` (SYS-12) сверяет теги тестов с AC для ТЗ `implemented`; ревью G2.
- **Применимость**: все.

| Уровень | Что проверяет | Инструменты | Где лежит | Когда обязателен |
|---|---|---|---|---|
| Unit backend | функция, класс, сервис в изоляции; Lua-скрипты и фабрики — с реальным Redis | pytest, pytest-asyncio, pytest-mock | `tests/core/**`, `tests/modules/<module>/unit/**` | всегда для доменной логики |
| Интеграционный backend | модуль через публичный API (`Protocol`) и REST-роутер с реальными PostgreSQL и Redis, Kafka — `TestKafkaBroker` | pytest, httpx `ASGITransport`, `TestKafkaBroker`, MinIO в контейнере при работе с файлами | `tests/modules/<module>/integration/**` | всегда для каждого AC с данными |
| Контрактный REST | сгенерированный FastAPI OpenAPI совпадает с `Analytics/Specs/<module>/api/openapi.yaml` | pytest, `openapi-spec-validator`, нормализованное сравнение (R7) | `tests/modules/<module>/contract/test_openapi.py` | у каждого модуля с роутером |
| Контрактный AsyncAPI | события Kafka и сообщения WebSocket совпадают с `asyncapi.yaml` | pytest, Pydantic-схемы событий, AsyncAPI FastStream (R7) | `tests/modules/<module>/contract/test_asyncapi.py` | у каждого модуля с Kafka или WebSocket |
| Архитектурный | границы модулей, запреты SYS-05, раскладка | import-linter, pytest AST-тесты | `tests/architecture/**` | всегда (общий набор) |
| Негативные тесты прав | каждая роль из матрицы SYS-06 получает 401/403 там, где не разрешено | pytest, параметризация по ролям (R26) | `tests/modules/<module>/contract/test_permissions.py` | у каждого модуля с роутером или каналом |
| Миграции | обратимость, совместимость с данными | pytest (R27) | `tests/modules/<module>/migrations/**`, `tests/architecture/test_migrations_*.py` | при каждой миграции, меняющей существующие данные |
| Frontend unit и компоненты | компоненты, хуки, zustand-store, i18n | Vitest, Testing Library, MSW из контракта | `src/features/<module>/**/*.test.tsx`, `src/components/**`, `src/lib/**` | всегда для компонентов с логикой |
| Frontend модуля | экран модуля с моками REST (orval MSW) и WebSocket (`msw` `ws.link`) по контракту | Vitest, MSW | `src/features/<module>/__tests__/**` | у каждого экрана из раздела 8.1 ТЗ |
| E2E на mock-сервере | сценарии ТЗ на всех языках интерфейса | Playwright, mock-server (Express + MSW) | `src/frontend/e2e/tests/<module>/**` | у каждого сценария раздела 2 ТЗ |
| E2E на стенде N3 | смоук «ходячего скелета», остановка инстанса | Playwright против HAProxy стенда N3 | `src/frontend/e2e/smoke/**` | смоук — всегда; сценарии фичи — если ТЗ требует реального бэкенда |
| Тесты на N инстансах | шесть сценариев SYS-05 | pytest, маркер `n_instances` | `tests/n_instances/<module>/**` | по таблице 6.7 ТЗ |
| Нагрузочные | p95 REST ≤ 300 мс при 100 пользователях, 300 WebSocket (SYS-02) | Locust (R34) | `tests/load/**` | с этапа 2: необязательный job; обязательный прогон на GS |
| Security | статический анализ, зависимости, права, песочница плагинов | bandit, `pip-audit`, `pnpm audit`, тесты R26, тесты SYS-13 (этап 7) | `tests/security/**` (этап 7), CI | всегда (bandit, audit); этап 7 — песочница |

### SYS-10-R2 Расположение тестов зеркалит код

- **Формулировка**: Тесты backend должны лежать по схеме `tests/core/<путь как в app/core>`, `tests/modules/<module>/{unit,integration,contract,migrations}/`, `tests/architecture/`, `tests/n_instances/<module>/`, `tests/load/`, `tests/fixtures/` (в том числе `llm_cassettes/<module>/`, `speech_cassettes/`, `llm_stub/`), `tests/seeds/`; тесты frontend — рядом с кодом (`*.test.ts`, `*.test.tsx`) или в `__tests__/` модуля, E2E — в `src/frontend/e2e/tests/<module>/` и `e2e/smoke/`; тест одного модуля не должен импортировать тесты и фикстуры другого модуля.
- **Обоснование**: ADR-002, раздел 3.1, правило 6 (тесты зеркалят `app/modules/<module>`); при выделении модуля его тесты переносятся вместе с ним.
- **Проверка**: архитектурный тест `tests/architecture/test_test_layout.py` (будет создан): каждый каталог `tests/modules/<name>` соответствует модулю реестра; в `tests/modules/<a>/**` нет импортов `tests.modules.<b>`; каждый файл в `tests/n_instances/**` помечен `n_instances` (SYS-05-R45); ESLint `import-x/no-restricted-paths` для тестов frontend (зоны модулей распространяются на `*.test.tsx`).
- **Применимость**: backend, frontend.

### SYS-10-R3 Реальные хранилища в интеграционных тестах

- **Формулировка**: Интеграционные тесты backend должны использовать реальные PostgreSQL (база `flt_test`) и Redis (база данных Redis `15` того же экземпляра) и реальный MinIO, если фича работает с файлами; подмена PostgreSQL на SQLite, Redis на `fakeredis` и MinIO на `moto` запрещена; Kafka в unit- и интеграционных тестах заменяется `TestKafkaBroker` FastStream в роли `all`, реальная Kafka используется только на стенде N3.
- **Обоснование**: CLAUDE.md «Уровни тестов»: интеграционные тесты «с реальными PostgreSQL, Redis, Kafka и, если фича их использует, MinIO»; Lua-скрипты, `FOR UPDATE SKIP LOCKED`, схемы и `citext` не воспроизводятся заменителями; ADR-011: job `backend-tests` с `services:` PostgreSQL и Redis без Kafka.
- **Проверка**: архитектурный тест `tests/architecture/test_test_layout.py::test_no_storage_fakes` (будет создан: в `pyproject.toml` и `tests/` отсутствуют `fakeredis`, `moto`, `aiosqlite`, `sqlite`); `pytest-socket` (R37) разрешает соединения только к `127.0.0.1`.
- **Применимость**: backend, tests.

### SYS-10-R4 Тестовая БД `flt_test` (решает OQ-31)

- **Формулировка**: pytest должен работать с отдельной базой PostgreSQL `flt_test` (роль `flt`, тот же экземпляр, что у стенда local) и базой Redis с индексом `15`; оверлей `envs/.test.env` должен задавать `PG_DATABASE=flt_test`, `REDIS_DB=15`, `TEST_MODE=true`, а сессионная фикстура `db_migrate` должна отказываться работать, если `TEST_MODE` не установлен или имя базы не оканчивается на `_test`; базу `flt_test` создают init-скрипт контейнера PostgreSQL (`deploy/docker-compose/postgres/init/01-create-test-db.sql`, каталог по SYS-11-R17) для `make compose-up`, `make test-docker` для одноразовых контейнеров и шаг job `backend-tests` в CI.
- **Обоснование**: OQ-31 (planned → SYS-10): pytest и стенд local делят базу `flt` и схему `ms_py_test`, запуск тестов стирает локальные данные (CLAUDE.md «Отличия проекта от boilerplate», п. 10). Выбран вариант 1 из карточки OQ-31 (отдельная база в том же PostgreSQL): он совпадает со способом запуска в CI (`services:` PostgreSQL и Redis — ADR-011) и не требует Docker при локальном запуске; вариант 2 (testcontainers) отвергнут, так как дублирует `services:` CI вторым механизмом, замедляет старт и требует Docker API у pytest; `make test-docker` (вариант 3) сохраняется как способ запуска без локальной инфраструктуры и расширяется контейнером Redis. Схема `ms_py_test` исчезает вместе с переходом на схемы модулей (ADR-003). Параллельный запуск `pytest-xdist` не применяется на этапе 1 (сессионные миграции); при появлении потребности каждый worker получает базу `flt_test_<worker_id>` тем же механизмом.
- **Проверка**: тест фикстуры `tests/core/test_test_db_guard.py` (будет создан: `db_migrate` поднимает `AssertionError` при `PG_DATABASE=flt`); `make test` документирован в `tests/README.md`; CI `backend-tests` создаёт базу командой `psql -c 'CREATE DATABASE flt_test'` перед pytest; тест `test_local_stand_db_untouched` (будет создан: после сессии тестов в базе `flt` нет схем модулей, созданных тестами).
- **Применимость**: backend, deploy, CI.

### SYS-10-R5 Фикстуры PostgreSQL: миграции на сессию, очистка между тестами

- **Формулировка**: Сессионная фикстура `db_migrate` должна выполнять `alembic -n <module> upgrade head` для каждого модуля реестра на старте сессии и `downgrade base` в её конце; между тестами изоляция обеспечивается фикстурой `clean_tables` (autouse для интеграционных тестов): `TRUNCATE <все таблицы всех модулей> RESTART IDENTITY CASCADE` после теста; тесты не должны полагаться на порядок выполнения и на данные других тестов.
- **Обоснование**: Boilerplate накатывает и откатывает миграции на сессию (`tests/conftest.py`), но не очищает данные между тестами; сервисный код делает `commit`, поэтому откат внешней транзакции не подходит; `TRUNCATE` всех таблиц модулей выполняется за миллисекунды и не зависит от порядка.
- **Проверка**: тест `tests/core/test_fixtures.py::test_tables_empty_at_start` (будет создан; запускается дважды в одной сессии в случайном порядке — `pytest -p randomly` с фиксированным seed, R37); фикстура `db_migrate` проверяет пустоту `information_schema.tables` для схем модулей перед `upgrade`.
- **Применимость**: backend, tests.

### SYS-10-R6 Фикстуры Redis: очистка и контроль TTL

- **Формулировка**: Фикстура `redis_clean` (autouse для интеграционных тестов) должна выполнять `FLUSHDB` базы `15` перед тестом; фикстура `redis_no_persistent_keys` (autouse) после теста должна обойти ключи `SCAN` и упасть, если у ключа `TTL == -1`, если ключ не начинается с префикса модуля или `shared_kernel:`, или если TTL превышает максимум категории SYS-05-R13; фикстура `redis_down` должна переключать `ModuleRedis` на закрытый порт для проверки поведения без Redis (SYS-05-R15).
- **Обоснование**: ADR-003, п. 2.6 A и 4.3 («Фикстура pytest: проверка `TTL == -1` после каждого теста»); SYS-05-R12, R13, R15.
- **Проверка**: тесты фикстур `tests/core/redis/test_fixtures.py` (будут созданы: ключ без TTL, созданный сырым клиентом в тесте, ведёт к падению фикстуры с именем ключа; `redis_down` даёт `ConnectionError` на `ModuleRedis.get`).
- **Применимость**: backend, tests.

### SYS-10-R7 Контрактные тесты REST и AsyncAPI

- **Формулировка**: Для каждого модуля с роутером тест `test_openapi_matches_spec` должен сравнивать нормализованный OpenAPI приложения (`app.openapi()`, только пути с префиксом модуля и его `extra_prefixes`) с `Analytics/Specs/<module>/api/openapi.yaml` по путям, методам, параметрам, схемам запросов и ответов и кодам ответов (описания и примеры игнорируются) и падать при любом расхождении; для каждого модуля с Kafka или WebSocket тест `test_asyncapi_matches_spec` должен сравнивать каналы, имена сообщений и JSON Schema их payload, сгенерированные из Pydantic-моделей событий и сообщений модуля, с `asyncapi.yaml`; оба контракта проходят валидацию стандарта (`openapi-spec-validator`, парсер AsyncAPI).
- **Обоснование**: CLAUDE.md «Взаимодействие»: «FastAPI генерирует OpenAPI из кода, контрактные тесты сверяют его с контрактом из ТЗ»; ADR-004, раздел 3.4 (контрактный тест AsyncAPI); frontend генерирует клиент из этих же файлов (ADR-005), поэтому расхождение ломает клиента.
- **Проверка**: тесты `tests/modules/<module>/contract/test_openapi.py`, `test_asyncapi.py` (будут созданы по шаблону shared kernel `tests/contract_utils.py`); правила нормализации (сортировка ключей, удаление `description`, `summary`, `example`, `examples`, `x-flt-*` кроме `x-flt-state-endpoint`) фиксируются в SYS-03 и SYS-04; job `contracts` (Spectral) проверяет сами файлы контрактов.
- **Применимость**: backend, tests.

### SYS-10-R8 Архитектурные тесты — общий набор

- **Формулировка**: Каталог `tests/architecture/` должен содержать тесты из таблицы ADR-002 (раздел 3.6), тесты SYS-05 (R1–R3, R7–R8, R14, R18, R22, R33–R37, R42, R44–R45) и негативный тест `test_boundary_violation_breaks_build`; каждый архитектурный тест несёт маркер `req` с ID требования, которое он проверяет, и выполняется в job `architecture` и в `make check`.
- **Обоснование**: SDD_plan.md, этап 1 Г.2 («архитектурные тесты пишутся первыми») и критерий выхода «нарушение границы модуля ломает сборку»; ADR-002, раздел 3.1 п. 6 (маркер требования обязателен).
- **Проверка**: `tests/architecture/test_test_layout.py::test_architecture_tests_have_req_marker` (будет создан); job `architecture` (SYS-12).
- **Применимость**: backend, tests, CI.

### SYS-10-R9 Тесты frontend: инструменты и правила

- **Формулировка**: Тесты компонентов и модулей frontend должны использовать Vitest, Testing Library и MSW, причём обработчики REST берутся из сгенерированных orval файлов `*.msw.ts` (при необходимости дополняются состоянием на `@mswjs/data`), обработчики WebSocket — из `src/testing/mocks/ws/<module>.ts` через `msw` `ws.link`; прямая подмена `fetch`, `axios` и `WebSocket` через `vi.mock` запрещена; рендер — через `src/testing/test-utils.tsx` с реальными ресурсами i18n `ru`; запросы к элементам — по роли и `aria-label`, по тексту — только там, где роль не применима.
- **Обоснование**: CLAUDE.md «Уровни тестов» (frontend: Vitest, Testing Library, MSW по контракту); ADR-005, разделы 3.3 и 3.5; подмена транспорта мимо MSW обходит контракт.
- **Проверка**: правило ESLint `no-restricted-syntax` для `vi.mock('axios')`, `vi.mock('@/lib/api-client')`, `vi.stubGlobal('fetch', …)`, `vi.stubGlobal('WebSocket', …)` в `eslint.config.js` (будет создано); `src/testing/setup-tests.ts` включает `server.listen({ onUnhandledRequest: 'error' })` — незамоканный запрос падает.
- **Применимость**: frontend.

### SYS-10-R10 Порог покрытия frontend

- **Формулировка**: `pnpm test:cov` должен падать при покрытии ниже `lines: 70`, `statements: 70`, `functions: 70`, `branches: 60` для `src/features/**`, `src/lib/**`, `src/components/**`, `src/hooks/**`, `src/utils/**` с исключениями `**/generated/**`, `**/*.stories.tsx`, `**/*.test.{ts,tsx}`, `src/testing/**`, `src/types/**`, `src/app/**`, `**/locales/**`; значения порогов не должны понижаться.
- **Обоснование**: ADR-005, раздел 3.7 (подтверждено пользователем 2026-10-10); CLAUDE.md: порог frontend задаётся ADR-005.
- **Проверка**: `coverage.thresholds` в `vite.config.ts`; job `frontend` (SYS-12); проверка «порог не понижен» — `flt-tools quality check-thresholds` сравнивает значения в PR с `main` (SYS-12).
- **Применимость**: frontend, CI.

### SYS-10-R11 Порог покрытия backend и состав измерения

- **Формулировка**: `make test-cov` должен измерять покрытие `app/` (без `app/*/migrations/**`, `app/__main__.py` и кода роли `migrate`) unit-, интеграционными, контрактными и архитектурными тестами и падать при покрытии ниже `fail_under = 75`; тесты `n_instances`, E2E и нагрузочные в измерение не входят; значение `fail_under` не должно понижаться, а тесты не должны исключать код из покрытия комментариями `# pragma: no cover` вне allowlist (`if TYPE_CHECKING:`, `raise NotImplementedError` в `Protocol`, `__repr__`).
- **Обоснование**: CLAUDE.md «TDD»: «Порог покрытия backend — не ниже 75% … повышать можно, понижать нельзя»; покрытие считает проверенную логику, а не достижимость на стенде.
- **Проверка**: `[tool.coverage]` в `pyproject.toml` (`omit`, `fail_under`); `flt-tools quality check-thresholds` (SYS-12); архитектурный тест `test_no_cover_pragmas_outside_allowlist` (будет создан).
- **Применимость**: backend, CI.

### SYS-10-R12 Маркеры pytest `ac` и `req`

- **Формулировка**: Каждый тест в `tests/modules/**`, `tests/n_instances/**` и `tests/core/**` должен нести хотя бы один маркер `@pytest.mark.ac("<ID ТЗ>-AC<N>")` (критерий приёмки) или `@pytest.mark.req("SYS-NN-R<M>")` (требование системной спецификации); каждый тест в `tests/architecture/**` — маркер `req`; значение маркера должно соответствовать регулярному выражению `^(VIS|ADM|STU|TCH)-\d{2}(\.\d+)?-AC\d+$` или `^SYS-\d{2}-R\d+$` и ссылаться на существующий критерий или требование в документе со статусом `approved`, `in-progress`, `implemented` или `changed`; один тест может нести несколько маркеров.
- **Обоснование**: SDD_plan.md §3: «Каждый тест помечается ID критерия приёмки (маркер pytest, имя теста в Vitest, тег в Playwright). По тегам автоматически строится матрица трассировки»; ADR-002, раздел 3.1 п. 6 (`req` для архитектурных тестов); OQ-33 (формат `SYS-NN-R<M>`).
- **Проверка**: плагин `tests/conftest.py` (`pytest_collection_modifyitems`): тест без маркера в перечисленных каталогах — ошибка сбора; `flt-tools traceability check` (R15) проверяет формат и существование ID и статус документа; маркеры зарегистрированы в `pyproject.toml`.
- **Применимость**: backend, tests.

### SYS-10-R13 Теги в Vitest

- **Формулировка**: Имя каждого теста Vitest в `src/features/**`, `src/lib/**`, `src/components/**`, `src/hooks/**` должно начинаться с одного или нескольких ID в квадратных скобках: `it('[STU-18-AC3] …')`, `test('[SYS-07-R4][SYS-07-R5] …')`; ID в `describe` не засчитывается.
- **Обоснование**: SDD_plan.md §3; шаблон ТЗ (раздел 13) предлагал `it("STU-18-AC3 …")` — квадратные скобки делают ID однозначно извлекаемым и отделяют его от текста; `describe` группирует несколько AC и не указывает, какой тест какой критерий покрывает.
- **Проверка**: локальное правило ESLint `flt/test-title-has-id` (файл `eslint-rules/test-title-has-id.js`, будет создано: для вызовов `it`, `test`, `it.each`, `test.each` первый аргумент соответствует `^(\[(VIS|ADM|STU|TCH)-\d{2}(\.\d+)?-AC\d+\]|\[SYS-\d{2}-R\d+\])+ `); `flt-tools traceability check`.
- **Применимость**: frontend.

### SYS-10-R14 Теги в Playwright

- **Формулировка**: Каждый тест Playwright должен объявлять теги через опцию `tag` (`test('…', { tag: ['@STU-18-AC3', '@smoke'] }, async () => …)`) с ID критериев в формате `@<ID>`; тег `@smoke` помечает сценарии «ходячего скелета»; тег в заголовке строкой (`test('@STU-18-AC3 …')`) не используется.
- **Обоснование**: SDD_plan.md §3; опция `tag` фильтруется `--grep @STU-18-AC3` и попадает в отчёт JSON, из которого матрица трассировки читает теги без разбора заголовков.
- **Проверка**: правило ESLint `flt/playwright-test-has-tag` (будет создано) для `src/frontend/e2e/**`; `flt-tools traceability check` читает `e2e/**/*.spec.ts` и `playwright-report/results.json`.
- **Применимость**: frontend (E2E).

### SYS-10-R15 Автогенерация матрицы трассировки

- **Формулировка**: Команда `uv run flt-tools traceability generate` (пакет `src/tools`, ADR-011) должна строить столбцы «Статус ТЗ» и «Тесты (теги)» разделов 6–10 `Analytics/traceability.md` из шапок спецификаций и тегов тестов, а `flt-tools traceability check` — пересобирать таблицы и падать, если файл в репозитории отличается; источники тегов: маркеры `ac`/`req` pytest (статический разбор декораторов в `src/backend/py-monolyth/tests/**` и, с этапа 4, `src/agent/tests/**`), имена тестов Vitest (`src/frontend/src/**/*.test.{ts,tsx}`), опция `tag` Playwright (`src/frontend/e2e/**/*.spec.ts`); промежуточный результат сохраняется в `reports/traceability.json`.
- **Обоснование**: SDD_plan.md §3 и `traceability.md`, раздел 3: «На этапе 1 по SYS-12 генерация матрицы автоматизируется в CI»; ADR-011 (job `docs`, пакет `flt_tools`).
- **Проверка**: unit-тесты `src/tools/tests/test_traceability.py` на фикстурах спецификаций и тестов (будут созданы); job `docs` (SYS-12) выполняет `check`; генерация выполняется на шаге 14 конвейера.
- **Применимость**: tests, CI, документация.

Формат ячейки «Тесты (теги)»: `<ID>-AC1…AC<N> (<покрыто>/<всего>)`, где «всего» — число AC в ТЗ, «покрыто» — число AC, у которых есть хотя бы один тег в любом источнике; для SYS — `R1…R<M> (<покрыто>/<всего>)` в разделе 10. Формат `reports/traceability.json`:

```json
{
  "generated_at": "2026-10-10T12:00:00Z",
  "specs": {
    "STU-18": {"path": "Analytics/Specs/learning_plan/STU-18-learning-plan.md", "status": "implemented", "acs": ["STU-18-AC1", "STU-18-AC2"]},
    "SYS-05": {"path": "Analytics/Specs/_system/SYS-05-state-and-scaling.md", "status": "approved", "reqs": ["SYS-05-R1"]}
  },
  "tags": {
    "STU-18-AC1": [{"kind": "pytest", "file": "src/backend/py-monolyth/tests/modules/learning_plan/integration/test_plan.py", "name": "test_create_plan"}],
    "STU-18-AC2": [{"kind": "vitest", "file": "src/frontend/src/features/learning-plan/__tests__/plan-form.test.tsx", "name": "[STU-18-AC2] shows duration"}],
    "SYS-05-R1": [{"kind": "pytest", "file": "src/backend/py-monolyth/tests/architecture/test_no_process_state.py", "name": "test_no_module_level_mutable_state"}]
  },
  "errors": []
}
```

### SYS-10-R16 Фабрики, детерминированные идентификаторы и сиды

- **Формулировка**: Тестовые объекты backend должны создаваться фабриками `polyfactory` (`ModelFactory` для Pydantic-схем, `SQLAlchemyFactory` для моделей) с `Faker`, инициализированным константой `FLT_TEST_SEED = 20261010`, и `__random_seed__` той же константой; идентификаторы сущностей в сидах и фикстурах должны браться из `tests/ids.py` (фиксированные UUID вида `00000000-0000-7000-8000-0000000000NN`, объявленные константами с именами по роли: `USER_LEARNER_1`, `USER_TEACHER_1`, `USER_PLATFORM_ADMIN`), а не генерироваться на лету; наборы данных для E2E и стенда N3 загружаются командой `python -m app seed --profile <e2e|n3>` (функции `tests/seeds/<module>.py`, идемпотентные, только на стендах с `TEST_MODE=true` или `STAND_NAME=test`).
- **Обоснование**: CLAUDE.md «TDD»: «тесты детерминированы»; одинаковые ID во всех прогонах делают падения воспроизводимыми и позволяют E2E ссылаться на пользователя по константе; `factory_boy` ориентирован на синхронные сессии и `Django`, `polyfactory` поддерживает Pydantic v2 и SQLAlchemy 2.0.
- **Проверка**: unit-тест `tests/core/test_factories_deterministic.py` (будет создан: две фабрики с одним seed дают одинаковые объекты); архитектурный тест `test_seeds_refuse_non_test_stand`; `python -m app seed` в job `stand-n3` и `e2e`.
- **Применимость**: backend, tests.

### SYS-10-R17 Управление временем

- **Формулировка**: Тесты, зависящие от времени, должны подменять `Clock` shared kernel фикстурой `frozen_clock` (`clock.set("2026-10-10T12:00:00Z")`, `clock.advance(timedelta(...))`), а не библиотеками `freezegun` и `time-machine` и не `sleep`; ожидание асинхронных эффектов — через опрос с таймаутом (`await eventually(lambda: …, timeout=2.0)`), а не фиксированные паузы.
- **Обоснование**: ADR-003, раздел 3, правило 3 (`Clock` подменяется в тестах); `sleep` делает тесты медленными и нестабильными; `freezegun` подменяет `datetime` глобально и ломает `asyncpg`.
- **Проверка**: правило ruff `ASYNC251` (`time.sleep` в async) и запрет `asyncio.sleep` с константой больше 0,1 с в тестах — архитектурный тест `test_no_sleep_in_tests` (будет создан; исключение — `tests/n_instances/**`, где опрос состояния стенда идёт с шагом 0,5 с); `freezegun` и `time-machine` отсутствуют в `pyproject.toml`.
- **Применимость**: backend, tests.

### SYS-10-R18 Детерминированная заглушка LLM: record/replay

- **Формулировка**: Провайдер `stub` модуля `llm_gateway` должен работать в режимах SYS-08-R25: `scripted` (по умолчанию в pytest, на стенде local и в CI: текст из `tests/fixtures/llm_stub/<scenario>.txt`) и `replay` (выбирается фикстурой `llm_stub` теста: ответ из кассеты `tests/fixtures/llm_cassettes/<module>/<name>.yaml`, выбранной по `request_hash` — `sha256` канонического JSON из `messages`, `llm_model`, `params`, `tools`, `response_format`), стримить дельты с задержкой `LLM_STUB_DELTA_DELAY_MS` (по умолчанию 20, в тестах — 0) и падать с ошибкой `CassetteMissingError` при отсутствии кассеты; в режиме `record` (только локально, при заданном реальном ключе провайдера и явном `LLM_STUB_RECORD_ALLOWED=1`; при `CI=true` запрещён валидатором настроек) — вызывать реального провайдера и записывать кассету с маскированием ключей и заголовков; кассеты не должны содержать персональные данные и реальные ключи.
- **Обоснование**: CLAUDE.md «TDD»: LLM-провайдеры в тестах подменяются заглушками, тесты детерминированы и не требуют сети или ключей; ADR-009, раздел 3.3 (провайдер `stub` с задержкой); ADR-011, раздел 3.6 (в тестах секретов нет).
- **Проверка**: unit-тесты `tests/modules/llm_gateway/unit/providers/test_stub.py` (будут созданы: `scripted` по сценарию, replay по ключу, `CassetteMissingError`, порядок `start → delta* → end`, `usage` из кассеты; `record` без `LLM_STUB_RECORD_ALLOWED` — ошибка); `detect-secrets` сканирует `tests/fixtures/llm_cassettes/**` и `tests/fixtures/speech_cassettes/**`; тест `tests/fixtures/test_cassettes_have_no_secrets.py` (регулярные выражения ключей провайдеров из ADR-010, п. 3.2.3); в CI переменная `LLM_STUB_MODE` не задаётся (`scripted` по умолчанию, `replay` — по фикстуре теста).
- **Применимость**: backend, tests, CI.

### SYS-10-R19 Заглушки синтеза и распознавания речи (этап 5)

- **Формулировка**: Модуль `speech` должен предоставлять провайдеры `stub` для TTS (возвращает детерминированный PCM16-сигнал заданной длительности, пропорциональной длине текста, и `visemes[]` из фикстуры) и STT (возвращает транскрипт из кассеты `tests/fixtures/speech_cassettes/<name>.yaml` по `sha256` аудио, промежуточные `partial` — префиксы финального текста); режимы `record`/`replay` — как у LLM (R18).
- **Обоснование**: CLAUDE.md «Технологический стек»: провайдеры речи по аналогии с LLM; ADR-009, раздел 3.7.
- **Проверка**: тесты `tests/modules/speech/unit/test_stub_providers.py` (этап 5); требование действует с появления модуля `speech`.
- **Применимость**: backend (этап 5).

### SYS-10-R20 Заглушки OAuth-провайдеров

- **Формулировка**: Интеграционные тесты OAuth (`identity`) должны подменять HTTP-вызовы к провайдерам фикстурами `respx` с ответами по форматам Google (OIDC: discovery, token с `id_token`, userinfo), Яндекс ID (`oauth.yandex.ru/token`, `login.yandex.ru/info`) и VK ID (`id.vk.com/oauth2/auth` с `device_id`, `user_info`), включая ошибочные ответы; E2E входа через Google должен выполняться против контейнера `mock-oidc` (`ghcr.io/navikt/mock-oauth2-server`, профиль `test` compose и `values-dev.yaml` Helm) с `OAUTH_GOOGLE_*` настроенными на него; E2E для Яндекс ID и VK ID не автоматизируется — ручная проверка к G3 по VIS-05 (OQ-12).
- **Обоснование**: OQ-12 (resolved): автотесты на mock OIDC-провайдере; ADR-006, раздел 3.6 («Тесты»); форматы Яндекс ID и VK ID не являются OIDC, и универсального контейнера для них нет.
- **Проверка**: тесты `tests/modules/identity/integration/test_oauth_<provider>.py` (этап 2); E2E `e2e/tests/identity/login-google.spec.ts` с тегом `@VIS-05-AC<N>`; контейнер `mock-oidc` в `docker-compose.yml` (профиль `test`) и Helm — тест паритета SYS-11.
- **Применимость**: backend, frontend (E2E), deploy.

### SYS-10-R21 Почта в тестах

- **Формулировка**: Unit- и интеграционные тесты не должны отправлять SMTP: SMTP-клиент shared kernel подменяется фикстурой `mail_outbox` (список отправленных писем в памяти теста); E2E и тесты на стенде N3 должны читать письма через HTTP API Mailpit (`GET /api/v1/messages`, контейнер `mailpit` профиля `test`).
- **Обоснование**: OQ-11 (resolved): Mailpit в dev, test, CI; E2E читает письма через HTTP API.
- **Проверка**: фикстура `mail_outbox` в `tests/conftest.py`; `pytest-socket` запрещает исходящие соединения, кроме `127.0.0.1` (R37); E2E-утилита `e2e/utils/mailpit.ts` (этап 2).
- **Применимость**: backend, frontend (E2E).

### SYS-10-R22 Заглушка капчи

- **Формулировка**: Провайдер капчи `stub` (интерфейс `CaptchaProvider` shared kernel) должен принимать токен `captcha-ok` и отклонять любой другой; на стендах `local`, `ci` и в pytest `CAPTCHA_PROVIDER=stub`, Yandex SmartCaptcha в тестах не вызывается.
- **Обоснование**: OQ-10 (resolved): капча за интерфейсом провайдера, заглушка в тестах, включение по конфигурации.
- **Проверка**: unit-тест `tests/core/captcha/test_stub.py` (этап 2); E2E быстрого теста и регистрации используют `captcha-ok` после мягкого лимита.
- **Применимость**: backend, frontend (E2E).

### SYS-10-R23 Хранилище файлов в тестах

- **Формулировка**: Тесты, работающие с файлами, должны использовать реальный MinIO (контейнер `minio` в `make compose-up`, `make test-docker` и `services:` job `backend-tests`) с бакетами, созданными `storage-init` в начале сессии; фикстура `storage_clean` удаляет объекты под префиксом теста после него; заглушка `FileStorage` допускается только в unit-тестах сервисов без проверки загрузки.
- **Обоснование**: CLAUDE.md «Уровни тестов» (MinIO в контейнерах, если фича их использует); presigned URL и политики бакетов (ADR-007) не воспроизводятся заглушками.
- **Проверка**: `tests/core/storage/test_file_storage.py` (этап 2, вместе с демо-видео VIS-01); `services:` MinIO в `backend-tests` (SYS-12).
- **Применимость**: backend, CI.

### SYS-10-R24 Цикл TDD: красные тесты до кода

- **Формулировка**: Тесты фичи должны быть написаны и закоммичены до кода реализации (шаги 5–7 конвейера до шага 9) и падать по ожидаемой причине (неверный ответ, `404`, отсутствие поля), а не из-за ошибки импорта, синтаксиса или окружения; коммиты тестов (`test(<module>): <ID> …`) должны предшествовать коммитам кода (`feat(<module>): <ID> …`) в ветке фичи.
- **Обоснование**: CLAUDE.md «TDD» (Red → Green → Refactor); SDD_plan.md §5 шаг 5: «Все новые тесты падают по ожидаемой причине, а не из-за ошибок импорта или окружения».
- **Проверка**: ревью G2 (человек видит красный прогон быстрой ступени CI на коммите тестов); `flt-tools commits check` (SYS-12): в PR фичи первый коммит с типом `feat` не раньше первого коммита с типом `test` для того же ID; ошибки сбора (`ImportError`, `SyntaxError`) считаются неверной «краснотой» — на шаге 5 допускаются только падения `assert` и ожидаемые исключения приложения, что фиксируется в отчёте `junit.xml` (поле `failure`, не `error`).
- **Применимость**: все.

### SYS-10-R25 Запрет ослабления тестов

- **Формулировка**: Тесты не должны отключаться, пропускаться или ослабляться ради зелёной сборки: `@pytest.mark.skip`, `@pytest.mark.xfail`, `it.skip`, `test.skip`, `test.fixme` допускаются только с причиной, содержащей ссылку `OQ-NN` или `#<номер issue>`; изменение ожидаемого значения в тесте без изменения ТЗ (статус `changed`) запрещено; пороги покрытия и `fail_under` не понижаются.
- **Обоснование**: CLAUDE.md «TDD»: «Нельзя ослаблять, удалять или отключать тесты, чтобы „пройти“ сборку. Если тест неверен — сначала исправить спецификацию/тест с объяснением причины».
- **Проверка**: плагин `tests/conftest.py`: `skip`/`xfail` без ссылки — ошибка сбора; правило ESLint `flt/no-unreferenced-skip` для Vitest и Playwright (будет создано); `flt-tools quality check-thresholds` (SYS-12); ревью G3 сверяет изменения тестов с историей изменений ТЗ.
- **Применимость**: все.

### SYS-10-R26 Негативные тесты прав для каждой роли

- **Формулировка**: Для каждого REST-эндпоинта и каждого WebSocket-канала модуля должен существовать параметризованный тест по ролям `anonymous`, `learner`, `teacher`, `platform_admin` (фикстура `as_role`), который проверяет, что роли, не имеющие права по матрице SYS-06, получают `401` (аноним) или `403` (аутентифицированный без права) либо `error forbidden` при подписке, и что проверка выполняется до обращения к данным; общий тест shared kernel `test_every_route_denies_unauthorized_roles` должен обходить все роутеры реестра и падать, если для маршрута нет записи в матрице прав.
- **Обоснование**: CLAUDE.md «Ключевые архитектурные требования»: «права проверять на сервере, не только в UI»; SDD_plan.md, критерий выхода этапа 3: «права проверяются на сервере и покрыты тестами»; SYS-06.
- **Проверка**: `tests/modules/<module>/contract/test_permissions.py` (по шаблону `tests/permissions_matrix.py` shared kernel); тест `tests/core/security/test_routes_in_matrix.py` (будет создан); фикстура `as_role` выпускает токен через `TokenIssuer` с одноразовой Ed25519-парой (ADR-006, ADR-013).
- **Применимость**: backend, tests.

### SYS-10-R27 Тесты миграций

- **Формулировка**: Для каждого модуля должен проходить тест `upgrade head → downgrade base → upgrade head` на пустой базе (SYS-05-R37), а для каждой миграции, изменяющей или переносящей существующие данные (backfill, смена значения, разделение колонки), — тест `tests/modules/<module>/migrations/test_<revision>.py`, который накатывает миграции до предыдущей ревизии, вставляет данные сырым SQL, применяет ревизию и проверяет результат, затем откатывает и проверяет сохранность данных.
- **Обоснование**: CLAUDE.md «Масштабирование и состояние» (совместимость миграций); ADR-003, п. 2.5 A; откат релиза должен сохранять данные.
- **Проверка**: наличие теста для ревизий с данными проверяет статический тест SYS-05 `test_data_statements_declare_row_bound` (ревизия с `op.execute(UPDATE|INSERT|DELETE)` обязана иметь парный файл теста); `tests/architecture/test_migrations_reversible.py`.
- **Применимость**: backend, tests.

### SYS-10-R28 Тесты на N инстансах

- **Формулировка**: Тесты масштабируемости должны писаться по методике SYS-05 (R44–R54): каталог `tests/n_instances/<module>/`, маркер `n_instances`, фикстуры стенда N3, шесть сценариев из таблицы 6.7 ТЗ; запуск — `make stand-up && make stand-test` локально и job `stand-n3` в CI; в покрытие не входят.
- **Обоснование**: CLAUDE.md «Тесты масштабируемости»; SYS-05.
- **Проверка**: SYS-05-R45, R53, R54; цели `stand-up`, `stand-test`, `stand-down` и `test-n3` в `src/backend/py-monolyth/Makefile` — единой точке входа бэкенда (уточнено при реализации Г.3, PR #5).
- **Применимость**: backend, tests, CI.

### SYS-10-R29 Нестабильные тесты: без ретраев, карантин со сроком

- **Формулировка**: Автоматические повторы упавших тестов запрещены (`retries: 0` в `playwright.config.ts` для всех проектов, `pytest-rerunfailures` не устанавливается, `test.retry` Vitest не используется); нестабильный тест переводится в карантин маркером `@pytest.mark.quarantine(issue="#123", until="2026-10-24")` (Vitest и Playwright — аннотация `{ annotation: { type: 'quarantine', description: '#123 until 2026-10-24' } }`) не дольше чем на 14 дней; карантинный тест выполняется, его падение не блокирует сборку, но попадает в отчёт; по истечении `until` маркер считается просроченным и тест снова блокирует; второй карантин одного теста подряд запрещён.
- **Обоснование**: Ретраи скрывают гонки, которые на N инстансах становятся ошибками пользователей; boilerplate frontend задаёт `retries: 2` на CI — заменяется.
- **Проверка**: плагин `tests/conftest.py` (маркер `quarantine`: падение → `xfail(strict=False)` до `until`, после — обычное падение); `playwright.config.ts` и `vite.config.ts` без `retries`/`retry`; еженедельный отчёт о карантине в `nightly.yml` (SYS-12); архитектурный тест `test_quarantine_not_expired`.
- **Применимость**: все.

### SYS-10-R30 Бюджеты времени прогона

- **Формулировка**: Время выполнения тестов на hosted runner-е CI не должно превышать: `backend-tests` (unit, интеграционные, контрактные) — 6 минут; `architecture` — 2 минуты; `frontend` (включая `test:cov`) — 6 минут; `stand-n3` (подъём стенда и `pytest -m n_instances`) — 12 минут; `e2e` — 10 минут; суммарно быстрая ступень — 15 минут настенного времени; отдельный тест вне `n_instances` и E2E не должен длиться дольше 5 секунд, иначе помечается `@pytest.mark.slow` с обоснованием.
- **Обоснование**: ADR-011, разделы 3.1 и 3.4 (оценки времени, `timeout-minutes`, бюджет минут); длинные прогоны съедают бесплатные минуты и удлиняют цикл TDD.
- **Проверка**: `timeout-minutes` job-ов (SYS-12); `pytest --durations=20` в выводе CI и `flt-tools quality durations` (падение при тесте > 5 с без `slow`); отчёт времени Vitest (`--reporter=verbose`) и Playwright.
- **Применимость**: tests, CI.

### SYS-10-R31 E2E: сценарии, проекты, смоук, RTL, вход

- **Формулировка**: E2E-тесты должны покрывать каждый сценарий раздела 2 ТЗ на mock-сервере в проектах Playwright `chromium-desktop`, `chromium-mobile` (`Pixel 7`) и `ar` (`locale: 'ar'`, проверка `html[dir=rtl]`, скриншоты лэйаута `toHaveScreenshot` с порогом `maxDiffPixelRatio: 0.01`), выполняться на языках `ru`, `en`, `ar`; смоук-набор `@smoke` («ходячий скелет» Г.11: открыть портал, переключить язык ru → en → ar, войти тестовым пользователем, получить стрим заглушки LLM по WebSocket, выполнить тестовое фоновое задание, остановка `flt-api-2` посреди стрима) должен выполняться против стенда N3 через HAProxy; вход тестового пользователя в E2E на стенде выполняется фикстурой `loginAs(role)` через `request.post('/api/v1/auth/login')` с сохранением cookie в `storageState`, без экрана входа.
- **Обоснование**: CLAUDE.md «Уровни тестов» (E2E, в том числе RTL); SDD_plan.md, этап 1 Г.11 и критерий выхода этапа 2; ADR-005, раздел 3.7 и 3.2 шаг 11 (вход через `POST /api/v1/auth/login`); ADR-011 (job `e2e`).
- **Проверка**: `playwright.config.ts` с тремя проектами и `retries: 0`; ESLint `flt/playwright-test-has-tag` требует хотя бы один `@<ID>`; job `e2e` запускает `pnpm test-e2e` (mock-сервер) и `pnpm test-e2e:smoke --base-url http://127.0.0.1:8080` (стенд N3); скриншоты `ar` хранятся в `e2e/__screenshots__/` и обновляются только коммитом с типом `test`.
- **Применимость**: frontend, CI.

### SYS-10-R32 Storybook как документация компонентов

- **Формулировка**: Каждый компонент в `src/components/**` должен иметь файл `*.stories.tsx` со всеми визуальными состояниями и декоратором направления (`ltr`/`rtl`); компоненты модулей `src/features/<module>/components/**` имеют истории по решению ТЗ (раздел 8.1: экраны с не менее чем тремя состояниями — обязательно); `pnpm build-storybook` входит в CI как проверка сборки, аддон `a11y` включён, Storybook test-runner не используется (проверка поведения — Vitest и Testing Library).
- **Обоснование**: CLAUDE.md «Frontend (boilerplate)»: Storybook для компонентов; ADR-005, разделы 3.2 шаг 6 и 3.7; истории — единственная документация визуальных состояний и RTL для ревью на G3.
- **Проверка**: архитектурный Vitest-тест `src/testing/architecture/stories-exist.test.ts` (будет создан: для каждого `src/components/**/*.tsx`, экспортирующего компонент, есть `*.stories.tsx`); job `frontend` (`build-storybook`).
- **Применимость**: frontend.

### SYS-10-R33 Тесты наблюдаемости

- **Формулировка**: Shared kernel должен иметь тесты: процессор `redact_sensitive_keys` маскирует каждый ключ списка ADR-010 (п. 3.2.3) и значения по регулярным выражениям JWT и ключей провайдеров; `/v1/ready` отвечает `503` без PostgreSQL и `200` без Redis, роль `worker` — `503` без Kafka; `/v1/health` всегда `200` с деталями; метрика `flt_instance_info` содержит `instance_id`, `role`, `version`, `stand`; каждая запись лога содержит обязательные поля; смоук на стенде N3 проверяет три цели `flt-api` и две `flt-worker` в состоянии `up` в Prometheus (в еженедельном полном прогоне `nightly.yml`, так как Prometheus не входит в профиль `ci`) и наличие записи с `request_id` из E2E в OpenSearch через API Grafana.
- **Обоснование**: ADR-010, раздел 4.3 («Требования: тесты процессора редактирования, тест readiness 503 … тест info-метрики»); критерий выхода этапа 1 Г.11.
- **Проверка**: `tests/core/logging/test_redact.py`, `tests/core/test_readiness.py`, `tests/core/metrics/test_instance_info.py` (будут созданы, маркер `req("SYS-10-R33")` и `req` соответствующих требований SYS-05); `nightly.yml` (SYS-12).
- **Применимость**: backend, tests, CI.

### SYS-10-R34 Нагрузочные тесты Locust

- **Формулировка**: Сценарии нагрузки должны лежать в `src/backend/py-monolyth/tests/load/locustfile.py` (пользователи REST и WebSocket через `locust-plugins`), запускаться против стенда N3 командой `make load-test` и в необязательном job `load` (`workflow_dispatch`, с этапа 2) с профилем из SYS-02 (100 одновременных пользователей, 300 WebSocket-соединений, 50 стримов заглушки LLM, 10 минут) и проверять пороги `p95 REST ≤ 300 мс` и доля ошибок `< 0.5 %`; прогон обязателен на гейте GS каждого этапа, отчёт (`locust --html`) прикладывается к приёмке этапа.
- **Обоснование**: OQ-13 (resolved): Locust, необязательный job с этапа 2, обязательный прогон на GS; SDD_plan.md, этап 1 Б.10.
- **Проверка**: job `load` в `ci.yml` (SYS-12); пороги — параметры `locustfile.py`, падение по `--exit-code-on-error` при превышении; чек-лист GS (SDD_plan.md §8) включает отчёт Locust.
- **Применимость**: backend, CI (этап 2 и далее).

### SYS-10-R35 Security-тесты

- **Формулировка**: В каждом прогоне быстрой ступени должны выполняться bandit (backend, `src/tools`, `src/agent`), `pip-audit` по `uv.lock` (падение при уязвимости уровня high и выше без зафиксированного исключения в `.pip-audit-ignore.toml` со ссылкой на OQ), `pnpm audit --prod --audit-level=high`, `detect-secrets`; негативные тесты прав (R26) и тесты редактирования логов (R33) — часть интеграционных; с этапа 7 — тесты изоляции песочницы плагинов по SYS-13 (`tests/security/plugins/**`).
- **Обоснование**: CLAUDE.md «Качество кода» (bandit, detect-secrets), «Ключевые архитектурные требования» (секреты и персональные данные не в логах); SDD_plan.md, этап 7 («Обязательны security-тесты песочницы») и §8 п. 5.
- **Проверка**: job-ы `backend-quality`, `frontend` (SYS-12); `make security` расширяется `pip-audit`.
- **Применимость**: backend, frontend, CI.

### SYS-10-R36 Тесты outbox, inbox и WebSocket-инфраструктуры shared kernel

- **Формулировка**: Shared kernel должен иметь интеграционные тесты: `OutboxPublisher` пишет строку в одной транзакции с данными (откат транзакции убирает и событие); relay публикует каждую строку один раз и помечает `published_at`; повторная доставка сообщения консьюмеру с `processed_events` не меняет данные; события одного агрегата читаются в порядке записи; `ws_publisher` доставляет сообщение подписчику того же процесса и другого процесса (два приложения в одном тесте с общим Redis); переподписка после переподключения; лимит соединений; закрытие по `SIGTERM` кодом 1012.
- **Обоснование**: ADR-004, раздел 4.3 («SYS-10: тесты outbox и inbox (повторная доставка, порядок по агрегату), `TestKafkaBroker` в роли `all`, WebSocket-клиент тестов на N инстансах»); SYS-05-R21, R24, R26, R30.
- **Проверка**: `tests/core/outbox/**`, `tests/core/inbox/**`, `tests/core/ws/**` (будут созданы в Г.4 с маркерами `req`).
- **Применимость**: backend, tests.

### SYS-10-R37 Детерминизм: без сети, случайный порядок, фиксированные seed

- **Формулировка**: pytest должен запускаться с `pytest-socket` (`--disable-socket --allow-hosts=127.0.0.1,::1,localhost`) для всех каталогов, кроме `tests/n_instances/**` и `tests/load/**`, с `pytest-randomly` и фиксированным `-p randomly --randomly-seed=20261010` (переопределяется для поиска порядковых зависимостей), с `asyncio_mode = "auto"` и сессионным event loop; Vitest — с `sequence.shuffle: true` и `sequence.seed: 20261010`; результат тестов не должен зависеть от часового пояса машины (`TZ=UTC` в `envs/.test.env` и `setup-tests.ts`) и локали.
- **Обоснование**: CLAUDE.md «TDD»: тесты детерминированы, не требуют сети; порядковые зависимости проявляются на CI и в карантине (R29).
- **Проверка**: `addopts` в `pyproject.toml`; `vite.config.ts`; тест `tests/core/test_no_network.py::test_external_socket_blocked` (будет создан).
- **Применимость**: backend, frontend, tests.

### SYS-10-R38 Тестовые данные для i18n и письменностей

- **Формулировка**: Фабрики и сиды должны включать строки на русском, английском и арабском (RTL), а с этапа 5 — на языке с вязью и языке с иероглифами, для каждого текстового поля, которое показывается пользователю; тесты компонентов, отображающих пользовательский текст, должны иметь хотя бы один случай с арабской строкой и проверкой `dir="auto"` или `<bdi>` по правилам SYS-07.
- **Обоснование**: CLAUDE.md «i18n с первого дня», «Поддержка LTR и RTL, арабской вязи, иероглифов»; CLAUDE.md «Уровни тестов»: E2E «в т.ч. RTL-языки».
- **Проверка**: константы `tests/i18n_samples.py` и `src/testing/i18n-samples.ts` (будут созданы) используются фабриками; ревью G2 проверяет наличие RTL-случая в тестах компонентов с пользовательским текстом; проект Playwright `ar`.
- **Применимость**: backend, frontend, tests.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| shared kernel (`app/core`) и `tests/` | Плагин маркеров `ac`, `req`, `n_instances`, `smoke`, `slow`, `quarantine` и проверки их наличия; фикстуры `db_migrate` (все модули реестра, `flt_test`), `clean_tables`, `redis_clean`, `redis_no_persistent_keys`, `redis_down`, `redis_flushed`, `frozen_clock`, `mail_outbox`, `storage_clean`, `as_role` (одноразовая Ed25519-пара, `TokenIssuer`), `eventually`; утилиты `tests/contract_utils.py`, `tests/permissions_matrix.py`, `tests/ids.py`, `tests/i18n_samples.py`; команда `python -m app seed`; `pytest-socket`, `pytest-randomly`, `polyfactory`, `respx`, `pip-audit` в dev-группе |
| llm_gateway | Провайдер `stub` с режимами `record`/`replay`, формат кассет, `LLM_STUB_DELTA_DELAY_MS`, `LLM_STUB_RECORD_ALLOWED` |
| identity | Фикстура `as_role` опирается на `TokenIssuer`; тесты OAuth на `respx` (этап 2); CLI `create-user` для сидов |
| speech (этап 5) | Провайдеры `stub` TTS/STT (R19) |
| все доменные модули | Структура `tests/modules/<module>/{unit,integration,contract,migrations}/`; контрактные тесты REST и AsyncAPI; `test_permissions.py`; тесты миграций с данными; кассеты в `tests/fixtures/llm_cassettes/<module>/`; сиды `tests/seeds/<module>.py` |
| frontend app_shell и модули | `coverage.thresholds`; правила ESLint `flt/test-title-has-id`, `flt/playwright-test-has-tag`, `flt/no-unreferenced-skip`, запрет `vi.mock` транспорта; `playwright.config.ts` с проектами `chromium-desktop`, `chromium-mobile`, `ar`, `retries: 0`, фикстура `loginAs`; `e2e/smoke/**`; `stories-exist.test.ts`; `src/testing/i18n-samples.ts` |
| `src/tools` | Команды `flt-tools traceability generate` и `check`, `quality check-thresholds`, `quality durations` (SYS-12); тесты на фикстурах |
| deploy | Init-скрипт `01-create-test-db.sql`; контейнеры `mailpit` и `mock-oidc` в профилях `dev` и `ci`, `minio` — в базовом составе (SYS-11-R4, R5); `REDIS_DB=15` не требует конфигурации Redis |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| 3. Критерии приёмки | Подсказка: ID критерия будет значением маркера `ac`, имени теста Vitest и тега Playwright — формулировать так, чтобы один AC проверялся отдельным тестом |
| 6.7 Тесты на N = 3 инстансах | Маркер `n_instances` (вместо предварительного `multi_instance`), файлы `tests/n_instances/<module>/` (совместно с SYS-05) |
| 8.1 Экраны и состояния | Отметка, какие экраны получают истории Storybook (R32) |
| 13. План тестов | Заменить предварительную конвенцию: pytest `@pytest.mark.ac("STU-18-AC3")`, N инстансов — `@pytest.mark.n_instances`; Vitest `it('[STU-18-AC3] …')`; Playwright `{ tag: ['@STU-18-AC3'] }`; добавить колонку «Негативные тесты прав» или строку «все эндпоинты — `test_permissions.py`»; указать кассеты LLM, если фича вызывает LLM |
| 15. Definition of Done | Пункт «Все критерии приёмки покрыты тестами» ссылается на `flt-tools traceability check`; пункт «тесты не ослаблены» (R25) |

## 5. Примеры

### Пример 1. Тест с маркерами критерия и требования (SYS-10-R12)

```python
# tests/modules/identity/integration/test_login.py
import pytest
from httpx import AsyncClient

from tests.ids import USER_LEARNER_1


@pytest.mark.ac("VIS-05-AC1")
@pytest.mark.req("SYS-06-R3")
async def test_login_sets_httponly_cookies(client: AsyncClient, seeded_learner: None) -> None:
    # Arrange
    body = {"email": "learner1@example.test", "password": "correct horse battery staple"}  # pragma: allowlist secret
    # Act
    response = await client.post("/api/v1/auth/login", json=body)
    # Assert
    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(USER_LEARNER_1)
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("__Host-flt_access=") and "HttpOnly" in c for c in cookies)
```

Проверка на этапе сбора (фрагмент `tests/conftest.py`):

```python
ID_RE = re.compile(r"^((VIS|ADM|STU|TCH)-\d{2}(\.\d+)?-AC\d+|SYS-\d{2}-R\d+)$")
TAGGED_DIRS = ("tests/modules/", "tests/n_instances/", "tests/core/", "tests/architecture/")

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    errors: list[str] = []
    for item in items:
        rel = str(item.path.relative_to(config.rootpath)).replace("\\", "/")
        if not rel.startswith(TAGGED_DIRS):
            continue
        tags = [m.args[0] for m in item.iter_markers() if m.name in ("ac", "req")]
        if not tags or any(not ID_RE.match(t) for t in tags):
            errors.append(f"{item.nodeid}: нет маркера ac/req или неверный формат ID (SYS-10-R12)")
        if rel.startswith("tests/architecture/") and not any(m.name == "req" for m in item.iter_markers()):
            errors.append(f"{item.nodeid}: архитектурный тест без маркера req (SYS-10-R8)")
    if errors:
        raise pytest.UsageError("\n".join(errors))
```

### Пример 2. Конфигурация pytest и coverage (SYS-10-R4, R11, R12, R37)

```toml
# src/backend/py-monolyth/pyproject.toml (фрагмент)
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
testpaths = ["tests"]
pythonpath = ["."]
env_files = ["envs/.test.env"]
addopts = "-v --strict-markers --durations=20 -p randomly --randomly-seed=20261010 --disable-socket --allow-hosts=127.0.0.1,::1,localhost"
markers = [
    "ac(id): критерий приёмки ТЗ, например ac('STU-18-AC3')",
    "req(id): требование системной спецификации, например req('SYS-05-R12')",
    "n_instances: тест на стенде N3 (SYS-05); пропускается без --stand-url",
    "smoke: смоук-набор «ходячего скелета»",
    "slow: тест длиннее 5 с с обоснованием",
    "quarantine(issue, until): карантин нестабильного теста не дольше 14 дней (SYS-10-R29)",
    "no_db: тест не требует БД",
]

[tool.coverage.run]
source = ["app"]
omit = ["app/*/migrations/*", "app/__main__.py", "app/core/roles/migrate.py"]

[tool.coverage.report]
show_missing = true
fail_under = 75
```

```ini
# src/backend/py-monolyth/envs/.test.env (фрагмент; решение OQ-31)
TEST_MODE=true
TZ=UTC
PG_DATABASE=flt_test
REDIS_DB=15
LLM_STUB_MODE=replay
LLM_STUB_DELTA_DELAY_MS=0
CAPTCHA_PROVIDER=stub
OTLP_EXPORTER_ENDPOINT=
```

```sql
-- deploy/docker-compose/postgres/init/01-create-test-db.sql — выполняется контейнером postgres при первом старте
CREATE DATABASE flt_test OWNER flt;
```

### Пример 3. Кассета заглушки LLM (SYS-10-R18)

```yaml
# tests/fixtures/llm_cassettes/llm_gateway/connection_check_en.yaml
version: 1
recorded_at: "2026-10-10T12:00:00Z"
provider: openai_compatible
model: yandexgpt-lite
request_sha256: "9f2c…e1"          # sha256 нормализованного запроса ниже
request:
  messages:
    - role: system
      content: "You are a language tutor. Reply with one short sentence."
    - role: user
      content: "Say hello in English."
  temperature: 0.0
  max_tokens: 32
response:
  start:
    provider: openai_compatible
    llm_model: yandexgpt-lite
  deltas:                            # воспроизводятся с задержкой LLM_STUB_DELTA_DELAY_MS
    - {kind: text, text: "Hello"}
    - {kind: text, text: "! Nice"}
    - {kind: text, text: " to meet you."}
  end:
    finish_reason: stop
    usage: {prompt_tokens: 31, completion_tokens: 7, total_tokens: 38, estimated: false}
```

Запись кассеты (только локально):

```bash
LLM_STUB_MODE=record LLM_STUB_RECORD_ALLOWED=1 PLATFORM_LLM_API_KEY=... \
  uv run pytest tests/modules/llm_gateway -k connection_check --record-cassettes
```

### Пример 4. Фикстуры хранилищ (SYS-10-R5, R6)

```python
# tests/conftest.py (фрагмент)
@pytest.fixture(scope="session")
def db_migrate() -> Iterator[None]:
    assert test_settings.TEST_MODE, "TEST_MODE не установлен — тесты запущены не на тестовой БД (SYS-10-R4)"
    assert settings.PG_DATABASE.endswith("_test"), f"PG_DATABASE={settings.PG_DATABASE}: ожидалась *_test"
    for module in MODULES:
        command.upgrade(Config("alembic.ini", ini_section=module), "head")
    yield
    for module in reversed(MODULES):
        command.downgrade(Config("alembic.ini", ini_section=module), "base")


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(request: pytest.FixtureRequest, db_migrate: None) -> AsyncIterator[None]:
    if request.node.get_closest_marker("no_db"):
        yield
        return
    yield
    tables = ", ".join(f'"{t.schema}"."{t.name}"' for m in load_modules(MODULES) for t in m.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def redis_no_persistent_keys(raw_test_redis: Redis) -> AsyncIterator[None]:
    await raw_test_redis.flushdb()
    yield
    bad: list[str] = []
    async for key in raw_test_redis.scan_iter(match="*", count=1000):
        ttl = await raw_test_redis.ttl(key)
        name = key.decode()
        if ttl == -1 or not re.match(r"^[a-z_]+:", name):
            bad.append(f"{name} (ttl={ttl})")
        elif ":lock:" in name and ttl > 60 and not name.startswith("shared_kernel:lock:schedule:"):
            bad.append(f"{name} (lock ttl={ttl} > 60s)")
    assert not bad, f"Ключи Redis без TTL, без префикса или с TTL сверх максимума (SYS-05-R12, R13): {bad}"
```

### Пример 5. Негативный тест прав по ролям (SYS-10-R26)

```python
# tests/modules/learning_plan/contract/test_permissions.py
from tests.permissions_matrix import ROLES, expect_for

@pytest.mark.ac("STU-18-AC10")
@pytest.mark.parametrize("role", ROLES)   # anonymous, learner, teacher, platform_admin
async def test_create_plan_requires_learner(as_role: AsRole, role: str, plan_request: dict) -> None:
    client = await as_role(role)
    response = await client.post("/api/v1/learning-plan/plans", json=plan_request)
    assert response.status_code == expect_for(role, permission="learning_plan:plans:create", success=201)
    # anonymous → 401, teacher и platform_admin без права → 403, learner → 201
```

### Пример 6. Теги в Vitest и Playwright (SYS-10-R13, R14, R31)

```tsx
// src/features/learning-plan/__tests__/plan-form.test.tsx
import { renderApp, screen } from '@/testing/test-utils';
import { AR_SAMPLE } from '@/testing/i18n-samples';

it('[STU-18-AC2] shows total duration computed from intensity', async () => {
  renderApp(<PlanForm />);
  expect(await screen.findByRole('status', { name: /duration/i })).toBeInTheDocument();
});

it('[STU-18-AC2][SYS-07-R6] renders learner topic in RTL with dir="auto"', async () => {
  renderApp(<PlanForm initialTopic={AR_SAMPLE} />);
  expect(screen.getByRole('textbox', { name: /topic/i })).toHaveAttribute('dir', 'auto');
});
```

```ts
// src/frontend/e2e/smoke/walking-skeleton.spec.ts
import { test, expect } from '@playwright/test';
import { loginAs } from '../utils/auth';

test('walking skeleton: language switch, login, LLM stream, background job',
  { tag: ['@smoke', '@SYS-05-R52', '@SYS-10-R31'] },
  async ({ page, request }) => {
    await page.goto('/');
    for (const lng of ['ru', 'en', 'ar'] as const) {
      await page.getByRole('combobox', { name: /language/i }).selectOption(lng);
      await expect(page.locator('html')).toHaveAttribute('dir', lng === 'ar' ? 'rtl' : 'ltr');
    }
    await loginAs(request, page, 'learner');               // POST /api/v1/auth/login, cookie в контексте
    await page.goto('/app/llm-check');
    await page.getByRole('button', { name: /send/i }).click();
    await expect(page.getByTestId('stream-output')).toContainText('Hello');
  });
```

```ts
// playwright.config.ts (фрагмент)
export default defineConfig({
  testDir: './e2e',
  retries: 0,                                             // SYS-10-R29
  reporter: [['html'], ['json', { outputFile: 'playwright-report/results.json' }]],
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'chromium-mobile', use: { ...devices['Pixel 7'] } },
    { name: 'ar', use: { ...devices['Desktop Chrome'], locale: 'ar' } },
  ],
});
```

### Пример 7. Карантин нестабильного теста (SYS-10-R29)

```python
@pytest.mark.ac("STU-19-AC4")
@pytest.mark.quarantine(issue="#142", until="2026-10-24")   # не дольше 14 дней с даты постановки
async def test_progress_recalculated_after_lesson(...): ...
```

```ts
test('[STU-19-AC4] recalculates progress', { annotation: { type: 'quarantine', description: '#142 until 2026-10-24' } }, async () => { ... });
```

## 6. Исключения и как их согласовать

Порядок согласования — как в SYS-05, раздел 6: вопрос OQ → решение человека → строка в таблице → запись в конфигурации проверки со ссылкой на строку.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-10-R3 | unit-тесты сервисов `tests/modules/<module>/unit/**` с подменой репозитория фейком в памяти | unit-уровень проверяет логику без хранилища; интеграционный уровень того же AC обязателен | бессрочно | Claude (черновик), подтверждается на G1 |
| SYS-10-R12 | `tests/cli/**` (тесты скаффолдера), `tests/test_lifespan.py` и тесты boilerplate до их удаления в Г.1 | не относятся к критериям и требованиям; `tests/cli` получает `req("SYS-12-R…")` после утверждения SYS-12 | до конца Г.1 | Claude (черновик), подтверждается на G1 |
| SYS-10-R17 | `tests/n_instances/**`: опрос состояния стенда с `asyncio.sleep(0.5)` | внешний процесс (HAProxy, контейнеры) нельзя подменить `Clock` | бессрочно | Claude (черновик), подтверждается на G1 |
| SYS-10-R20 | E2E входа через Яндекс ID и VK ID не автоматизируется | нет OIDC-совместимого мока их форматов; ручная проверка к G3 по VIS-05 (OQ-12) | до появления мока (новый OQ при потребности) | пользователь, 2026-10-10 (OQ-12) |
| SYS-10-R30 | `tests/modules/identity/integration/test_purge_tokens.py` (25 000 строк), тесты argon2id | помечены `slow`, выполняются в `backend-tests`, но исключены из `--durations` контроля | бессрочно | Claude (черновик), подтверждается на G1 |
| SYS-10-R33 | Проверка Prometheus и OpenSearch — только в `nightly.yml` | Prometheus, OpenSearch, Grafana не входят в профиль `ci` стенда N3 (ADR-011, SYS-05 раздел 6) | до появления self-hosted runner-а (OQ-68) | Claude (черновик), подтверждается на G1 |
| SYS-10-R37 | `tests/n_instances/**`, `tests/load/**`: сокеты к стенду разрешены | тесты по определению ходят на стенд | бессрочно | Claude (черновик), подтверждается на G1 |

## 7. Вне рамок

- Mutation testing (`mutmut`, `cosmic-ray`, Stryker) **не применяется**. Обоснование: (1) гейт G2 — ревью человеком красных тестов до кода, то есть чувствительность тестов проверяется процессом TDD: каждый тест обязан упасть до реализации (R24), что является прямой проверкой «тест замечает отсутствие поведения»; (2) полный прогон мутаций backend занимает часы и не укладывается в бюджет минут ADR-011; (3) выборочные мутации дают нестабильный сигнал. Пересмотр — на ревью этапа 4 (SDD_plan.md §8), когда появится объём доменной логики, оправдывающий ночной прогон на self-hosted runner-е.
- Методика тестов на N инстансах, стенд N3 и шесть обязательных сценариев — SYS-05 (здесь только место в пирамиде и запуск).
- Состав job-ов CI, обязательные проверки, бюджеты минут, публикация метрик качества — SYS-12.
- Правила нормализации OpenAPI и AsyncAPI для контрактных тестов, расширение `x-flt-state-endpoint` — SYS-03 и SYS-04.
- Матрица «роль × действие» — SYS-06 (здесь — обязанность тестировать каждую роль).
- Конфигурация контейнеров `mailpit`, `mock-oidc`, `minio`, профили compose и `values-dev.yaml` — SYS-11.
- Тесты песочницы плагинов — SYS-13 (этап 7).
- Пороги производительности и методика измерения голосовой задержки — SYS-02 и ТЗ STU-28 (OQ-72).
- Тесты локального агента (`src/agent`) — ADR-008 и спецификация агента этапа 4; правила маркеров и детерминизма наследуются.

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-002](../../ADR/ADR-002-module-layout.md) | основан на | тесты зеркалят `app/modules/<module>`, архитектурные тесты раздела 3.6, маркер `req`, негативный тест границ, `tests/cli` |
| [ADR-003](../../ADR/ADR-003-state-storage.md) | основан на | фикстура TTL, реальные PostgreSQL и Redis, схемы модулей в тестовой БД (OQ-31), `Clock` |
| [ADR-004](../../ADR/ADR-004-communication-patterns.md) | основан на | `TestKafkaBroker` в роли `all`, тесты outbox/inbox, WebSocket-клиент тестов |
| [ADR-005](../../ADR/ADR-005-frontend-stack.md) | основан на | Vitest, Testing Library, orval MSW, `ws.link`, пороги 70/60, проекты Playwright, вход через `POST /api/v1/auth/login`, Storybook |
| [ADR-006](../../ADR/ADR-006-authentication-and-authorization.md) | основан на | одноразовая Ed25519-пара в фикстуре, `TokenIssuer` для `as_role`, mock OIDC |
| [ADR-009](../../ADR/ADR-009-llm-streaming-and-voice.md) | основан на | провайдер `stub` с `LLM_STUB_DELTA_DELAY_MS`, сценарий остановки инстанса посреди стрима |
| [ADR-010](../../ADR/ADR-010-observability-stack.md) | основан на | тесты `redact_sensitive_keys`, readiness, `flt_instance_info`, смоук Prometheus и OpenSearch |
| [ADR-011](../../ADR/ADR-011-ci-cd.md) | уточняет | job-ы `backend-tests`, `architecture`, `frontend`, `stand-n3`, `e2e`, `docs`; пакет `flt_tools`; отсутствие секретов в тестах |
| [ADR-013](../../ADR/ADR-013-secrets-management.md) | ограничивает | тестовые значения в `envs/.test.env` с `pragma: allowlist secret`; `gen-secrets.sh --ci`; `detect-secrets` на кассетах |
| [ADR-007](../../ADR/ADR-007-file-storage.md) | уточняет | реальный MinIO в тестах, `storage-init` |
| [ADR-001](../../ADR/ADR-001-tech-stack.md) | ограничивает | версии pytest, Vitest, Playwright, Python 3.14 для `src/tools` |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-31](../../open-questions.md) | Разведение тестовой БД и стенда local | нет | planned → SYS-10: **решает** R4 — отдельная база `flt_test` и база Redis `15` в том же экземпляре, оверлей `envs/.test.env`, init-скрипт compose, `make test-docker` с PostgreSQL и Redis; testcontainers не используются |
| [OQ-13](../../open-questions.md) | Нагрузочные тесты | нет | resolved: Locust, необязательный job с этапа 2, обязательный прогон на GS — R34 |
| [OQ-33](../../open-questions.md) | Формат ID требований SYS | нет | resolved: `SYS-NN-R<M>` — маркер `req` (R12) |
| [OQ-12](../../open-questions.md) | OAuth-провайдеры в автотестах | нет | resolved: mock OIDC для Google, `respx` для форматов Яндекс ID и VK ID, ручная проверка к G3 — R20 |
| [OQ-10](../../open-questions.md), [OQ-11](../../open-questions.md) | Капча и почта в тестах | нет | resolved: заглушка капчи (R22), Mailpit и `mail_outbox` (R21) |
| [OQ-68](../../open-questions.md) | Self-hosted runner | нет | deferred; влияет на смоук наблюдаемости (R33, раздел 6) |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
| 0.2 | 2026-10-11 | Claude | Согласование SYS-01…SYS-12: профиль compose `test` → `ci` (профили `dev`, `ci`, `prod`, `recording` — SYS-11); кассеты — `tests/fixtures/llm_cassettes/<module>/`, `tests/fixtures/speech_cassettes/`, фикстуры заглушки — `tests/fixtures/llm_stub/`, тест секретов — `tests/fixtures/test_cassettes_have_no_secrets.py` (как в SYS-08-R25); R18 — режимы `scripted` (по умолчанию) и `replay` по фикстуре теста вместо «только replay», `CassetteMissingError`, ключ кассеты по SYS-08; пример теста прав — путь `learning-plan` и код права `learning_plan:plans:create` (SYS-06); раздел 4 — путь кассет | draft |
| 1.0 | 2026-10-11 | пользователь | Утверждена на гейте G1 блока Б этапа 1 без изменений (PR #3) | approved |
| 1.1 | 2026-10-11 | пользователь | Уточнения по реализации Г.3 (PR #5): путь init-скрипта — `deploy/docker-compose/postgres/init/` (как в SYS-11); R28 — цели стенда в `Makefile` бэкенда | approved |
