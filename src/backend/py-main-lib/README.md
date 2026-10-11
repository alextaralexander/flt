# py-main-lib

Внутренняя библиотека монолита FLT (`src/backend/py-monolyth`): базовые `BaseDAO` и `BaseService`,
фильтрация и пагинация (`filter_utils`), конверты ответов `SuccessfulResponseV1` / `ErrorResponseV1`,
схемы пользователя для проверки прав.

- Правится свободно в репозитории FLT (ADR-001, OQ-69).
- Подключается к монолиту как `path`-зависимость uv: `[tool.uv.sources] py-main-lib = { path = "../py-main-lib" }`
  в `src/backend/py-monolyth/pyproject.toml`. Отдельной установки не требует: `make install` монолита
  (`uv sync`) ставит библиотеку вместе с остальными зависимостями, точные версии — в `uv.lock` монолита.
- Зависимости объявлены диапазонами в `pyproject.toml`, совместимыми с монолитом.
- Docker-образ монолита получает библиотеку через build-context `py-main-lib`
  (`docker build --build-context py-main-lib=../py-main-lib .`, в docker-compose — `additional_contexts`).
