# ADR-002 — Раскладка доменных модулей в boilerplate, скаффолдер и контроль границ модулей

| Поле | Значение |
|---|---|
| Статус | proposed |
| Версия | 0.2 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | все |
| Модуль | все backend-модули и shared kernel (`app/core`) |
| Зависимости | ADR-001 |
| Связанные ADR/SYS | SYS-01, SYS-03, SYS-05, SYS-10, SYS-12; ADR-003, ADR-004, ADR-005, ADR-006, ADR-007, ADR-011, ADR-014; OQ-12, OQ-16, OQ-31 |

## 1. Контекст

- **Проблема**: boilerplate `src/backend/py-monolyth` раскладывает весь код по техническим слоям на весь сервис (`app/api/controllers`, `app/api/services`, `app/api/dao`, `app/api/schemas`, `app/brokers/kafka`), модели всех сущностей лежат в одном файле `app/core/dao/models.py`, миграции Alembic — в одном каталоге `app/core/dao/db_helpers/migrations/versions`, права — в одном файле `app/core/security/permissions.py`, роутеры подключаются вручную в `app/api/controllers/__init__.py`, а Kafka-обработчики — в одном файле `app/brokers/kafka/subscribers.py`. Скаффолдер (`cli/main.py`, `cli/templates.py`) генерирует файлы именно в эту раскладку. Сам boilerplate в `src/backend/py-monolyth/CLAUDE.md` предупреждает: «Если сервис вырастает в десятки доменов — пересматривайте в пользу доменных модулей». В FLT 23 доменных модуля (SDD_plan.md, Приложение В), и CLAUDE.md требует, чтобы каждый модуль был отдельным пакетом с собственными данными и был готов к выделению в микросервис без переписывания. Нужно решить, как раскладываются модули, что считается публичным API модуля, как регистрируются роутеры, подписчики и настройки модуля, как делятся схемы PostgreSQL и миграции, и чем автоматически проверяются границы.
- **Почему сейчас**: этап 1, п. Г.1 (скелет репозитория: раскладка по модулям и адаптация скаффолдера) и п. Г.2 (архитектурные тесты пишутся первыми). Критерий выхода этапа 1: «нарушение границы модуля ломает сборку (проверено специальным негативным тестом)». Первые модули `identity` и `llm_gateway` (п. Г.5, Г.6) создаются уже в новой раскладке.
- **Ограничения**:
  - CLAUDE.md, «Модульный монолит / Backend»: модуль — отдельный Python-пакет; другие модули импортируют только публичный API; свои схема PostgreSQL, модели, миграции; никаких JOIN, `relationship` и внешних ключей между модулями; ключи Redis только с префиксом `<модуль>:`; свои роутер FastAPI, обработчики WebSocket и Kafka, секция настроек; никаких циклических зависимостей; границы проверяются автоматически; `shared`/`common` минимален;
  - CLAUDE.md, «Отличия проекта от boilerplate», п. 1: «Доменные модули вместо слоёв на весь сервис… `app/core` остаётся общим ядром. Точная раскладка и адаптация скаффолдера под модули — ADR-002»;
  - CLAUDE.md, «Масштабирование и состояние»: миграции Alembic выполняются один раз отдельным шагом и совместимы с предыдущей версией кода;
  - `src/backend/py-monolyth/CLAUDE.md`: направление импортов `controllers → services → dao → models`, сервисы приходят через `Depends()`, `core` не зависит от `api` и `brokers`, Google-style docstring обязателен, новый код сначала генерируется скаффолдером, `make check` перед коммитом;
  - глоссарий, раздел 12: термины «модуль», «shared kernel», «публичный API модуля», «граница модуля», «архитектурный тест» с EN-именами `module`, `shared_kernel`, `module_public_api`, `module_boundary`, `architecture_test`;
  - OQ-16 (planned → ADR-002): рекомендация — import-linter с контрактами `independence`, `layers`, `forbidden` плюс негативный тест в CI; раскладка `app/modules/<module>/…`, скаффолдер получает параметр `module`;
  - OQ-03 (resolved): идентификаторы, файлы и пакеты — на английском, docstring-и — на русском.
- **Если не решить**: первые модули лягут в слоистую раскладку boilerplate, границы будут держаться только на дисциплине, а при 23 модулях общие `models.py`, `permissions.py` и `subscribers.py` превратятся в точки постоянных конфликтов; выделение модуля в микросервис потребует переписывания импортов и разделения миграций задним числом.
- **Ссылки**: CLAUDE.md «Модульный монолит», «Отличия проекта от boilerplate», «Масштабирование и состояние»; `src/backend/py-monolyth/CLAUDE.md` «Архитектура и направление импортов»; SDD_plan.md этап 1 (А.2, Г.1, Г.2, критерии выхода), Приложение В; OQ-16, OQ-31; ADR-001, ADR-003, ADR-004, ADR-011; SYS-01, SYS-05, SYS-10, SYS-12.

## 2. Рассматриваемые варианты

Решение состоит из трёх частей: раскладка кода (2.1), инструмент контроля границ (2.2), миграции и схемы PostgreSQL по модулям (2.3). Варианты внутри каждой части сравниваются по одной структуре.

### 2.1. Раскладка кода

#### Вариант A. Оставить слоистую раскладку boilerplate, модуль — соглашение об именовании

- **Описание**: код остаётся в `app/api/{controllers,services,dao,schemas}` и `app/brokers/kafka`; принадлежность модулю выражается префиксом файла (`identity_user_controller.py`) или подпапкой внутри каждого слоя (`app/api/services/identity/`). Скаффолдер не меняется.
- **Плюсы**:
  - нулевые изменения в boilerplate, скаффолдере и его шаблонах;
  - `src/backend/py-monolyth/CLAUDE.md` действует без правок.
- **Минусы**:
  - модуль размазан по пяти каталогам; «публичный API модуля» негде объявить — любой файл импортируем из любого;
  - общие `app/core/dao/models.py`, `permissions.py`, `subscribers.py` и `controllers/__init__.py` правятся при каждой фиче любого модуля;
  - import-linter может выразить границы только перечислением файлов по префиксу — контракты разрастаются и ломаются при каждом новом файле;
  - прямо противоречит CLAUDE.md «Отличия проекта от boilerplate», п. 1.
- **Масштабирование на N инстансах**: нейтрально — раскладка кода не влияет на хранение состояния.
- **Выделение модулей в микросервисы**: мешает: при выделении код модуля собирается из пяти каталогов вручную, общие файлы режутся задним числом.
- **Трудоёмкость и риски**: внедрение — ноль; эксплуатация — постоянные конфликты в общих файлах и невозможность автоматического контроля границ.

#### Вариант B. Пакет на модуль `app/modules/<module>/` со слоями boilerplate внутри и явным подпакетом `public`

