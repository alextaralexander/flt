# SYS-06 — Роли и права

| Поле | Значение |
|---|---|
| Статус | approved |
| Версия | 1.0 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-11 (PR #3) |
| Пункт(ы) BRD | все |
| Модуль | все; владелец ролей, санкций и матрицы — `identity`; проверка — shared kernel `app/core/security` |
| Зависимости | ADR-002, ADR-006; SYS-01 |
| Связанные ADR/SYS | ADR-004, ADR-008, ADR-012, ADR-015; SYS-02, SYS-03, SYS-04, SYS-10 |

## 1. Цель и область действия

- **Цель**: определить роли платформы и их наследование, формат и реестр прав, матрицу «роль × действие» по всем пунктам BRD (включая этапы 2–7 как план), правила проверки прав на сервере (объектные проверки, доступ к обучению после подтверждений, санкции и их немедленное действие), права неинтерактивных участников (локальный агент, роль `media_agent`, внутренние вызовы), права анонима и способ тестирования прав. Матрица раздела 3.3 — источник истины для `app/modules/identity/permissions_matrix.py`, для раздела 7.1 каждого ТЗ и для раздела 9 каждой спецификации модуля.
- **Область действия**: backend (все модули, shared kernel), frontend (отображение по правам, не проверка), локальный агент (границы токена), tests, CI.
- **Действует с этапа**: 1 (роли, формат прав, проверка, санкция `suspension` в объёме Г.5); строки матрицы этапов 2–7 — план, вступающий в силу вместе с ТЗ соответствующего этапа.
- **Уточняет**: CLAUDE.md «Разграничение ролей», «Роли пользователей»; SDD_plan.md этап 1 Б.6; ADR-006 (роли `learner`, `teacher`, `platform_admin`, claims, `RolePermissionsProvider`, `revoked_user`); ADR-002, раздел 3.3 (мнемокоды прав модуля, `ModuleDefinition.permissions`); решения OQ-14 (доступ к обучению после подтверждений); решает OQ-54, OQ-55 (принцип), OQ-75.

## 2. Термины

| Термин | Определение или ссылка |
|---|---|
| Роль, аноним, посетитель портала, ученик, преподаватель (человек), администратор платформы | [глоссарий](../../glossary.md), раздел 1; коды — `anonymous` (не роль, а отсутствие пользователя), `learner`, `teacher`, `platform_admin` |
| Право | Строка вида `<module>:<resource>:<action>` (английский, snake_case в сегментах; `resource` — во множественном числе), объявленная модулем в `permissions.py` и перечисленная в `ModuleDefinition.permissions`. Введено этой спецификацией; формат уточняет ADR-002, раздел 3.3 (префикс модуля сохранён как первый сегмент) |
| Область права (scope) | Ограничение права множеством объектов: `own` — только объекты, владелец которых — текущий пользователь; `rel` — свои объекты и объекты связанных пользователей (для преподавателя — его ученики по SYS-01-R17; для владельца и модератора группы учеников — её объекты; для участника класса — объекты класса); `any` — все объекты. Область — часть матрицы, а не кода права; код права один, область зависит от роли |
| Грант | Результат проверки права для запроса: код права и максимальная область среди ролей пользователя с учётом ограничений; объект `Grant(code, scope)` shared kernel |
| Доступ к обучению | Условие `email_verified ∧ age_confirmed ∧ consent(personal_data)`, обязательное для прав, помеченных в матрице признаком `L` (OQ-14, ADR-006) |
| Санкция | Мера администратора платформы к пользователю: отключение аккаунта (`suspension`), ограничение (`restriction`), бан преподавателя (`teacher_ban`). Решает OQ-54 и OQ-55 (принцип); термины глоссария `suspension`, `restriction`, `teacher_ban` (раздел 9) |
| Ограничиваемая возможность | Именованная группа прав, которую отключает `restriction`: `social_posting`, `messaging`, `course_publishing`, `plugin_publishing`, `teacher_contacts` (перечень — R12) |
| Отношение «преподаватель — ученик» | SYS-01-R17: активная запись ученика на курс преподавателя или активное участие в классе преподавателя |
| Токен агента | [глоссарий](../../glossary.md), раздел 5 |
| Роль монолита `media_agent` | [глоссарий](../../glossary.md), раздел 12 |

## 3. Требования

### 3.1. Роли и модель прав

### SYS-06-R1 Роли и наследование

- **Формулировка**: У пользователя должно быть множество ролей из `{learner, teacher, platform_admin}`; аноним — запрос без пользователя; роль `teacher` должна давать все права роли `learner` с теми же областями (TCH-01) и дополнительно права, отмеченные в столбце «teacher»; роль `platform_admin` не должна включать права `learner` и `teacher` автоматически — администратор, который учится или преподаёт, получает соответствующую роль явно; при регистрации и первом входе через OAuth назначается только `learner`.
- **Обоснование**: BRD TCH-01; ADR-006 (таблицы `roles`, `user_roles`, регистрация с ролью `learner`); разделение ролей администратора и ученика исключает случайный доступ администратора к учебным данным под видом ученика (R15).
- **Проверка**: тест `identity` `test_teacher_inherits_learner_permissions` (множество прав `teacher` ⊇ множество прав `learner` с областью не уже); `test_platform_admin_has_no_learning_permissions`; тест регистрации (`roles == ["learner"]`).
- **Применимость**: backend, tests.

### SYS-06-R2 Формат и реестр прав

- **Формулировка**: Каждое право должно иметь код `<module>:<resource>:<action>`, где `<module>` — имя модуля-владельца из SYS-01, `<resource>` — ресурс во множественном числе, `<action>` — одно из `read`, `create`, `update`, `delete`, `publish`, `unpublish`, `start`, `send`, `invite`, `join`, `leave`, `grant`, `revoke`, `suspend`, `restrict`, `moderate`, `export`, `use`, `manage`, а также специальные действия `accept`, `adjust`, `approve`, `archive`, `claim`, `confirm`, `decide`, `decline`, `disable`, `download`, `enable`, `finish`, `hide`, `install`, `invite_tutor`, `lift_restriction`, `login`, `logout`, `logout_all`, `mute`, `poll`, `read_any`, `read_course_content`, `read_draft`, `read_public`, `refresh`, `regenerate`, `register`, `reject`, `remove`, `resolve`, `restore`, `search`, `select`, `test`, `unhide`, `uninstall`, `unsuspend` (`manage` — все действия над ресурсом, используется только для административных и служебных ресурсов); перечень закрыт и совпадает с константой `PERMISSION_ACTIONS` в `app/core/security/permissions.py`, новое действие добавляется правкой этого требования; код объявляется константой в `app/modules/<module>/permissions.py`, перечисляется в `ModuleDefinition.permissions`, уникален в монолите и не используется модулем с другим именем.
- **Обоснование**: ADR-002, раздел 3.3 (коды с первым сегментом — именем модуля, чтобы коды не пересекались; формат сегментов с `:` совпадает с кодом действия в журнале аудита и с OpenAPI `security scopes`; ADR-002 v1.1 приводит пример `identity:users:read` к этому формату, прежний пример `IDENTITY_GET_USER` был иллюстративным); ADR-006 (permissions выводятся из ролей по реестру модулей).
- **Проверка**: архитектурный тест `tests/architecture/test_permissions.py::test_permission_codes_format` (`<будет создан>`): регулярное выражение `^[a-z_]+:[a-z_]+:[a-z_]+$` и проверка третьего сегмента по `PERMISSION_ACTIONS`, первый сегмент равен имени пакета, уникальность; `test_module_settings_prefix` ADR-002 проверяет для `permissions` префикс `<module>:` (уточнение теста).
- **Применимость**: backend, tests.

### SYS-06-R3 Матрица в коде совпадает со спецификацией

- **Формулировка**: Файл `app/modules/identity/permissions_matrix.py` должен содержать ровно те сочетания «право × роль → область», что и таблицы раздела 3.3 для модулей текущего этапа, включая признак `L`; расхождение в любую сторону — ошибка сборки.
- **Обоснование**: ADR-006, 3.8 (матрица — код `identity`, отдаётся ядру через `RolePermissionsProvider`); спецификация — источник истины (CLAUDE.md).
- **Проверка**: job `docs` CI: `uv run flt-tools permissions check` (`<будет создан>`) парсит таблицы раздела 3.3 (столбцы «Право», «Этап», «аноним», «learner», «teacher», «platform_admin», «L») и сравнивает с экспортом `permissions_matrix.py` (`python -m app identity export-matrix`); архитектурный тест `test_matrix_covers_all_registered_permissions`: каждое право из `ModuleDefinition.permissions` всех модулей присутствует в матрице и наоборот.
- **Применимость**: backend, CI, tests.

### SYS-06-R4 Права выводятся из ролей при проверке, не из токена

- **Формулировка**: Токен доступа должен содержать только `roles`; множество прав и областей должно вычисляться при каждой проверке `RolePermissionsProvider.grants_for(user)` из матрицы, статуса подтверждений (`email_verified`, `age_confirmed`, согласие `personal_data`) и активных ограничений пользователя; результат не кэшируется дольше запроса.
- **Обоснование**: ADR-006, 3.2 (permissions в токен не включаются); изменение матрицы или санкции действует без перевыпуска токенов.
- **Проверка**: тест shared kernel `test_token_has_no_permissions_claim`; тест `identity` `test_grants_recomputed_per_request`.
- **Применимость**: backend, tests.

### 3.2. Проверка на сервере

### SYS-06-R5 Каждый роут и обработчик объявляет доступ

- **Формулировка**: Каждый REST-роут, обработчик WebSocket-команды и проверка подписки на канал должны объявлять требуемое право через зависимость `auth_user(Permission.X)` (или `auth_user_optional(Permission.X)` для роутов, допускающих анонима с правом из столбца «аноним») либо явно помечаться `public=True` только для прав, у которых в столбце «аноним» стоит `✓`; роут без объявления доступа не должен попадать в приложение.
- **Обоснование**: CLAUDE.md «права проверять на сервере, не только в UI»; ADR-002 (`permissions.py`, `auth_user`); ADR-004 (`can_subscribe`).
- **Проверка**: архитектурный тест `tests/architecture/test_permissions.py::test_every_route_declares_access` (`<будет создан>`): обход `app.routes` всех модулей реестра — у каждого роута в зависимостях есть `auth_user`/`auth_user_optional` с кодом права или маркер `public`; аналогично для `ws_handlers` (`required_permission` у каждого канала и команды); контрактный тест SYS-03: `security` в OpenAPI соответствует объявленному (`[]` только у `public`).
- **Применимость**: backend, tests.

### SYS-06-R6 Объектные проверки по области

- **Формулировка**: Для прав с областью `own` или `rel` сервис должен проверять принадлежность объекта до выполнения действия и при выборках ограничивать результат областью: `own` — `owner_user_id == user_id`; `rel` — владелец объекта связан с пользователем через источники SYS-01-R17 (`courses`, `classroom`) или пользователь — владелец/модератор группы, участник класса или переписки; отказ — `403 core.forbidden` (объект существует, но недоступен) или `404 core.not_found` (SYS-03-R7, R21) для ресурсов, само существование которых раскрывать нельзя (личные сообщения, собственные материалы, записи закрытых групп); выбор кода фиксируется в ТЗ.
- **Обоснование**: CLAUDE.md «Разграничение ролей»; раздел 7.1 шаблона ТЗ («свои» — только над своими объектами).
- **Проверка**: тесты прав каждого ТЗ (R19): для каждого AC с областью `own`/`rel` — отрицательный тест «чужой объект → 403/404» и тест выборки «в списке нет чужих объектов»; хелпер shared kernel `Grant.ensure(owner_id, relation=...)` покрыт unit-тестами.
- **Применимость**: backend, tests.

### SYS-06-R7 Доступ к обучению после подтверждений

- **Формулировка**: Права, помеченные в матрице признаком `L`, должны предоставляться только пользователю с `email_verified = true`, `age_confirmed = true` и активным согласием `personal_data`; без любого из условий ответ — `403` с кодом `email_not_verified`, `age_not_confirmed` или `consent_required` и указанием недостающего шага; права без признака `L` (вход, профиль аккаунта, согласия, подтверждение email, выход, удаление аккаунта, публичные страницы) доступны сразу после регистрации.
- **Обоснование**: решение OQ-14 («без подтверждения доступ к обучению закрыт»); ADR-006, 3.5 (вход разрешён сразу, доступ к обучению закрыт до подтверждения email и 18+); SYS-02-R32.
- **Проверка**: тест `identity` `test_learning_gate_blocks_until_confirmed` на эндпоинтах `learner_profile` и `llm_gateway` (этап 1 — на диагностическом канале стрима); параметризованный тест R19 для каждой строки с `L`: пользователь без подтверждения → 403 с ожидаемым кодом.
- **Применимость**: backend, tests.

### SYS-06-R8 Проверка прав для WebSocket

- **Формулировка**: Подписка на канал `<module>.<channel>[:<id>]` и команда модуля по WebSocket должны проверяться теми же кодами прав и областями, что и REST-эндпоинт состояния этого канала (ADR-004); для анонимного быстрого теста канал `assessment.quick_test:<session_id>` и `lessons.demo_lesson:<session_id>` доступны только соединению с идентификатором той же анонимной сессии; отзыв сессии или санкция закрывают соединение кодом `4401`.
- **Обоснование**: ADR-004, 3.3 (`can_subscribe`); ADR-006, 3.7.
- **Проверка**: тесты SYS-04 на `can_subscribe` с чужим `<id>` → `ws.error` с кодом `ws.forbidden` (SYS-04); тест на N инстансах «`logout-all`/`suspend` на инстансе A закрывает соединение на инстансе B» (ADR-006, 3.9).
- **Применимость**: backend, tests.

### SYS-06-R9 Интерфейс не является источником прав

- **Формулировка**: Фронтенд должен скрывать или блокировать элементы по списку прав из `GET /api/v1/auth/me` (поле `permissions: [{code, scope}]`) только для удобства; при любом ответе `403` клиент показывает сообщение по коду ошибки, а не считает действие выполненным; E2E-тесты прав обращаются к API напрямую в обход UI.
- **Обоснование**: CLAUDE.md: права проверять на сервере, не только в UI.
- **Проверка**: E2E `permissions-ui.spec.ts` (`<будет создан>`): под ролью `learner` административные пункты меню отсутствуют и прямой `fetch` административного эндпоинта возвращает 403; MSW-мок `403` показывает сообщение.
- **Применимость**: frontend, tests.

### 3.3. Матрица «роль × действие»

Обозначения: `—` — запрещено; `✓` — разрешено (действие без объекта или объект — сам пользователь); `own`, `rel`, `any` — область (раздел 2); `L` — требуется доступ к обучению (R7); «этап» — этап появления строки (строки будущих этапов — план, уточняются в ТЗ без изменения направления: ТЗ может сузить область, но не расширить без `changed`-версии SYS-06). Столбец `teacher` содержит только права сверх `learner`; пустая ячейка у `teacher` означает «как `learner`». Административные права с областью `any`, изменяющие данные, записываются в журнал аудита (SYS-02-R50). Для прав этапов 2–7 коды — черновые имена ресурсов, которые ТЗ модуля вправе переименовать внутри модуля с правкой этой таблицы в той же `changed`-версии.

#### identity (этапы 1–3, 6)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `identity:auth:register` | 2 | VIS-04 | ✓ | — | — | — | |
| `identity:auth:login` (email и пароль; OAuth `start`, `callback`) | 1 | VIS-05 | ✓ | — | — | — | |
| `identity:auth:refresh`, `identity:auth:logout`, `identity:auth:logout_all` | 1 | VIS-05 | — | ✓ | | ✓ | |
| `identity:auth:read` (`jwks.json`, список включённых провайдеров) | 1 | VIS-05 | ✓ | ✓ | | ✓ | |
| `identity:password:update` (смена, восстановление `forgot`/`reset` — аноним) | 2 | VIS-05 | ✓ (forgot, reset) | own | | own | |
| `identity:email:update` (подтверждение, повторная отправка, смена) | 2 | VIS-04 | ✓ (verify по токену) | own | | own | |
| `identity:me:read` | 1 | VIS-05 | — | ✓ | | ✓ | |
| `identity:me:update` (`display_name`, `ui_language`, `timezone`, фото профиля) | 2, 6 | STU-06, STU-35.1 | — | own | | own | |
| `identity:me:delete` (запрос и отмена удаления аккаунта) | 3 | SYS-02-R35 | — | own | | own | |
| `identity:me:export` | 3 | SYS-02-R37 | — | own | | own | L |
| `identity:consents:manage` (выдача и отзыв согласий) | 2 | VIS-04 | — | own | | own | |
| `identity:sessions:read`, `identity:sessions:revoke` | 2 | VIS-05 | — | own | | own | |
| `identity:external_accounts:manage` (привязка, отвязка) | 2 | VIS-04 | — | own | | own | |
| `identity:users:read_public` (имя и фото профиля любого пользователя по id) | 6 | TCH-06, STU-35 | — | any | | any | L |
| `identity:users:read` (карточка пользователя: email, статус, роли, согласия, санкции) | 3 | ADM-01 | — | — | — | any | |
| `identity:users:search` | 3 | ADM-01 | — | — | — | any | |
| `identity:users:update` (атрибуты: имя, язык, подтверждение email вручную) | 3 | ADM-01 | — | — | — | any | |
| `identity:users:suspend`, `identity:users:unsuspend` | 3 | ADM-01 | — | — | — | any | |
| `identity:users:restrict`, `identity:users:lift_restriction` | 3, 7 | ADM-01, ADM-05 | — | — | — | any | |
| `identity:roles:grant`, `identity:roles:revoke` (в том числе бан преподавателя) | 3 | ADM-01, ADM-02 | — | — | — | any | |
| `identity:users:delete` (удаление по письменному запросу субъекта без периода отмены) | 3 | SYS-02-R35 | — | — | — | any | |

#### audit (этап 3)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `audit:records:read` (просмотр и фильтры; факт просмотра пишется в журнал) | 3 | ADM-01…ADM-06 | — | — | — | any | |

#### languages (этап 4)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `languages:languages:read` | 4 | STU-07, STU-08 | ✓ | ✓ | | ✓ | |
| `languages:languages:manage` (включение языка как изучаемого или языка интерфейса, метаданные) | 4 | STU-08…STU-11 | — | — | — | any | |

#### cms (этапы 2–3)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `cms:pages:read` (опубликованные) | 2 | VIS-01 | ✓ | ✓ | | ✓ | |
| `cms:pages:read_draft` | 3 | ADM-03 | — | — | — | any | |
| `cms:pages:create`, `cms:pages:update`, `cms:pages:delete` | 3 | ADM-03 | — | — | — | any | |
| `cms:pages:publish`, `cms:pages:unpublish` | 3 | ADM-03 | — | — | — | any | |
| `cms:media:manage` (загрузка и удаление медиа) | 3 | ADM-03 | — | — | — | any | |

#### courses (этапы 2, 3, 6)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `courses:catalog:read` (каталог и карточка опубликованного курса) | 2 | VIS-02 | ✓ | ✓ | | ✓ | |
| `courses:courses:create` | 6 | TCH-02 | — | — | ✓ | — | L |
| `courses:courses:update`, `courses:courses:delete` (черновик) | 6 | TCH-02 | — | — | own | — | L |
| `courses:courses:publish`, `courses:courses:unpublish` | 6 | TCH-02 | — | — | own | — | L |
| `courses:courses:read_draft` (черновики и архив) | 6 | TCH-02 | — | — | own | any | |
| `courses:content:manage` (структура теории и практики, ссылки на материалы) | 6 | TCH-03 | — | — | own | — | L |
| `courses:enrollments:create` (запись на открытый курс или по приглашению) | 6 | TCH-02 | — | own | | — | L |
| `courses:enrollments:delete` (отчисление себя; преподаватель — ученика со своего курса) | 6 | TCH-02 | — | own | rel | — | L |
| `courses:enrollments:read` (список записанных) | 6 | TCH-02, TCH-05 | — | own | rel | any | |
| `courses:invitations:create`, `courses:invitations:revoke` | 6 | TCH-02 | — | — | own | — | L |
| `courses:invitations:accept`, `courses:invitations:decline` | 6 | TCH-02 | — | own | | — | L |
| `courses:courses:disable`, `courses:courses:enable` (отключение администратором) | 3 | ADM-02 | — | — | — | any | |
| `courses:courses:archive`, `courses:courses:restore` | 3 | ADM-02 | — | — | — | any | |
| `courses:courses:read_any` (карточка любого курса с данными преподавателя для управления) | 3 | ADM-02 | — | — | — | any | |

#### assessment (этапы 2, 4, 5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `assessment:quick_tests:create` (в пределах лимитов и капчи) | 2 | VIS-03 | ✓ | ✓ | | — | |
| `assessment:quick_tests:update` (ответы), `assessment:quick_tests:read` (результат своей сессии) | 2 | VIS-03 | own (сессия) | own | | — | |
| `assessment:quick_tests:claim` (перенос результата в аккаунт после регистрации) | 2 | VIS-03 | — | own | | — | |
| `assessment:level_tests:create`, `assessment:level_tests:update`, `assessment:level_tests:read` | 4 | STU-15 | — | own | | — | L |
| `assessment:exams:read` (конфигурации экзаменов) | 5 | STU-23 | — | ✓ | | ✓ | L |
| `assessment:exams:manage` | 5 | STU-23 | — | — | — | any | |

#### lessons (этапы 2, 4, 5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `lessons:demo_lessons:start`, `lessons:demo_lessons:send` (демо-урок анонимной сессии быстрого теста) | 2 | VIS-03 | own (сессия) | own | | — | |
| `lessons:lessons:start` (теория, практика, тренинг, экзамен) | 4 | STU-20…STU-23 | — | own | | — | L |
| `lessons:lessons:send` (реплика, ответ на упражнение, отмена стрима) | 4 | STU-20, STU-21 | — | own | | — | L |
| `lessons:lessons:read` (история занятий и реплик) | 4 | STU-19 | — | own | | — | L |
| `lessons:lessons:delete` (удаление истории занятия) | 4 | SYS-02 | — | own | | — | L |
| `lessons:persona_scenes:read` (показанные сцены персонажа) | 5 | STU-36 | — | own | | — | L |

Преподаватель не имеет доступа к репликам занятий ученика: TCH-05 — просмотр прогресса (`progress`), не переписки с AI-преподавателем.

#### llm_gateway (этапы 1, 2, 4, 7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `llm_gateway:providers:read` (реестр провайдеров и моделей) | 1 | STU-01, STU-03 | ✓ (для быстрого теста) | ✓ | | ✓ | |
| `llm_gateway:platform_model:use` (только внутри быстрого теста и демо-урока) | 2 | VIS-03 | own (сессия) | — | — | — | |
| `llm_gateway:provider_bindings:create`, `update`, `delete`, `read` | 4 | STU-01 | — | own | | — | L |
| `llm_gateway:provider_bindings:test` (проверка соединения, диагностический стрим) | 1 | STU-01 | — | own | | — | L |
| `llm_gateway:completions:create` (прямой стрим; вызывается модулями, у клиента — только через каналы `lessons`, `dictionary`, диагностику) | 1 | STU-20 | — | own | | — | L |
| `llm_gateway:usage:read` (расход токенов) | 4 | STU-01 | — | own | | any (агрегаты без содержимого) | |
| `llm_gateway:harness:manage` (MCP-серверы, скилы, настройки harness ученика) | 7 | STU-25 | — | own | | — | L |
| `llm_gateway:platform_model:manage` (лимиты и статистика модели платформы) | 2 | VIS-03 | — | — | — | any | |

#### local_runtime (этапы 4–5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `local_runtime:pairings:create`, `local_runtime:pairings:poll` (агент, без аутентификации, лимит 5 в минуту с IP) | 4 | STU-05 | ✓ | — | — | — | |
| `local_runtime:pairings:confirm` | 4 | STU-05 | — | own | | — | L |
| `local_runtime:agents:read`, `local_runtime:agents:revoke`, `local_runtime:agents:select` | 4 | STU-05, STU-03 | — | own | | — | L |
| `local_runtime:agent_releases:read` (манифест релизов) | 4 | STU-05 | ✓ | ✓ | | ✓ | |
| `local_runtime:engines:manage` (список моделей, запуск и остановка движка через агент) | 4 | STU-05, STU-02 | — | own | | — | L |
| `local_runtime:hardware:read` | 5 | STU-04 | — | own | | — | L |
| `local_runtime:recommendations:read` | 5 | STU-04 | — | own | | — | L |
| `local_runtime:models:download`, `local_runtime:models:delete` | 5 | STU-02 | — | own | | — | L |
| `local_runtime:model_catalog:read`, `local_runtime:engine_builds:read` | 5 | STU-02 | — | ✓ | | ✓ | L |
| `local_runtime:model_catalog:manage`, `local_runtime:engine_builds:manage` | 5 | STU-02 | — | — | — | any | |

#### learner_profile (этапы 4–5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `learner_profile:profiles:read` | 4 | STU-07, STU-14 | — | own | rel (языки и уровни учеников) | — | L |
| `learner_profile:profiles:update` (темы, выбранная модель, продвинутые параметры, wizard) | 4, 5 | STU-03, STU-24, STU-26, STU-32 | — | own | | — | L |
| `learner_profile:learner_languages:create`, `update`, `delete` | 4 | STU-07, STU-33 | — | own | | — | L |
| `learner_profile:levels:update` (текущий, рабочий, целевой) | 4 | STU-14, STU-16, STU-17 | — | own | | — | L |

#### learning_plan (этапы 4, 6)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `learning_plan:plans:create` (генерация), `learning_plan:plans:read` | 4 | STU-18 | — | own | rel (read) | — | L |
| `learning_plan:plans:update` (параметры, перегенерация, архив) | 4 | STU-18, STU-24 | — | own | | — | L |
| `learning_plan:plans:adjust` (корректировка преподавателем с указанием автора) | 6 | TCH-05 | — | — | rel | — | L |

#### progress (этапы 4, 6, 7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `progress:progress:read` | 4 | STU-19, STU-33 | — | own | rel | — | L |
| `progress:achievements:read` | 7 | STU-35.1 | — | own | rel | — | L |
| `progress:achievements:update` (видимость на странице ученика) | 7 | STU-35.1 | — | own | | — | L |

#### dictionary (этапы 4–5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `dictionary:entries:read` (поиск в кэше, генерация своей моделью при промахе) | 4 | STU-12 | — | ✓ | | — | L |
| `dictionary:entries:regenerate` | 4 | STU-12 | — | ✓ | | — | L |
| `dictionary:entries:delete` (удаление статьи из общего кэша: ошибочный или недопустимый контент) | 4 | STU-12 | — | — | — | any | |
| `dictionary:pronunciations:read` (озвучивание через `speech`) | 5 | STU-13 | — | ✓ | | — | L |

#### speech (этап 5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `speech:voice_sessions:start`, `speech:voice_sessions:send` | 5 | STU-28, STU-34.2 | — | own | | — | L |
| `speech:voices:read` (доступные голоса провайдера) | 5 | STU-13, STU-29 | — | ✓ | | ✓ | L |
| `speech:recordings:read`, `speech:recordings:delete` (при согласии `voice_recording`) | 5 | SYS-02-R41 | — | own | | — | L |

#### avatar (этапы 5–7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `avatar:settings:read` (действующие настройки с учётом приоритета) | 5 | STU-29 | — | own | rel | — | L |
| `avatar:settings:update` уровня `learner` | 5 | STU-29 | — | own | rel (для своего ученика, с указанием автора — OQ-47) | — | L |
| `avatar:settings:update` уровня `course` | 6 | TCH-02, TCH-04 | — | — | own (курс) | — | L |
| `avatar:settings:update` уровня `system` | 5 | STU-29 | — | — | — | any | |
| `avatar:personas:read` (персонажи платформы: имя, образ, описание) | 5 | STU-36 | ✓ (стартовая страница) | ✓ | | ✓ | |
| `avatar:personas:manage` (создание, тексты, поведенческие паттерны, версии, назначение на язык) | 5, 7 | STU-36, ADM-06 | — | — | — | any | |

#### materials (этапы 5–6)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `materials:materials:create`, `read`, `update`, `delete` (собственные материалы; у преподавателя — также контент его курсов) | 5, 6 | STU-27, TCH-03 | — | own | own | — | L |
| `materials:materials:read_course_content` (контент курса, на который ученик записан) | 6 | TCH-03 | — | rel (записан на курс) | own | — | L |
| `materials:search:use` (семантический поиск по своим материалам) | 5 | STU-27 | — | own | | — | L |

#### memorization (этап 5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `memorization:word_sets:create`, `read`, `update`, `delete` | 5 | STU-34 | — | own | | — | L |
| `memorization:reviews:create` (ответ на повторение), `memorization:reviews:read` | 5 | STU-34 | — | own | | — | L |
| `memorization:settings:update` (частота показа, тихие часы, режимы) | 5 | STU-34.1 | — | own | | — | L |

#### notifications (этап 5)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `notifications:notifications:read`, `notifications:notifications:update` (прочитано, удалено) | 5 | TCH-07, STU-34.1 | — | own | | own | |
| `notifications:settings:update` (каналы, тихие часы) | 5 | STU-34.1 | — | own | | own | |
| `notifications:push_subscriptions:manage` | 5 | STU-34.1 | — | own | | own | |

#### classroom (этап 6)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `classroom:classrooms:create` | 6 | TCH-09 | — | — | ✓ | — | L |
| `classroom:classrooms:read` | 6 | TCH-07 | — | rel (участник) | own | any (карточка без переписки) | L |
| `classroom:classrooms:update`, `classroom:classrooms:delete` | 6 | TCH-09 | — | — | own | — | L |
| `classroom:members:invite`, `classroom:members:remove` | 6 | TCH-07 | — | — | own | — | L |
| `classroom:members:join` (по приглашению), `classroom:members:leave` | 6 | TCH-07 | — | own | | — | L |
| `classroom:group_lessons:create`, `update`, `delete` (расписание) | 6 | TCH-07 | — | — | own | — | L |
| `classroom:group_lessons:read` | 6 | TCH-07 | — | rel (участник) | own | — | L |
| `classroom:group_lessons:start`, `classroom:group_lessons:finish`, `classroom:group_lessons:invite_tutor` | 6 | TCH-08 | — | — | own | — | L |
| `classroom:media_tokens:create` (вход в комнату; занятие идёт или начинается в ближайшие 15 минут) | 6 | TCH-08 | — | rel (участник) | own | — | L |
| `classroom:recordings:start`, `classroom:recordings:delete` | 6 | TCH-08 | — | — | own | — | L |
| `classroom:recordings:read` (presigned GET) | 6 | TCH-08 | — | rel (участник, давший согласие) | own | — | L |
| `classroom:classrooms:archive` (следствие бана преподавателя — автоматически по событию; вручную — администратор) | 6 | ADM-02 | — | — | — | any | |

#### messaging (этапы 6–7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `messaging:conversations:create` (личная: преподаватель → свой ученик; ученик → ученик по настройкам приватности `social`; класс — создаёт `classroom`) | 6, 7 | TCH-06, STU-35.5 | — | rel | rel | — | L |
| `messaging:conversations:read`, `messaging:messages:read` | 6 | TCH-06, TCH-08 | — | rel (участник) | rel (участник) | any (только сообщение, на которое подана жалоба, в контексте ADM-05) | L |
| `messaging:messages:send` | 6 | TCH-06, TCH-08 | — | rel (участник) | rel (участник) | — | L |
| `messaging:messages:delete` | 6 | TCH-06 | — | own (своё сообщение) | own | any (по жалобе) | L |
| `messaging:conversations:leave`, `messaging:conversations:mute` | 6 | TCH-06 | — | rel (участник) | rel | — | L |

#### social (этап 7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `social:profile_pages:read` (с учётом настроек приватности владельца и блокировок) | 7 | STU-35.1, STU-35.7 | — | any | | any | L |
| `social:profile_pages:update` | 7 | STU-35.1 | — | own | | — | L |
| `social:posts:create` (на своей странице или в группе, где состоит) | 7 | STU-35.2 | — | own / rel (группа) | | — | L |
| `social:posts:read` (по приватности и политике группы) | 7 | STU-35.2, STU-35.4 | — | any | | any | L |
| `social:posts:update`, `social:posts:delete` | 7 | STU-35.2 | — | own | | any (ADM-05) | L |
| `social:comments:create`, `social:comments:delete` | 7 | STU-35.2 | — | ✓ / own | | any | L |
| `social:likes:create`, `social:likes:delete` | 7 | STU-35.2 | — | own | | — | L |
| `social:friend_requests:create`, `accept`, `decline`; `social:friends:delete` | 7 | STU-35.3 | — | own | | — | L |
| `social:follows:create`, `social:follows:delete` | 7 | STU-35.3 | — | own | | — | L |
| `social:feeds:read` (лента новостей, лента страницы, лента группы) | 7 | STU-35.3 | — | own / any по приватности | | — | L |
| `social:groups:create` | 7 | STU-35.4 | — | ✓ | | — | L |
| `social:groups:read` (карточка; записи и участники — по политике вступления, OQ-53) | 7 | STU-35.4 | — | any | | any | L |
| `social:groups:update`, `social:groups:delete` | 7 | STU-35.4 | — | own (владелец) | | any (ADM-05) | L |
| `social:group_members:invite`, `social:group_members:remove`, `social:join_requests:decide`, `social:group_posts:moderate` | 7 | STU-35.4 | — | rel (владелец или модератор) | | — | L |
| `social:group_moderators:grant`, `social:group_moderators:revoke` | 7 | STU-35.4 | — | own (владелец) | | — | L |
| `social:group_members:join`, `social:join_requests:create`, `social:group_members:leave` | 7 | STU-35.4 | — | own | | — | L |
| `social:search:use` (ученики и группы) | 7 | STU-35.6 | — | ✓ | | ✓ | L |
| `social:privacy_settings:update` | 7 | STU-35.7 | — | own | | — | L |
| `social:user_blocks:create`, `social:user_blocks:delete` | 7 | STU-35.7 | — | own | | — | L |
| `social:complaints:create` | 7 | STU-35.7 | — | ✓ | | — | L |
| `social:complaints:read`, `social:complaints:resolve` | 7 | ADM-05 | — | — | — | any | |
| `social:content:hide`, `social:content:unhide` (записи, страницы, группы) | 7 | ADM-05 | — | — | — | any | |

#### plugins (этап 7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `plugins:plugins:create`, `update`, `delete` (свои плагины, вайбкодинг) | 7 | STU-30 | — | own | | — | L |
| `plugins:plugins:install`, `plugins:plugins:uninstall` (свои и из каталога) | 7 | STU-30, STU-31 | — | own | | — | L |
| `plugins:plugins:publish` (отправка на модерацию), `plugins:plugins:unpublish` (своего) | 7 | STU-31 | — | own | | any | L |
| `plugins:catalog:read` | 7 | STU-31 | — | ✓ | | ✓ | L |
| `plugins:moderation:decide` (одобрить, отклонить, заблокировать опубликованный) | 7 | ADM-04 | — | — | — | any | |
| `plugins:moderation:read` (очередь, отчёты автоматической проверки) | 7 | ADM-04 | — | — | — | any | |

#### promotion (этап 7)

| Право | Этап | Пункт BRD | аноним | learner | teacher | platform_admin | L |
|---|---|---|---|---|---|---|---|
| `promotion:channels:manage` (Telegram, VK; привязка персонажа) | 7 | ADM-06 | — | — | — | any | |
| `promotion:schedules:manage` | 7 | ADM-06 | — | — | — | any | |
| `promotion:publications:read`, `promotion:publications:approve`, `promotion:publications:reject`, `promotion:publications:create` (ручная) | 7 | ADM-06 | — | — | — | any | |
| `promotion:thematic_groups:manage` (группы в `social` от имени персонажа) | 7 | ADM-06 | — | — | — | any | |

#### Сводка по пунктам BRD

| Пункты BRD | Где в матрице |
|---|---|
| VIS-01…VIS-05 | `cms`, `courses:catalog`, `assessment:quick_tests`, `lessons:demo_lessons`, `llm_gateway:platform_model`, `identity:auth` |
| ADM-01…ADM-06 | `identity:users`, `identity:roles`, `audit`, `courses:courses:disable/archive`, `cms`, `plugins:moderation`, `social:complaints`, `social:content`, `promotion`, `avatar:personas:manage` |
| STU-01…STU-05 | `llm_gateway:provider_bindings`, `local_runtime`, `learner_profile:profiles:update` |
| STU-06…STU-11 | `identity:me:update` (`ui_language`), `learner_profile:learner_languages`, `languages` |
| STU-12, STU-13 | `dictionary`, `speech:voices` |
| STU-14…STU-19, STU-33 | `learner_profile:levels`, `assessment:level_tests`, `learning_plan:plans`, `progress` |
| STU-20…STU-23 | `lessons:lessons`, `assessment:exams` |
| STU-24, STU-26, STU-32 | `learner_profile:profiles:update` |
| STU-25, STU-30, STU-31 | `llm_gateway:harness`, `plugins` |
| STU-27 | `materials` |
| STU-28, STU-29, STU-36 | `speech:voice_sessions`, `avatar:settings`, `avatar:personas`, `lessons:persona_scenes` |
| STU-34 | `memorization`, `notifications:settings`, `speech` |
| STU-35 | `social`, `messaging` |
| TCH-01 | R1 (наследование) |
| TCH-02, TCH-03, TCH-09 | `courses`, `materials`, `classroom:classrooms:create` |
| TCH-04 | `avatar:settings:update` (уровни `course`, `learner` с областью `rel`) |
| TCH-05 | `progress:progress:read rel`, `learning_plan:plans:adjust rel`, `learner_profile:profiles:read rel` |
| TCH-06 | `messaging:conversations:create rel` |
| TCH-07, TCH-08 | `classroom`, `messaging` (переписка класса) |

### SYS-06-R10 Права анонима исчерпываются матрицей

- **Формулировка**: Анонимный запрос должен получать доступ только к действиям, у которых в столбце «аноним» стоит `✓` или `own (сессия)` (быстрый тест и демо-урок с идентификатором анонимной сессии: cookie `flt_anon_session`, состояние в Redis с TTL 24 ч, OQ-77); любой другой роут отвечает `401 core.unauthenticated` (SYS-03-R21); анонимные действия с состоянием ограничены лимитами SYS-02-R21 и R44.
- **Обоснование**: BRD VIS-01…VIS-05: посетитель смотрит возможности и каталог, проходит быстрый тест, регистрируется и входит; остальное — для учеников.
- **Проверка**: параметризованный тест R19 для столбца «аноним»; архитектурный тест `test_public_routes_are_in_matrix`: роуты с `public=True` ⊆ множество прав с `✓` у анонима.
- **Применимость**: backend, tests.

### SYS-06-R11 Источник роли `teacher`

- **Формулировка**: Роль `teacher` должна назначаться и сниматься только администратором платформы (`identity:roles:grant`, `identity:roles:revoke`; `granted_by` — администратор; запись в журнал аудита с причиной); форма регистрации не содержит поля «я преподаватель»; самозаявка на роль преподавателя на старте не предоставляется и вводится, если потребуется, `changed`-версией этой спецификации вместе с ТЗ очереди заявок.
- **Обоснование**: решает OQ-75. Выбрано ручное назначение (рекомендация оркестратора), а не самозаявка: до появления преподавателей-пользователей роль получают только люди, с которыми владелец платформы договорился лично; это закрывает риск массового создания курсов с недопустимым контентом без очереди модерации, которой нет в BRD; при росте числа заявок добавляется экран заявок в ADM-01.
- **Проверка**: тесты ADM-01 (`grant` роли `teacher` администратором → у пользователя появляются права `teacher`, запись аудита); тест VIS-04 (схема регистрации без поля роли, `roles == ["learner"]`); отрицательный тест: `learner` вызывает `identity:roles:grant` → 403.
- **Применимость**: backend, frontend, tests.

### 3.4. Санкции

### SYS-06-R12 Набор санкций

- **Формулировка**: Администратор платформы должен располагать ровно тремя санкциями, хранящимися в `identity.sanctions` (`id`, `user_id`, `kind`, `starts_at`, `until` (null — бессрочно), `capabilities` (для `restriction`), `reason` (обязателен), `imposed_by`, `lifted_at`, `lifted_by`, `lift_reason`):
  - `suspension` — отключение аккаунта: вход и любые аутентифицированные запросы запрещены до `until` или до снятия; по истечении `until` снимается автоматически;
  - `restriction` — ограничение: вход и обучение разрешены, отключены возможности из перечня `capabilities` на срок или бессрочно; перечень возможностей: `social_posting` (`social:posts:*`, `social:comments:*`, `social:groups:create`), `messaging` (`messaging:conversations:create`, `messaging:messages:send`), `course_publishing` (`courses:courses:publish`, `courses:invitations:create`, `classroom:classrooms:create`), `plugin_publishing` (`plugins:plugins:publish`), `teacher_contacts` (`messaging:conversations:create` преподавателем к ученикам);
  - `teacher_ban` — бан преподавателя: отзыв роли `teacher` с `revoke_reason = ban` и запретом повторного назначения без снятия бана; права `learner` сохраняются; последствия для курсов и классов — R14.
  Блокировка пользователя учеником (`user_block`, STU-35.7) санкцией не является и принадлежит `social`.
- **Обоснование**: решает OQ-54: BRD называет санкции по-разному (ADM-01 «временное отключение», ADM-02 «бан преподавателей», ADM-05 «ограничение нарушителей»); две меры к аккаунту плюс мера к роли покрывают все три случая без размножения сущностей; `suspension` без `until` заменяет понятие «бессрочная блокировка».
- **Проверка**: тесты ADM-01, ADM-02, ADM-05 (критерии приёмки на каждую санкцию, срок, снятие, обязательную причину); контрактный тест: перечисление `kind` в OpenAPI `identity` — ровно три значения.
- **Применимость**: backend, tests.

### SYS-06-R13 Действие отключения и ограничения

- **Формулировка**: Наложение `suspension` должно немедленно отзывать все сессии пользователя (`identity:revoked_user`, событие `session_revoked`, закрытие WebSocket кодом `4401` на всех инстансах), запрещать вход (`403 identity.user_suspended` с `until`) и обновление токенов, останавливать доставку уведомлений и публикацию запланированных действий пользователя; наложение `restriction` должно вступать в силу при следующей проверке прав на любом инстансе не позже чем через 600 с без перевыпуска токена (через `identity:revoked_user` клиент обновляет токен, и грант пересчитывается); при недоступном Redis действует правило fail-open ADR-006 с окном ≤ 600 с; снятие санкции и истечение `until` восстанавливают права без действий пользователя, кроме повторного входа после `suspension`.
- **Обоснование**: ADR-006, разделы 3.1, 3.7 (`revoked_user`, `4401`, fail-open подтверждён пользователем); CLAUDE.md: корректность не зависит от инстанса.
- **Проверка**: тест на N инстансах `tests/n_instances/identity/test_sanctions_take_effect.py` (`<будет создан>`): `suspend` на инстансе A → запрос с валидным токеном на инстанс B → 401, WebSocket на инстансе C закрыт `4401`; `restrict social_posting` → `social:posts:create` на другом инстансе → 403 `restricted`; истечение `until` с подменой `Clock` → права восстановлены.
- **Применимость**: backend, tests.

### SYS-06-R14 Бан преподавателя и его последствия

- **Формулировка**: `teacher_ban` должен: отзывать роль `teacher` (событие `flt.identity.role_revoked.v1` с `reason = ban`); по этому событию `courses` снимает с публикации и переводит в архив все курсы преподавателя, сохраняя записи учеников, их программы и прогресс, и отправляет записанным ученикам уведомление (команда в `notifications`, этап 5; на этапе 3 — письмо через SMTP-клиент с исключением в разделе 6 SYS-01); `classroom` архивирует классы преподавателя и отменяет будущие групповые занятия с уведомлением участников (этап 6); материалы курсов остаются у преподавателя как собственные; при снятии бана роль возвращается, курсы остаются в архиве и публикуются преподавателем повторно; бан не запрещает вход и обучение, если одновременно не наложено `suspension`.
- **Обоснование**: решает OQ-55 (принцип; детали судьбы курсов — ТЗ ADM-02 и дополнение этапа 6): BRD ADM-02 «отключение и бан преподавателей» относится к управлению курсами, то есть к роли, а не к аккаунту; TCH-01 (преподаватель — тоже ученик) делает лишение учебного доступа несоразмерным; при необходимости администратор дополнительно накладывает `suspension`.
- **Проверка**: тесты ADM-02 (бан → курсы в архиве на другом инстансе после обработки события, записи сохранены, уведомление отправлено, роль отсутствует в `GET /me`, `identity:roles:grant teacher` без снятия бана → 409 `teacher_banned`); регрессия ADM-02 после TCH-02 (SDD_plan.md, этап 6).
- **Применимость**: backend, tests.

### SYS-06-R15 Администратор не читает учебный и личный контент

- **Формулировка**: Роль `platform_admin` не должна иметь прав на чтение реплик занятий, собственных материалов, словарных запросов, наборов слов, программ и прогресса конкретного ученика, личных переписок и содержимого привязок провайдеров; исключения — объект, на который подана жалоба (ADM-05: запись, комментарий, страница, группа, одно сообщение), и агрегаты без содержимого (расход токенов, число занятий); доступ к объекту по жалобе ограничен контекстом жалобы и записывается в журнал аудита.
- **Обоснование**: 152-ФЗ (минимизация доступа, SYS-02); BRD не содержит кейсов администратора по просмотру учебных данных; разделение ролей R1.
- **Проверка**: параметризованный тест R19: столбец `platform_admin` для перечисленных ресурсов — `—` или `any (по жалобе)`; тест ADM-05: чтение сообщения вне жалобы → 403.
- **Применимость**: backend, tests.

### SYS-06-R16 Защита от самоблокировки администратора

- **Формулировка**: Администратор платформы не должен иметь возможности снять с себя роль `platform_admin`, наложить на себя санкцию или удалить свой аккаунт, если он — единственный активный администратор; первый администратор создаётся командой CLI `python -m app identity create-user --role platform_admin` на стенде, а не через интерфейс.
- **Обоснование**: иначе платформа может остаться без администратора; ADR-006, 3.9 (CLI `create-user`).
- **Проверка**: тесты ADM-01 (`409 last_admin` на самоснятие роли и самоотключение); тест CLI.
- **Применимость**: backend, tests.

### 3.5. Неинтерактивные участники

### SYS-06-R17 Права локального агента

- **Формулировка**: Токен агента `flta_…` должен давать право только открыть `/ws/agent` и обмениваться сообщениями белого списка ADR-008 от имени модуля `local_runtime` в контексте пользователя, к которому агент привязан; агент не должен получать доступа к REST API, к `/ws` и к данным других модулей; все действия платформы, инициированные через агент (стрим локальной модели, скачивание модели), выполняются по правам пользователя-владельца агента, проверенным на момент запроса пользователя, а не агента; отозванный агент получает код закрытия `4401`.
- **Обоснование**: ADR-006, 3.4; ADR-008, 3.6, 3.8.
- **Проверка**: тест shared kernel `test_agent_token_rejected_on_rest_and_ws`; тесты `local_runtime` (ТЗ STU-05): соединение с отозванным токеном → `4401`; запрос пользователя без права `local_runtime:engines:manage` (например, без доступа к обучению) не доходит до агента.
- **Применимость**: backend, local agent, tests.

### SYS-06-R18 Права внутренних процессов и сервисных вызовов

- **Формулировка**: Роли монолита `worker`, `migrate`, `media_agent`, relay outbox, планировщик и консьюмеры Kafka должны выполнять действия без пользовательского контекста через внутренние сервисы модулей (не через REST и не через `auth_user`), а права пользователя, от имени которого выполняется фоновое задание, проверяются при создании задания; роль `media_agent` входит в комнату LiveKit с идентичностью `tutor:<lesson_id>` по ключу API LiveKit и обращается к `llm_gateway` и `speech` в процессе с учётными данными, определёнными спецификацией `classroom` (OQ-67); webhooks LiveKit, `/v1/*`, `/asyncapi/kafka`, метрики принимаются только из внутренней сети (ACL HAProxy) и не используют пользовательские права.
- **Обоснование**: ADR-004 (роли, задания), ADR-015 (3.3, 3.4, 3.7), ADR-012 (служебные пути закрыты снаружи).
- **Проверка**: архитектурный тест `test_internal_routes_not_under_api_prefix` (служебные пути вне `/api`); smoke-тест ADR-012 (`/v1/ready`, `/livekit/twirp/*`, webhook снаружи недостижимы); тест заданий «задание, созданное пользователем без права, не создаётся» (SYS-04).
- **Применимость**: backend, deploy, tests.

### 3.6. Тестирование и изменение прав

### SYS-06-R19 Тесты прав обязательны для каждого критерия приёмки

- **Формулировка**: Для каждого критерия приёмки ТЗ, затрагивающего защищённое действие, должны существовать: тест положительного пути для каждой роли с разрешением; отрицательный тест для каждой роли и анонима с запретом (`401`/`403`, ожидаемый код ошибки); для областей `own`/`rel` — тест чужого объекта и тест выборки; для прав с `L` — тест без подтверждений; кроме того, shared kernel предоставляет параметризованный тест `tests/security/test_permission_matrix.py`, который по матрице раздела 3.3 для каждого эндпоинта модуля текущего этапа и каждой роли проверяет код ответа (`401`, `403` или не `401/403`) на минимальном валидном запросе.
- **Обоснование**: шаблон ТЗ, раздел 3 («AC обязаны покрывать ошибки прав доступа — каждая роль, которой действие запрещено») и раздел 7.1; критерий выхода этапа 3 («права проверяются на сервере и покрыты тестами»).
- **Проверка**: G2 (ревью красных тестов); job `docs`: матрица трассировки показывает для каждого AC с правами наличие тестов с суффиксом `-forbidden` (`flt-tools traceability check`, правило `<будет добавлено>`); параметризованный тест в job `backend-tests`.
- **Применимость**: backend, frontend, tests, CI.

### SYS-06-R20 Фикстуры ролей

- **Формулировка**: Тестовая инфраструктура должна предоставлять фикстуры `anonymous_client`, `learner_client`, `teacher_client`, `admin_client`, `unconfirmed_learner_client` (без email и 18+), `restricted_learner_client(capabilities)` и `suspended_learner_client`, выпускающие токены через `TokenIssuer` с одноразовой парой ключей тестовой сессии; E2E — те же пользователи, создаваемые `cli create-user` на стенде из N инстансов.
- **Обоснование**: единообразие тестов R19; ADR-006, 3.3 и 3.9 (фикстура ключей, CLI).
- **Проверка**: наличие фикстур в `tests/conftest.py` shared kernel и `src/frontend/e2e/fixtures/auth.ts` (SYS-10); используются в тесте R19.
- **Применимость**: tests.

### SYS-06-R21 Изменение прав — только через эту спецификацию

- **Формулировка**: Добавление права, изменение области или столбца роли, новый вид санкции или возможность ограничения должны вноситься `changed`-версией SYS-06 (строка матрицы с этапом и пунктом BRD) до правки `permissions.py` и `permissions_matrix.py`; ТЗ вправе сузить область (например, `any` → `rel`) только с одновременной правкой матрицы в той же версии.
- **Обоснование**: CLAUDE.md «Источник истины»: спецификация — главный артефакт; матрица — главный артефакт этой спецификации.
- **Проверка**: `flt-tools permissions check` (R3) падает при расхождении; ревью на G1.
- **Применимость**: backend, CI.

## 4. Влияние на модули и на шаблон ТЗ

### 4.1. Модули

| Модуль | Что меняется |
|---|---|
| все | `permissions.py` с кодами из матрицы своего модуля; каждый роут и WebSocket-обработчик — с зависимостью прав (R5); объектные проверки через `Grant.ensure` (R6); раздел 9 `_module.md` — выдержка матрицы; тесты R19 |
| `identity` | `permissions_matrix.py` (R3); `RolePermissionsProvider.grants_for` с учётом подтверждений и ограничений (R4, R7); таблица `sanctions`, эндпоинты санкций и ролей, события `user_suspended`, `user_restricted`, `role_revoked` (R12–R14); защита последнего администратора (R16); `GET /me` возвращает `permissions` |
| shared kernel | `auth_user`, `auth_user_optional`, маркер `public`, `Grant`, `Permission`; проверка `L`; тест `test_permission_matrix`; фикстуры ролей (R20) |
| `courses`, `classroom` | консьюмеры `role_revoked` (архив при бане, R14); `is_learner_of_teacher` (SYS-01-R17) |
| `audit` | приём записей обо всех административных действиях (SYS-02-R50), включая просмотр журнала и доступ по жалобе |
| `local_runtime` | проверка токена агента на `/ws/agent`, отклонение везде ещё (R17) |
| `social`, `messaging` | исключение «доступ администратора по жалобе» с записью в аудит (R15) |
| app shell | `permissions` из `GET /me` для отображения; обработка `401`/`403` по кодам (R9) |

### 4.2. Шаблон ТЗ

| Раздел шаблона ТЗ | Что добавить или проверять |
|---|---|
| 3. Критерии приёмки | На каждое защищённое действие — AC запрета для каждой роли без права и для анонима; для `own`/`rel` — AC чужого объекта; для `L` — AC без подтверждений (R19) |
| 7.1. Матрица прав | Строки — коды прав `module:resource:action` из раздела 3.3 SYS-06 с областями; новая строка возможна только после `changed`-версии SYS-06 (R21); указать, какие действия пишутся в журнал аудита |
| 13. План тестов | Ссылка на параметризованный тест матрицы и перечень тестов `-forbidden` |

## 5. Примеры

### Пример 1. Объявление прав модуля и роута (SYS-06-R2, R5)

```python
# app/modules/learning_plan/permissions.py
class LearningPlanPermissions:
    PLANS_READ = "learning_plan:plans:read"
    PLANS_CREATE = "learning_plan:plans:create"
    PLANS_ADJUST = "learning_plan:plans:adjust"

# app/modules/learning_plan/api/plan_controller.py
@router.get("/plans/{plan_id}")
async def get_plan(plan_id: UUID,
                   grant: Annotated[Grant, auth_user(LearningPlanPermissions.PLANS_READ)],
                   service: PlanServiceDep) -> PlanResponse:
    """Возвращает программу; область own или rel проверяет сервис."""
    return await service.get_plan(grant, plan_id)
```

Неправильно: роут без `auth_user` и без `public=True` — `test_every_route_declares_access` падает; код `LEARNING_PLAN_GET_PLAN` — не проходит `test_permission_codes_format`.

### Пример 2. Объектная проверка с областью `rel` (SYS-06-R6)

```python
async def get_plan(self, grant: Grant, plan_id: UUID) -> PlanResponse:
    plan = await self._dao.get(plan_id)
    if plan is None:
        raise NotFoundError("plan_not_found")
    await grant.ensure(
        owner_id=plan.user_id,
        relation=lambda: self._is_teacher_of(grant.user_id, plan.user_id),  # courses + classroom (SYS-01-R17)
    )   # own: owner_id == user_id; rel: own или relation(); any: всегда; иначе ForbiddenError
    return PlanResponse.model_validate(plan)
```

### Пример 3. Фрагмент `permissions_matrix.py` (SYS-06-R3)

```python
MATRIX: dict[str, dict[Role, Scope]] = {
    "learning_plan:plans:read":   {Role.LEARNER: Scope.OWN, Role.TEACHER: Scope.REL},
    "learning_plan:plans:adjust": {Role.TEACHER: Scope.REL},
    "identity:users:suspend":     {Role.PLATFORM_ADMIN: Scope.ANY},
    "cms:pages:read":             {Role.ANONYMOUS: Scope.ANY, Role.LEARNER: Scope.ANY, Role.PLATFORM_ADMIN: Scope.ANY},
}
LEARNING_GATED: frozenset[str] = frozenset({"learning_plan:plans:read", "learning_plan:plans:adjust"})
RESTRICTABLE: dict[str, frozenset[str]] = {
    "social_posting": frozenset({"social:posts:create", "social:comments:create", "social:groups:create"}),
}
```

`teacher` получает строки `learner` автоматически при экспорте (R1); `flt-tools permissions check` сравнивает экспорт с таблицами раздела 3.3.

### Пример 4. Параметризованный тест матрицы (SYS-06-R19)

```python
@pytest.mark.req("SYS-06-R19")
@pytest.mark.parametrize(("route", "role", "expected"), matrix_cases(stage=CURRENT_STAGE))
async def test_permission_matrix(route, role, expected, clients):
    resp = await clients[role].request(route.method, route.sample_path, json=route.sample_body)
    if expected == "denied":
        assert resp.status_code in (401, 403), f"{role} must not access {route}"
    else:
        assert resp.status_code not in (401, 403)
```

### Пример 5. Санкция и её немедленное действие (SYS-06-R12, R13)

`POST /api/v1/identity/users/{user_id}/sanctions {kind: "suspension", until: "2026-11-10T00:00:00Z", reason: "spam"}` → `201`; в той же транзакции: строка `identity.sanctions`, `users.status = suspended`, отзыв семейств refresh-токенов, ключ `identity:revoked_user:<user_id>`, события `user_suspended` и `session_revoked` в outbox, команда `audit.record` с `action = identity:users:suspend`. Запрос пользователя с ещё не истёкшим токеном на любом инстансе → `401 session_revoked`; попытка входа → `403 user_suspended {"until": "2026-11-10T00:00:00Z"}`.

Неправильно: `kind: "ban"` для аккаунта — такого вида нет (R12); бан преподавателя — `POST /api/v1/identity/users/{user_id}/sanctions {kind: "teacher_ban", reason: "..."}`.

## 6. Исключения и как их согласовать

Порядок: вопрос в `Analytics/open-questions.md` → решение человека → строка ниже → allowlist в архитектурном тесте или строка матрицы с пометкой. Право, выданное роли вне матрицы, или роут без объявления доступа — нарушение.

| Требование | Где | Обоснование | Срок действия | Кто согласовал и когда |
|---|---|---|---|---|
| SYS-06-R15 | `messaging:messages:read`, `social:posts:read` для `platform_admin` в контексте жалобы | ADM-05 требует рассмотреть объект жалобы; доступ ограничен объектом жалобы и пишется в аудит | бессрочно | — (утверждается с документом) |
| SYS-06-R5 | `GET /v1/health`, `/v1/ready`, `/v1/metrics`, `/asyncapi/kafka`, webhook LiveKit | служебные пути вне `/api`, закрыты ACL HAProxy (ADR-012), пользовательских прав не имеют (R18) | бессрочно | — (ADR-012 accepted 2026-10-10) |

## 7. Вне рамок

- Выпуск и проверка токенов, cookie, CSRF, OAuth — ADR-006 (здесь — только вывод прав из ролей).
- Формулировки согласий и правила 152-ФЗ — SYS-02 (здесь — условие `L`).
- Состав журнала аудита — SYS-02-R50 (здесь — какие действия административные).
- Права плагинов в песочнице (`plugin_permissions`) — SYS-13.
- Чьи учётные данные использует роль `media_agent` для LLM и речи (OQ-67) — спецификация `classroom`.
- Приоритет настроек аватара преподавателя и ученика (OQ-47) — ТЗ TCH-04 (матрица допускает обе области, порядок применения — в ТЗ).
- Видимость закрытых групп (OQ-53), механики друзей и подписок (OQ-52) — ТЗ STU-35.x (матрица задаёт максимальную область).
- Последствия бана для конкретных состояний курсов и классов — ТЗ ADM-02 и дополнение этапа 6 (здесь — принцип R14).

## 8. Связанные ADR

| ADR | Связь | Что берётся |
|---|---|---|
| [ADR-002](../../ADR/ADR-002-module-layout.md) | уточняет | `permissions.py` модуля и `ModuleDefinition.permissions`; формат кода уточнён до `module:resource:action` (первый сегмент — префикс модуля) |
| [ADR-004](../../ADR/ADR-004-communication-patterns.md) | основан на | `can_subscribe`, команды и задания от имени пользователя, роли монолита |
| [ADR-006](../../ADR/ADR-006-authentication-and-authorization.md) | основан на | роли, claims `roles`, `email_verified`, `age_confirmed`; `RolePermissionsProvider`; `revoked_user`; код `4401`; fail-open без Redis |
| [ADR-008](../../ADR/ADR-008-local-agent.md) | основан на | токен агента только для `/ws/agent`, белый список сообщений |
| [ADR-012](../../ADR/ADR-012-haproxy-entry-point.md) | основан на | служебные и внутренние пути закрыты снаружи |
| [ADR-015](../../ADR/ADR-015-media-server.md) | основан на | права в токене медиасервера, роль `media_agent`, webhooks из внутренней сети |

## 9. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-14](../../open-questions.md) | Доступ к обучению после подтверждений | нет | resolved: признак `L` и R7 |
| [OQ-54](../../open-questions.md) | Набор санкций | нет | planned → SYS-06: решено здесь — `suspension`, `restriction`, `teacher_ban` (R12) |
| [OQ-55](../../open-questions.md) | Природа бана преподавателя | нет | planned → SYS-06 и ТЗ ADM-02: принцип решён здесь — отзыв роли с последствиями для курсов и классов (R14); детали — ТЗ ADM-02 |
| [OQ-75](../../open-questions.md) | Источник роли `teacher` | нет | planned → SYS-06: решено здесь — назначает администратор платформы вручную (R11) |
| [OQ-77](../../open-questions.md) | Анонимная сессия быстрого теста (`flt_anon_session`) — субъект области `own (сессия)` | нет | open: рабочее решение принято (R10) |
| [OQ-67](../../open-questions.md) | Учётные данные AI-преподавателя в групповом занятии | нет | planned → спецификация `classroom` |
| [OQ-47](../../open-questions.md) | Приоритет настроек аватара | нет | planned → ТЗ TCH-04 |
| [OQ-52](../../open-questions.md), [OQ-53](../../open-questions.md) | Друзья и подписки; видимость закрытых групп | нет | planned → ТЗ STU-35.3, STU-35.4 |

## 10. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | draft |
| 0.2 | 2026-10-11 | Claude | Согласование SYS-01…SYS-12: R2 — закрытый перечень действий дополнен всеми действиями матрицы (`PERMISSION_ACTIONS`), проверка формата без многоточия, обоснование — ADR-002 v1.1; R10 — анонимная сессия `flt_anon_session` (OQ-77), код ошибки `core.unauthenticated`; R13 — путь теста N3 `tests/n_instances/identity/`; раздел 9 — OQ-77; коды ошибок в формате `<module>.<error_name>` (SYS-03-R7) | draft |
| 1.0 | 2026-10-11 | пользователь | Утверждена на гейте G1 блока Б этапа 1 без изменений (PR #3) | approved |
