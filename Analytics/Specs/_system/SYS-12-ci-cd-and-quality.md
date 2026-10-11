# SYS-12 — CI/CD и качество

| Поле | Значение |
|---|---|
| Статус | draft |
| Версия | 0.1 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | все |
| Модуль | все (backend, frontend, `src/tools`, deploy, Analytics) |
| Зависимости | ADR-011 (accepted); ADR-001, ADR-002, ADR-005, ADR-013 (accepted); SYS-10 (тесты и теги), SYS-05 (стенд N3), SYS-11 (compose CI, Helm `values-ci.yaml`, чек-лист VPS) |
| Связанные ADR/SYS | ADR-003, ADR-004, ADR-006, ADR-010, ADR-012; SYS-03, SYS-04 (правила Spectral); OQ-05, OQ-06, OQ-07, OQ-39, OQ-68, OQ-70 |

## 1. Цель и область действия

- **Цель**: зафиксировать как проверяемые требования состав и порядок автоматических проверок, без которых изменение не попадает в `main` (линтеры, типы, безопасность, архитектура, тесты всех уровней, стенд N3, Helm в kind), правила ветвления, коммитов, релизов и деплоя на VPS, автоматическую генерацию матрицы трассировки и проверку статусов спецификаций, разделение Definition of Done на то, что проверяет CI, и то, что проверяет человек, а также бюджеты времени и минут и публикацию метрик качества.
- **Область действия**: CI (`.github/workflows/*`), pre-commit на уровне репозитория, `src/tools` (пакет `flt_tools`), конфигурации линтеров backend, frontend, Analytics и deploy, настройки репозитория GitHub (branch protection, environments, Renovate), CD на VPS. Не задаёт содержимое тестов (SYS-10) и структуру `deploy/` (SYS-11).
- **Действует с этапа**: 1 — минимальный `ci.yml` с первым коммитом кода (п. Г.1), полный пайплайн — п. Г.10; CD на VPS — с этапа 2 (OQ-07, OQ-08).
- **Уточняет**: ADR-011 целиком; CLAUDE.md, разделы «Процесс разработки» (TDD, Definition of Done), «Соглашения» (ветвление и коммиты — OQ-05), «Правила для Claude» (`make check`, `pnpm`-проверки перед коммитом); SDD_plan.md §5 (шаги конвейера и момент перевода PR в ready); `traceability.md`, раздел 3.

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| Конвейер фичи, Гейт, Definition of Done, Матрица трассировки, Статус ТЗ, Этап | [глоссарий](../../glossary.md), раздел 12 |
| Быстрая ступень | Job-ы `ci.yml`, выполняемые на каждый push в PR и в `main`: `changes`, `backend-quality`, `architecture`, `backend-tests`, `frontend`, `tools`, `contracts`, `docs`, `commits` (ADR-011, раздел 3.1; `tools` и `commits` добавлены этой спецификацией — R2) |
| Тяжёлая ступень | Job-ы `images`, `stand-n3`, `e2e`, `helm`, выполняемые при `run_full == true` (R3) |
| `run_full` | Признак запуска тяжёлой ступени: push в `main`, PR вне состояния draft, метка `ci:full`, `workflow_dispatch` (ADR-011) |
| Обязательная проверка | Status check, требуемый branch protection для слияния в `main` (R4) |
| `ci-ok` | Сводный job, который падает, если любой нужный job упал или был пропущен при `run_full == true` (ADR-011) |
| Паттерн always-report | Job, не затронутый изменением путей, отчитывается статусом `success` пустым шагом, а не `skipped`, чтобы обязательная проверка считалась пройденной (ADR-011, раздел 3.3) |
| `flt_tools` | Python-пакет `src/tools` с командами `traceability`, `contracts`, `specs`, `quality`, `commits` (ADR-011; OQ-70) |
| Метка `deps:major`, `deps:runtime`, `ci:full` | Метки PR: мажорное обновление зависимости и обновление runtime (Renovate, ADR-001); принудительный полный прогон CI (ADR-011) |

## 3. Требования

Группы: структура пайплайна и обязательные проверки (R1–R5), линтеры и форматтеры (R6–R12), архитектурные проверки, трассировка и спецификации (R13–R15), Definition of Done (R16), ветвление, коммиты, релизы (R17–R21), зависимости и секреты (R22–R24), кэш, время, бюджет (R25–R27), CD на VPS (R28–R30), метрики качества и регулярные прогоны (R31–R33), локальный запуск (R34).

### SYS-12-R1 Три workflow-файла

- **Формулировка**: CI/CD репозитория должен состоять из workflow-ов `.github/workflows/ci.yml` (проверки PR и `main`), `.github/workflows/release.yml` (публикация образов и chart по тегу `stage-*`), `.github/workflows/deploy-vps.yml` (ручной деплой на VPS), регулярного `.github/workflows/nightly.yml` (R33) и, с этапа 4, `.github/workflows/agent-release.yml` (ADR-008); другие workflow-файлы не добавляются без изменения этой спецификации.
- **Обоснование**: ADR-011, раздел 3 (вариант B): ступенчатый `ci.yml`, отдельные `release.yml` и `deploy-vps.yml`; ограниченный набор файлов упрощает отладку условий `if:`.
- **Проверка**: тест `src/tools/tests/test_workflows.py::test_only_known_workflows` (будет создан: список файлов `.github/workflows/` равен ожидаемому); `actionlint` (R12).
- **Применимость**: CI.

### SYS-12-R2 Быстрая ступень на каждый push

- **Формулировка**: На каждый push в PR и в `main` должны выполняться job-ы быстрой ступени с фильтром изменённых путей (`dorny/paths-filter` в job `changes`): `backend-quality` (`make format-check`, `make lint`, `make typecheck`, `make security`), `architecture` (`make arch`, `pytest tests/architecture`), `backend-tests` (`make test-cov` с `services:` PostgreSQL, Redis, MinIO), `frontend` (`pnpm install --frozen-lockfile`, `lint`, `format:check`, `check-types`, `i18n:check`, `api:check`, `test:cov`, `build`, `build-storybook`), `tools` (`uv run ruff check`, `mypy`, `pytest` в `src/tools`), `contracts` (Spectral и `flt-tools contracts check`), `docs` (`markdownlint`, `flt-tools specs check`, `flt-tools traceability check`), `commits` (`commitlint` и `flt-tools commits check` по коммитам PR); job, чьи пути не менялись, отчитывается `success` пустым шагом.
- **Обоснование**: ADR-011, раздел 3.1 (состав быстрой ступени и фильтр путей); CLAUDE.md «TDD»: «Все тесты запускаются в CI, красная сборка блокирует слияние». Job-ы `tools` и `commits` добавлены: пакет `flt_tools` должен проходить те же проверки, что бэкенд (ADR-011, раздел 3), а Conventional Commits (OQ-05) нуждаются в автоматической проверке.
- **Проверка**: `src/tools/tests/test_workflows.py::test_fast_stage_jobs_present` (разбор `ci.yml`: имена job-ов, отсутствие условия `run_full` у них, шаги с перечисленными командами); `actionlint`.
- **Применимость**: CI.

### SYS-12-R3 Тяжёлая ступень по условию `run_full`

- **Формулировка**: Job-ы `images`, `stand-n3`, `e2e`, `helm` должны выполняться только при `run_full == true` (`github.event_name == 'push'` в `main`, `pull_request.draft == false`, метка `ci:full`, `workflow_dispatch`) и при изменении соответствующих путей; `stand-n3` выполняет `pytest -m n_instances` на стенде N3 и тест совместимости миграций (SYS-05-R34, R54), `e2e` — Playwright на mock-сервере и смоук на стенде N3 (SYS-10-R31), `helm` — `helm lint`, `kubeconform`, установку в kind и smoke-запросы из ADR-011.
- **Обоснование**: ADR-011, раздел 3.1: красные коммиты шагов 5–7 проверяются только быстрой ступенью; полный прогон — на готовых PR и в `main`.
- **Проверка**: `test_workflows.py::test_heavy_jobs_gated_by_run_full`; `actionlint`; ручная проверка условий на первом PR этапа 1 (ADR-011, раздел 2.1 B, риск ошибок `if:`) — результат фиксируется в описании PR.
- **Применимость**: CI.

### SYS-12-R4 Обязательные проверки и защита `main`

- **Формулировка**: Branch protection ветки `main` должна требовать успешного статуса проверок `ci-ok`, `backend-quality`, `architecture`, `backend-tests`, `frontend`, `tools`, `contracts`, `docs`, `commits`, `images`, `stand-n3`, `e2e`, `helm`, актуальности ветки («Require branches to be up to date»), одного одобрения ревьюера с отзывом устаревших одобрений, разрешения всех разговоров; прямые push и force push запрещены всем, включая администраторов; слияние — только merge commit; `ci-ok` должен падать, если при `run_full == true` любой тяжёлый job пропущен или упал.
- **Обоснование**: ADR-011, раздел 3.3; OQ-05 (resolved): `main` защищён, слияние merge-коммитом без squash на гейте G3.
- **Проверка**: настройки GitHub выполняет пользователь по чек-листу `deploy/README.md` (раздел «Настройки репозитория»); автоматическая сверка — `flt-tools quality check-branch-protection` (вызов GitHub API `GET /repos/{owner}/{repo}/branches/main/protection` в job `docs` на `main` с `GITHUB_TOKEN`, сравнение со списком; падение — предупреждение в step summary, не ошибка, так как настройка вне репозитория); `test_workflows.py::test_ci_ok_depends_on_all_jobs`.
- **Применимость**: CI, настройки репозитория (человек).