- **Описание**: каждый модуль — пакет `app/modules/<module>/` с подпакетами `public` (публичный API), `api`, `services`, `dao`, `models`, `schemas`, `brokers`, `migrations` и файлами `settings.py`, `permissions.py`, `module.py` (описание модуля для регистрации). `app/core` — shared kernel без бизнес-логики. Реестр модулей `app/modules/registry.py` перечисляет модули; `app/main.py` подключает роутеры, Kafka-роутеры и WebSocket-обработчики по реестру. Скаффолдер получает команды `add-module` и параметр `--module` у `add-entity` и `add-subscriber`. Точная структура — раздел 3.
- **Плюсы**:
  - модуль — один каталог: его можно вынести вместе с миграциями, настройками и тестами;
  - публичный API — один подпакет `public`, что даёт import-linter простое правило «чужой модуль импортирует только `public`»;
  - слои boilerplate сохраняются внутри модуля, поэтому правила `src/backend/py-monolyth/CLAUDE.md` о направлении импортов и `Depends()` действуют без изменений;
  - общие файлы boilerplate (`models.py`, `permissions.py`, `subscribers.py`, `controllers/__init__.py`) исчезают — каждый модуль владеет своими.
- **Минусы**:
  - переработка скаффолдера и всех его шаблонов, перенос инфраструктурного кода из `app/api` и `app/brokers` в `app/core`, правка `alembic.ini` и `env.py`;
  - глубже вложенность путей (`app/modules/identity/services/user_service.py`);
  - реестр модулей и `.importlinter` нужно поддерживать при добавлении модуля (решается скаффолдером и архитектурным тестом полноты).
- **Масштабирование на N инстансах**: нейтрально по коду; способствует правилу «состояние только в PostgreSQL и Redis», так как у модуля есть единственная точка доступа к Redis с префиксом и единственный `Base` для своей схемы.
- **Выделение модулей в микросервисы**: помогает: пакет `app/modules/<module>` переносится целиком; у других модулей меняется только реализация за интерфейсом в `public` (вызов в процессе заменяется на REST- или Kafka-клиент с тем же `Protocol`).
- **Трудоёмкость и риски**: внедрение — 2–3 рабочих дня Claude в п. Г.1 (скаффолдер, перенос, тесты скаффолдера); риск — расхождение реестра модулей, `.importlinter` и `alembic.ini` с деревом каталогов, закрывается архитектурным тестом полноты (раздел 3.6).

#### Вариант C. Отдельный устанавливаемый пакет на модуль (uv workspace)

- **Описание**: каждый модуль — собственный проект с `pyproject.toml` (`src/backend/modules/identity/`), монолит собирается как uv workspace, модули ставятся как зависимости приложения-оболочки; границы контролируются объявленными зависимостями между пакетами.
- **Плюсы**:
  - максимальная изоляция: модуль не может импортировать то, что не объявлено зависимостью;
  - выделение в микросервис — добавление точки входа к уже отдельному пакету.
- **Минусы**:
  - 23 `pyproject.toml`, 23 набора настроек ruff, mypy, pytest и покрытия; скаффолдер, `make check`, Dockerfile и CI переписываются полностью;
  - объявленные зависимости пакетов не различают `public` и внутренности соседнего пакета — import-linter всё равно нужен;
  - boilerplate рассчитан на один проект (`[tool.uv] package = false`, один `uv.lock`, один `alembic.ini`).
- **Масштабирование на N инстансах**: нейтрально.
- **Выделение модулей в микросервисы**: помогает сильнее всего, но та же готовность достигается вариантом B с меньшей ценой.
- **Трудоёмкость и риски**: внедрение — 1–2 недели; риск — сложность инструментов на этапе, когда модулей два.

### 2.2. Инструмент контроля границ

#### Вариант D. import-linter

- **Описание**: декларативные контракты в файле `.importlinter` (формат INI) в корне `src/backend/py-monolyth`: `independence` между модулями с исключением для `public`, `layers` внутри модулей и между модулями в порядке зависимостей из SYS-01, `forbidden` для `app/core` и для прямого доступа к инфраструктуре. Запуск `lint-imports` в `make check`, в pre-commit и в CI; поверх — pytest-тесты в `tests/architecture/`. Версия на 2026-10-10 — 2.12 (июнь 2026); поддерживаются wildcards в `ignore_imports`, проверка косвенных импортов, вывод `BROKEN CONTRACTS` с цепочкой импортов.
- **Плюсы**:
  - зрелый инструмент (с 2019 года), декларативный формат, проверяет косвенные импорты через цепочки;
  - читаемый отчёт с конкретной цепочкой `a -> b -> c`;
  - не требует изменения кода, работает по графу импортов (grimp).
- **Минусы**:
  - проверяет только статические импорты Python: не видит обращения к чужой таблице через сырой SQL, ключи Redis без префикса, внешние ключи между схемами — для них нужны отдельные архитектурные тесты (раздел 3.6);
  - списки модулей в контрактах поддерживаются вручную или скаффолдером.
- **Масштабирование на N инстансах**: не применимо к инструменту; архитектурные тесты дополняют его проверками хранения состояния.
- **Выделение модулей в микросервисы**: помогает: доказывает, что модуль зависит от соседей только через `public`.
- **Трудоёмкость и риски**: внедрение — полдня; эксплуатация — поддержка списков в `.importlinter` (генерируется скаффолдером).

#### Вариант E. tach

- **Описание**: инструмент на Rust с файлом `tach.toml`, в котором у каждого модуля объявлены разрешённые зависимости и публичный интерфейс (`interfaces`), команды `tach check`, `tach sync`, визуализация графа.
- **Плюсы**:
  - быстрее import-linter на больших деревьях;
  - встроенное понятие публичного интерфейса модуля и автогенерация конфигурации по текущим импортам.
- **Минусы**:
  - моложе (первый релиз 2024), формат конфигурации менялся между минорными версиями;
  - `tach sync` «узаконивает» текущие импорты — в вайбкодинге это риск случайно зафиксировать нарушение;
  - нет контракта `layers` в терминах boilerplate (controllers → services → dao) — слои внутри модуля пришлось бы описывать как отдельные «модули» tach.
- **Масштабирование на N инстансах**: не применимо.
- **Выделение модулей в микросервисы**: помогает так же, как D.
- **Трудоёмкость и риски**: внедрение — полдня; риск — изменения формата при обновлениях по политике «последние стабильные версии» (ADR-001).

#### Вариант F. Собственный тест на AST

- **Описание**: pytest-тест обходит файлы `app/modules`, разбирает `import` через `ast` и проверяет правила из этого ADR.
- **Плюсы**:
  - нет внешней зависимости; правила произвольные (можно проверять и префиксы Redis).
