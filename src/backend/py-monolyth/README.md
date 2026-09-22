# FastAPI Boilerplate

Готовая заготовка для нового микросервиса на FastAPI. Берёшь копию — и сразу получаешь
работающий HTTP API, брокеры сообщений, БД, кэш, авторизацию, метрики, логи и тесты,
собранные в едином стиле. Остаётся писать бизнес-логику.

**Навигация:** [Что внутри](#что-внутри) · [Быстрый старт](#быстрый-старт) ·
[Аутентификация](#аутентификация) · [Как устроен проект](#как-устроен-проект) ·
[Как добавить новое](#как-добавить-новое) · [Тесты](#тесты) · [Шпаргалка make](#шпаргалка-make)

---

## Что внутри

Код разложен по трём слоям, и зависимости идут строго сверху вниз:

```
Контроллер (REST) / Consumer (брокер)   ← входная точка любого внешнего вызова
            │
         Сервис                         ← бизнес-логика и границы транзакций
            │
           DAO                          ← доступ ко всему внешнему: БД, Redis, другие сервисы
```

| Задача | Чем решена |
| --- | --- |
| HTTP API и OpenAPI (Swagger) | FastAPI |
| Kafka: consumers, producers, AsyncAPI | FastStream |
| База данных и миграции | SQLAlchemy 2.0 (async) + Alembic |
| Кэш | Redis |
| DTO и валидация | Pydantic — типизирован каждый вход и выход |
| Транзакции | контекст-менеджер на уровне сервиса |
| Аутентификация и права | собственная проверка JWT, внешний auth-сервис не нужен |
| Ошибки | единые обработчики для REST и брокеров |
| Наблюдаемость | Prometheus-метрики, OpenTelemetry-трейсы, structlog (+ отправка в OpenSearch) |
| Конфигурация и секреты | env-файлы на каждый стенд + Vault |
| Качество кода | ruff, mypy (strict), bandit, detect-secrets, pre-commit |
| Поставка | Docker (прод и dev-сборка), GitLab CI |
| Генерация кода | CLI-скаффолдер для сущностей и консьюмеров |

---

## Быстрый старт

### Что понадобится

- [**uv**](https://docs.astral.sh/uv/getting-started/installation/) — менеджер зависимостей;
  нужный Python (3.13, см. `.python-version`) он скачает сам.
- [**Docker** и **Docker Compose**](https://docs.docker.com/get-docker/) — для инфраструктуры и сборки образа.

### 1. Разложите репозитории рядом

Сервису нужна внутренняя библиотека **py-main-lib**. Удобнее всего держать её клон по соседству —
например, в общей папке `set_of_assistant`:

```sh
mkdir set_of_assistant && cd set_of_assistant
git clone <URL_ЭТОГО_РЕПОЗИТОРИЯ>
git clone <URL_py-main-lib>
```

```
set_of_assistant/
├── python-boilerplate/
└── py-main-lib/
```

Дальше все команды выполняются из `python-boilerplate/`.

### 2. Установите зависимости

```sh
make install
```

Под капотом — `uv sync --all-groups` (создаст `.venv` строго по `uv.lock`) и установка
py-main-lib из `../py-main-lib`. Библиотека лежит в другом месте — укажите путь:
`make install PY_MAIN_LIB=<путь>`.

### 3. Поднимите инфраструктуру

```sh
make compose-up      # PostgreSQL, Redis, Kafka
make compose-down    # остановить
```

Compose-файл — `deploy/docker-compose/docker-compose.yml` в корне репозитория FLT; другой путь —
`make compose-up COMPOSE_FILE=<путь>`. Весь стек вместе с сервисом в Docker поднимается из корня
репозитория: `docker compose -f deploy/docker-compose/docker-compose.yml up -d --build`.

### 4. Выберите стенд

Скопируйте `.env.template` в `.env`. Единственная переменная там — `STAND_NAME`, она решает,
какие файлы из `envs/<стенд>/` будут прочитаны. По умолчанию — `local`.

### 5. Запустите сервис

```sh
make dev    # dev-сервер с автоперезагрузкой
make run    # как в Docker: миграции + uvicorn
```

### 6. Убедитесь, что всё живо

| Что | Адрес |
| --- | --- |
| Swagger UI | <http://localhost:8000/docs> |
| AsyncAPI для Kafka | <http://localhost:8000/asyncapi/kafka> |
| Health / readiness | <http://localhost:8000/v1/health>, <http://localhost:8000/v1/ready> |

### Сборка Docker-образа

```sh
# прод: py-main-lib берётся из локального клона (private registry недоступен)
docker build --build-context py-main-lib=../py-main-lib .   # или: make docker-build

# dev: py-main-lib берётся из локального клона
docker build -f Dockerfile-dev --build-context py-main-lib=../py-main-lib .
```

---

## Аутентификация

Сервис проверяет токены сам, отдельный сервис авторизации ему не нужен. Каждый запрос
с `Authorization: Bearer <JWT>` проходит так:

1. **Подпись** сверяется с ключом `JWT_SECRET_KEY`: общий секрет для `HS*` или публичный
   PEM-ключ для `RS*`/`ES*`. Разрешён только алгоритм из `JWT_ALGORITHM` (по умолчанию `HS256`).
2. **Срок действия** обязателен: токен без `exp` отклоняется. Если задан `JWT_ISSUER`,
   дополнительно проверяется `iss`.
3. **Пользователь** определяется по claim `USER_ID`, а если его нет — по `sub`.
4. **Права** — это объединение claim `PERMISSIONS` и прав всех ролей из claim `ROLES`.
   Какие права у какой роли, задаёт `JWT_ROLE_PERMISSIONS` в формате JSON:
   `{"ADMIN": ["GET_MY_ENTITY", ...]}`.

На dev и prod `JWT_SECRET_KEY` приходит из Vault (или из переменной окружения деплоя).
Для local ключ и маппинг ролей уже прописаны в `envs/local/local.env`. Токен для ручных
запросов выпускается одной командой:

```sh
uv run python -m cli issue-token 00000000-0000-0000-0000-000000000002 --role ADMIN
```

---

## Как устроен проект

```
.
├── app/
│   ├── api/                         REST API
│   │   ├── controllers/             контроллеры (пример — my_entity_controller.py)
│   │   ├── services/                бизнес-логика (my_entity_service.py)
│   │   ├── dao/                     доступ к данным (my_entity_dao.py)
│   │   ├── schemas/                 DTO и Enums (my_entity_schema.py)
│   │   └── exception_handlers.py    обработка ошибок HTTP
│   │
│   ├── brokers/
│   │   ├── kafka/
│   │   │   ├── subscribers.py       consumers — тонкие хендлеры
│   │   │   ├── publishers.py        описание исходящих сообщений для AsyncAPI (не удалять!)
│   │   │   ├── kafka_router.py      регистрация consumers/publishers, единая точка publish
│   │   │   ├── services/            логика обработки сообщений
│   │   │   ├── schemas/
│   │   │   │   ├── enums.py         реестр топиков
│   │   │   │   ├── publisher_messages/   DTO исходящих сообщений (inf_topic_01_schema.py)
│   │   │   │   └── subscriber_messages/  DTO входящих сообщений (inf_topic_02_schema.py)
│   │   │   ├── middlewares/         обработка ошибок и их переадресация
│   │   │   └── logger.py
│   │
│   ├── core/                        общее ядро для api и brokers
│   │   ├── dao/
│   │   │   ├── caching/             Redis: общий клиент и RedisDAO
│   │   │   ├── db_helpers/          подключение к БД и миграции Alembic
│   │   │   └── models.py            ORM-модели
│   │   ├── security/
│   │   │   ├── auth_service.py      проверка JWT и сборка прав из claims
│   │   │   ├── security.py          FastAPI/FastStream-зависимости авторизации
│   │   │   ├── permissions.py       мнемокоды прав для эндпоинтов
│   │   │   └── schemas.py
│   │   ├── metrics/                 /health, /ready, /metrics и Prometheus-middleware
│   │   ├── logging/                 structlog, контекст логов, sink в OpenSearch
│   │   ├── middlewares/             HTTP-логирование и ответы 500
│   │   ├── telemetry.py             OpenTelemetry
│   │   ├── exceptions.py            доменные исключения
│   │   └── schemas.py               общие схемы ошибок
│   │
│   └── main.py                      сборка приложения (create_app + lifespan)
│
├── configs/                         settings.py, выбор стенда (stands.py), Vault,
│                                    настройки Kafka / Redis
├── envs/                            env-файлы по стендам: local/, dev/, test/, prod/
│   │                                (основной + kafka_*, redis_*)
│   └── .test.env                    оверлей для pytest поверх стенда local
│
├── tests/                           повторяет структуру app/ (api/, brokers/, core/)
│   ├── fixtures/                    узкие фикстуры отдельных тестов
│   └── conftest.py                  общие фикстуры
│
├── cli/                             скаффолдер и выпуск dev-токенов
├── Makefile                         все команды разработки в одном месте
├── CLAUDE.md                        правила для людей и AI-агентов: слои, импорты, DoD, анти-паттерны
├── Dockerfile / Dockerfile-dev      прод- и dev-сборка образа
├── pyproject.toml / uv.lock         зависимости и настройки инструментов
├── alembic.ini                      конфигурация миграций
├── .pre-commit-config.yaml          проверки перед коммитом
└── uvi_run.py                       точка запуска в контейнере
```

---

## Как добавить новое

Новый код не пишется с нуля — его генерирует **скаффолдер** (`cli/`, вызывается через `make`).
Он создаёт все слои в стиле проекта и сам подключает их. Эталонные примеры каждого слоя —
файлы `my_entity_*` (REST) и `inf_topic_*` (брокеры). Правила архитектуры и список
анти-паттернов — в [CLAUDE.md](./CLAUDE.md).

### REST-сущность

```sh
make scaffold-entity name=Order
```

Что появится:

| Слой | Где |
| --- | --- |
| DTO | `app/api/schemas/order_schema.py` |
| DAO на `BaseDAO` | `app/api/dao/order_dao.py` |
| Сервис на `BaseService` | `app/api/services/order_service.py` |
| CRUD-контроллер | `app/api/controllers/order_controller.py`, уже подключён в `app/api/controllers/__init__.py` |
| Права | класс `OrderPermissions` в `app/core/security/permissions.py` |
| Тест сервиса | `tests/api/services/test_order_service.py` |

Дальше руками:

- [ ] описать ORM-модель в `app/core/dao/models.py` (стиль SQLAlchemy 2.0: `Mapped` +
      `mapped_column`, служебные колонки даёт `BaseEntityModel`);
- [ ] сгенерировать миграцию `make makemigration name="add_order"`, просмотреть её и применить `make migrate`;
- [ ] довести DTO и логику сервиса (как переопределять базовые методы — смотри `my_entity_service.py`);
- [ ] выдать новые права ролям в `JWT_ROLE_PERMISSIONS` или передавать их в claim `PERMISSIONS`;
- [ ] `make check`.

### Kafka-консьюмер

```sh
make scaffold-subscriber topic=ORDER_CREATED value="svc.order.created.01"
```

Что появится:

| Что | Где |
| --- | --- |
| Схема сообщения | `app/brokers/kafka/schemas/subscriber_messages/order_created_schema.py` |
| Топик | `KafkaSubscriberTopics.ORDER_CREATED` в `app/brokers/kafka/schemas/enums.py` |
| Хендлер | дописывается в `app/brokers/kafka/subscribers.py`: только лог-контекст и вызов сервиса через `Depends()` |
| Сервис | `app/brokers/kafka/services/order_created_service.py` |

Дальше руками:

- [ ] описать payload в сгенерированной схеме;
- [ ] реализовать обработку в сервисе;
- [ ] написать тест в `tests/brokers/kafka/` через `TestKafkaBroker` (образец — `test_kafka_subscribers.py`);
- [ ] `make check` — AsyncAPI на `/asyncapi/kafka` обновится сам.

Все возможности скаффолдера: `uv run python -m cli --help`. В Claude Code то же самое доступно
слэш-командами `/add-endpoint` и `/add-subscriber`.

---

## Тесты

Тесты в основном интеграционные: они гоняют реальные контроллеры FastAPI и хендлеры
FastStream, чтобы проверять поведение, близкое к настоящим бизнес-сценариям.

**Устройство.** `tests/api/`, `tests/brokers/` и `tests/core/` зеркалят соответствующие части `app/`.
Общие фикстуры — в `conftest.py`. Фикстуры, нужные паре конкретных тестов, живут в `tests/fixtures/`,
чтобы не засорять `conftest.py`; жёсткой структуры там нет.

**Перед первым запуском** создайте тестовую БД и укажите доступы к ней в `envs/.test.env`.
В этом же файле стоит `TEST_MODE=true` — предохранитель от прогона на настоящей базе.
Обратите внимание: pytest работает на стенде local, а `envs/.test.env` лишь переопределяет
часть его значений. Каталог `envs/test/` — это конфигурация деплой-стенда test, pytest его не читает.

```sh
make test          # на локальном Postgres (после make compose-up)
make test-docker   # на одноразовом Postgres в Docker, без остальной инфраструктуры
uv run pytest -s   # с выводом логов в консоль
make test-cov      # с отчётом о покрытии
```

Покрытие считается по `app/` и не может опуститься ниже порога `fail_under` из `pyproject.toml` —
иначе падают и `make test-cov`, и CI.

---

## Шпаргалка make

| Команда | Что делает |
| --- | --- |
| `make help` | список всех целей |
| `make install` / `make lock` | установить зависимости / пересобрать `uv.lock` |
| `make dev` / `make run` | dev-сервер / запуск как в Docker |
| `make compose-up` / `make compose-down` | поднять / остановить инфраструктуру |
| `make migrate` / `make makemigration name=...` | применить / создать миграцию |
| `make scaffold-entity` / `make scaffold-subscriber` | сгенерировать сущность / консьюмер |
| `make format` / `make lint` / `make typecheck` | форматирование / линт / mypy |
| `make security` | bandit + detect-secrets |
| `make test` / `make test-docker` / `make test-cov` | тесты |
| **`make check`** | **всё сразу — Definition of Done перед коммитом** |
| `make clean` | удалить кэши |