### SYS-12-R5 Момент перевода PR из draft в ready

- **Формулировка**: PR фичи должен открываться черновиком на шаге 2 конвейера и переводиться в состояние ready на шаге 11 (E2E green — все тесты backend, frontend и E2E зелёные локально), до шага 12 (рефакторинг); первый полный прогон CI после перевода должен быть зелёным до начала рефакторинга, а рефакторинг (шаг 12) и последующие шаги выполняются при включённой тяжёлой ступени; досрочный полный прогон на черновике запускается меткой `ci:full`.
- **Обоснование**: ADR-011 (раздел 3): правило принято пользователем 2026-10-10 с формулировкой «на шаге 8 (зелёный код)». В SDD_plan.md §5 шаг 8 — гейт G2 (ревью красных тестов), а зелёный код — шаги 9 (backend), 10 (frontend), 11 (E2E); перевод в ready на шаге 9 запускал бы тяжёлую ступень на заведомо красных frontend- и E2E-тестах и тратил бы минуты (ADR-011, раздел 2.1 B). Поэтому спецификация фиксирует номер шага по нумерации SDD_plan.md — 11, сохраняя смысл решения «после зелёного кода, до рефакторинга». Расхождение номера с ADR-011 отмечено в отчёте оркестратору для правки SDD_plan.md §5.
- **Проверка**: шаблон PR (`.github/PULL_REQUEST_TEMPLATE.md`, R16) содержит чек-бокс «переведён в ready на шаге 11, полный прогон зелёный»; `flt-tools commits check` предупреждает, если событие `ready_for_review` произошло раньше первого коммита `feat`/`fix` с типом E2E green (`test(e2e)` или `feat` после `test`) — проверка информационная (step summary); ревью G3.
- **Применимость**: процесс, CI.

### SYS-12-R6 Линтеры и типы backend

- **Формулировка**: Код `src/backend/py-monolyth` (а также `src/tools` и `src/agent`) должен проходить `ruff format --check`, `ruff check` с набором правил boilerplate, дополненным `DTZ` (SYS-05-R42), `PGH` (запрет пустых `noqa` и `type: ignore` без кода), `B019`, `ASYNC`; `mypy --strict` с `enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool"]`; `bandit -c pyproject.toml`; `detect-secrets-hook --baseline .secrets.baseline`; `lint-imports`; любое послабление (`# noqa: <код>`, `# type: ignore[<код>]`, `# nosec B<NNN>`) должно содержать код правила и комментарий с причиной в той же строке.
- **Обоснование**: CLAUDE.md «Качество кода» (ruff, mypy strict, bandit, detect-secrets, pre-commit, `make check`); ADR-002 (`lint-imports` в `make check`); ADR-001 (политика версий инструментов).
- **Проверка**: job `backend-quality` и `architecture`; архитектурный тест `tests/architecture/test_suppressions_have_reason.py` (будет создан: регулярное выражение на `noqa`, `type: ignore`, `nosec`, `pragma: no cover` без кода или без текста после `#` через ` -- `); `make check` локально.
- **Применимость**: backend, `src/tools`, CI.

### SYS-12-R7 Линтеры и типы frontend

- **Формулировка**: Код `src/frontend` должен проходить `eslint src e2e` по `eslint.config.js` (flat config) с правилами ADR-005 и локальными правилами `flt/*` (SYS-10), `prettier --check .`, `tsc --noEmit` (`strict`, `verbatimModuleSyntax`), `i18next-parser --fail-on-update --fail-on-warnings` (`i18n:check`), `api:check` (сгенерированный клиент и zod-схемы не расходятся с контрактами), `pnpm audit --prod --audit-level=high`; директивы `eslint-disable` и `@ts-expect-error` должны содержать имя правила и причину, `@ts-ignore` запрещён (`@typescript-eslint/ban-ts-comment`).
- **Обоснование**: CLAUDE.md «Frontend (boilerplate)» и «Правила для Claude» (`lint`, `check-types`, `test` перед коммитом); ADR-005, разделы 3.3, 3.5, 3.6; ADR-011 (состав job `frontend`).
- **Проверка**: job `frontend`; правило `eslint-comments/require-description` (плагин `@eslint-community/eslint-plugin-eslint-comments`) в `eslint.config.js`; скрипт `pnpm check` (R34).
- **Применимость**: frontend, CI.

### SYS-12-R8 Линтеры документации Analytics

- **Формулировка**: Файлы `Analytics/**/*.md`, `CLAUDE.md`, `README.md` должны проходить `markdownlint-cli2` с конфигурацией `.markdownlint-cli2.yaml` в корне (отключены `MD013` длина строки и `MD033` HTML только для `Analytics/Specs/_templates/**`; включены `MD001`, `MD003`, `MD022`, `MD024` с `siblings_only`, `MD031`, `MD040`, `MD047`, `MD055`, `MD056` — число столбцов таблиц) и проверку `flt-tools specs check` (R15), которая запрещает в заполненных спецификациях (все файлы `Analytics/Specs/**` и `Analytics/ADR/**`, кроме `_templates/`) HTML-комментарии вне блоков кода, незаполненные плейсхолдеры шаблона (литерал `<…>`, `<ГГГГ-ММ-ДД>`, `<название>`, `<имя …>`, `<кратко>`), слова «и т.д.», «и т.п.», «и прочее», «и другие» вне цитат BRD и требует совпадения статуса и версии в шапке с последней строкой истории изменений.
- **Обоснование**: `Analytics/Specs/_templates/README.md`, «Как заполнять шаблон» (пп. 4, 6, 8, 10); ADR-011 (job `docs`, `markdownlint`); матрица трассировки читает шапки документов.
- **Проверка**: job `docs`; pre-commit hook `markdownlint-cli2` с `files: ^(Analytics/|CLAUDE\.md|README\.md)`; unit-тесты `src/tools/tests/test_specs_check.py` на фикстурах документов.
- **Применимость**: документация, CI.

### SYS-12-R9 Линт контрактов API

- **Формулировка**: Каждый файл `Analytics/Specs/<module>/api/openapi.yaml` и `asyncapi.yaml` должен проходить Spectral (`@stoplight/spectral-cli`, версия зафиксирована в `src/tools/contracts/package.json` и обновляется Renovate) с наборами `spectral:oas`, `spectral:asyncapi` и правилами проекта `src/tools/contracts/.spectral.yaml` (требования SYS-03 и SYS-04: префикс `/api/v1/<module>`, `ErrorResponseV1` для ошибок, `version` в схемах изменения, имена топиков `flt.<module>.<event>.v<N>`, `x-flt-state-endpoint` у каналов WebSocket); `flt-tools contracts check` должен проверять, что у каждого модуля реестра с роутером есть `openapi.yaml`, с Kafka или WebSocket — `asyncapi.yaml`, и что контракты не содержат путей чужих модулей.
- **Обоснование**: CLAUDE.md «Спецификации»: контракты spec-first; ADR-011 (job `contracts`); ADR-005 (генерация клиента из этих файлов).
- **Проверка**: job `contracts`; pre-commit hook `spectral` (`language: node`) с `files: ^Analytics/Specs/.*/api/.*\.ya?ml$`; тесты `src/tools/tests/test_contracts_check.py`.
- **Применимость**: документация (контракты), CI.

### SYS-12-R10 Линтеры развёртывания

- **Формулировка**: Файлы развёртывания должны проходить: `hadolint` для каждого `Dockerfile` (`src/backend/py-monolyth/Dockerfile`, `Dockerfile-dev`, `src/frontend/Dockerfile`, `src/agent/Dockerfile` при появлении) с правилами `DL3007` (запрет `latest`), `DL3008`/`DL3018` (пины пакетов) без игнорирования; `docker compose config -q` для каждой комбинации файлов и профилей (`docker-compose.yml`; `+ docker-compose.ci.yml --profile ci`; `--profile dev`; `--profile test`; `--profile prod`); `helm lint deploy/helm/flt` и `helm template … \| kubeconform -strict -summary -schema-location default -schema-location 'deploy/helm/schemas/{{ .ResourceKind }}.json'` для `values.yaml`, `values-ci.yaml`, `values-dev.yaml`, `values-prod.yaml`; `haproxy -c -f deploy/config/haproxy/haproxy.cfg` для веток с `FLT_TLS_DOMAIN` и без; `shellcheck -S warning` для `deploy/scripts/*.sh`; `actionlint` для `.github/workflows/*.yml`.
- **Обоснование**: CLAUDE.md «Развёртывание»: оба варианта в паритете с первого дня; ADR-011 (job `helm`, `actionlint`); ADR-012 (`haproxy -c` для обеих веток).
- **Проверка**: шаги job-ов `backend-quality` (hadolint backend), `frontend` (hadolint frontend), `helm`, `images` (`docker compose config`), `docs` (`actionlint`, `shellcheck`); pre-commit hooks `hadolint-docker`, `shellcheck`, `actionlint`, `helmlint` (`local`).
- **Применимость**: deploy, CI.

