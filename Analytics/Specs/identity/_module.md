# identity — Пользователи, аутентификация и права

| Поле | Значение |
|---|---|
| Статус | review |
| Версия | 0.1 |
| Дата | 2026-10-11 |
| Автор | Claude (черновик) |
| Утвердил | |
| Пункт(ы) BRD | VIS-04, VIS-05, ADM-01, ADM-02, ADM-05 (санкции), STU-06 (язык интерфейса), STU-35.1 (фото профиля) |
| Модуль | identity |
| Зависимости | shared kernel; `audit` (с этапа 3, команда записи) |
| Связанные ADR/SYS | ADR-002, ADR-003, ADR-004, ADR-006, ADR-013; SYS-01, SYS-02, SYS-03, SYS-04, SYS-05, SYS-06, SYS-07, SYS-10, SYS-11 |

## 1. Назначение и границы

- **Отвечает за**: учётные записи и вход (SYS-01, таблица 3.1): пользователь (`user`), учётные данные (пароль argon2id), внешние аккаунты OAuth (Google, Яндекс ID, VK ID), роли (`learner`, `teacher`, `platform_admin`) и их назначение, матрицу «роль → права» (`RolePermissionsProvider`, SYS-06), согласия 152-ФЗ и 18+ (`consent`), сессии (семейства refresh-токенов), выпуск токенов (`TokenIssuer`), санкции (отключение аккаунта `suspension`, ограничение нарушителя `restriction`, бан преподавателя `teacher_ban` — SYS-06-R12), атрибуты пользователя `display_name`, `ui_language`, `timezone`, фото профиля, транзакционные письма подтверждения email и восстановления пароля, удаление аккаунта и событие `user_deleted`.
- **Появляется на этапе**: 1 (базовая часть, ADR-006, раздел 3.9); дополняется на этапах 2 (регистрация, OAuth, сессии, согласия), 3 (администрирование, санкции, удаление и выгрузка данных), 6 (фото профиля).
- **Объём этапа 1 (Г.5)**: таблицы `users`, `credentials`, `roles`, `user_roles`, `consents`, `refresh_tokens`, `one_time_tokens`; `TokenIssuer`, cookie и Bearer, CSRF, эндпоинты `login`, `refresh`, `logout`, `me`, `jwks.json`; лимит попыток входа; отключение аккаунта через `users.status`; события `user_registered`, `user_suspended`, `session_revoked`; `RolePermissionsProvider` с матрицей SYS-06 для прав этапа 1; CLI `issue-token` и `create-user`; тесты на N инстансах: вход на A, запрос на B, refresh на C, отзыв всех сессий на A закрывает WebSocket на B.
- **Не отвечает за**:
  - проверку токена на каждом запросе и механизм прав — это shared kernel (`TokenVerifier`, `auth_user`, ADR-006, раздел 3.8);
  - настройки обучения, изучаемые языки и уровни — это модуль `learner_profile`;
  - журнал действий администраторов — это модуль `audit` (`identity` отправляет команду записи);
  - уведомления, кроме транзакционных писем входа и подтверждения — это модуль `notifications` (SYS-01-R13);
  - страницу ученика и блокировку пользователя учеником (`user_block`) — это модуль `social`;
  - токены локального агента и сопряжение — это модуль `local_runtime` (ADR-008);
  - анонимную сессию быстрого теста `flt_anon_session` — это модуль `assessment` (OQ-77).

## 2. Пункты BRD и ТЗ модуля

| ID | Пункт BRD | ТЗ | Этап | Статус ТЗ |
|---|---|---|---|---|
| — | Каркас: вход тестовым пользователем, токены, права | нет ТЗ фичи: объём — SDD_plan.md, этап 1, Г.5; требования — ADR-006, SYS-06 | 1 | не начато |
| VIS-04 | Регистрация (email и пароль, OAuth, согласия 18+ и ПД) | VIS-04-registration.md (имя уточняется в ТЗ этапа 2) | 2 | не начато |
| VIS-05 | Вход, выход, восстановление пароля, сессии | VIS-05-login.md (имя уточняется в ТЗ этапа 2) | 2 | не начато |
| ADM-01 | Управление пользователями: поиск, карточка, роли, отключение аккаунта | ADM-01-users.md (этап 3) | 3 | не начато |
| ADM-02 | Бан преподавателя (часть `identity`: отзыв роли) | ADM-02 в модуле `courses` (этап 3) | 3 | не начато |
| ADM-05 | Ограничение нарушителя (часть `identity`: санкция `restriction`) | ADM-05 в модуле `social` (этап 7) | 7 | не начато |
| STU-06 | Язык интерфейса (хранение `ui_language`) | ТЗ в модуле `learner_profile` или app shell (этап 4) | 4 | не начато |
| STU-35.1 | Страница ученика (фото профиля) | ТЗ в модуле `social` (этап 7); хранение фото — `identity` | 6, 7 | не начато |
| — | Удаление аккаунта и выгрузка данных (SYS-02-R35–R37) | нужен пункт BRD (OQ-78), этап 3 | 3 | не начато |