- **Минусы**:
  - своё сопровождение: косвенные импорты, относительные импорты, импорты внутри функций, `importlib` — всё это уже решено в grimp;
  - нет стандартного отчёта.
- **Масштабирование на N инстансах**: не применимо.
- **Выделение модулей в микросервисы**: нейтрально.
- **Трудоёмкость и риски**: внедрение — 1–2 дня; риск — ложные срабатывания и пропуски, которые никто не исправит.

### 2.3. Схемы PostgreSQL и миграции Alembic по модулям

#### Вариант G. Один env Alembic, одна таблица `alembic_version`, ветки (`branch_labels`) на модуль

- **Описание**: `alembic.ini` с `version_locations = app/modules/identity/migrations app/modules/courses/migrations …`; каждая ревизия модуля помечена `branch_labels = ("identity",)`; `alembic upgrade heads` применяет все ветки; одна таблица `alembic_version` в общей схеме со строкой на ветку; `alembic revision --autogenerate --head identity@head --version-path …` создаёт ревизию в каталоге модуля; `include_name` в `env.py` ограничивает autogenerate схемой модуля.
- **Плюсы**:
  - одна команда `alembic upgrade heads` для всех модулей;
  - штатный механизм Alembic.
- **Минусы**:
  - общая таблица `alembic_version` — общее состояние всех модулей: при выделении модуля его строку нужно вручную переносить в новую базу;
  - `version_locations` в `alembic.ini` — один общий список, редактируемый при каждом новом модуле;
  - ошибка в `--head`/`--version-path` молча кладёт ревизию модуля в чужую ветку.
- **Масштабирование на N инстансах**: миграции выполняются отдельным шагом (одна команда), инстансы не мигрируют при старте (`MIGRATE_ON_START=false`).
- **Выделение модулей в микросервисы**: мешает умеренно: каталог ревизий переносится, но таблицу версий и `env.py` нужно разделять.
- **Трудоёмкость и риски**: внедрение — полдня; риск — путаница веток при autogenerate.

#### Вариант H. Общий `env.py`, секция `alembic.ini` на модуль, таблица `alembic_version` в схеме модуля

- **Описание**: один общий `env.py` и `script.py.mako` в shared kernel (`app/core/dao/db_helpers/migrations/`); в `alembic.ini` на каждый модуль своя секция `[<module>]` с `version_locations = app/modules/<module>/migrations`, именем схемы и путём к метаданным; команда `alembic -n <module> upgrade head`; `env.py` читает секцию, импортирует `app.modules.<module>.models`, создаёт схему `CREATE SCHEMA IF NOT EXISTS <module>`, пишет версию в таблицу `alembic_version` внутри схемы модуля (`version_table_schema=<module>`) и ограничивает autogenerate этой схемой (`include_name`). `make migrate` выполняет `upgrade head` для каждого модуля из реестра; `make makemigration module=<module> name=…` — autogenerate только для него.
- **Плюсы**:
  - у модуля полностью своё состояние миграций: каталог ревизий, своя таблица версий в своей схеме, своя секция ini — всё переносится в микросервис копированием;
  - нет веток и общего списка `version_locations`; autogenerate физически не видит чужие схемы;
  - порядок применения между модулями не важен: внешних ключей между схемами нет (архитектурный тест).
- **Минусы**:
  - `make migrate` — цикл по модулям вместо одной команды (скрыт в Makefile и в сервисе миграций docker-compose/Job Helm);
  - 23 секции в `alembic.ini` (добавляются скаффолдером).
- **Масштабирование на N инстансах**: как G — миграции отдельным шагом; при обновлении старые инстансы работают со схемами, расширенными совместимо (правило CLAUDE.md «Масштабирование и состояние», детализируется в SYS-05).
- **Выделение модулей в микросервисы**: помогает: миграции модуля независимы от остальных с первого дня.
- **Трудоёмкость и риски**: внедрение — полдня (общий `env.py` параметризуется секцией); риск — забытая секция для нового модуля, закрывается архитектурным тестом полноты.

## 3. Решение

- **Выбран**: Вариант B (раскладка) + Вариант D (import-linter) + Вариант H (секция Alembic и схема на модуль).
- **Решение**: каждый доменный модуль — пакет `app/modules/<module>/` со слоями boilerplate внутри и подпакетом `public`, который единственный доступен другим модулям; `app/core` — shared kernel без бизнес-логики; модули регистрируются через реестр `app/modules/registry.py` и объект `ModuleDefinition` в `module.py`; у модуля своя схема PostgreSQL `<module>`, свой каталог миграций и секция `alembic.ini`, свой префикс Redis `<module>:` и свой класс настроек с префиксом `<MODULE>_`; границы проверяет import-linter (контракты в `.importlinter`) и pytest-тесты `tests/architecture/`, запускаемые в `make check`, pre-commit и CI; нарушение границы ломает сборку, что доказывает негативный тест.
- **Обоснование**: вариант B — единственный, при котором модуль является одним переносимым каталогом и правило «только публичный API» выражается одним контрактом import-linter; слои boilerplate сохраняются внутри модуля, поэтому правила boilerplate продолжают действовать. import-linter (D) — зрелый декларативный инструмент с проверкой косвенных импортов; то, что он не проверяет (сырой SQL, Redis, внешние ключи), закрывают архитектурные тесты. Вариант H даёт модулю независимые миграции без общего состояния — это прямое требование готовности к выделению.
- **Отвергнуты**:
  - Вариант A — противоречит CLAUDE.md «Отличия проекта от boilerplate», п. 1; границы невозможно проверить автоматически.
  - Вариант C — цена (23 проекта, переписывание сборки и CI) не оправдана при двух модулях на этапе 1; переход на workspace остаётся возможным позже без изменения внутренней структуры модулей.
  - Вариант E — моложе, формат менялся, `tach sync` опасен в вайбкодинге; пересмотр возможен отдельным ADR, если import-linter станет узким местом по времени в CI.
  - Вариант F — собственное сопровождение того, что уже решено в grimp.
  - Вариант G — общая таблица версий и общий список `version_locations` — общее состояние модулей.
- **Границы решения**: ADR не задаёт состав модулей и направление зависимостей между ними (SYS-01), формат топиков и событий Kafka и устройство WebSocket-инфраструктуры (ADR-004, SYS-04), содержание shared kernel по хранению состояния (ADR-003, SYS-05), правила ESLint для frontend-модулей (ADR-005), стратегию тестов (SYS-10). Политика версий import-linter и uv — ADR-001.

### 3.1. Структура каталогов