### SYS-12-R11 Pre-commit на уровне репозитория

- **Формулировка**: В корне репозитория должен быть один `.pre-commit-config.yaml` с хуками из таблицы ниже, каждый ограничен `files:` своего компонента; `husky` и `lint-staged` из `src/frontend/package.json` удаляются (`lint-staged` остаётся как инструмент, вызываемый хуком `local`); `.pre-commit-config.yaml` в `src/backend/py-monolyth` удаляется; у каждого хука должен быть эквивалентный шаг CI (CI — источник истины, pre-commit — ускорение).
- **Обоснование**: CLAUDE.md «Отличия проекта от boilerplate», п. 7 (backend) и п. 10 (frontend); ADR-011, раздел 3.7; ADR-005, п. 2.4 («Git-хуки»).
- **Проверка**: `test_workflows.py::test_every_precommit_hook_has_ci_step` (разбор `.pre-commit-config.yaml` и `ci.yml` по таблице соответствия в `src/tools/flt_tools/precommit_map.toml`); отсутствие `husky` в `package.json` и `.pre-commit-config.yaml` в `src/backend/py-monolyth` — тот же тест; `pre-commit run --all-files` в job `docs` на `main` раз в неделю (`nightly.yml`).
- **Применимость**: все, CI.

| Хук | Репозиторий или `local` | `files:` | Эквивалент в CI |
|---|---|---|---|
| `ruff-check --fix`, `ruff-format` | `astral-sh/ruff-pre-commit` | `^src/(backend/py-monolyth\|tools\|agent)/` | `backend-quality`, `tools` |
| `uv-lock` | `astral-sh/uv-pre-commit` | `^src/(backend/py-monolyth\|tools\|agent)/(pyproject\.toml\|uv\.lock)$` | `backend-quality` (`uv lock --check`) |
| `mypy` | `local` (`uv run mypy app cli configs` в каталоге) | `^src/backend/py-monolyth/` | `backend-quality` |
| `bandit` | `PyCQA/bandit` | `^src/(backend\|tools\|agent)/` без `tests/` | `backend-quality`, `tools` |
| `detect-secrets` | `Yelp/detect-secrets` с `.secrets.baseline` в корне | весь репозиторий | `backend-quality` |
| `lint-imports` | `local` (`uv run lint-imports`) | `^src/backend/py-monolyth/(app\|configs\|\.importlinter)` | `architecture` |
| `lint-staged` | `local` (`pnpm --dir src/frontend lint-staged`: eslint `--fix`, prettier `--write`) | `^src/frontend/` | `frontend` |
| `commitlint` | `local`, стадия `commit-msg` | — | `commits` |
| `markdownlint-cli2` | `DavidAnson/markdownlint-cli2` | `^(Analytics/\|CLAUDE\.md\|README\.md)` | `docs` |
| `spectral` | `local` (`pnpm --dir src/tools/contracts spectral lint`) | `^Analytics/Specs/.*/api/` | `contracts` |
| `hadolint-docker` | `hadolint/hadolint` | `Dockerfile` | `backend-quality`, `frontend` |
| `shellcheck` | `shellcheck-py/shellcheck-py` | `^deploy/scripts/.*\.sh$` | `docs` |
| `actionlint` | `rhysd/actionlint` | `^\.github/workflows/` | `docs` |
| `helm lint` | `local` | `^deploy/helm/` | `helm` |
| `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`, `no-commit-to-branch --branch main` | `pre-commit/pre-commit-hooks` | весь репозиторий | `docs` (`pre-commit run --all-files` в `nightly.yml`), branch protection |

### SYS-12-R12 Проверка workflow-файлов

- **Формулировка**: Каждый workflow должен проходить `actionlint`, объявлять `permissions: contents: read` на уровне workflow (расширение до `packages: write` только в job-ах `images` на `main` и в `release.yml`, `id-token` не используется), задавать `timeout-minutes` у каждого job-а (10 — быстрые, 20 — тяжёлые, 30 — `deploy-vps`), `concurrency` с отменой устаревших прогонов для PR, и ссылаться на внешние actions по полному SHA коммита с комментарием версии (`uses: actions/checkout@<sha> # v5.0.0`), обновляемому Renovate.
- **Обоснование**: ADR-011, разделы 3.4 (таймауты, `concurrency`) и 3.6 (минимальные `permissions`); пин по SHA защищает от подмены тега action.
- **Проверка**: `actionlint`; `test_workflows.py::test_permissions_timeouts_and_pinned_actions` (будет создан).
- **Применимость**: CI.

### SYS-12-R13 Архитектурные проверки как отдельная обязательная проверка

- **Формулировка**: Job `architecture` должен выполнять `make arch` (`lint-imports`) и `pytest tests/architecture` отдельно от остальных тестов, быть обязательной проверкой и падать при любом нарушении; негативный тест `test_boundary_violation_breaks_build` должен входить в него; для frontend архитектурные Vitest-тесты (`src/testing/architecture/**`: границы ESLint, зарезервированные пути, физические классы направления, наличие историй) выполняются в job `frontend`.
- **Обоснование**: SDD_plan.md, критерий выхода этапа 1: «нарушение границы модуля ломает сборку (проверено специальным негативным тестом)»; ADR-002, раздел 3.6; ADR-011 (отдельный job, чтобы нарушение было видно по имени проверки).
- **Проверка**: `test_workflows.py::test_architecture_job_runs_lint_imports_and_tests`; branch protection (R4).
- **Применимость**: CI.

### SYS-12-R14 Матрица трассировки: генерация и проверка актуальности

- **Формулировка**: Матрица `Analytics/traceability.md` должна генерироваться командой `uv run flt-tools traceability generate` на шаге 14 конвейера (и при изменении требований, SDD_plan.md §9), а job `docs` должен выполнять `flt-tools traceability check` и падать, если пересобранные таблицы разделов 6–10 отличаются от файла в репозитории или если тег теста ссылается на несуществующий ID либо на документ в статусе `draft`/`review`; ручные правки генерируемых столбцов не допускаются.
- **Обоснование**: `traceability.md`, раздел 3; SDD_plan.md §3; ADR-011 (job `docs`: «генерация выполняется на шаге 14 конвейера, CI только проверяет»); SYS-10-R15 (алгоритм и источники тегов).
- **Проверка**: job `docs`; тесты `src/tools/tests/test_traceability.py`; шаблон PR (R16) содержит пункт «матрица пересобрана».
- **Применимость**: CI, документация.

### SYS-12-R15 Проверка статусов и полноты спецификаций

- **Формулировка**: Команда `flt-tools specs check` (job `docs`) должна для каждого документа в `Analytics/Specs/**` и `Analytics/ADR/**`: проверять формальные правила шаблона (R8); для ТЗ в статусе `approved` и выше — что разделы 3, 6.1–6.7, 13 заполнены; для ТЗ и SYS в статусе `implemented` — что каждый критерий приёмки и каждое требование имеют хотя бы один тег в `reports/traceability.json` (SYS-10-R15), а каждая строка «да» таблицы 6.7 — тест с маркерами `n_instances` и `ac(<ID>)` (SYS-05-R53); для документов в статусе `draft`/`review` — что на них нет тегов тестов; падать с перечнем нарушений.
- **Обоснование**: CLAUDE.md «Определение готовности»: «Спецификация в статусе `approved`, после реализации — `implemented`», «Все критерии приёмки покрыты тестами»; SDD_plan.md §4; порядок «спецификация → тесты → код» (тесты не пишутся по неутверждённому ТЗ).
- **Проверка**: тесты `src/tools/tests/test_specs_check.py` на фикстурах (документ `implemented` без тестов → ошибка; тег на `draft` → ошибка); job `docs`.
- **Применимость**: CI, документация.

### SYS-12-R16 Definition of Done: что проверяет CI, что — человек

- **Формулировка**: Шаблон PR `.github/PULL_REQUEST_TEMPLATE.md` должен содержать чек-лист Definition of Done из CLAUDE.md, разделённый на автоматические пункты (проверяются job-ами из таблицы ниже и считаются выполненными при зелёном `ci-ok`) и пункты человека (отмечает ревьюер на G3); слияние с незаполненными пунктами человека не допускается (ревью G3).
- **Обоснование**: CLAUDE.md «Определение готовности (Definition of Done)»; SDD_plan.md §5 шаг 15.
- **Проверка**: наличие шаблона и его пунктов — `test_workflows.py::test_pr_template_has_dod` (будет создан); ревью G3.
- **Применимость**: процесс, CI.