## 3. Публичный API

Подпакет `app/modules/identity/public/`. Другие модули импортируют только его (ADR-002).

### 3.1. Сервисные интерфейсы

| Интерфейс | Метод | Назначение | Кто вызывает |
|---|---|---|---|
| `IdentityService` | `async get_user(user_id: UUID) -> UserPublic \| None` | атрибуты пользователя для других модулей (без email и учётных данных) | `local_runtime`, `courses`, `classroom`, `messaging`, `social`, `notifications` |
| `IdentityService` | `async get_users(user_ids: Sequence[UUID]) -> dict[UUID, UserPublic]` | пакетное чтение (до 200 идентификаторов) для списков | `courses`, `classroom`, `messaging`, `social` |
| `IdentityService` | `async get_contact(user_id: UUID) -> UserContact \| None` | email, `ui_language`, `timezone`, статус — только для доставки писем | `notifications` (этап 5) |
| `IdentityService` | `async has_consent(user_id: UUID, kind: ConsentKind) -> bool` | проверка действующего согласия (`foreign_llm_transfer`, `voice_recording`, `lesson_recording`) | `llm_gateway` (SYS-08-R10), `speech`, `classroom` |
| `IdentityService` | `async has_role(user_id: UUID, role: RoleCode) -> bool` | проверка роли вне HTTP-запроса (консьюмеры, планировщик) | `courses`, `classroom` |
| `RolePermissionsProvider` (интерфейс ядра) | `grants_for(roles: Sequence[str], flags: UserFlags) -> frozenset[Grant]` | права из ролей с учётом признака `L` и активных ограничений (SYS-06-R4, R7, R13) | shared kernel (`auth_user`); регистрируется в `ModuleDefinition.role_permissions_provider` |
| `TokenIssuer` (внутренний, не в `public/`) | `issue(user, client, family_id) -> TokenPair` | выпуск access JWT EdDSA и refresh-токена (ADR-006, раздел 3.2) | только `identity`, CLI `issue-token`, фикстура тестов `as_role` (SYS-10) |

### 3.2. Pydantic-схемы

| Схема | Назначение | Кто использует |
|---|---|---|
| `UserPublic` | `id`, `display_name`, `ui_language`, `timezone`, `status`, `roles`, `profile_picture_file_id` | модули из 3.1 |
| `UserContact` | `user_id`, `email`, `email_verified`, `ui_language`, `timezone`, `status` | `notifications` |
| `ConsentKind` | перечисление `personal_data`, `age_18plus`, `foreign_llm_transfer`, `voice_recording`, `lesson_recording` (SYS-02-R33) | `llm_gateway`, `speech`, `classroom` |
| `RoleCode` | перечисление `learner`, `teacher`, `platform_admin` (SYS-06-R1) | все модули с правами |
| `UserStatus` | перечисление `active`, `suspended`, `deleted` (SYS-06-R12; OQ-83) | модули из 3.1 |
| `IdentityErrorCode` | коды ошибок `identity.*` (раздел 7.1) | frontend через контракт, тесты |

### 3.3. События

Публикуемые события — раздел 6.1; схемы событий — `public/events.py`, декларации топиков — `public/topics.py` (SYS-04-R21).

## 4. Зависимости

### 4.1. От каких модулей зависит

| Модуль | Что используется | Способ | Зачем |
|---|---|---|---|
| shared kernel | `TokenVerifier`, `auth_user`, `ModuleRedis`, `OutboxPublisher`, `MailClient`, `CaptchaProvider`, `WsPublisher`, `Clock`, `new_id()` | вызов в процессе | инфраструктура (раздел 3.1 спецификации ядра) |
| `audit` (с этапа 3) | команда `flt.audit.jobs.record.v1` | команда через outbox `identity` | запись административных действий (SYS-01-R14, SYS-02-R50) |