```
src/backend/py-monolyth/
  .importlinter                      # контракты границ (раздел 3.5)
  alembic.ini                        # секция [<module>] на каждый модуль (раздел 3.4)
  app/
    main.py                          # create_app(): подключает модули по реестру
    core/                            # shared kernel: без бизнес-логики, не импортирует app.modules
      modules.py                     # ModuleDefinition, load_modules()
      http/                          # exception_handlers.py (из app/api), конверт ErrorResponseV1
      kafka/                         # broker.py (общий брокер и middleware из app/brokers/kafka), base_message.py
      ws/                            # инфраструктура WebSocket (ADR-004, SYS-04)
      dao/
        db_helpers/base.py           # make_module_base(schema) — Base с MetaData(schema=…)
        db_helpers/db_connection.py  # engine, get_session
        db_helpers/migrations/       # общие env.py и script.py.mako для всех модулей
        caching/module_redis.py      # ModuleRedis(prefix=<module>) — ключи только с префиксом <module>:, TTL обязателен (ADR-003)
      security/                      # проверка JWT и permissions (выпуск токенов — модуль identity, ADR-006)
      logging/ metrics/ telemetry.py exceptions.py schemas.py
    modules/
      __init__.py
      registry.py                    # MODULES: кортеж имён модулей в порядке зависимостей из SYS-01
      identity/
        __init__.py                  # docstring модуля; ничего не экспортирует
        module.py                    # module = ModuleDefinition(name="identity", router=…, kafka_router=…, …)
        public/                      # ПУБЛИЧНЫЙ API: единственное, что импортируют другие модули
          __init__.py                # реэкспорт: интерфейсы, схемы, события, ошибки, зависимости
          interfaces.py              # Protocol сервисов (IdentityService) и фабрики для Depends()
          schemas.py                 # Pydantic-схемы, которые видят другие модули
          events.py                  # схемы доменных событий модуля (топики — SYS-04)
          errors.py                  # доменные ошибки, которые могут получить другие модули
        api/
          router.py                  # APIRouter(prefix="/api/v1/identity"); включает роутеры ресурсов (ADR-004); identity дополнительно владеет /api/v1/auth
          user_controller.py         # контроллеры по ресурсам (как в boilerplate)
          ws.py                      # обработчики WebSocket модуля (если есть)
        services/                    # бизнес-логика (BaseService из py_main_lib)
        dao/                         # репозитории (BaseDAO из py_main_lib)
        models/
          __init__.py                # Base = make_module_base("identity"); импорт всех моделей
          user.py
        schemas/                     # внутренние DTO запросов и ответов REST
        brokers/
          router.py                  # KafkaRouter модуля; subscribers.py и publishers.py подключаются к нему
          subscribers.py
          publishers.py
          topics.py                  # StrEnum топиков модуля (формат имени — SYS-04)
          messages/                  # схемы сообщений (входящих и исходящих)
        migrations/                  # ревизии Alembic только этого модуля
          versions/
        settings.py                  # IdentitySettings(BaseSettings), env_prefix="IDENTITY_"
        permissions.py               # мнемокоды прав модуля (матрица — SYS-06)
      llm_gateway/                   # та же структура
  configs/                           # инфраструктурные настройки процесса: БД, Redis, Kafka, Vault, стенды
  cli/                               # скаффолдер (раздел 3.7)
  envs/<stand>/
    <stand>.env  kafka_<stand>.env  redis_<stand>.env
    identity_<stand>.env             # настройки модуля на стенде (создаёт скаффолдер; без секретов)
  tests/
    architecture/                    # тесты границ (раздел 3.6)
    core/
    modules/
      identity/                      # зеркалит app/modules/identity: api/, services/, brokers/
    conftest.py
```

Правила раскладки:

1. Подпакеты `api`, `services`, `dao`, `models`, `schemas`, `brokers`, `migrations` и файлы `settings.py`, `permissions.py` — внутренние. Отсутствующий у модуля слой не создаётся (модуль без Kafka не имеет `brokers/`), но `public/`, `module.py`, `models/` с `Base` и `migrations/` есть у каждого модуля с данными.
2. Направление импортов внутри модуля (контракт `layers`, раздел 3.5): `api`, `brokers` → `public` → `services` → `dao` → `models`; `schemas` и `settings.py` импортируются любым слоем и сами не импортируют слои бизнес-логики; `permissions.py` импортируется `api` и `brokers`.
3. Модуль импортирует из чужого модуля только `app.modules.<other>.public` (сам пакет или его подмодули) и только в направлении, разрешённом картой зависимостей SYS-01. Вызов — через интерфейс (`Protocol`) и фабрику зависимости из `public.interfaces`, в том же процессе, не по HTTP:

```python
# app/modules/identity/public/interfaces.py
from typing import Protocol
from uuid import UUID

from app.modules.identity.public.schemas import UserPublicSchema


class IdentityService(Protocol):
    """Публичный интерфейс модуля identity для других модулей."""

    async def get_user(self, user_id: UUID) -> UserPublicSchema | None:
        """Вернуть публичные данные пользователя или None, если пользователь не найден."""
        ...


def get_identity_service() -> IdentityService:
    """Фабрика для Depends(): возвращает реализацию из services (при выделении модуля — REST-клиент)."""
    from app.modules.identity.services.user_service import UserService

    return UserService()
```

```python
# app/modules/courses/services/enrollment_service.py — пример использования из другого модуля
from typing import Annotated

from fastapi import Depends

from app.modules.identity.public import IdentityService, get_identity_service

IdentityDep = Annotated[IdentityService, Depends(get_identity_service)]
```

4. `app/core` не импортирует `app.modules`. `configs/` не импортирует ни `app.core`, ни `app.modules` (как в boilerplate). `app.modules.*` не импортирует пакет `redis` и общий клиент `app.core.dao.caching.redis_conn` напрямую — только `ModuleRedis` (ADR-003); не импортирует брокер Kafka (`app.core.kafka.broker`) — публикация только через `OutboxPublisher` (ADR-004); не импортирует клиенты внешних хранилищ (`aioboto3`, `botocore` — ADR-007; `opensearchpy`, `qdrant_client` — ADR-014) — только обёртки shared kernel.
5. Пример boilerplate (`my_entity`, `cache_my_entity`, топики `inf_topic_*`) удаляется в п. Г.1 после того, как сгенерированный скаффолдером модуль проходит `make check`; образцом стиля становится сгенерированный код.
6. Тесты зеркалят `app/`: `tests/modules/<module>/…`, `tests/core/…`, `tests/architecture/…`. Маркер требования из SYS-10 (`@pytest.mark.req("SYS-NN-R<M>")`) обязателен для архитектурных тестов.

### 3.2. Регистрация модуля

`app/core/modules.py`:

```python
"""Описание модуля и его подключение к приложению."""

from dataclasses import dataclass, field
from importlib import import_module

from fastapi import APIRouter
from faststream.kafka import KafkaRouter
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData


@dataclass(frozen=True)
class ModuleDefinition:
    """Всё, что shared kernel должен знать о модуле, чтобы его подключить."""

    name: str                                  # имя пакета и схемы PostgreSQL, snake_case
    metadata: MetaData                         # метаданные моделей модуля (для Alembic и тестов)
    router: APIRouter | None = None            # REST-роутер модуля с префиксом /api/v1/<name> (ADR-004)
    extra_prefixes: tuple[str, ...] = ()       # дополнительные префиксы модуля; единственное исключение — ("/api/v1/auth",) у identity (OQ-12, SYS-03)
    kafka_router: KafkaRouter | None = None    # Kafka-роутер модуля
    ws_handlers: tuple = ()                    # обработчики WebSocket (контракт — ADR-004, SYS-04)
    settings: BaseSettings | None = None       # настройки модуля
    permissions: tuple[str, ...] = field(default_factory=tuple)  # мнемокоды прав модуля


def load_modules(names: tuple[str, ...]) -> list[ModuleDefinition]:
    """Импортирует `app.modules.<name>.module` для каждого имени и возвращает описания в порядке реестра."""
    return [import_module(f"app.modules.{name}.module").module for name in names]
```

`app/modules/registry.py`:

```python
"""Реестр модулей монолита. Порядок — порядок зависимостей из SYS-01 (нижние раньше)."""

MODULES: tuple[str, ...] = (
    "identity",
    "llm_gateway",
)
```

`app/main.py` (`create_app()`): `for module in load_modules(MODULES): app.include_router(module.router)` для модулей с роутером (префикс `/api/v1/<module>` задаёт сам роутер; архитектурный тест проверяет, что все пути роутера начинаются с `/api/v1/<name>/` или с одного из `extra_prefixes`); `broker_router.include_router(module.kafka_router)` для модулей с Kafka; регистрация `ws_handlers` в инфраструктуре `app/core/ws`. Подключение подмножества модулей или только Kafka-роутеров в роли воркера (`APP_ROLE`, ADR-004) делается тем же реестром через фильтр.

### 3.3. Настройки, права и Redis модуля

- Настройки: `app/modules/<module>/settings.py` объявляет `class <Module>Settings(BaseSettings)` с `model_config = SettingsConfigDict(env_prefix="<MODULE>_", env_file=stand_env_file("<module>"), extra="ignore")`; файл стенда — `envs/<stand>/<module>_<stand>.env` (уже поддерживается `configs.stands.stand_env_file(prefix)`). Секреты модуля — только переменные окружения, поля `SecretStr` без значения по умолчанию (клиент Vault из boilerplate удаляется — ADR-013). В docker-compose и Helm переменные модуля передаются с тем же префиксом (паритет — SYS-11).
- Права: мнемокоды модуля — в `app/modules/<module>/permissions.py` (`class UserPermissions: GET_MODEL = "IDENTITY_GET_USER"`), с префиксом `<MODULE>_`, чтобы коды модулей не пересекались; `ModuleDefinition.permissions` перечисляет их для матрицы SYS-06 и для тестов.
- Redis: `app/core/dao/caching/module_redis.py` даёт `ModuleRedis(prefix="identity")` с методами `get`, `set` (TTL обязателен), `delete`, `publish` и доступом к блокировкам и лимитам; все ключи получают префикс `identity:`. Модуль не импортирует ни пакет `redis`, ни общий клиент `redis_conn` (контракты `forbidden`). Состав методов, устройство блокировок, pub/sub и TTL — ADR-003 и SYS-05.

### 3.4. Схема PostgreSQL и миграции модуля

- `app/core/dao/db_helpers/base.py` дополняется фабрикой `make_module_base(schema: str) -> type[DeclarativeBase]`: возвращает класс `Base` с `metadata = MetaData(schema=schema, naming_convention=NAMING_CONVENTION)`. Модуль объявляет `Base = make_module_base("identity")` в `models/__init__.py` и наследует от него все модели; `__table_args__` со схемой не требуется.
- Внешние ключи и `relationship` между схемами запрещены; ссылки на сущности других модулей — колонки `UUID` без `ForeignKey` (проверяет архитектурный тест).
- `alembic.ini`:

```ini
[alembic]
script_location = app/core/dao/db_helpers/migrations
prepend_sys_path = .
path_separator = os

[identity]
script_location = app/core/dao/db_helpers/migrations
version_locations = app/modules/identity/migrations/versions
flt_module = identity

[llm_gateway]
script_location = app/core/dao/db_helpers/migrations
version_locations = app/modules/llm_gateway/migrations/versions
flt_module = llm_gateway
```

- Общий `env.py`: читает `flt_module` из текущей секции (`config.get_section_option(config.config_ini_section, "flt_module")`), импортирует `app.modules.<module>.module` и берёт `module.metadata`, выполняет `CREATE SCHEMA IF NOT EXISTS <module>`, настраивает `context.configure(…, version_table_schema=<module>, include_schemas=True, include_name=<фильтр: только схема модуля>)`. Запуск без `-n` (секция `[alembic]`) запрещён — `env.py` завершает работу с ошибкой «укажите модуль».
- Команды Makefile: `make migrate` — `for m in $(MODULES); do uv run alembic -n $$m upgrade head; done` (список модулей читается из `app/modules/registry.py` командой `python -m cli list-modules`); `make makemigration module=identity name="add_user"` — `uv run alembic -n identity revision --autogenerate -m "add_user"`; `make migrate-downgrade module=identity rev=base` — для тестов и отката.
- Сервис миграций docker-compose и Job Helm выполняют `make migrate` (ту же команду) до запуска инстансов; `MIGRATE_ON_START=false` на всех стендах, кроме local (SYS-11).
- Тестовая БД: фикстура `db_migrate` в `tests/conftest.py` накатывает и откатывает миграции всех модулей реестра; разведение тестовой БД и стенда local — OQ-31 (SYS-10).

### 3.5. Контракты import-linter

Файл `src/backend/py-monolyth/.importlinter` (пример для двух модулей; списки модулей поддерживает скаффолдер, полноту проверяет тест `test_registry_and_contracts_are_complete`):