| Пункт Definition of Done (CLAUDE.md) | Кто проверяет | Чем |
|---|---|---|
| Спецификация `approved` → `implemented` | CI + человек | `flt-tools specs check` (статус, история изменений); человек подтверждает `implemented` на G3 |
| Все критерии приёмки покрыты тестами, все тесты зелёные | CI | `flt-tools traceability check`, `specs check`; job-ы `backend-tests`, `frontend`, `e2e`, `stand-n3` |
| Границы модулей не нарушены | CI | job `architecture`; ESLint-зоны в `frontend` |
| Контракт API соответствует реализации | CI | контрактные тесты в `backend-tests`; `api:check` в `frontend`; `contracts` |
| Тесты на N инстансах зелёные, состояние только в PostgreSQL, MinIO и Redis | CI | `stand-n3`; архитектурные тесты SYS-05 в `architecture` |
| Добавлены метрики и логи | человек (по ТЗ, раздел 9) + CI частично | тесты наблюдаемости SYS-10-R33; ревьюер сверяет метрики ТЗ с кодом |
| Строки UI вынесены в i18n | CI | `i18n:check`, правило `react/jsx-no-literals` в `frontend` |
| docker-compose и Helm обновлены | CI + человек | `docker compose config`, `helm`, тест паритета SYS-11; ревьюер проверяет смысловую полноту |
| Документация модуля обновлена | человек + CI частично | `_module.md` изменён в PR, если менялся публичный API (`flt-tools specs check` сравнивает список файлов `public/` с разделом 3 `_module.md` — предупреждение); ревьюер |
| Красные тесты написаны до кода, не ослаблены | CI + человек | `flt-tools commits check` (порядок `test` → `feat`), плагин запрета `skip` без ссылки; ревью G2 |
| Демо фичи проведено | человек | G3 |

### SYS-12-R17 Ветвление

- **Формулировка**: Работа над ТЗ должна вестись в ветке `feat/<id>-<slug>` (ID строчными, например `feat/vis-04-registration`), спецификации этапа — в ветках `spec/stage-<N>-<блок>`; ветка создаётся от актуального `main`, регулярно подливает `main` слиянием (не rebase после открытия PR); имена веток других видов (`fix/<id>-<slug>` для исправлений вне конвейера, `deps/<пакет>` для PR Renovate, `ci/<slug>`) должны соответствовать шаблону `^(feat|fix|spec|deps|ci|docs|renovate)/[a-z0-9.-]+$`.
- **Обоснование**: OQ-05 (resolved); SDD_plan.md §1 п. 7.
- **Проверка**: шаг `branch-name` в job `commits` (регулярное выражение по `github.head_ref`); hook `no-commit-to-branch --branch main` в pre-commit.
- **Применимость**: процесс, CI.

### SYS-12-R18 Сообщения коммитов: Conventional Commits и commitlint

- **Формулировка**: Каждый коммит должен соответствовать формату `<type>(<scope>): <subject>` на английском, где `type ∈ {spec, test, feat, fix, refactor, deploy, docs, ci, deps, chore}`, `scope` — имя модуля из реестра, `core`, `frontend`, `app-shell`, `tools`, `deploy`, `analytics` или `repo`, `subject` для `test`, `feat`, `fix`, `refactor` начинается с ID ТЗ или SYS (`test(identity): VIS-04 add red tests for AC1-AC7`), длина заголовка ≤ 100 символов; проверка — `commitlint` с конфигурацией `commitlint.config.mjs` в корне (`@commitlint/config-conventional` плюс `type-enum`, `scope-enum` из `python -m cli list-modules` и фиксированного списка, собственное правило `subject-starts-with-spec-id`); сообщения коммитов слияния `main` и коммитов Renovate (`deps(...)`) проверяются теми же правилами.
- **Обоснование**: OQ-05 (resolved): Conventional Commits на английском, scope — модуль, subject начинается с ID ТЗ; автоматический перечень PR в GitHub Release (ADR-011) опирается на типы.
- **Проверка**: job `commits` (`commitlint --from ${{ github.event.pull_request.base.sha }} --to ${{ github.sha }}`); pre-commit hook `commitlint` на стадии `commit-msg`; тесты правила в `src/tools/tests/test_commitlint_rules.py`.
- **Применимость**: процесс, CI.

### SYS-12-R19 Порядок коммитов в конвейере

- **Формулировка**: В PR фичи коммиты должны следовать шагам конвейера: `spec` (шаг 2 и правки на G1) → `spec` или `docs` контрактов (шаг 4) → `test` (шаги 5–7) → `feat`/`fix` (шаги 9–11) → `refactor` (шаг 12) → `deploy` (шаг 13) → `docs` (шаг 14); первый коммит `feat` для ID не должен предшествовать первому коммиту `test` для того же ID; один шаг — один коммит (допустимы дополнительные коммиты `fix` после замечаний на гейте).
- **Обоснование**: SDD_plan.md §1 п. 7 и §5; CLAUDE.md «TDD» (red до green); SYS-10-R24.
- **Проверка**: `flt-tools commits check` в job `commits` (разбор коммитов PR: ошибка, если `feat`/`fix` с ID встречается раньше любого `test` с тем же ID; предупреждение при нарушении общего порядка); ревью G2 и G3.
- **Применимость**: процесс, CI.

### SYS-12-R20 Релизы: теги `stage-N`, образы и chart

- **Формулировка**: Релиз этапа должен оформляться защищённым тегом `stage-<N>` на коммите `main`, который ставит человек на гейте GS; `release.yml` по этому тегу должен проверить принадлежность коммита `main`, собрать и опубликовать образы `ghcr.io/alextaralexander/flt/backend:<tag>` и `…/frontend:<tag>` (дополнительно `sha-<7>`), упаковать и опубликовать chart `oci://ghcr.io/alextaralexander/flt/charts/flt` версии `0.<N>.0` с `appVersion = <tag>` и создать GitHub Release с автоматическим перечнем PR; образы на `main` публикуются `ci.yml` с тегами `main` и `sha-<7>`; тег `latest` не используется; образы и chart одного тега неизменяемы (повторная публикация того же тега запрещена `docker/build-push-action` с `provenance: false` и проверкой `docker manifest inspect` перед push).
- **Обоснование**: ADR-011, раздел 3.2; OQ-05 (теги `stage-N`); ADR-001 (единство версий через образ).
- **Проверка**: `test_workflows.py::test_release_workflow` (триггер `push: tags: ['stage-*']`, шаги); tag protection `stage-*` в настройках GitHub (человек); `deploy-vps.yml` принимает только существующие теги (R28).
- **Применимость**: CI, настройки репозитория.

### SYS-12-R21 Содержимое и теги образов

- **Формулировка**: Образ `flt-backend` должен собираться из `src/backend/py-monolyth/Dockerfile` с `build-contexts: py-main-lib=src/backend/py-main-lib` (до перевода библиотеки в path-зависимость по ADR-001) и содержать метки OCI `org.opencontainers.image.revision`, `.version`, `.source`; образ `flt-frontend` — из `src/frontend/Dockerfile` с контекстом корня репозитория (контракты копируются для `api:check`); в PR образы не публикуются (артефакт `images.tar`, срок хранения 1 день), на `main` — push в GHCR; `APP_VERSION` внутри образа равен тегу или `sha-<7>` и отдаётся в `flt_instance_info` (ADR-010).
- **Обоснование**: ADR-011, раздел 3.1 (job `images`) и 3.4; ADR-005, раздел 3.8; ADR-010 (`version` в info-метрике).
- **Проверка**: `test_workflows.py::test_images_job`; smoke в `stand-n3`: `flt_instance_info{version="sha-<7>"}` на `GET /v1/metrics` каждого инстанса; `hadolint` (R10).
- **Применимость**: CI, deploy.

### SYS-12-R22 Обновление зависимостей через Renovate

- **Формулировка**: Файл `renovate.json` должен лежать в корне репозитория и охватывать менеджеры `pep621` (uv), `npm` (pnpm), `dockerfile`, `docker-compose`, `helm-values`, `github-actions`, `pre-commit`; расписание — `before 6am on monday`; `lockFileMaintenance` включено; минорные и патч-обновления группируются в один PR `deps: weekly minor and patch`; мажорные — отдельный PR на пакет с меткой `deps:major`; обновления CPython, Node и базовых образов — отдельные PR с меткой `deps:runtime` и `minimumReleaseAge: 30 days`; автослияние выключено; `dependencyDashboard` включён; PR Renovate проходят быструю ступень, а при изменении `uv.lock`, `pnpm-lock.yaml`, `Dockerfile`, `docker-compose*.yml`, `values*.yaml` — ещё и тяжёлую (они открываются не черновиками); мажорный PR выполняется Claude как мини-задача по ADR-001, п. 3.2.4.
- **Обоснование**: ADR-001, раздел 3.2 (политика версий, Renovate); ADR-011 (CI для PR Renovate).
- **Проверка**: тест `src/tools/tests/test_renovate_config.py` (будет создан: менеджеры, расписание, группы, метки, `automerge: false`); `renovate-config-validator` в pre-commit (`local`, `pnpm dlx`).
- **Применимость**: все, CI.

### SYS-12-R23 Секреты в CI