### 4.2. Кто зависит от модуля

| Модуль | Что использует | Способ |
|---|---|---|
| shared kernel | `RolePermissionsProvider` | регистрация в `ModuleDefinition`, вызов в процессе |
| `llm_gateway` | `IdentityService.has_consent`; события `consent_revoked`, `user_deleted` | вызов в процессе; подписка на топики |
| `local_runtime` | `IdentityService.get_user`; событие `user_deleted` | вызов в процессе; подписка |
| `notifications` | `IdentityService.get_contact`; события `user_deleted`, `user_suspended` | вызов в процессе; подписка |
| `learner_profile` | событие `user_registered` (создание профиля), `user_deleted` | подписка |
| `courses`, `classroom` | `IdentityService.get_users`, `has_role`; события `role_revoked`, `user_deleted` | вызов в процессе; подписка |
| все модули с данными пользователя | событие `user_deleted` (каскад удаления, SYS-02-R35) | подписка |

## 5. Владение данными

### 5.1. PostgreSQL

- Схема: `identity`.
- Миграции Alembic: `app/modules/identity/migrations/`, секция `[identity]` в `alembic.ini`, таблица версий `identity.alembic_version` (ADR-002).
- Все таблицы — `EntityBase` (`id` UUID v7, `created_at`, `updated_at`, `version`), кроме связующих; физическое удаление (soft delete не используется, SYS-02-R36).

| Таблица | Назначение | Описана в ТЗ |
|---|---|---|
| `identity.users` | `email citext unique null`, `email_verified_at`, `display_name`, `status` (`active`, `suspended`, `deleted`), `ui_language` (`ru`, `en`, `ar`), `timezone` (IANA), `profile_picture_file_id` (этап 6) | ADR-006, раздел 3.1; SYS-06-R12; SYS-07; этап 1 Г.5 |
| `identity.credentials` | `password_hash` (argon2id), `password_updated_at`, `failed_attempts`, `locked_until` | ADR-006; этап 1 Г.5 |
| `identity.external_accounts` | привязки OAuth `unique(provider, subject)` | ADR-006, раздел 3.6; ТЗ VIS-04, VIS-05 |
| `identity.roles`, `identity.user_roles` | коды ролей и назначения (`granted_at`, `granted_by`, `revoked_at`, `revoke_reason`) | ADR-006; SYS-06-R1, R11; этап 1 Г.5 |
| `identity.consents` | согласия `kind`, `version`, `granted_at`, `revoked_at`, `ip_hash`, `user_agent`; `unique(user_id, kind) where revoked_at is null` | ADR-006; SYS-02-R32, R33, R39; этап 1 Г.5 |
| `identity.refresh_tokens` | семейства и ротация refresh-токенов (`family_id` = `sid`), `token_hash`, `client_type`, `revoke_reason` | ADR-006, раздел 3.2; этап 1 Г.5 |
| `identity.one_time_tokens` | токены `email_verify`, `password_reset`, `email_change` | ADR-006; этап 1 Г.5 (таблица), ТЗ VIS-04, VIS-05 (использование) |
| `identity.sanctions` | санкции `kind`, `starts_at`, `until`, `capabilities`, `reason`, `imposed_by`, `lifted_at`, `lifted_by`, `lift_reason` | SYS-06-R12; ТЗ ADM-01 (этап 3) |
| `identity.deletion_requests` (имя уточняется в ТЗ этапа 3) | запрос удаления аккаунта с отсрочкой 7 дней | SYS-02-R35; ТЗ этапа 3 (OQ-78) |
| `identity.outbox`, `identity.processed_events`, `identity.jobs` | шаблоны ядра (раздел 5.1 спецификации ядра) | SYS-04-R24, R26, R29 |

Хранение: отозванные и истёкшие refresh-токены удаляются через 90 дней, одноразовые — через 30 дней задачей `identity.purge_tokens` (SYS-02-R48); согласия хранятся 3 года после удаления аккаунта (SYS-02, таблица категорий ПД).

### 5.2. Redis

Префикс ключей: `identity:` (через `ModuleRedis(prefix="identity")`).