```ini
[importlinter]
root_packages =
    app
    configs
include_external_packages = True   ; нужно контрактам 5–7 (внешние пакеты redis, faststream, aioboto3, botocore, opensearchpy, qdrant_client)

; 1. Модули независимы; разрешён только публичный API соседа.
[importlinter:contract:modules-public-api-only]
name = Доменные модули независимы, кроме импортов из public
type = independence
modules =
    app.modules.identity
    app.modules.llm_gateway
ignore_imports =
    app.modules.** -> app.modules.*.public
    app.modules.** -> app.modules.*.public.**

; 2. Направление зависимостей между модулями — по карте SYS-01 (нижние слои не знают о верхних).
;    Строка с «|» — модули одного уровня, независимые друг от друга.
[importlinter:contract:modules-dependency-order]
name = Зависимости между модулями направлены по карте модулей SYS-01
type = layers
containers = app.modules
layers =
    llm_gateway
    identity
exhaustive = true
exhaustive_ignores =
    registry

; 3. Слои внутри каждого модуля — как в boilerplate.
[importlinter:contract:module-internal-layers]
name = Слои внутри модуля: api и brokers -> public -> services -> dao -> models
type = layers
containers =
    app.modules.identity
    app.modules.llm_gateway
layers =
    api | brokers
    public
    services
    dao
    models

; 4. Shared kernel и configs не знают о модулях.
[importlinter:contract:core-does-not-import-modules]
name = app.core и configs не импортируют app.modules
type = forbidden
source_modules =
    app.core
    configs
forbidden_modules =
    app.modules

; 5. Доступ к Redis — только через ModuleRedis с префиксом модуля (ADR-003).
[importlinter:contract:redis-only-via-module-redis]
name = Модули не используют пакет redis и общий Redis-клиент напрямую
type = forbidden
source_modules =
    app.modules
forbidden_modules =
    redis
    app.core.dao.caching.redis_conn
allow_indirect_imports = True

; 6. Публикация в Kafka — только через outbox (ADR-004).
[importlinter:contract:kafka-publish-only-via-outbox]
name = Модули не импортируют брокер Kafka; публикация только через OutboxPublisher
type = forbidden
source_modules =
    app.modules
forbidden_modules =
    app.core.kafka.broker
    faststream.kafka.KafkaBroker
allow_indirect_imports = True

; 7. Клиенты внешних хранилищ — только через обёртки shared kernel (ADR-007, ADR-014).
[importlinter:contract:storage-clients-only-via-core]
name = Модули не импортируют aioboto3, botocore, opensearchpy, qdrant_client
type = forbidden
source_modules =
    app.modules
forbidden_modules =
    aioboto3
    botocore
    opensearchpy
    qdrant_client
allow_indirect_imports = True
```

Пояснения:
- Контракты 5–7 запрещают внешние пакеты, поэтому в секции `[importlinter]` задано `include_external_packages = True`; контракты 1–4 это не затрагивает (они перечисляют только пакеты `app`). `allow_indirect_imports = True` означает, что запрещён только прямой импорт из `app.modules`: модуль вправе импортировать `ModuleRedis`, `OutboxPublisher`, `FileStorage` и поисковые обёртки из `app.core`, которые внутри используют эти пакеты. Исключение для тестов (`tests/` вне `root_packages`) — `TestKafkaBroker` и прямой Redis в фикстурах разрешены.
- Контракт 1 исключает из графа только рёбра, ведущие в `public` соседа; цепочка `identity.services -> courses.public -> courses.services` не является нарушением, так как первое ребро исключено, а остальная цепочка лежит внутри `courses`. Импорт `identity.services -> courses.dao` остаётся нарушением.
- Контракт 2 запрещает циклы между модулями и обратное направление зависимостей, в том числе через `public`: нижний модуль не может вызывать `public` верхнего. Порядок строк — из SYS-01; при добавлении модуля скаффолдер вставляет его строку, а место в порядке подтверждается в спецификации модуля. `exhaustive = true` требует, чтобы каждый пакет в `app.modules` был перечислен — забытый модуль ломает проверку.
- Контракт 3 применяется к каждому контейнеру независимо. `schemas`, `settings`, `permissions`, `migrations`, `module` в слои не входят и могут импортироваться из любого слоя модуля; `module.py` импортирует `api`, `brokers`, `models`, `settings` — он выше всех слоёв и в контракт не включён.
- Запуск: `uv run lint-imports` (цель `make arch`, входит в `make check` между `typecheck` и `security`), hook `lint-imports` в `.pre-commit-config.yaml`, job `architecture` в CI (ADR-011).

### 3.6. Архитектурные тесты `tests/architecture/`

| Тест | Что проверяет | Как |
|---|---|---|
| `test_import_linter_passes` | Все контракты `.importlinter` выполняются на текущем дереве | `subprocess.run(["lint-imports"])`, код возврата 0 |
| `test_boundary_violation_breaks_build` (негативный тест, критерий выхода этапа 1) | Нарушение границы действительно ломает проверку | Копирует `app/`, `configs/` и `.importlinter` во временный каталог, дописывает в `app/modules/identity/services/_probe.py` импорт `from app.modules.llm_gateway.dao import …`, запускает `lint-imports` в копии; ожидает код возврата 1 и строку `BROKEN CONTRACTS` с именем контракта `modules-public-api-only`; второй сценарий — импорт `app.modules.identity.public` из `app.modules.llm_gateway` ломает `modules-dependency-order` |
| `test_registry_and_contracts_are_complete` | Каждый каталог `app/modules/<name>` (кроме `registry.py`) есть в `MODULES`, в контрактах 1–3 `.importlinter` и в секциях `alembic.ini`; и наоборот | Сравнение множеств имён |
| `test_no_cross_module_foreign_keys` | Ни одна таблица модуля не ссылается `ForeignKey` на таблицу другой схемы | Обход `module.metadata.tables` для всех модулей реестра |
| `test_module_tables_live_in_module_schema` | Все таблицы `module.metadata` имеют `schema == module.name` | Обход метаданных |
| `test_module_settings_prefix` | `env_prefix` настроек модуля равен `<MODULE>_`, у `permissions` — префикс `<MODULE>_` | Проверка `model_config` и значений |
| `test_module_public_exports_only_contracts` | В `public/` нет импортов моделей SQLAlchemy и репозиториев (`dao`, `models`) | AST-обход файлов `public/` (дополняет контракт 3, где `public` выше `services` и может их импортировать для фабрик, но не должен реэкспортировать модели) |
| `test_redis_keys_are_namespaced` | В `app/modules` нет строковых литералов-ключей без префикса модуля в вызовах Redis | Проверка, что вызовы Redis идут через `ModuleRedis` (контракт 5 запрещает прямой клиент; тест проверяет, что аргумент `prefix` у `ModuleRedis` равен имени пакета, в котором он создаётся) |
| `test_router_prefix_matches_module` | Все пути REST-роутера модуля начинаются с `/api/v1/<name>/` или с одного из `extra_prefixes`; `extra_prefixes` непуст только у `identity` (`/api/v1/auth`) | Обход `module.router.routes` для всех модулей реестра |
| `test_no_direct_broker_publish` | В `app/modules` нет вызовов `broker.publish` и `kafka_router.broker` — публикация только через `OutboxPublisher` (ADR-004) | AST-обход файлов модулей (дополняет контракт 6 на случай получения брокера через `Depends`) |