- **Формулировка**: В репозитории не должно быть секретов; GitHub Secrets используются только в окружении `prod` (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`) и, при приватном репозитории, `GHCR_PULL_TOKEN` для VPS; тесты и стенды CI получают секреты от `deploy/scripts/gen-secrets.sh --ci` в шаге job-а и от фикстур (одноразовая Ed25519-пара — ADR-006), пароль PostgreSQL CI — несекретная константа `flt_ci` в `docker-compose.ci.yml` с комментарием `# pragma: allowlist secret`; `detect-secrets` с `.secrets.baseline` в корне проверяет весь репозиторий, включая `tests/cassettes/**` и `Analytics/**`; job-ы не печатают переменные окружения стендов, значения из `gen-secrets.sh` маскируются (`::add-mask::`); job-ы `pull_request` из форков не получают секретов и не выполняются на self-hosted runner-е.
- **Обоснование**: ADR-011, раздел 3.6; ADR-013, раздел 3.5 (CI); CLAUDE.md «Правила для Claude»: не коммитить секреты.
- **Проверка**: job `backend-quality` (`detect-secrets-hook`); `test_workflows.py::test_secrets_only_in_prod_environment` (в `ci.yml` нет `secrets.` кроме `GITHUB_TOKEN`; в `deploy-vps.yml` — только в job с `environment: prod`); ревью `.secrets.baseline` при каждом его изменении.
- **Применимость**: CI.

### SYS-12-R24 Тестовые ключи и стенды CI

- **Формулировка**: Стенд N3 в `stand-n3` и `e2e`, а также установка в kind в `helm`, должны получать секреты из `gen-secrets.sh --ci` (значения генерируются в job и не повторяются между прогонами) и из `values-ci.yaml` с `ClusterSecretStore` провайдера `fake` (ADR-013); реальные ключи LLM, OAuth, SMTP, капчи в CI не передаются — все внешние сервисы заменяются заглушками SYS-10 (R18–R23).
- **Обоснование**: ADR-013, разделы 3.3 и 3.5; ADR-011, раздел 3.6; CLAUDE.md «TDD» (тесты не требуют ключей).
- **Проверка**: `test_workflows.py::test_stand_jobs_call_gen_secrets_ci`; `LLM_STUB_MODE` не задаётся в CI (SYS-10-R18); отсутствие `PLATFORM_LLM_API_KEY`, `OAUTH_*_CLIENT_SECRET`, `SMTP_PASSWORD`, `SMARTCAPTCHA_SERVER_KEY` в workflow-файлах — тот же тест.
- **Применимость**: CI, deploy.

### SYS-12-R25 Кэширование

- **Формулировка**: Job-ы должны использовать кэши: uv (`astral-sh/setup-uv` с `enable-cache: true`, `cache-dependency-glob` по `uv.lock` каждого Python-проекта), pnpm (`pnpm/action-setup` + `actions/setup-node` с `cache: pnpm`, `cache-dependency-path: src/frontend/pnpm-lock.yaml`), Docker-слои (`cache-from/cache-to: type=gha,scope=<image>`), Playwright (`~/.cache/ms-playwright` по версии `@playwright/test`), Helm и kind (фиксированные версии через `azure/setup-helm`, `helm/kind-action`); образы между job-ами передаются артефактом `images.tar`.
- **Обоснование**: ADR-011, раздел 3.4; бюджет минут (R27).
- **Проверка**: `test_workflows.py::test_caches_configured` (наличие перечисленных параметров в шагах).
- **Применимость**: CI.

### SYS-12-R26 Бюджеты времени job-ов

- **Формулировка**: Время job-ов на hosted runner-е не должно превышать: `changes` — 1 мин, `backend-quality` — 4, `architecture` — 2, `backend-tests` — 6, `frontend` — 6, `tools` — 2, `contracts` — 1, `docs` — 2, `commits` — 1, `images` — 8, `stand-n3` — 12, `e2e` — 10, `helm` — 10; быстрая ступень целиком — 15 минут настенного времени, полный прогон — 25 минут настенного времени (job-ы параллельны); `timeout-minutes` задаются с запасом (10 для быстрых, 20 для тяжёлых); превышение бюджета два прогона подряд на `main` — задача на оптимизацию (новый OQ или issue) до следующего слияния фич.
- **Обоснование**: ADR-011, разделы 3.1 (оценки времени) и 3.4; SYS-10-R30 (бюджеты тестов); цикл TDD требует быстрой обратной связи.
- **Проверка**: `flt-tools quality ci-durations` в `nightly.yml`: GitHub API `GET /repos/{owner}/{repo}/actions/runs` за неделю, сравнение медианы длительности job-ов с бюджетом, отчёт в step summary и в issue метрик (R31); `timeout-minutes` — R12.
- **Применимость**: CI.

### SYS-12-R27 Бюджет минут и переключение runner-а

- **Формулировка**: Тяжёлые job-ы должны задавать `runs-on: ${{ vars.CI_HEAVY_RUNNER }}` (переменная репозитория, по умолчанию `ubuntu-latest`; при включении self-hosted — `["self-hosted", "linux", "x64", "flt"]`), чтобы переключение не требовало правки workflow-ов; пользователь проверяет расход минут раз в неделю; при расходе 80 % месячного лимита или при полном прогоне дольше 20 минут из-за очереди включается self-hosted runner по OQ-68 (ephemeral, `docker system prune` после job-а, без job-ов из форков); `concurrency: group: ci-${{ github.ref }}, cancel-in-progress: true` для PR, без отмены для `main`.
- **Обоснование**: ADR-011, разделы 3.4 и 3.5; OQ-06 и OQ-68 (deferred).
- **Проверка**: `test_workflows.py::test_heavy_jobs_use_runner_variable`, `::test_concurrency_groups`; переменная `CI_HEAVY_RUNNER` заводится человеком (чек-лист `deploy/README.md`).
- **Применимость**: CI, настройки репозитория.

### SYS-12-R28 Деплой на VPS: ручной запуск с подтверждением

- **Формулировка**: `deploy-vps.yml` должен запускаться только `workflow_dispatch` с входами `image_tag` (обязательный; допустимы только значения вида `stage-<N>` или `sha-<7>`, образы с которыми существуют в GHCR — проверка `docker manifest inspect` до любых действий на VPS) и `run_migrations` (булев, по умолчанию `true`), выполняться в окружении `prod` с обязательным подтверждением ревьюера (пользователь) и секретами окружения, и по SSH в каталоге `/opt/flt` на VPS: записать `FLT_IMAGE_TAG=<tag>` в `.image-tag.env`; `docker compose pull`; при `run_migrations` — `docker compose run --rm migrate`; `docker compose up -d --remove-orphans`; дождаться `healthy` всех реплик `api` и `worker` (`docker compose ps --format json`, не дольше 5 минут); CI не читает и не пишет `/opt/flt/.env`.
- **Обоснование**: ADR-011, раздел 3.2 (вариант E); ADR-013 (секреты на VPS ведёт человек); OQ-07 (prod — compose на VPS).
- **Проверка**: `test_workflows.py::test_deploy_vps_workflow` (триггер, входы, `environment: prod`, последовательность шагов, отсутствие `.env` в командах); первый деплой этапа 2 — ручная проверка по чек-листу SYS-11.
- **Применимость**: CI, deploy.

### SYS-12-R29 Смоук-тест после деплоя и критерий успеха

- **Формулировка**: После `up -d` `deploy-vps.yml` должен выполнить `deploy/scripts/smoke.sh https://<FLT_TLS_DOMAIN>` (через HAProxy: `GET /healthz` — 200; `GET /` — 200 и `<html`; `GET /api/v1/auth/.well-known/jwks.json` — 200 и непустой `keys`; `GET /api/docs` — 404; `GET /v1/ready` — не ответ монолита (нет заголовка `X-Instance-Id`, статус 200 или 404 от Nginx); `GET /flt-materials/` — 403; 10 запросов `GET /api/v1/auth/.well-known/jwks.json` — все 200 за ≤ 1 с каждый) и `docker compose ps` с проверкой, что число реплик `api` равно заданному в compose и все `healthy`; падение любого пункта — ненулевой код job-а с выводом `docker compose logs --tail=200 api worker haproxy`; смоук-набор E2E `@smoke` против прода не выполняется (не создаёт данных на проде).
- **Обоснование**: ADR-011, раздел 3.2 («дождаться `/v1/ready` всех реплик через HAProxy… при неуспехе — вывести логи»); ADR-012 (smoke-проверки путей); CLAUDE.md «Развёртывание» (миграции до инстансов, N реплик за HAProxy).
- **Проверка**: `shellcheck` и тест `deploy/scripts/tests/test_smoke.sh` (bats) против стенда N3 в job `stand-n3`; `test_workflows.py::test_deploy_vps_runs_smoke`.
- **Применимость**: CI, deploy.

### SYS-12-R30 Откат

- **Формулировка**: Откат деплоя должен выполняться повторным запуском `deploy-vps.yml` с предыдущим `image_tag` и `run_migrations = false`; миграции при откате не откатываются (`downgrade` на проде не выполняется), поэтому совместимость схемы с предыдущим кодом гарантируется правилами expand/contract (SYS-05-R34); откат, требующий `downgrade`, считается инцидентом и выполняется человеком вручную по runbook SYS-11 после бэкапа.
- **Обоснование**: ADR-011, раздел 2.2 E («откат — повторный запуск с предыдущим тегом»); ADR-003, п. 2.5 A («откат кода без отката миграции возможен благодаря совместимости»).
- **Проверка**: тест совместимости миграций в `stand-n3` (старый код на новой схеме — SYS-05-R34); чек-лист деплоя в `deploy/README.md` (человек).
- **Применимость**: deploy, процесс.

### SYS-12-R31 Публикация метрик качества

- **Формулировка**: Каждый прогон `ci.yml` должен публиковать в `GITHUB_STEP_SUMMARY` и артефактами: покрытие backend (`coverage.xml`, процент и дельта к `main`), покрытие frontend (`coverage/coverage-summary.json`), `junit.xml` с тегами тестов, отчёт Playwright (`playwright-report/`), 20 самых долгих тестов backend, список карантинных тестов; срок хранения артефактов — 7 дней (образы — 1 день); `nightly.yml` раз в неделю должен обновлять единственный закреплённый issue «Quality metrics» комментарием с таблицей: покрытие backend и frontend, число тестов по уровням, число карантинных тестов и просроченных карантинов, медианы длительности job-ов против бюджетов R26, расход минут CI за месяц (GitHub API `GET /repos/{owner}/{repo}/actions/cache/usage` и billing при доступности), доля AC без тегов по `reports/traceability.json`.
- **Обоснование**: CLAUDE.md «Определение готовности» и SDD_plan.md §8 (регрессия и ревью на каждом этапе) требуют видимости покрытия и стабильности; ADR-011, раздел 3.4 (мониторинг бюджета раз в неделю).
- **Проверка**: `test_workflows.py::test_quality_artifacts_uploaded`; `flt-tools quality report` с unit-тестами; наличие комментария в issue проверяется человеком раз в неделю.
- **Применимость**: CI.

### SYS-12-R32 Пороги качества не понижаются

- **Формулировка**: Команда `flt-tools quality check-thresholds` (job `docs`) должна сравнивать значения `fail_under` (`pyproject.toml` backend и `src/tools`), `coverage.thresholds` (`vite.config.ts`), списки правил ruff `select`/`ignore`, флаги mypy, `audit-level`, `timeout-minutes` в PR с `main` и падать при понижении порога, расширении `ignore`, отключении `strict`, увеличении `timeout-minutes` сверх значений R26 или удалении обязательной проверки из `ci-ok`; изменение в сторону ужесточения допускается без согласований.
- **Обоснование**: CLAUDE.md «TDD»: порог покрытия «повышать можно, понижать нельзя»; ADR-005 (то же для frontend); SYS-10-R25.
- **Проверка**: тесты `src/tools/tests/test_quality_thresholds.py` (PR с `fail_under = 70` → ошибка); job `docs`.
- **Применимость**: CI.

### SYS-12-R33 Регулярный полный прогон `nightly.yml`

- **Формулировка**: `nightly.yml` должен запускаться по расписанию раз в неделю (`cron: '0 3 * * 1'`, понедельник 03:00 UTC) и вручную, не блокировать слияния и выполнять: полный `docker compose up -d --wait` со всеми контейнерами «Состава контейнеров» (без профиля `ci`, с профилями `test` и `dev`), смоук наблюдаемости (три цели `flt-api` и две `flt-worker` `up` в Prometheus; запись с `request_id` из смоук-сценария в OpenSearch через API Grafana — SYS-10-R33), `pre-commit run --all-files`, `flt-tools quality report` и `ci-durations` (R26, R31), отчёт о карантине (SYS-10-R29) и `pip-audit`/`pnpm audit` по `main`; при падении — issue с меткой `nightly` создаётся автоматически (одна открытая issue на причину).
- **Обоснование**: ADR-011, раздел 4.2 («полный состав проверяется… в еженедельном расписании `schedule` (ночной прогон полного compose, не блокирующий)»); SYS-05 раздел 6 и SYS-10 раздел 6 (OpenSearch и Prometheus вне профиля `ci`).
- **Проверка**: `test_workflows.py::test_nightly_workflow`; результат — issue и комментарий метрик (R31).
- **Применимость**: CI.

### SYS-12-R34 Локальный эквивалент CI

- **Формулировка**: Корневой `Makefile` должен предоставлять цели, воспроизводящие быструю ступень локально одной командой: `make check` (= `check-backend` → `make check` в `src/backend/py-monolyth`; `check-frontend` → `pnpm check` = `lint`, `format:check`, `check-types`, `i18n:check`, `api:check`, `test:cov`, `build`; `check-tools` → ruff, mypy, pytest в `src/tools`; `check-docs` → `markdownlint-cli2`, `flt-tools specs check`, `flt-tools traceability check`, `flt-tools contracts check`), а также `make stand-up`, `make stand-test`, `make stand-down` (стенд N3 — SYS-05-R44), `make e2e`, `make load-test` (SYS-10-R34), `make traceability` (генерация), `make pre-commit-install`; Claude обязан выполнять `make check` перед каждым коммитом кода и `make check-docs` — перед коммитом документов.
- **Обоснование**: CLAUDE.md «Правила для Claude» (`make check`, `yarn lint`, `check-types`, `test` перед коммитом — после ADR-005 `pnpm`); ADR-011, раздел 3.7 (CI — источник истины, локальные проверки ускоряют цикл).
- **Проверка**: тест `src/tools/tests/test_root_makefile.py::test_targets_present` (будет создан); `make check` и шаги job-ов используют одни и те же команды (таблица соответствия `precommit_map.toml`, R11).
- **Применимость**: все.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| все backend-модули | Проходят `make check` (R6), архитектурные тесты в отдельном job-е (R13); коммиты по R18–R19 со scope модуля; ТЗ модуля проверяется `specs check` (R15) |
| shared kernel | `APP_VERSION` из образа в `flt_instance_info` (R21); маркеры тестов и плагин (SYS-10) используются проверками R14–R15 |
| frontend app_shell и модули | `pnpm check` (R7, R34); правила `eslint-comments/require-description`; удаление `husky`; `coverage-summary.json` как артефакт (R31) |
| `src/tools` (`flt_tools`) | Команды `traceability generate`, `traceability check`, `specs check`, `contracts check`, `commits check`, `quality check-thresholds`, `quality report`, `quality ci-durations`, `quality durations`, `quality check-branch-protection`; тесты workflow-файлов, Renovate и корневого Makefile; `src/tools/contracts/` с `.spectral.yaml` и `package.json`; `precommit_map.toml`; собственный `pyproject.toml` на Python 3.14 (ADR-001) и job `tools` |
| deploy | `deploy/scripts/smoke.sh` с bats-тестом; `deploy/README.md` с чек-листами настроек репозитория (branch protection, tag protection, окружение `prod`, `CI_HEAVY_RUNNER`, Renovate App) и деплоя; `docker-compose.ci.yml` с комментарием `pragma: allowlist secret` у пароля CI |
| Analytics | `.markdownlint-cli2.yaml`; `traceability.md` генерируется (разделы 6–10); документы соответствуют проверкам R8 и R15 |
| корень репозитория | `.pre-commit-config.yaml`, `commitlint.config.mjs`, `renovate.json`, `.secrets.baseline`, `Makefile`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/{ci,release,deploy-vps,nightly}.yml` |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| Шапка (статус, версия, история) | Подсказка: `flt-tools specs check` требует совпадения статуса и версии с последней строкой истории; `draft`/`review` не могут иметь тегов тестов (R15) |
| 13. План тестов | Ссылка: матрица трассировки генерируется из тегов этого плана командой `make traceability` на шаге 14 (R14) |
| 15. Definition of Done | Разделить пункты на «проверяет CI» и «проверяет человек» по таблице R16; добавить пункт «PR переведён в ready на шаге 11, полный прогон зелёный до рефакторинга» (R5) и «коммиты по шагам конвейера, `test` раньше `feat`» (R19) |
| 16. История изменений | Подсказка: запись при переводе в `implemented` делается в коммите `docs(<module>): <ID> …` шага 14 вместе с матрицей трассировки |

## 5. Примеры

### Пример 1. Фрагмент `ci.yml`: `changes`, `backend-tests`, `stand-n3`, `ci-ok` (SYS-12-R2, R3, R4, R12, R25, R27)

```yaml
name: ci
on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened, ready_for_review, labeled]
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  changes:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    outputs:
      backend: ${{ steps.filter.outputs.backend }}
      frontend: ${{ steps.filter.outputs.frontend }}
      deploy: ${{ steps.filter.outputs.deploy }}
      docs: ${{ steps.filter.outputs.docs }}
      contracts: ${{ steps.filter.outputs.contracts }}
      tools: ${{ steps.filter.outputs.tools }}
      run_full: ${{ steps.full.outputs.run_full }}
    steps:
      - uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0
      - uses: dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36 # v3.0.2
        id: filter
        with:
          filters: |
            backend: ['src/backend/**', 'deploy/**']
            frontend: ['src/frontend/**']
            deploy: ['deploy/**']
            docs: ['Analytics/**', '*.md']
            contracts: ['Analytics/Specs/**/api/*.yaml']
            tools: ['src/tools/**']
      - id: full
        run: |
          if [[ "${{ github.event_name }}" == "push" || "${{ github.event_name }}" == "workflow_dispatch" \
             || "${{ github.event.pull_request.draft }}" == "false" \
             || "${{ contains(github.event.pull_request.labels.*.name, 'ci:full') }}" == "true" ]]; then
            echo "run_full=true" >> "$GITHUB_OUTPUT"
          else
            echo "run_full=false" >> "$GITHUB_OUTPUT"
          fi

  backend-tests:
    needs: changes
    runs-on: ubuntu-latest
    timeout-minutes: 10
    services:
      postgres:
        image: postgres:18-alpine
        env: { POSTGRES_USER: flt, POSTGRES_PASSWORD: flt_ci, POSTGRES_DB: flt }   # pragma: allowlist secret
        options: --health-cmd "pg_isready -U flt" --health-interval 5s --health-retries 10
        ports: ["5432:5432"]
      redis:
        image: redis:8-alpine
        ports: ["6379:6379"]
      minio:
        image: ${{ vars.MINIO_IMAGE }}        # зафиксированный тег (ADR-001, OQ-64)
        ports: ["9000:9000"]
    steps:
      - if: needs.changes.outputs.backend != 'true'
        run: echo "backend not changed — always-report success"
      - if: needs.changes.outputs.backend == 'true'
        uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0
      - if: needs.changes.outputs.backend == 'true'
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86 # v6.4.3
        with:
          enable-cache: true
          cache-dependency-glob: src/backend/py-monolyth/uv.lock
      - if: needs.changes.outputs.backend == 'true'
        working-directory: src/backend/py-monolyth
        env: { PG_HOST: 127.0.0.1, PG_USERNAME: flt, PG_PASSWORD: flt_ci, REDIS_HOST: 127.0.0.1 }   # pragma: allowlist secret
        run: |
          make install
          psql "postgresql://flt:flt_ci@127.0.0.1:5432/flt" -c 'CREATE DATABASE flt_test'   # SYS-10-R4
          make test-cov PYTEST_ADDOPTS="--junitxml=reports/junit.xml --cov-report=xml:reports/coverage.xml"
      - if: always() && needs.changes.outputs.backend == 'true'
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with: { name: backend-reports, path: src/backend/py-monolyth/reports/, retention-days: 7 }

  stand-n3:
    needs: [changes, images]
    if: needs.changes.outputs.run_full == 'true' && (needs.changes.outputs.backend == 'true' || needs.changes.outputs.deploy == 'true')
    runs-on: ${{ vars.CI_HEAVY_RUNNER || 'ubuntu-latest' }}
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0
      - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
        with: { name: images }
      - run: docker load -i images.tar
      - run: deploy/scripts/gen-secrets.sh --ci > deploy/docker-compose/.env.ci && echo "::add-mask::$(cut -d= -f2 deploy/docker-compose/.env.ci | tr '\n' ' ')"
      - run: |
          docker compose -p flt --env-file deploy/docker-compose/.env.ci \
            -f deploy/docker-compose/docker-compose.yml -f deploy/docker-compose/docker-compose.ci.yml \
            --profile ci up -d --wait --scale api=3
      - working-directory: src/backend/py-monolyth
        run: |
          uv run python -m app seed --profile n3
          uv run pytest -m n_instances --stand-url http://127.0.0.1:8080 --junitxml=reports/junit-n3.xml
      - name: migration compatibility (old code, new schema)   # SYS-05-R34
        run: deploy/scripts/migration-compat.sh main sha-${GITHUB_SHA::7}
      - if: failure()
        run: docker compose -p flt logs --no-color > compose-logs.txt
      - if: failure()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with: { name: stand-n3-logs, path: compose-logs.txt, retention-days: 7 }
      - if: always()
        run: docker compose -p flt down -v

  ci-ok:
    needs: [changes, backend-quality, architecture, backend-tests, frontend, tools, contracts, docs, commits, images, stand-n3, e2e, helm]
    if: always()
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - run: |
          echo '${{ toJSON(needs) }}' > needs.json
          python3 - <<'EOF'
          import json, sys
          needs = json.load(open("needs.json"))
          run_full = needs["changes"]["outputs"]["run_full"] == "true"
          heavy = {"images", "stand-n3", "e2e", "helm"}
          bad = [n for n, r in needs.items()
                 if r["result"] == "failure" or r["result"] == "cancelled"
                 or (run_full and n in heavy and r["result"] == "skipped")]
          print("failed or wrongly skipped:", bad)
          sys.exit(1 if bad else 0)
          EOF