| Шаблон ключа | Назначение | TTL | Описан в ТЗ |
|---|---|---|---|
| `identity:revoked_sid:<sid>` | сессия отозвана: access-токены с этим `sid` отклоняются | 600 с | ADR-006, раздел 3.1 |
| `identity:revoked_user:<user_id>` | отзыв всех токенов пользователя, выпущенных раньше значения | 600 с | ADR-006; SYS-06-R13 |
| `identity:login_fail:<sha256(email)>` | счётчик неудачных входов по email (лимит 10 за 15 минут) | 900 с | ADR-006; этап 1 Г.5 |
| `identity:login_fail_ip:<ip>` | счётчик неудачных входов по IP (лимит 50 за 15 минут) | 900 с | ADR-006; этап 1 Г.5 |
| `identity:oauth:<state>` | состояние OAuth-перехода | 600 с | ADR-006, раздел 3.6; ТЗ VIS-04 |
| `identity:session:<sid>` | кэш активности сессии | 24 ч с продлением | ADR-006; ТЗ VIS-05 |

Поведение без Redis (ADR-003, раздел 3, п. 8; ADR-006, раздел 3.7): проверка отзыва — fail-open с метрикой и алертом; лимит попыток входа — fail-open; OAuth — достаточно подписанной cookie `flt_oauth`; вход и refresh работают по PostgreSQL.

### 5.3. MinIO

| Бакет | Схема ключа объекта | Таблица метаданных |
|---|---|---|
| `flt-identity` (этап 6) | `u/<user_id>/avatar/<file_id>.<ext>` | `identity.users.profile_picture_file_id` и таблица файлов модуля с `StoredFileMixin` (имя уточняется в ТЗ этапа 6) |

### 5.4. OpenSearch

Не применимо: поиск пользователей администратором (ADM-01) выполняется по PostgreSQL (`citext`, `pg_trgm`); поиск учеников по страницам — модуль `social` (ADR-014).

### 5.5. Qdrant

Не применимо: модуль не использует Qdrant.

## 6. События Kafka

Контракт: `api/asyncapi.yaml` (создаётся на шаге 4 конвейера для этапа 1 Г.5; общие схемы — `Analytics/Specs/_system/asyncapi-common.yaml`).

### 6.1. Публикуемые топики

Все события публикуются через outbox в транзакции с изменением данных; ключ сообщения — `aggregate_id` = `user_id`; `visibility = "public"`, payload без ПД сверх идентификаторов (SYS-04-R21, SYS-09-R12).

| Топик | Событие | Схема | Версия | Когда публикуется | Outbox |
|---|---|---|---|---|---|
| `flt.identity.user_registered.v1` | пользователь создан | `UserRegistered` (`user_id`, `ui_language`, `roles`) | 1 | регистрация, первый вход OAuth, CLI `create-user` (этап 1) | да |
| `flt.identity.user_email_verified.v1` | email подтверждён | `UserEmailVerified` | 1 | этап 2 | да |
| `flt.identity.user_updated.v1` | изменены `display_name`, `ui_language`, `timezone`, фото | `UserUpdated` (`user_id`, `changed_fields`) | 1 | этапы 2, 4, 6 | да |
| `flt.identity.user_suspended.v1` | аккаунт отключён | `UserSuspended` (`user_id`, `until`) | 1 | этап 1 (через `status`, CLI), этап 3 (санкция) | да |
| `flt.identity.user_unsuspended.v1` | отключение снято | `UserUnsuspended` | 1 | этап 3 | да |
| `flt.identity.user_restricted.v1`, `flt.identity.user_restriction_lifted.v1` | наложено или снято ограничение | `UserRestricted`, `UserRestrictionLifted` (`user_id`, `capabilities`, `until`) | 1 | этап 3 | да |
| `flt.identity.role_granted.v1`, `flt.identity.role_revoked.v1` | роль назначена или отозвана (в том числе бан преподавателя, `reason = ban`) | `RoleGranted`, `RoleRevoked` (`user_id`, `role`, `reason`) | 1 | этап 3 | да |
| `flt.identity.consent_granted.v1`, `flt.identity.consent_revoked.v1` | согласие выдано или отозвано | `ConsentGranted`, `ConsentRevoked` (`user_id`, `kind`, `version`) | 1 | этап 2 | да |
| `flt.identity.session_revoked.v1` | отозвана сессия или все сессии | `SessionRevoked` (`user_id`, `sid` или `null` для всех, `reason`) | 1 | этап 1 (`logout`, повторное использование refresh, отключение) | да |
| `flt.identity.user_deleted.v1` | аккаунт удалён | `UserDeleted` (`user_id`) | 1 | этап 3 | да |