Проверки хранения состояния в памяти процесса (глобальные изменяемые словари, кэши `functools.lru_cache` на данных запроса) — в той мере, в какой они проверяются автоматически, — добавляются в `tests/architecture/` по требованиям SYS-05 (п. Г.2).

### 3.7. Скаффолдер

Команды `cli/main.py` (Makefile — те же имена целей):

| Команда | Что делает |
|---|---|
| `make scaffold-module name=identity` (`python -m cli add-module identity`) | Создаёт `app/modules/identity/` по структуре 3.1 с `module.py`, `public/__init__.py`, `models/__init__.py` (`Base = make_module_base("identity")`), `settings.py`, `permissions.py`, `api/router.py` (`APIRouter(prefix="/api/v1/identity")`), `migrations/versions/`; добавляет имя в `MODULES` (`registry.py`), строки в контракты 1–3 `.importlinter`, секцию в `alembic.ini`, файлы `envs/<stand>/identity_<stand>.env` для всех стендов, каталог `tests/modules/identity/` с `conftest.py`; запускает ruff на созданных файлах; идемпотентна |
| `make scaffold-entity module=identity name=User` (`python -m cli add-entity User --module identity`) | Как сегодняшний `add-entity`, но пути `app/modules/identity/{schemas,dao,services,api}/user_*.py`, модель `app/modules/identity/models/user.py` с импортом в `models/__init__.py`, права в `app/modules/identity/permissions.py`, роутер подключается в `app/modules/identity/api/router.py`, тест — `tests/modules/identity/services/test_user_service.py`. Параметр `--module` обязателен; при отсутствии модуля — ошибка с подсказкой `make scaffold-module` |
| `make scaffold-subscriber module=identity topic=USER_REGISTERED value="…"` (`python -m cli add-subscriber … --module identity`) | Схема сообщения в `brokers/messages/`, сервис в `brokers/services/` или `services/`, член `StrEnum` в `brokers/topics.py`, хендлер в `brokers/subscribers.py` на роутере модуля; значение топика по формату SYS-04 |
| `python -m cli list-modules` | Печатает `MODULES` построчно (используется Makefile для `make migrate` и CI) |
| `make makemigration module=identity name="add_user"` | `alembic -n identity revision --autogenerate` |

Шаблоны `cli/templates.py` получают токен `__MODULE__` и пути `app.modules.__MODULE__.…`; шаблон контроллера использует `app.modules.__MODULE__.permissions` и `app.core.security.security.auth_user`. Тесты скаффолдера (`tests/cli/`): генерация модуля и сущности во временной копии дерева, затем `ruff check`, `mypy` и `lint-imports` на результате — сгенерированный код обязан проходить `make check` без правок.

### 3.8. Что остаётся в `app/core` (shared kernel)

Только сквозные вещи без бизнес-логики: `modules.py` (реестр), `http/` (конверт ошибок, обработчики исключений), `kafka/` (общий брокер, middleware, базовые схемы сообщений, outbox-инфраструктура по ADR-004), `ws/` (ADR-004), `dao/db_helpers/` (engine, сессии, `make_module_base`, общий `env.py`), `dao/caching/` (`ModuleRedis`, блокировки и лимиты по ADR-003), `storage/` (`FileStorage`, ADR-007), `search/` (обёртки OpenSearch и Qdrant, ADR-014), `security/` (проверка JWT, `auth_user`, permissions-механизм), `logging/`, `metrics/`, `telemetry.py`, `exceptions.py`, `schemas.py`, идентификаторы и время (п. Г.4). Любой код, который знает о пользователях, курсах, моделях LLM или другой предметной области, в `app/core` не допускается — это проверяется на ревью спецификации модуля и при ревью разбиения в конце этапа (SDD_plan.md, раздел 8, п. 6).

## 4. Последствия

### 4.1. Положительные