```

### Пример 2. Корневой `.pre-commit-config.yaml` (SYS-12-R11)

```yaml
default_install_hook_types: [pre-commit, commit-msg]
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.17.0
    hooks:
      - id: ruff-check
        args: ["--fix"]
        files: ^src/(backend/py-monolyth|tools|agent)/
      - id: ruff-format
        files: ^src/(backend/py-monolyth|tools|agent)/
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.9.11
    hooks:
      - id: uv-lock
        files: ^src/backend/py-monolyth/(pyproject\.toml|uv\.lock)$
        args: ["--project", "src/backend/py-monolyth"]
  - repo: https://github.com/PyCQA/bandit
    rev: 1.9.4
    hooks:
      - id: bandit
        args: ["-c", "src/backend/py-monolyth/pyproject.toml"]
        additional_dependencies: ["bandit[toml]"]
        files: ^src/(backend|tools|agent)/
        exclude: /tests/
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]
  - repo: https://github.com/DavidAnson/markdownlint-cli2
    rev: v0.18.1
    hooks:
      - id: markdownlint-cli2
        files: ^(Analytics/|CLAUDE\.md|README\.md)
  - repo: https://github.com/hadolint/hadolint
    rev: v2.14.0
    hooks:
      - id: hadolint-docker
  - repo: https://github.com/shellcheck-py/shellcheck-py
    rev: v0.11.0.1
    hooks:
      - id: shellcheck
        args: ["-S", "warning"]
        files: ^deploy/scripts/.*\.sh$
  - repo: https://github.com/rhysd/actionlint
    rev: v1.7.7
    hooks:
      - id: actionlint
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: check-yaml
        exclude: ^deploy/helm/.*/templates/
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-merge-conflict
      - id: no-commit-to-branch
        args: ["--branch", "main"]
  - repo: local
    hooks:
      - id: lint-imports
        name: import-linter (ADR-002)
        entry: bash -c 'cd src/backend/py-monolyth && uv run lint-imports'
        language: system
        pass_filenames: false
        files: ^src/backend/py-monolyth/(app/|configs/|\.importlinter)
      - id: mypy-backend
        name: mypy strict (backend)
        entry: bash -c 'cd src/backend/py-monolyth && uv run mypy app cli configs'
        language: system
        pass_filenames: false
        files: ^src/backend/py-monolyth/.*\.py$
      - id: frontend-lint-staged
        name: lint-staged (frontend)
        entry: pnpm --dir src/frontend lint-staged
        language: system
        pass_filenames: false
        files: ^src/frontend/
      - id: spectral
        name: spectral (контракты)
        entry: pnpm --dir src/tools/contracts exec spectral lint --ruleset .spectral.yaml
        language: system
        files: ^Analytics/Specs/.*/api/.*\.ya?ml$
      - id: helm-lint
        name: helm lint
        entry: helm lint deploy/helm/flt
        language: system
        pass_filenames: false
        files: ^deploy/helm/
      - id: commitlint
        name: commitlint
        entry: pnpm --dir src/tools/contracts exec commitlint --edit
        language: system
        stages: [commit-msg]