### 6.2. Потребляемые топики

Не применимо: `identity` — модуль нижнего слоя SYS-01 и не подписывается на события других модулей.

## 7. REST-роутер и WebSocket-обработчики

### 7.1. REST

- Префиксы: `/api/v1/auth` (единственное исключение из правила префикса, SYS-03-R2, OQ-12) и `/api/v1/identity` (этап 3).
- Контракт: `api/openapi.yaml` (создаётся на шаге 4 конвейера для этапа 1 Г.5).
- Коды ошибок: `identity.invalid_credentials` (401), `identity.refresh_reused` (401), `identity.csrf_invalid` (403), `identity.user_suspended` (403), `identity.login_rate_limited` (429), `identity.account_exists_use_password` (409), `identity.external_account_taken` (409), `identity.email_taken` (409) — в конверте `ErrorResponseV1` (SYS-03-R7); имя `identity.user_suspended` вместо `identity.user_blocked` — OQ-83.

| Роутер | Ресурсы | Описан в ТЗ |
|---|---|---|
| `auth_router` (этап 1) | `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, `GET /api/v1/auth/.well-known/jwks.json` | ADR-006, раздел 3.5; этап 1 Г.5 |
| `auth_router` (этап 2) | `POST /register`, `POST /logout-all`, `GET /sessions`, `DELETE /sessions/{sid}`, `POST /email/verify`, `POST /email/resend`, `POST /password/forgot`, `POST /password/reset`, `POST /password/change`, `POST /consents`, `GET /me/auth-providers`, `GET /{provider}/start`, `GET /{provider}/callback`, `DELETE /external-accounts/{provider}` | ТЗ VIS-04, VIS-05 |
| `identity_router` (этап 3) | `/api/v1/identity/users`, `/users/{user_id}`, `/users/{user_id}/sanctions`, `/users/{user_id}/roles` | ТЗ ADM-01, ADM-02 |

`GET /api/v1/auth/me` (этап 1) возвращает `id`, `email`, `display_name`, `ui_language`, `timezone`, `roles`, `permissions` (SYS-06-R9), `email_verified`, `age_confirmed`, `consents`.

### 7.2. WebSocket

| Тип сообщения | Направление | Схема | Канал Redis pub/sub | Описан в ТЗ |
|---|---|---|---|---|
| `identity.session.revoked` | сервер → клиент, затем закрытие соединения кодом `4401` | `SessionRevokedMessage` (`reason`) | `ws:user:<user_id>` | ADR-006, раздел 3.7; SYS-04, раздел 4; этап 1 Г.5 |

## 8. Секция настроек

Класс `IdentitySettings`, префикс `IDENTITY_`, файл `envs/<стенд>/identity_<стенд>.env` (ADR-002). Исключения из префикса: `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID` и `OAUTH_*` — имена закреплены ADR-006 и ADR-013, читаются только секцией `identity`.

| Переменная | Тип | По умолчанию | Секрет | Назначение |
|---|---|---|---|---|
| `JWT_SIGNING_KEYS` | SecretStr (JSON `{"<kid>": "<PEM Ed25519>"}`) | — | да | приватные ключи подписи access JWT |
| `JWT_ACTIVE_KID` | str | — | нет | ключ, которым подписываются новые токены |
| `IDENTITY_ACCESS_TTL_SECONDS` | int | `600` | нет | срок access JWT |
| `IDENTITY_REFRESH_TTL_DAYS` | dict[str, int] | `{"web": 30, "mobile": 90}` | нет | срок refresh-токена по типу клиента |
| `IDENTITY_SESSION_MAX_DAYS` | int | `180` | нет | абсолютный предел семейства |
| `IDENTITY_REFRESH_REUSE_GRACE_SECONDS` | int | `10` | нет | окно повторной выдачи при сетевом повторе refresh |
| `IDENTITY_LOGIN_FAIL_LIMIT_EMAIL` | int | `10` | нет | неудачных входов на email за окно |
| `IDENTITY_LOGIN_FAIL_LIMIT_IP` | int | `50` | нет | неудачных входов с IP за окно |
| `IDENTITY_LOGIN_FAIL_WINDOW_SECONDS` | int | `900` | нет | окно лимита попыток входа |
| `IDENTITY_PASSWORD_MIN_LENGTH`, `IDENTITY_PASSWORD_MAX_LENGTH` | int | `10`, `128` | нет | длина пароля (NIST SP 800-63B) |
| `IDENTITY_TOKEN_PURGE_DAYS` | int | `90` | нет | срок хранения отозванных refresh-токенов (SYS-02-R48) |
| `IDENTITY_ONE_TIME_TOKEN_PURGE_DAYS` | int | `30` | нет | срок хранения одноразовых токенов (SYS-02-R48) |
| `OAUTH_GOOGLE_ENABLED`, `OAUTH_YANDEX_ENABLED`, `OAUTH_VK_ENABLED` | bool | `false` | нет | флаги провайдеров (этап 2, OQ-12) |
| `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_YANDEX_CLIENT_ID`, `OAUTH_VK_CLIENT_ID` | str | пусто | нет | идентификаторы приложений (этап 2) |
| `OAUTH_GOOGLE_CLIENT_SECRET`, `OAUTH_YANDEX_CLIENT_SECRET`, `OAUTH_VK_CLIENT_SECRET` | SecretStr | — | да (обязателен при включённом флаге) | секреты приложений (этап 2) |

## 9. Права и роли

Полная матрица — SYS-06, раздел 3.3, таблица `identity`. Права этапа 1:

| Permission | Роли | Правило |
|---|---|---|
| `identity:auth:login` | аноним | вход по email и паролю; лимит попыток |
| `identity:auth:refresh`, `identity:auth:logout` | `learner`, `teacher`, `platform_admin` | только своя сессия (`sid` из refresh-токена) |
| `identity:auth:read` | аноним, все роли | `jwks.json`, список включённых провайдеров |
| `identity:me:read` | все роли | только свой профиль |

Права этапов 2, 3, 6 (`identity:auth:register`, `identity:auth:logout_all`, `identity:password:update`, `identity:email:update`, `identity:me:update`, `identity:me:delete`, `identity:me:export`, `identity:consents:manage`, `identity:sessions:read`, `identity:sessions:revoke`, `identity:external_accounts:manage`, `identity:users:*`, `identity:roles:*`) — по матрице SYS-06 в ТЗ соответствующих этапов. Роль `teacher` назначает только администратор платформы (SYS-06-R11); последнего администратора нельзя лишить роли или отключить (SYS-06-R16).

## 10. Наблюдаемость

### 10.1. Метрики

| Имя | Тип | Метки | Описана в ТЗ |
|---|---|---|---|
| `flt_identity_logins_total` | counter | `result` (`success`, `invalid_credentials`, `rate_limited`, `suspended`), `client` | этап 1 Г.5 |
| `flt_identity_token_refresh_total` | counter | `result` (`success`, `reused`, `expired`, `revoked`), `client` | этап 1 Г.5 |
| `flt_identity_sessions_revoked_total` | counter | `reason` (`logout`, `logout_all`, `reuse_detected`, `suspended`) | этап 1 Г.5 |
| `flt_identity_registrations_total` | counter | `method` (`password`, `google`, `yandex`, `vk`) | ТЗ VIS-04 |
| `flt_identity_tokens_purged_total` | counter | `kind` (`refresh`, `one_time`) | SYS-02-R48 |

### 10.2. Логи

- Поле `module`: `identity`.
- События: `identity.login_succeeded`, `identity.login_failed` (без email: только `sha256` и причина), `identity.refresh_reused`, `identity.session_revoked`, `identity.user_suspended`, `identity.signing_key_missing`. Пароли, токены, cookie и email не логируются (ADR-010).

### 10.3. Дашборды и алерты

Панели входов и отзывов — в дашборде `deploy/config/grafana/dashboards/http.json` (этап 1 Г.9); алерт `FltAuthRevocationSkipped` (ядро) и алерт `FltIdentityRefreshReuseSpike` (доля `reused` больше 5 % за 15 минут, этап 2).

## 11. Frontend-модуль

Папка: `src/features/identity`. Пространство ключей i18n: `identity.*` (namespace `identity`). На этапе 1 экранов нет: вход тестового пользователя в E2E Г.11 — фикстурой через `POST /api/v1/auth/login`; аутентификация браузера — общий слой `src/lib/auth.tsx` в `app_shell`, построенный на сгенерированном клиенте `identity` (ADR-005, раздел 3.2, п. 7).

### 11.1. Страницы

| Страница | Роут | Роли | Описана в ТЗ |
|---|---|---|---|
| Вход | `/auth/login` | аноним | ТЗ VIS-05 (этап 2) |
| Регистрация | `/auth/register` | аноним | ТЗ VIS-04 (этап 2) |
| Завершение профиля после OAuth | `/auth/complete-profile` | аноним после OAuth | ТЗ VIS-04 (этап 2) |
| Восстановление пароля | `/auth/forgot`, `/auth/reset` | аноним | ТЗ VIS-05 (этап 2) |
| Сессии и способы входа | `/settings/security` | все роли | ТЗ VIS-05 (этап 2) |

### 11.2. API-хуки

Хуки генерирует orval из `api/openapi.yaml`; `operationId` по SYS-03-R24.

| Хук | operationId | Назначение |
|---|---|---|
| `useIdentityLogin` | `identity_login` | вход (этап 1 — используется `src/lib/auth.tsx`) |
| `useIdentityRefresh` | `identity_refresh` | single-flight refresh в интерсепторе axios |
| `useIdentityLogout` | `identity_logout` | выход |
| `useIdentityGetMe` | `identity_getMe` | текущий пользователь и `permissions` для `app_shell` |

### 11.3. Подписки WebSocket

| Тип сообщения | Что обновляет |
|---|---|
| `identity.session.revoked` | сбрасывает состояние аутентификации `src/lib/auth.tsx` и переводит на `/auth/login` |

### 11.4. Клиентское состояние

Не применимо: состояние пользователя хранится в кэше TanStack Query (`useIdentityGetMe`), токены — только в httpOnly-cookie; zustand не используется.

## 12. Готовность к выделению в микросервис

| Что потребуется | Описание | Готово сейчас |
|---|---|---|
| Замена вызовов в процессе на сетевые | `IdentityService` у модулей из 4.2 — на REST-клиент; `RolePermissionsProvider` у ядра других сервисов — на кэш матрицы по событиям `role_*` или REST | да: вызовы идут через `Protocol` |
| Отдельная БД | схема `identity` без FK наружу | да |
| Конфигурация | раздел 8; выделенный сервис получает `JWT_SIGNING_KEYS`, остальные — только `JWT_PUBLIC_KEYS` (ADR-006, раздел 3.3) | да |
| Развёртывание | контейнер сервиса, маршрут HAProxy `/api/v1/auth/*` и `/api/v1/identity/*` на него | нет: нужен ADR при выделении |
| Известные препятствия | закрытие WebSocket при отзыве сессии идёт через ядро текущего инстанса (`ws:user:*`); при выделении — событие `session_revoked` слушает сервис с WebSocket | нет |

## 13. Вне рамок

- Внешний IdP (Keycloak, Ory) — отклонён ADR-006.
- Многофакторная аутентификация — не входит в BRD; при появлении требования — новый пункт BRD.
- Нативный обмен кода OAuth для мобильных приложений (`POST /{provider}/exchange`) — задел до появления приложений (ADR-006).
- Токены агента — `local_runtime`.
- Самозаявка на роль преподавателя — не предоставляется (SYS-06-R11).

## 14. Открытые вопросы

| Вопрос | Суть | Блокирует G1 | Статус |
|---|---|---|---|
| [OQ-83](../../open-questions.md) | статус и событие отключения аккаунта: `suspended`/`user_suspended` (SYS-01, SYS-06, глоссарий: «блокировка» без уточнения запрещена) против `blocked`/`user_blocked` (ADR-006, SYS-03, SYS-04); предлагается глоссарный вариант и `changed`-версии SYS-03 и SYS-04 | да | open |
| [OQ-78](../../open-questions.md) | пункт BRD для удаления аккаунта и выгрузки данных | нет | open |
| [OQ-12](../../open-questions.md) | OAuth за флагами конфигурации, mock OIDC в тестах | нет | resolved |
| [OQ-14](../../open-questions.md) | 18+ — самодекларация, факт и время подтверждения | нет | resolved |
| [OQ-75](../../open-questions.md) | источник роли `teacher` | нет | resolved: назначает администратор платформы |

## 15. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-11 | Claude | Черновик | draft |
| 0.1 | 2026-10-11 | Claude | Передан на гейт G1 (PR блока В) | review |
