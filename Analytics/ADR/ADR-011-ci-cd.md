# ADR-011 — CI/CD на GitHub Actions

| Поле | Значение |
|---|---|
| Статус | accepted |
| Версия | 1.0 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-10 (PR #2) |
| Пункт(ы) BRD | все |
| Модуль | все (backend, frontend, deploy); новый компонент репозитория `src/tools/` |
| Зависимости | ADR-001, ADR-002 |
| Связанные ADR/SYS | SYS-10, SYS-11, SYS-12; ADR-004 (имена сервисов compose `api`, `worker`, `migrate`), ADR-005 (скрипты frontend), ADR-006 и ADR-013 (тестовые ключи), ADR-008 (сборка агента), ADR-010 (smoke-тесты наблюдаемости), ADR-012; OQ-05, OQ-06, OQ-07, OQ-39, OQ-70 |

## 1. Контекст

- **Проблема**: в репозитории нет ни одного пайплайна: в `src/backend/py-main-lib/.gitlab-ci.yaml` лежит заглушка GitLab CI из двух строк без job-ов, в `src/frontend` — только `husky` и `lint-staged` в `package.json`, pre-commit бэкенда лежит внутри `src/backend/py-monolyth`. Критерии выхода этапа 1 требуют: «CI зелёный», «тесты на N инстансах входят в CI и проходят», «нарушение границы модуля ломает сборку», «система в полном составе контейнеров разворачивается одной командой обоими способами». Нужно решить состав и структуру workflow-ов GitHub Actions, обязательные проверки для слияния в `main`, способ запуска стенда из N = 3 инстансов за HAProxy внутри CI, проверку Helm chart в kind, сборку и публикацию Docker-образов, генерацию матрицы трассировки, кэширование и бюджет бесплатных минут, обращение с секретами CI и способ доставки на продуктивный VPS.
- **Почему сейчас**: этап 1, п. Г.10 (CI-пайплайн), п. Г.1 (удаление `.gitlab-ci.yaml`, pre-commit на уровне репозитория), п. Г.2 (архитектурные тесты в CI), п. Г.8 (smoke-тесты развёртывания в CI), п. Г.11 (E2E на N инстансах). Первый коммит кода этапа 1 уже должен проходить CI, иначе правило «main защищён, слияние только через PR с зелёным CI» (OQ-05) не выполняется.
- **Ограничения**:
  - OQ-06 (resolved): GitHub Actions, репозиторий остаётся на GitHub; при нехватке бесплатных минут — self-hosted runner на VPS из OQ-07; `.gitlab-ci.yaml` удаляется в п. Г.1;
  - OQ-05 (resolved): ветка на ТЗ `feat/<id>-<slug>`, коммит на шаг конвейера, PR-черновик открывается на шаге 2, слияние merge-коммитом на гейте G3, `main` защищён, Conventional Commits, теги `stage-N`;
  - OQ-07 (resolved): prod — docker-compose на VPS в РФ, Helm chart проверяется установкой в kind в CI;
  - OQ-39 (open): видимость репозитория не решена; для приватного репозитория бесплатные минуты GitHub Actions ограничены (2000 минут в месяц на тарифе Free), для публичного — не ограничены;
  - CLAUDE.md «TDD»: все тесты запускаются в CI, красная сборка блокирует слияние; тесты детерминированы, без сети и ключей; покрытие backend ≥ 75 % (`fail_under`), порог frontend — ADR-005;
  - CLAUDE.md «Масштабирование и состояние»: каждая фича проверяется на стенде из N = 3 инстансов за HAProxy с общими PostgreSQL, Redis, Kafka; интеграционные backend-тесты и E2E по умолчанию выполняются на этом стенде;
  - CLAUDE.md «Развёртывание»: docker-compose и Helm в паритете, миграции отдельным шагом, секреты — `.env` на VPS (не коммитится) и Vault в Kubernetes (ADR-013);
  - CLAUDE.md «Правила для Claude»: все исходники только внутри `src/`; секреты не коммитятся; `make check` и `yarn lint`, `yarn check-types`, `yarn test` (после ADR-005 — `pnpm`) перед коммитом;
  - решение пользователя от 2026-10-10 (ADR-005): менеджер пакетов frontend — pnpm;
  - boilerplate: `renovate.json` (lockFileMaintenance по понедельникам, группа dev tooling), `.pre-commit-config.yaml` (ruff, uv-lock, bandit, detect-secrets), Dockerfile с build-context `py-main-lib`.
- **Если не решить**: код этапа 1 будет сливаться без автоматических проверок, критерии выхода этапа 1 не проверяемы, тесты на N инстансах останутся ручными, а бесплатные минуты CI закончатся на первых же PR из-за неэкономной структуры пайплайна.
- **Ссылки**: CLAUDE.md «Процесс разработки: спецификации + TDD», «Масштабирование и состояние», «Развёртывание», «Соглашения»; SDD_plan.md этап 1 (А.11, Б.12, Г.1, Г.2, Г.8, Г.10, Г.11, критерии выхода); OQ-05, OQ-06, OQ-07, OQ-39; ADR-001, ADR-002, ADR-005, ADR-012, ADR-013; SYS-10, SYS-11, SYS-12.

## 2. Рассматриваемые варианты

Платформа CI (GitHub Actions) решена в OQ-06 и не пересматривается. Сравниваются структура пайплайна (2.1) и способ доставки на VPS (2.2).

### 2.1. Структура пайплайна

#### Вариант A. Один workflow, все проверки на каждый push

- **Описание**: один файл `.github/workflows/ci.yml` с последовательными job-ами (backend, frontend, образы, стенд из 3 инстансов, Helm в kind, E2E) без фильтров по путям и состоянию PR; на тег `stage-N` тот же workflow дополнительно публикует образы.
- **Плюсы**:
  - один файл, простая отладка;
  - любой коммит проверен полностью.
- **Минусы**:
  - конвейер фичи даёт 10–15 коммитов на PR (один коммит на шаг); полный прогон занимает 40–60 минут машинного времени — при 2000 бесплатных минут в месяц это 35–50 прогонов, то есть 3–5 PR;
  - на шагах 5–7 конвейера (красные тесты) стенд из 3 инстансов и E2E заведомо падают — минуты тратятся на ожидаемый отказ;
  - правка только `Analytics/` запускает сборку образов и kind.
- **Масштабирование на N инстансах**: стенд из 3 инстансов проверяется на каждом коммите — избыточно, но корректно.
- **Выделение модулей в микросервисы**: нейтрально; при появлении второго сервиса workflow растёт линейно и становится нечитаемым.
- **Трудоёмкость и риски**: внедрение — 1 день; риск — исчерпание минут в первую неделю этапа 1.

#### Вариант B. Ступенчатый пайплайн: быстрые проверки всегда, тяжёлые — для готовых PR и `main`; отдельные workflow-ы для релиза и доставки

- **Описание**: `ci.yml` с фильтром изменённых путей и двумя ступенями: ступень 1 (линтеры, типы, безопасность, архитектура, unit- и интеграционные тесты backend с PostgreSQL и Redis как `services`, unit-тесты и сборка frontend, линт контрактов) — на каждый push в PR и в `main`; ступень 2 (сборка образов, стенд из 3 инстансов за HAProxy через docker compose с интеграционными тестами масштабируемости и Playwright E2E, Helm в kind) — для PR вне состояния draft, для PR с меткой `ci:full`, для push в `main` и для тегов. `release.yml` на тег `stage-N` публикует образы и chart. `deploy-vps.yml` — ручной запуск с подтверждением. Подробности — раздел 3.
- **Плюсы**:
  - красные коммиты шагов 5–7 проверяются только быстрой ступенью (3–8 минут); полный прогон — на шаге 2 (черновик), при переводе в ready (после зелёного кода) и на `main`;
  - фильтр путей: изменения только в `Analytics/` запускают только проверку документов и матрицы трассировки;
  - разделение по компонентам (backend, frontend, deploy) — основа для пайплайнов отдельных сервисов;
  - `concurrency` с отменой устаревших прогонов той же ветки.
- **Минусы**:
  - три workflow-файла и логика условий `if:` — сложнее отлаживать;
  - draft-PR не проверяется на N инстансах до перевода в ready; Claude обязан перевести PR в ready на шаге 8 конвейера (зелёный код) и дождаться полного прогона до рефакторинга (шаг 9).
- **Масштабирование на N инстансах**: стенд из 3 инстансов проверяется на каждом PR перед слиянием и на каждом коммите `main` — требование CLAUDE.md выполняется там, где это имеет смысл.
- **Выделение модулей в микросервисы**: помогает: job-ы уже разделены по компонентам и путям; новый сервис — новый набор job-ов с тем же шаблоном.
- **Трудоёмкость и риски**: внедрение — 2 дня (минимальная ступень 1 — в п. Г.1, полный пайплайн — в п. Г.10); риск — ошибка в условиях `if:` пропустит тяжёлую ступень; смягчение — обязательные проверки в branch protection требуют успешного статуса тяжёлых job-ов, а не их пропуска (пропущенная обязательная проверка блокирует слияние).

#### Вариант C. Переиспользуемые workflow-ы на компонент с матрицей и composite actions

- **Описание**: `backend.yml`, `frontend.yml`, `deploy.yml` как `workflow_call`, оркестрирующий `ci.yml`, общие шаги в `.github/actions/*` (composite).
- **Плюсы**:
  - переиспользование между репозиториями и будущими сервисами;
  - короткие файлы.
- **Минусы**:
  - при одном репозитории и одном сервисе — лишний уровень косвенности; `workflow_call` усложняет передачу секретов и артефактов между workflow-ами (стенд из 3 инстансов использует образы, собранные другим job-ом);
  - отладка требует знания ограничений вложенных workflow-ов (глубина, лимиты входов).
- **Масштабирование на N инстансах**: как B.
- **Выделение модулей в микросервисы**: помогает сильнее всего, но нужно это будет не раньше первого выделенного сервиса.
- **Трудоёмкость и риски**: внедрение — 3–4 дня; риск — преждевременная сложность.

### 2.2. Доставка на продуктивный VPS

#### Вариант D. Автоматический деплой при push тега `stage-N`

- **Описание**: `release.yml` после публикации образов по SSH выполняет на VPS `docker compose pull` и `up -d`.
- **Плюсы**:
  - одна операция: тег — релиз — деплой.
- **Минусы**:
  - тег `stage-N` ставится на гейте GS по решению человека, но момент деплоя (окно, резервная копия, уведомление учеников) — отдельное решение; автоматический деплой лишает человека паузы между «этап принят» и «обновляем прод»;
  - повторный деплой того же тега (откат, перезапуск после смены `.env`) требует искусственных действий с тегами.
- **Масштабирование на N инстансах**: рестарт реплик по очереди делает docker compose (`up -d` с `--no-deps`), HAProxy исключает инстансы по `/v1/ready`.
- **Выделение модулей в микросервисы**: нейтрально.
- **Трудоёмкость и риски**: внедрение — полдня; риск — непреднамеренный деплой при тегировании.

#### Вариант E. Ручной запуск `workflow_dispatch` с параметром «тег образа» и окружением `prod` с обязательным подтверждением

- **Описание**: `deploy-vps.yml` запускается человеком из вкладки Actions с входом `image_tag` (по умолчанию — последний тег `stage-N`); job привязан к GitHub Environment `prod` с required reviewers (пользователь) и секретами SSH; шаги: проверить, что образы с этим тегом есть в GHCR; по SSH записать тег в файл `/opt/flt/.image-tag.env` на VPS (файл `.env` с секретами CI не трогает); выполнить `docker compose run --rm migrate`; `docker compose up -d --remove-orphans`; дождаться `/v1/ready` всех реплик через HAProxy; при неуспехе — вывести логи и завершиться с ошибкой; откат — повторный запуск с предыдущим тегом.
- **Плюсы**:
  - деплой — осознанное действие человека с подтверждением, отделённое от тегирования; соответствует гейту GS;
  - откат и повторный деплой — тот же workflow;
  - журнал деплоев — история запусков workflow с параметрами.
- **Минусы**:
  - два действия вместо одного (тег, затем запуск);
  - нужен SSH-доступ CI к VPS (ключ в GitHub Secrets окружения `prod`).
- **Масштабирование на N инстансах**: как D.
- **Выделение модулей в микросервисы**: нейтрально; при появлении сервисов `image_tag` становится параметром на сервис.
- **Трудоёмкость и риски**: внедрение — 1 день (вместе с подготовкой VPS в SYS-11); риск — компрометация SSH-ключа; смягчение — отдельный пользователь на VPS с правом только на `docker compose` в `/opt/flt`, ключ только в окружении `prod`, ограничение по IP не применяется (runner-ы GitHub не имеют фиксированных адресов), при переходе на self-hosted runner на том же VPS SSH не нужен.

#### Вариант F. Pull-модель: VPS сам обновляется (watchtower или cron с `docker compose pull`)

- **Описание**: на VPS агент следит за тегом `:prod` в GHCR и перезапускает контейнеры при обновлении образа.
- **Плюсы**:
  - CI не имеет доступа к VPS.
- **Минусы**:
  - не управляет порядком «миграции → инстансы», не ждёт `/v1/ready`, не даёт подтверждения человеком;
  - состояние «что развёрнуто» видно только на VPS.
- **Масштабирование на N инстансах**: перезапуск всех реплик одновременно (watchtower) — простой на время рестарта.
- **Выделение модулей в микросервисы**: нейтрально.
- **Трудоёмкость и риски**: внедрение — полдня; риск — обновление без миграций.

## 3. Решение

- **Выбран**: Вариант B (ступенчатый пайплайн) + Вариант E (ручной деплой с подтверждением).
- **Решение**: CI/CD выполняется в GitHub Actions тремя workflow-ами в `.github/workflows/`: `ci.yml` (две ступени проверок на PR и `main`), `release.yml` (публикация образов и Helm chart в GHCR по тегу `stage-N`), `deploy-vps.yml` (ручной деплой на VPS с подтверждением в окружении `prod`); слияние в `main` возможно только при успехе обязательных проверок из раздела 3.3; стенд из N = 3 инстансов за HAProxy поднимается в CI через docker compose и является обязательной проверкой; Helm chart проверяется `helm lint`, `helm template` с kubeconform и установкой в kind; все секреты CI хранятся в GitHub Secrets и Environments, в репозитории секретов нет; при исчерпании 80 % месячного лимита минут подключается self-hosted runner на отдельном VPS. Репозиторные скрипты (матрица трассировки, правила контрактов) живут в `src/tools/` — Python-пакете `flt_tools` с тестами и теми же линтерами, что у бэкенда (ruff, mypy strict, pytest); скрипты развёртывания — в `deploy/scripts/` (подтверждено пользователем 2026-10-10). Правило конвейера «PR переводится из draft в ready на шаге 8 (зелёный код)» принято пользователем 2026-10-10 (OQ-70) и записывается в SDD_plan.md §5 и SYS-12.
- **Обоснование**: вариант B укладывает конвейер фичи (10–15 коммитов на PR, из них 3–5 с намеренно красными тестами) в бюджет бесплатных минут, не ослабляя требование «стенд из N инстансов перед слиянием»; вариант E сохраняет за человеком решение о моменте обновления прода и даёт откат тем же инструментом.
- **Отвергнуты**:
  - Вариант A — исчерпывает бесплатные минуты за несколько PR и тратит их на ожидаемо красные коммиты.
  - Вариант C — преждевременная сложность при одном сервисе; переход к `workflow_call` возможен без изменения состава job-ов при выделении первого микросервиса.
  - Вариант D — смешивает приёмку этапа и обновление прода; откат неудобен.
  - Вариант F — не управляет миграциями и готовностью инстансов.
- **Границы решения**: ADR не задаёт содержимое Helm chart и структуру `deploy/` (SYS-11, OQ-28, OQ-29), состав стенда и методику тестов масштабируемости (SYS-05, SYS-10), пороги покрытия frontend (ADR-005), способ хранения секретов на VPS и в Kubernetes (ADR-013), конфигурацию HAProxy (ADR-012), лицензию и видимость репозитория (OQ-39). Нагрузочные тесты Locust (OQ-13) появляются как необязательный job с этапа 2 и здесь только зарезервированы.

### 3.1. Workflow `ci.yml`

Триггеры: `pull_request` (типы `opened`, `synchronize`, `reopened`, `ready_for_review`, `labeled`) в `main`; `push` в `main`; `workflow_dispatch`. `concurrency: group: ci-${{ github.ref }}, cancel-in-progress: true` для PR (для `main` — без отмены).

Условие тяжёлой ступени (переменная `run_full` в job `changes`): `github.event_name == 'push'` или `github.event.pull_request.draft == false` или метка `ci:full` на PR или `workflow_dispatch`.

| Job | Ступень | Условие запуска | Шаги | Runner, оценка времени |
|---|---|---|---|---|
| `changes` | 1 | всегда | `dorny/paths-filter`: флаги `backend` (`src/backend/**`, `deploy/**`), `frontend` (`src/frontend/**`), `deploy` (`deploy/**`), `docs` (`Analytics/**`, `*.md`), `contracts` (`Analytics/Specs/**/api/*.yaml`); вычисляет `run_full` | ubuntu-latest, менее 1 мин |
| `backend-quality` | 1 | `backend` | `astral-sh/setup-uv` (кэш по `uv.lock`), `uv python install` версии из `.python-version`, `make install`, `make format-check`, `make lint`, `make typecheck`, `make security` (bandit, detect-secrets) | ubuntu-latest, 3–4 мин |
| `architecture` | 1 | `backend` | `make arch` (`lint-imports`), `uv run pytest tests/architecture` (в том числе негативный тест границ, ADR-002); отдельный job, чтобы нарушение границы было видно по имени проверки | ubuntu-latest, 2 мин |
| `backend-tests` | 1 | `backend` | `services:` PostgreSQL (образ из `deploy/docker-compose/docker-compose.yml`), Redis; Kafka не нужен (`TestKafkaBroker`); `make test-cov` с порогом `fail_under`; отчёт покрытия и `junit.xml` с тегами критериев приёмки — артефакты | ubuntu-latest, 4–6 мин |
| `frontend` | 1 | `frontend` | `pnpm/action-setup` (версия из `packageManager`), `actions/setup-node` (версия из `.nvmrc`, кэш pnpm store), `pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm format:check`, `pnpm check-types`, `pnpm i18n:check`, `pnpm api:check` (сгенерированный клиент и zod-схемы не устарели относительно контрактов), `pnpm test:cov` (порог — ADR-005), `pnpm build`, `pnpm build-storybook`; `dist/` — артефакт (имена скриптов — ADR-005) | ubuntu-latest, 5–6 мин |
| `contracts` | 1 | `contracts` | Spectral (`pnpm dlx @stoplight/spectral-cli@<версия>`, версия зафиксирована в `src/tools/contracts/.spectral.yaml` и обновляется Renovate) с наборами правил `spectral:oas` для `Analytics/Specs/**/api/openapi.yaml` и `spectral:asyncapi` для `asyncapi.yaml`; собственные правила проекта (`.spectral.yaml` в `src/tools/contracts/`, требования — SYS-03, SYS-04); `uv run flt-tools contracts check` из `src/tools` оборачивает вызов и проверяет перечень контрактов по реестру модулей | ubuntu-latest, 1 мин |
| `docs` | 1 | `docs` | `markdownlint` для `Analytics/**/*.md`; проверка матрицы трассировки: `uv run flt-tools traceability check` из `src/tools/` (Python-пакет `flt_tools`, тесты и линтеры как у бэкенда) — пересобирает таблицы `Analytics/traceability.md` из шапок спецификаций и тегов тестов и падает, если файл в репозитории отличается (генерация выполняется на шаге 14 конвейера, CI только проверяет) | ubuntu-latest, 1 мин |
| `images` | 2 | `run_full` и (`backend` или `frontend` или `deploy`) | `docker/setup-buildx-action`, `docker/build-push-action` для `flt-backend` (контекст `src/backend/py-monolyth`, `build-contexts: py-main-lib=src/backend/py-main-lib`) и `flt-frontend` (контекст `src/frontend`, Nginx); кэш слоёв `type=gha`; на PR — `push: false`, `outputs: type=docker,dest=…` и артефакт `images.tar`; на `main` — push в GHCR с тегами `main` и `sha-<7>` | ubuntu-latest, 5–8 мин |
| `stand-n3` | 2 | `run_full` и (`backend` или `deploy`) | загрузить образы из артефакта; `docker compose -p flt -f deploy/docker-compose/docker-compose.yml -f deploy/docker-compose/docker-compose.ci.yml --profile ci up -d --wait --scale api=3` — сервис `api` в 3 репликах за HAProxy, `worker` в 2, PostgreSQL, Redis, Kafka, MinIO и сервис `migrate` (имена сервисов — ADR-004); `uv run pytest -m n_instances` (тесты масштабируемости SYS-10 через HAProxy, в том числе остановка одного инстанса — `docker compose -p flt stop` конкретного контейнера `flt-api-2`, имена контейнеров compose `<project>-<service>-<n>`, и одного воркера `flt-worker-2`); при падении — `docker compose logs` артефактом; `docker compose down -v` | ubuntu-latest (4 vCPU, 16 ГБ), 8–12 мин |
| `e2e` | 2 | `run_full` и (`frontend` или `backend`) | Playwright с проектами `chromium-desktop`, `chromium-mobile`, `ar` (ADR-005): сценарии на mock-сервере (языки ru, en, ar) и сквозной сценарий «ходячего скелета» на стенде из 3 инстансов (Г.11), для чего job поднимает тот же compose, что `stand-n3`; кэш браузеров по версии Playwright; отчёт и трассы — артефакты | ubuntu-latest, 8–10 мин |
| `helm` | 2 | `run_full` и `deploy` | `helm lint deploy/helm/flt`, `helm template … \| kubeconform -strict -summary`, `helm/kind-action`, `kind load docker-image` для образов из артефакта, `helm install flt deploy/helm/flt -f deploy/helm/flt/values-ci.yaml --wait --timeout 10m` (2 реплики `flt-api`, 1 `flt-worker`, уменьшенные ресурсы, Vault выключен — профиль CI, SYS-11), `kubectl rollout status`, smoke: `kubectl exec` в под `flt-api` — `GET localhost:8000/v1/ready` 200, в под `flt-worker` — `GET localhost:8001/v1/ready` 200; через HAProxy — `GET /` 200, `GET /api/v1/auth/.well-known/jwks.json` 200, `GET /api/docs` 404, `GET /v1/ready` не достигает монолита (ADR-012); при падении — `kubectl describe` и логи артефактом | ubuntu-latest, 8–10 мин |
| `ci-ok` | — | всегда (`if: always()`) | Сводный job: падает, если любой нужный job упал или был пропущен при `run_full == true`; единственная обязательная проверка в branch protection помимо именованных (раздел 3.3) | ubuntu-latest, менее 1 мин |

Оценка минут: быстрая ступень — 10–15 минут машинного времени на коммит (job-ы параллельны), полный прогон — 45–60 минут. Конвейер одной фичи (12 коммитов, 3 полных прогона) — 250–300 минут; при 2000 минут в месяц — 6–7 фич в месяц на бесплатном тарифе приватного репозитория. При публичном репозитории (OQ-39) лимита нет.

### 3.2. Workflow `release.yml` и `deploy-vps.yml`

`release.yml` — триггер `push` тега `stage-*` (тег ставит человек на гейте GS по OQ-05): проверка, что коммит тега входит в `main`; сборка и push образов `ghcr.io/alextaralexander/flt/backend:<tag>` и `…/frontend:<tag>` (плюс `sha-<7>`); `helm package` и push chart в `oci://ghcr.io/alextaralexander/flt/charts` с версией `0.<N>.0` для `stage-N` и `appVersion = <tag>`; GitHub Release с автоматическим перечнем PR. Образы на `main` (`:main`, `:sha-<7>`) публикует `ci.yml`; тег `latest` не используется. Отдельный workflow `agent-release.yml` по тегу `agent-v<X.Y.Z>` собирает локальный агент на матрице платформ и публикует дистрибутивы в бакет `flt-local-runtime` (ADR-008; появляется на этапе 4).

`deploy-vps.yml` — триггер `workflow_dispatch` с входами `image_tag` (строка, обязательный) и `run_migrations` (булев, по умолчанию `true`); job в окружении `prod` (required reviewers: пользователь; секреты окружения `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`); шаги: проверить наличие образов с тегом в GHCR (`docker manifest inspect`); по SSH на VPS в каталоге `/opt/flt`: записать `FLT_IMAGE_TAG=<tag>` в `.image-tag.env` (compose читает его через `env_file`, файл `.env` с секретами CI не читает и не пишет — ADR-013); `docker compose pull`; при `run_migrations` — `docker compose run --rm migrate` (цель `make migrate` по всем модулям, ADR-002); `docker compose up -d --remove-orphans`; ожидание `/v1/ready` каждой реплики через HAProxy статистику или `docker compose ps --format json` (все `healthy`) не дольше 5 минут; вывод `docker compose ps`. Откат — повторный запуск с предыдущим `image_tag`. Предварительная подготовка VPS (Docker, пользователь `flt-deploy` с доступом к `docker compose` только в `/opt/flt`, каталог, `.env`) — ручная по чек-листу SYS-11; CI не создаёт и не меняет секреты на VPS.

### 3.3. Защита ветки `main` (branch protection, настраивает пользователь)

- Прямые push запрещены, в том числе администраторам; слияние только через PR; merge commit (squash и rebase отключены — OQ-05).
- Обязательные проверки (status checks, «Require branches to be up to date»): `ci-ok`, `backend-quality`, `architecture`, `backend-tests`, `frontend`, `contracts`, `docs`, `images`, `stand-n3`, `e2e`, `helm`. Пропущенный job (`skipped`) из-за фильтра путей считается успешным только для job-ов, чьи пути не менялись: это обеспечивает `ci-ok`, который падает при пропуске нужного job-а; job-ы, не затронутые изменением, отчитываются статусом `success` через явный пустой шаг (паттерн «always-report»), а не `skipped`.
- Одно одобрение ревьюера (пользователь) — гейт G3; «Dismiss stale approvals» включено; разрешение разговоров перед слиянием включено.
- Force push и удаление ветки `main` запрещены; теги `stage-*` защищены правилом tag protection (создаёт только пользователь).

### 3.4. Кэширование, время, бюджет

- uv: `astral-sh/setup-uv` с `enable-cache: true` и `cache-dependency-glob: src/backend/py-monolyth/uv.lock`; интерпретатор Python из кэша uv.
- pnpm: `pnpm/action-setup` + `actions/setup-node` с `cache: pnpm` и `cache-dependency-path: src/frontend/pnpm-lock.yaml`.
- Docker: `cache-from/cache-to: type=gha,scope=<image>`; образы между job-ами передаются артефактом `images.tar` (срок хранения 1 день).
- Playwright: кэш `~/.cache/ms-playwright` по версии `@playwright/test` из `pnpm-lock.yaml`.
- Helm и kind: кэш бинарников через `azure/setup-helm` и `helm/kind-action` с фиксированными версиями.
- Таймауты: `timeout-minutes` у каждого job-а (быстрые — 10, тяжёлые — 20), чтобы зависший стенд не сжигал минуты.
- Мониторинг бюджета: пользователь проверяет Settings → Billing раз в неделю; при расходе 80 % лимита до конца месяца — включается self-hosted runner (раздел 3.5). Срок хранения артефактов — 7 дней (отчёты покрытия и Playwright), 1 день (образы).

### 3.5. Self-hosted runner (запасной вариант по OQ-06)

- Когда: расход минут превысил 80 % месячного лимита или полный прогон на hosted runner стал дольше 20 минут из-за очереди.
- Где: отдельный VPS в РФ (не продуктивный: совместное размещение CI и прода на одной машине даёт CI доступ к продуктивным данным и `.env`); если пользователь решит использовать продуктивный VPS, это отдельное решение с изоляцией runner-а в пользователе без доступа к `/opt/flt` — новый OQ (раздел отчёта).
- Как: `actions-runner` как systemd-сервис под отдельным пользователем с доступом к Docker, метки `self-hosted, linux, x64, flt`; `runs-on` тяжёлых job-ов задаётся переменной репозитория `CI_HEAVY_RUNNER` (`ubuntu-latest` по умолчанию, `[self-hosted, flt]` при включении) — переключение без правки workflow-ов; ephemeral-режим (`--ephemeral`) и очистка `docker system prune` после job-а.
- Ограничения: self-hosted runner не выполняет job-ы для PR из форков (для приватного репозитория форков нет; при публикации репозитория по OQ-39 — настройка «Require approval for all outside collaborators» и запрет self-hosted для `pull_request` из форков).

### 3.6. Секреты CI

- Хранилище: GitHub Secrets уровня репозитория (пока нет) и окружения `prod` (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`). Публикация в GHCR — встроенный `GITHUB_TOKEN` с `permissions: packages: write` только в job-ах `images` (на `main`) и `release.yml`; остальные job-ы — `permissions: contents: read`.
- В тестах секретов нет: LLM, TTS/STT, капча, OAuth подменяются заглушками (CLAUDE.md «TDD», OQ-10, OQ-12); ключи подписи JWT для pytest генерирует фикстура shared kernel (одноразовая Ed25519-пара на сессию тестов — ADR-006), для стенда `stand-n3` и kind их создаёт `deploy/scripts/gen-secrets.sh --ci` в шаге job-а (ADR-013); пароль PostgreSQL CI — несекретная константа в `docker-compose.ci.yml`, помеченная как тестовая.
- `detect-secrets` с базлайном `.secrets.baseline` — в `backend-quality`; при переносе pre-commit на уровень репозитория базлайн охватывает весь репозиторий.
- Логи workflow-ов не печатают переменные окружения стендов; `.env` на VPS не передаётся через CI.

### 3.7. Pre-commit на уровне репозитория

Один `.pre-commit-config.yaml` в корне: hook-и бэкенда из `src/backend/py-monolyth/.pre-commit-config.yaml` с `files: ^src/backend/py-monolyth/` (ruff-check, ruff-format, uv-lock, bandit, detect-secrets, lint-imports), hook-и фронтенда (`pnpm lint-staged` через `local` hook с `files: ^src/frontend/`), `markdownlint` для `Analytics/`; `husky` из boilerplate фронтенда удаляется (ADR-005). CI остаётся источником истины: pre-commit ускоряет цикл, но не заменяет проверки.

## 4. Последствия

### 4.1. Положительные

- Критерии выхода этапа 1 «CI зелёный», «тесты на N инстансах входят в CI», «нарушение границы ломает сборку» становятся проверяемыми автоматически и видны по именам обязательных проверок.
- Конвейер фичи с красными коммитами укладывается в бесплатный бюджет минут; полный прогон гарантирован перед слиянием и на `main`.
- Деплой на прод — явное действие человека с подтверждением, журналом и откатом тем же workflow-ом.
- Образы и chart публикуются по тегу этапа; любой тег воспроизводим.
- Структура job-ов по компонентам готова к появлению отдельных сервисов.

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Draft-PR не проходит стенд из 3 инстансов и E2E до перевода в ready | Шаг 8 конвейера (зелёный код) обязывает перевести PR в ready; метка `ci:full` запускает полный прогон на draft по требованию |
| Условия `if:` могут ошибочно пропустить тяжёлый job | `ci-ok` падает при пропуске нужного job-а; обязательные проверки требуют статуса `success` |
| 2000 минут в месяц на приватном репозитории — около 6–7 фич в месяц с полным конвейером | Фильтр путей, отмена устаревших прогонов, self-hosted runner (3.5), публикация репозитория (OQ-39) |
| Hosted runner (4 vCPU, 16 ГБ) ограничивает состав стенда: OpenSearch, Qdrant, Grafana в CI-профиль не входят | `docker-compose.ci.yml` поднимает только контейнеры, нужные тестам масштабируемости; полный состав проверяется `up -d --wait` без тестов в job `helm` и в еженедельном расписании `schedule` (ночной прогон полного compose, не блокирующий) |
| SSH-ключ CI к продуктивному VPS | Отдельный пользователь на VPS, ключ только в окружении `prod` с required reviewers, ротация при каждом этапе |
| Три workflow-файла и переменные условий — сложнее поддерживать | Единый job `changes` вычисляет все флаги; документация в SYS-12; `actionlint` в pre-commit и в job `docs` |
| Генерация матрицы трассировки требует скрипта вне `src/backend` и `src/frontend` | Компонент `src/tools/` (Python-пакет `flt_tools`: traceability, contracts; тесты и линтеры бэкенда) — новый пункт структуры репозитория, подтверждён пользователем 2026-10-10; скрипты развёртывания — `deploy/scripts/` |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Удалить заглушку GitLab CI | `src/backend/py-main-lib/.gitlab-ci.yaml` | Claude (этап 1 Г.1) | не начато |
| Создать минимальный `ci.yml` (job-ы `changes`, `backend-quality`, `architecture`, `backend-tests`, `frontend`, `docs`, `ci-ok`) с первым коммитом кода этапа 1 | `.github/workflows/ci.yml` | Claude (этап 1 Г.1) | не начато |
| Дополнить `ci.yml` job-ами `contracts`, `images`, `stand-n3`, `e2e`, `helm`; создать `release.yml` и `deploy-vps.yml` | `.github/workflows/` | Claude (этап 1 Г.10) | не начато |
| Добавить `deploy/docker-compose/docker-compose.ci.yml` (`api` ×3 через `--scale api=3`, `worker` ×2, HAProxy, сервис `migrate`, профиль `ci`, имя проекта `flt`) и `deploy/helm/flt/values-ci.yaml` одновременно; сервис `migrate` и `FLT_IMAGE_TAG` через `.image-tag.env` в продуктивном compose | `deploy/docker-compose/` и `deploy/helm/` одновременно; SYS-11 | Claude (этап 1 Г.8) | не начато |
| Описать маркер `n_instances`, запуск тестов масштабируемости через HAProxy и остановку инстанса в CI (`docker compose -p flt stop flt-api-2`); E2E в проектах `chromium-desktop`, `chromium-mobile`, `ar` | SYS-10 | Claude | не начато |
| Описать этапы пайплайна, обязательные проверки, бюджет минут, self-hosted runner, `actionlint` | SYS-12 | Claude | не начато |
| Записать правило «PR переводится из draft в ready на шаге 8 конвейера (зелёный код), полный прогон ждётся до рефакторинга» (принято пользователем 2026-10-10, OQ-70) | `Analytics/BRD/SDD_plan.md` §5, SYS-12 | Claude | не начато |
| Правила Spectral для OpenAPI и AsyncAPI, версии стандартов | SYS-03, SYS-04; `src/tools/contracts/.spectral.yaml` | Claude | не начато |
| Пакет `src/tools/` (`flt_tools`: `pyproject.toml` с Python 3.14 по ADR-001, команды `traceability check`/`generate`, `contracts check`, тесты, ruff и mypy strict); описать в CLAUDE.md «Структура репозитория» вместе с `deploy/scripts/` | `src/tools/`, CLAUDE.md | Claude (этап 1 Г.10) | не начато |
| Workflow `agent-release.yml` (сборка агента по тегу `agent-v*`, матрица платформ, публикация в `flt-local-runtime`, выключенные шаги подписи) | `.github/workflows/agent-release.yml` (ADR-008) | Claude (этап 4) | не начато |
| Перенести pre-commit на уровень репозитория, удалить husky | `.pre-commit-config.yaml` в корне, `src/frontend/package.json` | Claude (этап 1 Г.1, вместе с ADR-005) | не начато |
| Настроить branch protection для `main` и tag protection для `stage-*` по разделу 3.3, окружение `prod` с required reviewers, секреты окружения | GitHub, Settings репозитория | человек | не начато |
| Подготовить VPS по чек-листу: Docker, пользователь `flt-deploy`, `/opt/flt`, `.env` | SYS-11 (чек-лист), VPS | человек (по чек-листу Claude) | не начато |
| Переменная репозитория `CI_HEAVY_RUNNER`; при необходимости — отдельный VPS под runner | GitHub Settings → Variables; OQ (новый, раздел отчёта) | человек | не начато |
| Обновить разделы «Соглашения» (CI, обязательные проверки, деплой по `workflow_dispatch`), «Команды» (`make arch`, `pnpm`), «Структура репозитория» (`.github/workflows`, `src/tools`, `deploy/scripts`) | CLAUDE.md | Claude (при принятии ADR) | не начато |
| Уточнить п. Г.10 (состав workflow-ов) и п. Г.1 (минимальный CI с первого коммита) | `Analytics/BRD/SDD_plan.md`, этап 1 | Claude | не начато |
| Решить OQ-39 (видимость и лицензия) — влияет на бюджет минут и доступ к GHCR | `Analytics/open-questions.md` | человек | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-001](ADR-001-tech-stack.md) | зависит от | Версии Python, Node, pnpm, uv; Renovate обновляет и GitHub Actions |
| [ADR-002](ADR-002-module-layout.md) | зависит от | Job `architecture`: `lint-imports` и негативный тест; `make migrate` по модулям в сервисе `migrate` |
| [ADR-004](ADR-004-communication-patterns.md) | зависит от | Имена сервисов compose `api`, `worker`, `migrate`; порты 8000/8001 для smoke |
| [ADR-005](ADR-005-frontend-stack.md) | дополняет | pnpm, скрипты `api:check`, `test:cov`, `format:check`, `i18n:check`, `build-storybook`, проекты Playwright, порог покрытия, удаление husky |
| [ADR-006](ADR-006-authentication-and-authorization.md) | дополняет | Одноразовая Ed25519-пара в фикстуре pytest |
| [ADR-008](ADR-008-local-agent.md) | дополняет | Workflow `agent-release.yml`, матрица платформ |
| [ADR-010](ADR-010-observability-stack.md) | дополняет | Smoke-тесты обнаружения инстансов и логов в CI |
| [ADR-012](ADR-012-haproxy-entry-point.md) | дополняет | Пути smoke-проверок через HAProxy, health-check `/v1/ready`, служебные пути снаружи недостижимы |
| [ADR-013](ADR-013-secrets-management.md) | ограничен | `.env` на VPS ведёт человек; CI передаёт только тег образа; `gen-secrets.sh --ci` для стендов CI |
| [SYS-10](../Specs/_system/SYS-10-test-strategy.md) | дополняет | Маркеры тестов, стенд из N инстансов, Locust с этапа 2 |
| [SYS-11](../Specs/_system/SYS-11-deployment-and-environments.md) | дополняет | `docker-compose.ci.yml`, `values-ci.yaml`, чек-лист VPS, сервис миграций |
| [SYS-12](../Specs/_system/SYS-12-ci-cd-and-quality.md) | детализирует это ADR | Этапы пайплайна, обязательные проверки, матрица трассировки |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Решения пользователя 2026-10-10: `src/tools/` — Python-пакет с тестами и линтерами бэкенда, `deploy/scripts/` — скрипты развёртывания, правило «PR в ready на шаге 8» (OQ-70). Согласование с ADR-005 (имена скриптов `api:check`, `test:cov`, `format:check`, `i18n:check`, `build-storybook`, проекты Playwright), ADR-004 (сервис `api` с `--scale api=3`, остановка контейнера `flt-api-2`), ADR-012 и ADR-010 (пути smoke-проверок), ADR-006 и ADR-013 (тестовые ключи JWT из фикстуры и `gen-secrets.sh --ci`), ADR-008 (`agent-release.yml`) | proposed |
| 1.0 | 2026-10-10 | пользователь | Принят без изменений (PR #2, слияние в main) | accepted |