```

### Пример 3. Сообщения коммитов и `commitlint.config.mjs` (SYS-12-R18, R19)

```text
spec(identity): VIS-04 draft feature spec for registration
spec(identity): VIS-04 add openapi contract for /auth/register
test(identity): VIS-04 add red tests for AC1-AC7
test(app-shell): VIS-04 add red component tests for registration form
test(e2e): VIS-04 add red e2e scenarios ru/en/ar
feat(identity): VIS-04 implement registration service and router
feat(app-shell): VIS-04 registration form with i18n and RTL
fix(identity): VIS-04 return 409 already_exists on duplicate email
refactor(identity): VIS-04 extract consent service
deploy(deploy): VIS-04 add SMTP variables to compose and helm
docs(identity): VIS-04 update _module.md and traceability, status implemented
deps(repo): weekly minor and patch
ci(repo): add tools job to fast stage
```

```js
// commitlint.config.mjs
import { execSync } from 'node:child_process';

const modules = execSync('cd src/backend/py-monolyth && uv run python -m cli list-modules', { encoding: 'utf8' })
  .split('\n').map((s) => s.trim()).filter(Boolean);
const scopes = [...modules, 'core', 'frontend', 'app-shell', 'e2e', 'tools', 'deploy', 'analytics', 'repo'];
const SPEC_ID = /^((VIS|ADM|STU|TCH)-\d{2}(\.\d+)?|SYS-\d{2}|ADR-\d{3}) /;

export default {
  extends: ['@commitlint/config-conventional'],
  plugins: [{
    rules: {
      'subject-starts-with-spec-id': ({ type, subject }) =>
        ['test', 'feat', 'fix', 'refactor'].includes(type) && !SPEC_ID.test(subject ?? '')
          ? [false, 'subject must start with spec ID, e.g. "VIS-04 add red tests"']
          : [true],
    },
  }],
  rules: {
    'type-enum': [2, 'always', ['spec', 'test', 'feat', 'fix', 'refactor', 'deploy', 'docs', 'ci', 'deps', 'chore']],
    'scope-enum': [2, 'always', scopes],
    'scope-empty': [2, 'never'],
    'header-max-length': [2, 'always', 100],
    'subject-case': [0],
    'subject-starts-with-spec-id': [2, 'always'],
  },
};
```

### Пример 4. Шаблон PR с Definition of Done (SYS-12-R5, R16)

```markdown
## ТЗ
STU-18 — Analytics/Specs/learning_plan/STU-18-learning-plan.md