- Модуль — один каталог с кодом, миграциями, настройками, правами и тестами; его перенос в микросервис — копирование каталога и замена реализации фабрик в `public` соседей.
- Правило «только публичный API» и направление зависимостей из SYS-01 проверяются автоматически на каждом коммите и в CI; негативный тест доказывает, что проверка работает.
- Общие файлы boilerplate, которые правились при каждой фиче, исчезают; конфликты между параллельными ветками ТЗ разных модулей сводятся к `registry.py`, `.importlinter` и `alembic.ini`, которые правит скаффолдер при создании модуля, а не при каждой фиче.
- Скаффолдер остаётся первым шагом написания кода (правило boilerplate), но генерирует код сразу в модуль.
- Схема PostgreSQL и таблица версий Alembic на модуль исключают скрытые связи данных между модулями и упрощают проверку правила «никаких внешних ключей между модулями».

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Переработка скаффолдера, шаблонов, `alembic.ini`, `env.py`, `main.py` и перенос `app/api`, `app/brokers` в `app/core` в п. Г.1 (2–3 рабочих дня) | Делается один раз до первого модуля; тесты скаффолдера фиксируют результат |
| `.importlinter`, `registry.py` и `alembic.ini` содержат списки модулей, которые можно забыть обновить | Обновляет скаффолдер; `test_registry_and_contracts_are_complete` и `exhaustive = true` ломают сборку при расхождении |
| import-linter не видит сырой SQL, ключи Redis и внешние ключи | Архитектурные тесты раздела 3.6; сырой SQL между схемами запрещается в SYS-05 и ловится ревью |
| `make migrate` — цикл по модулям; при 23 модулях — 23 подключения к БД | Выполняется один раз отдельным шагом развёртывания, не инстансами; время — секунды |
| Правила `src/backend/py-monolyth/CLAUDE.md` описывают старую раскладку | Файл обновляется в п. Г.1 (раздел 4.3) |
| Глубже пути импортов | Абсолютные импорты `app.modules.<module>.…`; ruff/isort форматирует автоматически |
| `public` может «утолщаться» и превращаться в второй слой сервисов | `public` содержит только `Protocol`, схемы, события, ошибки и фабрики; `test_module_public_exports_only_contracts`; ревью спецификации модуля (раздел 3 `_module.md`) |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Утвердить состав модулей этапа 1 и порядок зависимостей для контракта `modules-dependency-order` | SYS-01 (карта модулей), раздел «Зависимости между модулями» | Claude (черновик), человек (G1) | не начато |
| Синхронизировать формат раздела «Публичный API» шаблона спецификации модуля с содержимым `public/` (интерфейсы, схемы, события, ошибки) и раздел «Данные» со схемой `<module>` | `Analytics/Specs/_templates/module-spec.md`, разделы 3 и 5 (подсказки) | Claude | не начато |
| Оформить исключение `/api/v1/auth/*` для модуля `identity` (OQ-12) как единственное отступление от правила «префикс роутера = имя модуля» | SYS-03 | Claude (этап 1 Б.3) | не начато |
| Перенести `app/api/exception_handlers.py` в `app/core/http/`, `app/brokers/kafka/{kafka_router,middlewares,logger,template_schema}` в `app/core/kafka/`; удалить пример `my_entity`, `cache_my_entity`, `inf_topic_*` после прохождения тестов скаффолдера | `src/backend/py-monolyth/app` | Claude (этап 1 Г.1) | не начато |
| Добавить `app/core/modules.py`, `app/modules/registry.py`, `make_module_base`, `ModuleRedis`; переписать `create_app()` на реестр | `src/backend/py-monolyth/app/core`, `app/main.py` | Claude (этап 1 Г.1, Г.4) | не начато |
| Переписать `alembic.ini` на секции по модулям и общий параметризованный `env.py`; цели `migrate`, `makemigration module=…`, `migrate-downgrade` | `src/backend/py-monolyth/alembic.ini`, `app/core/dao/db_helpers/migrations/env.py`, `Makefile` | Claude (этап 1 Г.1) | не начато |
| Добавить `import-linter` в dev-группу, файл `.importlinter`, цель `make arch` в `make check`, hook в `.pre-commit-config.yaml` | `src/backend/py-monolyth/pyproject.toml`, `.importlinter`, `Makefile`, `.pre-commit-config.yaml` | Claude (этап 1 Г.1) | не начато |
| Написать архитектурные тесты раздела 3.6, в том числе негативный тест | `src/backend/py-monolyth/tests/architecture/` | Claude (этап 1 Г.2, первыми) | не начато |
| Переписать скаффолдер: `add-module`, `--module` у `add-entity` и `add-subscriber`, `list-modules`, токен `__MODULE__` в шаблонах; тесты скаффолдера | `src/backend/py-monolyth/cli/`, `tests/cli/` | Claude (этап 1 Г.1) | не начато |
| Обновить правила boilerplate: раздел «Архитектура и направление импортов» (структура `app/modules/<module>`, `public`, реестр), «Добавление REST-эндпоинта» и «Добавление брокер-консьюмера» (новые команды), «Анти-паттерны» (импорт внутренностей чужого модуля, прямой Redis-клиент, внешний ключ в чужую схему) | `src/backend/py-monolyth/CLAUDE.md` | Claude (этап 1 Г.1) | не начато |
| Обновить команды скаффолдера и миграций, снять TODO «import-linter или аналог», описать раскладку модуля и `public` | CLAUDE.md, разделы «Команды», «Модульный монолит / Backend», «Отличия проекта от boilerplate» п. 1, «Структура репозитория» | Claude (при принятии ADR) | не начато |
| Сервис миграций docker-compose и Job Helm выполняют `make migrate` по всем модулям; переменные настроек модулей с префиксом `<MODULE>_` передаются в обоих вариантах одинаково | `deploy/docker-compose/docker-compose.yml` и `deploy/helm` одновременно; SYS-11 | Claude (этап 1 Г.8) | не начато |
| Описать job `architecture` (lint-imports + `tests/architecture`) как обязательную проверку | ADR-011, SYS-12 | Claude | не начато |
| Зафиксировать маркер требований для архитектурных тестов и правило «тесты зеркалят `app/modules/<module>`» | SYS-10 | Claude | не начато |
| Уточнить пункт Г.1 (перечень работ по этому ADR) и критерий выхода «негативный тест» ссылкой на `test_boundary_violation_breaks_build` | `Analytics/BRD/SDD_plan.md`, этап 1 Г.1, Г.2, критерии выхода | Claude | не начато |
| Закрыть OQ-16 ссылкой на этот ADR | `Analytics/open-questions.md` | оркестратор | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-001](ADR-001-tech-stack.md) | зависит от | Версии Python, uv, import-linter и политика их обновления |
| [ADR-003](ADR-003-state-storage.md) | дополняет | Содержимое `ModuleRedis`, блокировки, TTL; схема на модуль как единица владения данными; контракт 5 |
| [ADR-004](ADR-004-communication-patterns.md) | дополняет | Префикс `/api/v1/<module>`, Kafka-роутер модуля, outbox в shared kernel (контракт 6), WebSocket-обработчики модуля, роли через реестр |
| [ADR-005](ADR-005-frontend-stack.md) | дополняет | Зеркальные правила границ для frontend-модулей (ESLint `import/no-restricted-paths`) |
| [ADR-006](ADR-006-authentication-and-authorization.md) | ограничен | Проверка JWT остаётся в `app/core/security`, выпуск токенов — в модуле `identity`; исключение `/api/v1/auth` |
| [ADR-007](ADR-007-file-storage.md) | дополняет | `app/core/storage`, запрет импорта `aioboto3`/`botocore` из модулей (контракт 7) |
| [ADR-011](ADR-011-ci-cd.md) | дополняет | Job `architecture` в CI, pre-commit на уровне репозитория |
| [ADR-013](ADR-013-secrets-management.md) | дополняет | Секреты модуля — переменные окружения с `SecretStr`, без `vault_secret` |
| [ADR-014](ADR-014-search-engines.md) | дополняет | `app/core/search`, запрет импорта `opensearchpy`/`qdrant_client` из модулей (контракт 7) |
| [SYS-03](../Specs/_system/SYS-03-rest-api-conventions.md) | дополняет | Исключение `/api/v1/auth/*` для `identity` (OQ-12) |
| [SYS-01](../Specs/_system/SYS-01-module-map.md) | зависит от | Состав модулей и направление зависимостей для контракта `modules-dependency-order` |
| [SYS-05](../Specs/_system/SYS-05-state-and-scaling.md) | дополняет | Префиксы Redis, запрет состояния в процессе, совместимость миграций |
| [SYS-10](../Specs/_system/SYS-10-test-strategy.md) | дополняет | Архитектурные тесты в пирамиде тестов, маркер требований, тестовая БД (OQ-31) |
| [SYS-12](../Specs/_system/SYS-12-ci-cd-and-quality.md) | дополняет | Архитектурные проверки как обязательные в CI |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Согласование с ADR-003 (`RedisNamespace` → `ModuleRedis`, контракт на пакет `redis`), ADR-004 (префикс `/api/v1/<module>`, контракт «публикация только через outbox», `APP_ROLE`), ADR-007 и ADR-014 (контракт на клиенты хранилищ, пакеты `storage/` и `search/` в shared kernel); исключение `/api/v1/auth` для `identity` (`extra_prefixes`, тест `test_router_prefix_matches_module`) — решение оркестратора (OQ-12) | proposed |