## Проверяет CI (зелёный `ci-ok`)
- статус ТЗ и история изменений согласованы (`flt-tools specs check`)
- все AC имеют теги тестов, матрица трассировки пересобрана (`flt-tools traceability check`)
- границы модулей (`architecture`), контракты (`contracts`, `api:check`), i18n (`i18n:check`)
- тесты всех уровней и стенд N3 (`backend-tests`, `frontend`, `e2e`, `stand-n3`), Helm в kind (`helm`)
- коммиты по шагам конвейера, `test` раньше `feat` (`commits`)

## Проверяет человек (гейт G3)
- [ ] демо фичи проведено
- [ ] метрики и события логов из раздела 9 ТЗ присутствуют в коде
- [ ] docker-compose и Helm изменены согласованно по смыслу (если затронуто развёртывание)
- [ ] `_module.md` обновлён, если менялся публичный API
- [ ] PR переведён в ready на шаге 11 (все тесты зелёные), полный прогон был зелёным до рефакторинга
- [ ] тесты не ослаблены без изменения ТЗ (статус `changed`)
```

### Пример 5. `deploy/scripts/smoke.sh` — смоук после деплоя (SYS-12-R29)

```bash
#!/usr/bin/env bash
# Смоук-проверки через HAProxy после деплоя (SYS-12-R29). Использование: smoke.sh https://flt.example
set -euo pipefail
base="${1:?base url}"
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$base$1"; }

[[ "$(code /healthz)" == "200" ]] || fail "/healthz"
curl -s --max-time 5 "$base/" | grep -q '<html' || fail "/ is not html"
curl -s --max-time 5 "$base/api/v1/auth/.well-known/jwks.json" | grep -q '"keys"' || fail "jwks"
[[ "$(code /api/docs)" == "404" ]] || fail "/api/docs must be closed"
curl -sI --max-time 5 "$base/v1/ready" | grep -qi '^x-instance-id:' && fail "/v1/ready reached monolith"
[[ "$(code /flt-materials/)" == "403" ]] || fail "/flt-materials/ bucket listing must be 403"
for _ in $(seq 1 10); do
  t=$(curl -s -o /dev/null -w '%{time_total}' --max-time 5 "$base/api/v1/auth/.well-known/jwks.json")
  awk -v t="$t" 'BEGIN { exit (t <= 1.0) ? 0 : 1 }' || fail "jwks slower than 1s: $t"
done
echo "SMOKE OK"
```

## 6. Исключения и как их согласовать

Порядок согласования — как в SYS-05, раздел 6.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-12-R2, R3 | Первый коммит кода этапа 1 (п. Г.1): `ci.yml` только с job-ами `changes`, `backend-quality`, `architecture`, `backend-tests`, `frontend`, `docs`, `ci-ok` | ADR-011, раздел 4.3: минимальный CI с первого коммита, полный пайплайн — п. Г.10 | до завершения п. Г.10 этапа 1 | Claude (черновик), подтверждается на G1 |
| SYS-12-R4 | До настройки branch protection пользователем проверки не являются обязательными | настройка выполняется человеком; до неё слияния в `main` не выполняются (OQ-04: коммиты делает оркестратор) | до первого PR с кодом этапа 1 | Claude (черновик), подтверждается на G1 |
| SYS-12-R22 | Образ MinIO исключён из обновлений Renovate | ADR-001 и ADR-007 §3.10 (community-образ не публикуется, OQ-64) | до решения OQ-64 | пользователь, 2026-10-10 (ADR-001) |
| SYS-12-R28 | До выбора домена (OQ-08) и подготовки VPS (SYS-11) `deploy-vps.yml` не запускается | CD появляется на этапе 2 | до начала этапа 2 | Claude (черновик), подтверждается на G1 |
| SYS-12-R33 | Еженедельный полный прогон compose на hosted runner-е может не уместиться по памяти (OpenSearch 1 ГБ heap, Kafka, Qdrant) | при нехватке ресурсов прогон переносится на self-hosted runner (OQ-68) или сокращается до `up -d --wait` без тестов | до решения OQ-68 | Claude (черновик), подтверждается на G1 |

## 7. Вне рамок

- Содержание и методика тестов (уровни, фикстуры, теги, флаки-политика, бюджеты тестов) — SYS-10; стенд N3 и шесть сценариев — SYS-05.
- Структура `deploy/`, `docker-compose.ci.yml`, `values-ci.yaml`, чек-лист подготовки VPS, runbook отката с `downgrade`, бэкапы — SYS-11.
- Правила Spectral по содержанию контрактов — SYS-03 (OpenAPI) и SYS-04 (AsyncAPI); здесь только факт и место проверки.
- Выбор платформы CI (OQ-06), структура пайплайна и способ деплоя (ADR-011) — не пересматриваются.
- Лицензия и видимость репозитория (OQ-39): влияет на бюджет минут и доступ к GHCR; при публикации репозитория требования R27 (self-hosted) и `GHCR_PULL_TOKEN` теряют актуальность, остальные не меняются.
- Расположение self-hosted runner-а (OQ-68) — deferred; здесь только механизм переключения `CI_HEAVY_RUNNER`.
- Сборка и подпись локального агента (`agent-release.yml`, OQ-65) — ADR-008 и этап 4.
- Нагрузочный job `load` (SYS-10-R34) — появляется на этапе 2 как необязательный `workflow_dispatch` внутри `ci.yml`; порядок обязательного прогона на GS — SDD_plan.md §8.

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-011](../../ADR/ADR-011-ci-cd.md) | основан на | три workflow-а, две ступени, `run_full`, состав job-ов, обязательные проверки, `ci-ok`, кэши, таймауты, бюджет минут, self-hosted runner, секреты CI, pre-commit в корне, `src/tools`, деплой `workflow_dispatch` с подтверждением, правило перевода PR в ready (уточнён номер шага) |
| [ADR-001](../../ADR/ADR-001-tech-stack.md) | основан на | Renovate в корне, группы и метки обновлений, Python 3.14 для `src/tools`, пины версий инструментов, исключение MinIO |
| [ADR-002](../../ADR/ADR-002-module-layout.md) | уточняет | job `architecture` с `lint-imports` и негативным тестом; `python -m cli list-modules` для `scope-enum` |
| [ADR-005](../../ADR/ADR-005-frontend-stack.md) | уточняет | скрипты `lint`, `format:check`, `check-types`, `i18n:check`, `api:check`, `test:cov`, `build`, `build-storybook`; удаление husky; Dockerfile frontend |
| [ADR-013](../../ADR/ADR-013-secrets-management.md) | ограничивает | GitHub Secrets только для деплоя, `gen-secrets.sh --ci`, `fake`-провайдер ESO в kind, `.env` на VPS вне CI, `detect-secrets` на весь репозиторий |
| [ADR-010](../../ADR/ADR-010-observability-stack.md) | уточняет | `APP_VERSION` в `flt_instance_info`; смоук Prometheus и OpenSearch в `nightly.yml` |
| [ADR-012](../../ADR/ADR-012-haproxy-entry-point.md) | уточняет | smoke-проверки путей после деплоя и в kind; `haproxy -c` для обеих веток |
| [ADR-003](../../ADR/ADR-003-state-storage.md), [ADR-004](../../ADR/ADR-004-communication-patterns.md) | уточняет | откат без `downgrade` благодаря expand/contract; сервис `migrate` в деплое |
| [ADR-006](../../ADR/ADR-006-authentication-and-authorization.md) | уточняет | одноразовая Ed25519-пара в тестах CI; `jwks.json` как смоук-проверка |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-05](../../open-questions.md) | Ветвление и коммиты | нет | resolved: R17–R20 детализируют (commitlint добавлен как механизм проверки) |
| [OQ-06](../../open-questions.md) | Платформа CI | нет | resolved: GitHub Actions |
| [OQ-07](../../open-questions.md) | Prod на VPS, Helm в kind | нет | resolved: R28–R30 (деплой на VPS), job `helm` |
| [OQ-70](../../open-questions.md) | Расположение репозиторных скриптов | нет | в реестре `open`, но ADR-011 (accepted, раздел 3) фиксирует решение пользователя 2026-10-10: `src/tools/` — Python-пакет `flt_tools`, `deploy/scripts/` — скрипты развёртывания; спецификация следует ADR-011; карточку OQ-70 нужно перевести в `resolved` (отчёт оркестратору) |
| [OQ-68](../../open-questions.md) | Self-hosted runner | нет | deferred: механизм переключения — R27 |
| [OQ-39](../../open-questions.md) | Видимость и лицензия репозитория | нет | open: влияет на бюджет минут (R27) и `GHCR_PULL_TOKEN` (R23), требования от решения не зависят |
| [OQ-64](../../open-questions.md) | Образ MinIO | нет | open: исключение из Renovate (раздел 6) |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
