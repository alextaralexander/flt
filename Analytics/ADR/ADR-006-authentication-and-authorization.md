# ADR-006 — Аутентификация и авторизация: собственная реализация в модуле identity, cookie для браузера и Bearer для остальных клиентов

| Поле | Значение |
|---|---|
| Статус | accepted |
| Версия | 1.0 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-10 (PR #2) |
| Пункт(ы) BRD | VIS-04 (регистрация), VIS-05 (вход), ADM-01 (блокировка), TCH-01; косвенно — все (каждый запрос аутентифицируется) |
| Модуль | identity (владелец); shared kernel `app/core/security` (проверка токена); app_shell (клиентская часть); local_runtime (токен агента `flta_…` — ADR-008, здесь только граница с identity) |
| Зависимости | ADR-003 (PostgreSQL и Redis), ADR-004 (WebSocket), ADR-013 (хранение ключей подписи) |
| Связанные ADR/SYS | ADR-002 (раскладка `app/modules/identity`, исключение `/api/v1/auth`), ADR-005 (клиент), ADR-008 (аутентификация агента), ADR-010 (метрика пропущенной проверки отзыва, запрет токенов в логах), ADR-012 (HAProxy, TLS), SYS-02 (152-ФЗ, 18+), SYS-03 (пути REST), SYS-04 (аутентификация WebSocket), SYS-05 (Redis), SYS-06 (матрица ролей); OQ-12, OQ-14 |

## 1. Контекст

- **Проблема**: boilerplate бэкенда только проверяет JWT (`app/core/security/auth_service.py`: HS256 по `JWT_SECRET_KEY`, claims `USER_ID`, `ROLES`, `PERMISSIONS`, маппинг ролей из `JWT_ROLE_PERMISSIONS`; `security.py`: `HTTPBearer` → `get_current_user` → `check_permissions`; `cli issue-token` выпускает dev-токены тем же секретом). Выпуска токенов, пользователей, паролей, OAuth, сессий, отзыва и восстановления пароля в нём нет. Boilerplate фронтенда рассчитан на cookie-сессию (`withCredentials: true`, `react-query-auth`). Нужно спроектировать аутентификацию, которая работает на N инстансах без состояния в процессе, не разлогинивает пользователей при сбое Redis, пригодна для браузера, нативных мобильных приложений и локального агента.
- **Почему сейчас**: этап 1 Г.5 (модуль `identity`: пользователи, роли, аутентификация, серверная авторизация), Г.4 (WebSocket-инфраструктура shared kernel), Г.11 (E2E входит тестовым пользователем); экраны регистрации и входа — этап 2 (VIS-04, VIS-05).
- **Ограничения**:
  - решение пользователя (2026-10-10): собственная реализация в модуле `identity`, без внешнего IdP; браузер получает httpOnly-cookie, мобильные клиенты и локальный агент — `Authorization: Bearer`;
  - CLAUDE.md, «Масштабирование и состояние»: refresh-токены в PostgreSQL, короткоживущие сессии в Redis с TTL, сбой Redis не разлогинивает; состояние в памяти процесса запрещено;
  - CLAUDE.md, «Технологический стек»: email и пароль, вход через Google, Яндекс ID, VK ID; OQ-12: провайдеры за флагами конфигурации, автотесты на mock OIDC-провайдере, redirect URI `/api/v1/auth/<provider>/callback`;
  - OQ-14: подтверждение 18+ — чекбокс при регистрации и при первом входе через OAuth, хранятся факт и время; без подтверждения доступ к обучению закрыт; 152-ФЗ — согласие на обработку персональных данных, отдельное согласие на передачу данных зарубежным LLM-провайдерам (CLAUDE.md, «Ключевые архитектурные требования»);
  - CLAUDE.md, «Модульный монолит»: `identity` владеет своими таблицами; другие модули ссылаются на пользователя по `user_id` и проверяют права через shared kernel, не импортируя внутренности `identity`;
  - права проверяются на сервере (CLAUDE.md), матрица «роль × действие» — SYS-06;
  - API пригоден для будущих нативных мобильных клиентов (SYS-03).
- **Если не решить**: модуль `identity` и WebSocket-инфраструктура Г.4 не могут быть специфицированы; фронтенд (ADR-005) не знает, как передавать токен и защищаться от CSRF; ТЗ VIS-04 и VIS-05 этапа 2 не имеют основы.
- **Ссылки**: CLAUDE.md «Backend-сервис (boilerplate)», «Отличия проекта от boilerplate» п. 6, «Масштабирование и состояние», «Ключевые архитектурные требования»; SDD_plan.md этап 1 А.6, Г.4, Г.5; OQ-12, OQ-14; `src/backend/py-monolyth/app/core/security/*`, `cli/main.py` (`issue_token`), `configs/settings.py` (`JWT_*`).

## 2. Рассматриваемые варианты

### Вариант A. Собственная реализация в `identity`: короткоживущий access JWT (EdDSA, `kid`) + ротируемые refresh-токены в PostgreSQL; cookie для браузера, Bearer для остальных

- **Описание**: `identity` хранит пользователей, учётные данные (argon2id), внешние аккаунты, роли, согласия, refresh-токены и одноразовые токены в PostgreSQL; выпускает access JWT со сроком 10 минут, подписанный Ed25519 с идентификатором ключа `kid`; refresh-токен — случайная строка, в БД хранится хэш, при каждом обновлении токен ротируется, повторное использование отзывает всё семейство. Браузер получает токены в httpOnly-cookie и защищён CSRF-токеном; мобильные клиенты получают токены в теле ответа и передают `Authorization: Bearer`; локальный агент использует отдельный непрозрачный токен `flta_…` модуля `local_runtime` (ADR-008), а не JWT пользователя. Проверка токена — локально на любом инстансе по публичному ключу; отзыв — через Redis с TTL, равным сроку access-токена.
- **Плюсы**:
  - проверка без обращения к БД и к `identity`: подпись + `exp` + одна операция `GET` в Redis; на N инстансах нет общего состояния, кроме Redis и PostgreSQL;
  - при сбое Redis пользователи остаются в системе: access-токены проверяются по подписи, refresh — по PostgreSQL; теряется только мгновенный отзыв (окно ≤ 10 минут);
  - один и тот же бэкенд обслуживает браузер (cookie) и нативные клиенты (Bearer) без двух реализаций;
  - механизм boilerplate (`auth_user`, `check_permissions`, `UserSecuritySchema`, маппинг ролей → permissions) переиспользуется; меняются только источник токена и алгоритм;
  - при выделении `identity` в микросервис остальные модули продолжают проверять токены по JWKS, ничего не переписывая.
- **Минусы**:
  - собственный код паролей, OAuth, восстановления и ротации — больше поверхности для ошибок, чем у готового IdP; смягчается библиотеками (`argon2-cffi`, `authlib`, `PyJWT`) и тестами на каждый критерий;
  - отзыв access-токена не мгновенный без Redis;
  - ротация ключей подписи требует хранения нескольких публичных ключей и процедуры (раздел 3.3).
- **Масштабирование на N инстансах**: состояние — PostgreSQL (пользователи, refresh, одноразовые токены) и Redis (отозванные сессии, лимиты попыток входа, OAuth `state`); инстанс не хранит ничего; остановка инстанса не влияет на вход; одновременный refresh одного токена с двух инстансов разрешается уникальным ограничением и транзакцией `SELECT … FOR UPDATE` (раздел 3.2).
- **Выделение модулей в микросервисы**: помогает — проверка токена не зависит от `identity`; публичные ключи публикуются по `/.well-known/jwks.json`.
- **Трудоёмкость и риски**: средняя; риски — ошибки в CSRF и OAuth, смягчаются тестами с mock OIDC и чек-листом OWASP (ASVS V2, V3).

### Вариант B. Внешний IdP (Keycloak или Ory Kratos + Hydra) в составе контейнеров

- **Описание**: отдельный контейнер IdP хранит пользователей и выпускает OIDC-токены; монолит проверяет их по JWKS; фронтенд ходит на IdP через Authorization Code + PKCE.
- **Плюсы**:
  - готовые OAuth-провайдеры, восстановление пароля, MFA, брутфорс-защита;
  - проверенный код.
- **Минусы**:
  - отвергнут решением пользователя (2026-10-10);
  - ещё один контейнер с собственной БД в docker-compose и Helm (Keycloak — JVM, 1 ГБ RAM на VPS из OQ-07);
  - модель пользователя FLT (согласия 152-ФЗ, 18+, роли учеников и преподавателей) распадается между IdP и `identity`;
  - кастомизация экранов регистрации под i18n ru/en/ar и RTL — темы IdP вместо React-компонентов проекта.
- **Масштабирование на N инстансах**: нейтрально (IdP масштабируется отдельно).
- **Выделение модулей в микросервисы**: помогает.
- **Трудоёмкость и риски**: низкая в коде, высокая в эксплуатации и интеграции модели данных.

### Вариант C. Непрозрачные серверные сессии без JWT (идентификатор сессии в cookie, данные сессии в PostgreSQL с кэшем в Redis)

- **Описание**: cookie содержит случайный `session_id`; на каждом запросе инстанс ищет сессию в Redis, при промахе — в PostgreSQL. Для мобильных клиентов тот же `session_id` в `Authorization: Bearer`.
- **Плюсы**:
  - мгновенный отзыв (удалить строку сессии);
  - нет ключей подписи и ротации.
- **Минусы**:
  - каждый запрос — обращение в Redis, при сбое Redis — в PostgreSQL на каждый запрос (деградация под нагрузкой);
  - при выделении модуля в микросервис каждому сервису нужен доступ к таблице сессий или синхронный вызов `identity` на каждый запрос;
  - WebSocket и Kafka-воркеры не могут проверить подлинность без общей БД сессий;
  - boilerplate-механизм проверки JWT не используется.
- **Масштабирование на N инстансах**: работает, но связывает все инстансы одной горячей таблицей.
- **Выделение модулей в микросервисы**: мешает — общее хранилище сессий.
- **Трудоёмкость и риски**: низкая в реализации, высокая по нагрузке на Redis/PostgreSQL.

### 2.4. Частные выборы внутри варианта A

| Вопрос | Кандидаты | Выбор и причина |
|---|---|---|
| Алгоритм подписи access JWT | HS256 (как в boilerplate), RS256, ES256, EdDSA (Ed25519) | EdDSA: асимметричный (проверяющие инстансы и будущие сервисы знают только публичный ключ), короткие ключи и подписи, детерминированная подпись без генератора случайных чисел; поддержан PyJWT ≥ 2.6 с `cryptography`. ES256 — запасной вариант, если потребуется совместимость с клиентом без EdDSA (JWT-библиотеки iOS/Android поддерживают оба) |
| SameSite cookie с access-токеном | Strict, Lax | Lax: cookie должна отправляться при top-level переходе из письма (подтверждение email, сброс пароля) и при возврате с OAuth-провайдера; Strict сломал бы эти переходы. Lax не отправляет cookie при cross-site `POST`, что уже закрывает CSRF для изменяющих запросов; дополнительно — CSRF-токен |
| Защита от CSRF | только SameSite; синхронизированный токен в сессии; double-submit cookie; signed double-submit | Signed double-submit (OWASP Cheat Sheet): cookie `flt_csrf` читается JS и повторяется в заголовке `X-CSRF-Token`; значение подписано HMAC с привязкой к `sid`, поэтому поддельная cookie с поддомена не проходит; серверного состояния нет — подходит для N инстансов |
| Аутентификация WebSocket | cookie при handshake; первое сообщение с токеном; токен в query-string | Cookie (браузер) или `Authorization: Bearer` (агент, мобильные) при handshake + проверка `Origin`. Токен в query попадает в логи HAProxy — отвергнут; первое сообщение с токеном не нужно, так как ни один клиент FLT не лишён возможности передать cookie или заголовок (браузер — cookie, Python-агент и нативные приложения — заголовок) |
| OAuth-библиотека | `authlib`, `httpx-oauth`, свой клиент | `authlib` (`authlib.integrations.starlette_client`): OIDC discovery для Google, generic OAuth2 для Яндекс ID, PKCE из коробки; VK ID требует два нестандартных параметра (`device_id`, `state` в запросе токена) — реализуется наследованием клиента authlib |
| Хранение одноразовых токенов (подтверждение email, сброс пароля) | Redis с TTL; PostgreSQL | PostgreSQL (`identity.one_time_tokens`): ссылка в письме живёт до 24 часов, потеря Redis не должна её обесценивать (CLAUDE.md разрешает терять только кэш, лимиты, блокировки и быстрый тест) |

## 3. Решение

- **Выбран**: Вариант A с частными выборами из 2.4.
- **Решение**: аутентификацию и авторизацию реализует модуль `identity`: учётные данные с argon2id, access JWT (EdDSA, 10 минут, `kid`), ротируемые refresh-токены в PostgreSQL с обнаружением повторного использования, OAuth/OIDC Google, Яндекс ID и VK ID через `authlib` за флагами конфигурации. Браузер получает токены в httpOnly-cookie с signed double-submit CSRF; мобильные клиенты — в теле ответа и передают `Authorization: Bearer`. Любой инстанс проверяет токен по публичному ключу из конфигурации и по списку отозванных сессий в Redis; при недоступном Redis проверка отзыва пропускается (fail-open, окно ≤ 10 минут, метрика и алерт), а refresh выполняется через PostgreSQL — **подтверждено пользователем 2026-10-10**. OAuth-аккаунт автоматически привязывается к существующему пользователю по email, который подтверждён провайдером (Google, Яндекс ID); для VK ID — только явная привязка из настроек — **подтверждено пользователем 2026-10-10**. Локальный агент аутентифицируется непрозрачным токеном `flta_…`, который выдаёт, хранит (хэш) и проверяет модуль `local_runtime` только для `/ws/agent` (ADR-008); `identity` в сопряжении участвует лишь публичным API для подтверждения привязки вошедшим пользователем. Shared kernel `app/core/security` переиспользуется с заменой источника токена и алгоритма.
- **Обоснование**: вариант A единственный одновременно удовлетворяет решению пользователя (своя реализация), требованию «сбой Redis не разлогинивает», N инстансам без состояния и будущему выделению `identity` в сервис (сравнение в разделе 2).
- **Отвергнуты**:
  - Вариант B — исключён решением пользователя; дополнительный контейнер и расщепление модели пользователя.
  - Вариант C — обращение к хранилищу сессий на каждый запрос, общее хранилище при выделении модулей, неиспользование механизма boilerplate.
- **Границы решения**: матрица «роль × действие», набор санкций (OQ-54) и правило «без подтверждения 18+ и email доступ к обучению закрыт» — SYS-06; формулировки согласий и чекбокса — SYS-02; тексты писем и экраны — ТЗ VIS-04 и VIS-05; сопряжение агента, формат и хранение токена `flta_…` — ADR-008 (здесь — только правило, что токен агента не является JWT `identity`, действует только на `/ws/agent` и проверяется модулем `local_runtime`); формат сообщений WebSocket и коды закрытия — ADR-004/SYS-04 (здесь — код `4401` для отзыва); хранение ключей подписи в Vault и `.env` — ADR-013; MFA — вне рамок (не в BRD).

### 3.1. Модель данных `identity` (схема PostgreSQL `identity`)

| Таблица | Назначение и ключевые поля |
|---|---|
| `users` | `id uuid pk`, `email citext unique null` (null у OAuth-аккаунта без email), `email_verified_at`, `display_name`, `status` (`active`, `blocked`, `deleted`), `blocked_at`, `blocked_reason`, `ui_language`, `created_at`, `updated_at`, `version int` (оптимистическая блокировка) |
| `credentials` | `user_id pk fk users`, `password_hash text` (argon2id, строка PHC), `password_updated_at`, `failed_attempts int`, `locked_until timestamptz null`. Отсутствие строки — аккаунт без пароля (только OAuth) |
| `external_accounts` | `id uuid pk`, `user_id fk`, `provider` (`google`, `yandex`, `vk`), `subject text` (ID у провайдера), `email`, `email_verified bool`, `linked_at`, `last_login_at`; `unique(provider, subject)` |
| `roles`, `user_roles` | коды ролей из глоссария: `learner`, `teacher`, `platform_admin` (аноним — отсутствие пользователя); `user_roles(user_id, role_code, granted_at, granted_by)`; матрица прав — SYS-06 |
| `consents` | `id uuid pk`, `user_id fk`, `kind` (`personal_data`, `age_18plus`, `foreign_llm_transfer`), `version text` (версия текста согласия из SYS-02), `granted_at`, `revoked_at null`, `ip_hash`, `user_agent`; `unique(user_id, kind) where revoked_at is null`. OQ-14: `age_18plus` — факт и время подтверждения |
| `refresh_tokens` | `id uuid pk` (= `jti`), `family_id uuid` (= `sid`, сессия), `user_id fk`, `token_hash bytea` (SHA-256 от секрета токена), `client_type` (`web`, `mobile`; агент refresh-токенов не получает — ADR-008), `client_label` (user-agent или имя устройства), `created_at`, `expires_at`, `used_at null`, `replaced_by uuid null`, `revoked_at null`, `revoke_reason` (`logout`, `logout_all`, `reuse_detected`, `blocked`, `expired`, `rotated`); индексы по `family_id`, `user_id`, `token_hash unique` |
| `one_time_tokens` | `id uuid pk`, `user_id fk`, `purpose` (`email_verify`, `password_reset`, `email_change`), `token_hash bytea unique`, `expires_at`, `used_at null`, `created_at`; TTL: `email_verify` 24 ч, `password_reset` 1 ч; при выдаче нового токена прежние того же `purpose` помечаются использованными |
| `signing_keys` | не хранятся в БД: ключи — секреты конфигурации (раздел 3.3) |

Ключи Redis (префикс `identity:`, у всех TTL):

| Ключ | Значение | TTL | Назначение |
|---|---|---|---|
| `identity:revoked_sid:<sid>` | `1` | = срок access (600 с) | сессия отозвана (выход, повторное использование refresh, блокировка): access-токены с этим `sid` отклоняются до истечения |
| `identity:revoked_user:<user_id>` | unix-время отзыва | 600 с | «выйти везде», блокировка администратором: отклоняются все access-токены пользователя с `iat` меньше значения |
| `identity:login_fail:<sha256(email)>`, `identity:login_fail_ip:<ip>` | счётчик | 900 с | лимит попыток входа: 10 на email и 50 на IP за 15 минут, затем ответ `429` и, по OQ-10, капча |
| `identity:oauth:<state>` | JSON `{provider, code_verifier, nonce, redirect_to, link_user_id}` | 600 с | состояние OAuth-перехода (дублирует cookie `flt_oauth` на случай сбоя cookie) |
| `identity:session:<sid>` | hash `{user_id, last_seen_at, ip_hash, client_label}` | 24 ч, продлевается при записи | кэш активности сессии для `GET /sessions` и присутствия онлайн; обновляется не чаще раза в 60 с на `sid`; это и есть «короткоживущая сессия в Redis» из глоссария |

Все ключи — через обёртку `ModuleRedis(prefix="identity")` shared kernel с обязательным TTL (ADR-003). Источник истины для «активных сессий» пользователя — семейства в `refresh_tokens` (`revoked_at is null and expires_at > now()`); Redis держит отзывы, лимиты и кэш активности, поэтому его потеря не разлогинивает.

### 3.2. Токены

**Access JWT** (срок `IDENTITY_ACCESS_TTL_SECONDS=600`): заголовок `{"alg":"EdDSA","kid":"<kid>","typ":"JWT"}`; claims: `iss` = `JWT_ISSUER` (например `flt`), `aud` = `JWT_AUDIENCE` (`flt-api`), `sub` = `user_id`, `sid` = `family_id`, `jti`, `iat`, `exp`, `roles` = `["learner"]`, `client` = `web|mobile`, `email_verified` bool, `age_confirmed` bool. Permissions в токен не включаются: их выводит проверяющий из `roles` по реестру permissions (как сейчас `JWT_ROLE_PERMISSIONS`, но реестр собирается из кода модулей и матрицы SYS-06, а не из JSON в env). Claim boilerplate `USER_ID` больше не выпускается; `get_user_id` читает `sub`.

**Refresh-токен**: 32 случайных байта (`secrets.token_urlsafe(32)`), клиенту передаётся строка `<id>.<secret>`, в БД — `sha256(secret)`. Срок `IDENTITY_REFRESH_TTL_DAYS`: `web` 30, `mobile` 90; абсолютный предел семейства `IDENTITY_SESSION_MAX_DAYS=180` от `created_at` первого токена. Ротация при каждом обновлении в одной транзакции:

1. `SELECT … FROM refresh_tokens WHERE id = :id FOR UPDATE`; проверить `token_hash`, `expires_at`, `revoked_at`, статус пользователя (`status = 'active'`).
2. Если `used_at is not null` — повторное использование: отозвать все токены семейства (`revoked_at = now(), revoke_reason = 'reuse_detected'`), записать `identity:revoked_sid:<sid>`, вернуть `401 refresh_reused`, опубликовать событие `identity.session_revoked`.
3. Иначе пометить `used_at = now()`, создать новый токен того же `family_id` с `replaced_by` у старого, выпустить новый access; срок нового refresh — `min(now() + TTL, family_created_at + SESSION_MAX)`.

Одновременные обновления одного токена с разных инстансов упираются в `FOR UPDATE`: второй увидит `used_at` и получит `refresh_reused` — клиент (ADR-005) выполняет refresh single-flight, поэтому в норме такого не происходит; окно допуска для сетевых повторов — повторная выдача того же результата, если старый токен использован менее `IDENTITY_REFRESH_REUSE_GRACE_SECONDS=10` секунд назад и `replaced_by` ещё не использован.

**Проверка на любом инстансе** (`app/core/security`, async): извлечь токен (порядок — раздел 3.4) → `jwt.decode` с набором публичных ключей по `kid`, `algorithms=["EdDSA"]`, `issuer`, `audience`, `require=["exp","sub","sid","iat"]`, `leeway=30` → Redis: `GET identity:revoked_sid:<sid>` и `GET identity:revoked_user:<sub>` (один pipeline) → если Redis недоступен — пропустить проверку отзыва (fail-open), записать warning и метрику `flt_auth_revocation_check_skipped_total` с алертом (ADR-010); окно риска ≤ 600 с принято осознанно — подтверждено пользователем 2026-10-10. Результат — `UserSecuritySchema` с `user_id`, `sid`, `roles`, `permissions`, `client`, `email_verified`, `age_confirmed`.

**Выпуск** — только `identity` (сервис `TokenIssuer`), приватные ключи — секрет `JWT_SIGNING_KEYS` (JSON `{"<kid>": "<PEM приватного ключа Ed25519>"}`) и `JWT_ACTIVE_KID` (имена — ADR-013). `cli issue-token` переводится на `TokenIssuer` (dev-токены для ручных запросов сохраняются).

### 3.3. Ключи подписи и ротация

- Приватные ключи `JWT_SIGNING_KEYS` читает только секция настроек `identity` (тот же процесс, но отдельная секция, чтобы при выделении модуля ключи уехали с ним). Проверяющая часть в shared kernel получает публичные ключи из `JWT_PUBLIC_KEYS` (JSON `{"<kid>": "<PEM публичного ключа>"}`); если переменная не задана, shared kernel выводит публичные ключи из `JWT_SIGNING_KEYS` — так в монолите задаётся один секрет, а выделенный сервис получает только `JWT_PUBLIC_KEYS`.
- Ротация: добавить новый `kid` в `JWT_SIGNING_KEYS` на всех инстансах (поочерёдный перезапуск, ADR-013) → переключить `JWT_ACTIVE_KID` → удалить старый `kid` не раньше чем через 600 с + leeway после того, как все инстансы перестали им подписывать (refresh-токены не являются JWT, поэтому ждать срока refresh не нужно). Период плановой ротации — 180 дней (SYS-02).
- JWKS: `GET /api/v1/auth/.well-known/jwks.json` отдаёт публичные ключи (для будущих сервисов и внешних проверяющих); сами инстансы читают ключи из конфигурации, а не по сети.
- Dev и тесты: Ed25519-пару для стенда генерирует `deploy/scripts/gen-secrets.sh` в `.env` (ADR-013); `envs/local` содержит только имена переменных; pytest-фикстура shared kernel генерирует одноразовую пару на сессию тестов.

### 3.4. Передача токена: cookie и Bearer в одном бэкенде

Порядок извлечения в `get_current_user`:

1. Заголовок `Authorization: Bearer <jwt>` — если есть, используется он; cookie игнорируются; CSRF-проверка не выполняется (заголовок нельзя подделать cross-site).
2. Иначе cookie `__Host-flt_access` — используется; для методов `POST`, `PUT`, `PATCH`, `DELETE` обязателен заголовок `X-CSRF-Token`, равный cookie `__Host-flt_csrf`, и валидная HMAC-подпись (ниже); при несовпадении — `403 csrf_invalid`.
3. Иначе — аноним: `401` для защищённых роутов, `anonymous` для роутов, допускающих анонима (SYS-06).

Cookie (все `Secure`, `Path=/`, кроме refresh; `Domain` не задаётся; префикс `__Host-` требует `Secure`, `Path=/` и отсутствие `Domain` — на `http://localhost` браузеры считают контекст безопасным):

| Cookie | Содержимое | Атрибуты | Срок |
|---|---|---|---|
| `__Host-flt_access` | access JWT | `HttpOnly; Secure; SameSite=Lax; Path=/` | `Max-Age=600` |
| `flt_refresh` | refresh-токен `<id>.<secret>` | `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` | `Max-Age` = срок refresh |
| `__Host-flt_csrf` | `<random>.<hmac>` | `Secure; SameSite=Lax; Path=/` (читается JS) | = сроку refresh |
| `flt_oauth` | `state` | `HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth` | `Max-Age=600`, удаляется в callback |

CSRF-токен: `random` — 16 байт base64url, `hmac` = HMAC-SHA256(`AUTH_CSRF_SECRET`, `random || sid`), сравнение константное по времени; токен переустанавливается при входе и при каждом refresh. Refresh-cookie ограничена путём `/api/v1/auth` и `SameSite=Strict`: она не отправляется ни при каких cross-site переходах и не покидает эндпоинты аутентификации. Доменов и поддоменов у FLT нет (один origin через HAProxy, OQ-08), поэтому `Domain` не используется.

Клиент `mobile`: `POST /api/v1/auth/login` с полем `client: "mobile"` возвращает `{ "access_token", "refresh_token", "token_type": "Bearer", "expires_in": 600 }`; обновление — `POST /api/v1/auth/refresh` с телом `{ "refresh_token": "…" }`; выход — `POST /api/v1/auth/logout` с тем же телом. Для `web` те же эндпоинты читают и пишут cookie, тело ответа содержит только пользователя.

**Токен агента** (третий тип учётных данных, ADR-008): непрозрачная строка `flta_` + 32 случайных байта base64url, без срока действия; выдаётся модулем `local_runtime` при подтверждении сопряжения (`POST /api/v1/local-runtime/pairings`, `…/pairings/{pairing_id}/token`), на сервере хранится только `sha256` в `local_runtime.agents`; передаётся заголовком `Authorization: Bearer flta_…` только при открытии `/ws/agent` и проверяется обработчиком `local_runtime` по хэшу; на REST API и `/ws` не принимается (`TokenVerifier` отклоняет строку с префиксом `flta_` как не-JWT, `401`). Отзыв — учеником в списке устройств или при удалении аккаунта (событие `identity.user_deleted`). Роль `identity` в сопряжении: страница подтверждения требует вошедшего пользователя (обычная cookie-аутентификация), `local_runtime` получает `user_id` из `UserSecuritySchema` и при необходимости вызывает `IdentityService.get_user` через публичный API; отдельных эндпоинтов `identity` для агента нет.

### 3.5. Эндпоинты `identity` (префикс `/api/v1/auth`; полный контракт — `Analytics/Specs/identity/api/openapi.yaml`)

| Метод и путь | Назначение | Этап |
|---|---|---|
| `POST /register` | email, пароль, `consents: {personal_data: true, age_18plus: true}`; создаёт пользователя `learner`, отправляет письмо подтверждения; вход сразу разрешён (доступ к обучению закрыт до подтверждения email и 18+ — SYS-06) | 2 (VIS-04) |
| `POST /login` | email + пароль (+ `client`); при `locked_until` или лимите — `429`; успех — cookie или пара токенов | 1 (Г.5, без экрана) |
| `POST /refresh` | ротация refresh | 1 |
| `POST /logout` | отзыв текущего семейства, очистка cookie | 1 |
| `POST /logout-all` | отзыв всех семейств пользователя, `identity:revoked_user` | 2 (VIS-05) |
| `GET /me` | текущий пользователь, роли, флаги `email_verified`, `age_confirmed`, список согласий | 1 |
| `GET /sessions`, `DELETE /sessions/{sid}` | активные семейства с `client_label`, отзыв одного | 2 |
| `POST /email/verify` (`{token}`), `POST /email/resend` | подтверждение email | 2 |
| `POST /password/forgot` (`{email}`), `POST /password/reset` (`{token, new_password}`) | восстановление; ответ `forgot` одинаков для существующего и несуществующего email; после сброса — `logout-all` | 2 |
| `POST /password/change` | требует текущий пароль; для аккаунта без пароля — путь через `password/forgot` | 2 |
| `POST /consents` (`{kind, version}`) | подтверждение 18+ после первого OAuth-входа, согласие на зарубежные LLM | 2 |
| `GET /{provider}/start?redirect_to=` | 302 на провайдера; `provider ∈ {google, yandex, vk}`; `404`, если провайдер выключен флагом | 2 |
| `GET /{provider}/callback` | обмен кода, создание или связывание, cookie, 302 на `redirect_to` (только относительный путь) или на `/auth/complete-profile`, если нет согласий | 2 |
| `POST /{provider}/exchange` | для нативных клиентов: `{code, code_verifier, redirect_uri, client}` → пара токенов (задел для мобильных приложений, не реализуется до их появления) | задел |
| `DELETE /external-accounts/{provider}` | отвязка; запрещена, если это единственный способ входа | 2 |
| `GET /.well-known/jwks.json` | публичные ключи | 1 |

Пароли: длина 10–128 символов, без требований к составу (NIST SP 800-63B), проверка по списку из 10 000 самых частых паролей (файл в репозитории); `argon2-cffi` с параметрами по умолчанию библиотеки (`time_cost=3`, `memory_cost=65536`, `parallelism=4`), при входе `check_needs_rehash` → перехэширование. Сравнение email — без учёта регистра (`citext`). Ответы на вход не раскрывают, существует ли email (`401 invalid_credentials`).

### 3.6. OAuth / OIDC

- Флаги: `OAUTH_GOOGLE_ENABLED`, `OAUTH_YANDEX_ENABLED`, `OAUTH_VK_ENABLED` (по умолчанию `false`); конфигурация `OAUTH_<PROVIDER>_CLIENT_ID` (не секрет), секреты `OAUTH_<PROVIDER>_CLIENT_SECRET` (имена — ADR-013); при включённом флаге без секрета сервис не стартует (проверка настроек). `GET /me/auth-providers` (публичный) отдаёт список включённых провайдеров — фронтенд скрывает кнопки (OQ-12).
- Redirect URI: `<APP_PUBLIC_URL>/api/v1/auth/<provider>/callback`; dev — `http://localhost:8000/api/v1/auth/<provider>/callback` (OQ-12).
- Общий флоу: `start` генерирует `state` (32 байта), `code_verifier` (PKCE S256), `nonce` (OIDC); сохраняет в `identity:oauth:<state>` и cookie `flt_oauth`; если запрос аутентифицирован — `link_user_id` = текущий пользователь (привязка из настроек). `callback` сверяет `state` из query с cookie и Redis (если Redis недоступен — достаточно cookie, так как `state` подписан HMAC тем же способом, что CSRF), обменивает код, получает профиль.
- Провайдеры:

| Провайдер | Протокол | Эндпоинты | Особенности |
|---|---|---|---|
| Google | OIDC (discovery `https://accounts.google.com/.well-known/openid-configuration`) | authorize, token, userinfo из discovery | проверка `id_token` (подпись, `nonce`, `aud`); `email_verified` из `id_token`; scope `openid email profile` |
| Яндекс ID | OAuth 2.0 + PKCE | `https://oauth.yandex.ru/authorize`, `https://oauth.yandex.ru/token`, профиль `https://login.yandex.ru/info?format=json` | `subject` = `id`, email = `default_email` (считается подтверждённым провайдером); scope `login:email login:info` |
| VK ID | OAuth 2.1 + PKCE (обязателен) | `https://id.vk.com/authorize`, токен `https://id.vk.com/oauth2/auth`, профиль `https://id.vk.com/oauth2/user_info` | callback получает `code`, `state`, `device_id`; запрос токена передаёт `device_id`, `state`, `code_verifier`; профиль — `POST` с `access_token` и `client_id`; email возвращается только при scope `email` и считается неподтверждённым; JS SDK VK ID (One Tap) не используется — только redirect-флоу, чтобы серверный код был общим с мобильными клиентами |

- Связывание и создание:
  1. Есть `external_accounts(provider, subject)` → вход этим пользователем (если `status = 'blocked'` — `403 user_blocked`).
  2. Иначе, если `link_user_id` задан → привязать к нему (если `subject` уже привязан к другому — `409 external_account_taken`).
  3. Иначе, если провайдер вернул email и у пользователя с таким email `email_verified_at` не null и провайдер подтверждает email (Google `email_verified=true`, Яндекс `default_email`) → автоматическая привязка и вход (подтверждено пользователем 2026-10-10).
  4. Иначе, если email совпал, но не подтверждён провайдером (VK ID) → `409 account_exists_use_password`: страница предлагает войти паролем и привязать из настроек — для VK ID только явная привязка (подтверждено пользователем 2026-10-10).
  5. Иначе → новый пользователь без `credentials`, `email_verified_at` = now() если провайдер подтвердил email, роль `learner`, согласий нет → редирект на `/auth/complete-profile` (чекбоксы 18+ и персональные данные — OQ-14), до `POST /consents` доступ к обучению закрыт (SYS-06).
- Тесты: mock OIDC-провайдер (контейнер для интеграционных тестов и E2E; MSW для фронтенда) с discovery, authorize, token, userinfo; для Яндекс ID и VK ID — те же моки с их форматами ответов; реальные провайдеры — ручная проверка к G3 VIS-05 (OQ-12).

### 3.7. Выход, «выйти везде», блокировка, WebSocket

- `logout`: семейство текущего `sid` отзывается, `identity:revoked_sid:<sid>` на 600 с, cookie очищаются (`Max-Age=0`).
- `logout-all` и смена пароля: все семейства пользователя отзываются, `identity:revoked_user:<user_id>` = now на 600 с.
- Блокировка администратором (ADM-01): `users.status = 'blocked'`, отзыв всех семейств, `identity:revoked_user`, событие `identity.user_blocked` через outbox; инстансы с WebSocket-соединениями пользователя закрывают их с кодом `4401` (`session_revoked`) по сообщению в Redis pub/sub канала WebSocket-инфраструктуры (ADR-004). Разблокировка — `status = 'active'`, пользователь входит заново.
- WebSocket `/ws`: аутентификация один раз при handshake (cookie или `Authorization: Bearer <jwt>`), проверка заголовка `Origin` против `APP_PUBLIC_URL` для cookie-клиентов; идентичность соединения фиксируется (`user_id`, `sid`); истечение access-токена во время жизни соединения не разрывает его — отзыв делается событием (выше, через канал `ws:user:<user_id>` — ADR-004); при переподключении клиент сначала делает `POST /refresh` (ADR-005). Токен в query-string запрещён. `/ws/agent` аутентифицируется токеном агента модулем `local_runtime` (3.4), отзыв устройства закрывает соединение кодом `4401`.
- Без Redis: отзывы не видны до истечения access (≤ 10 минут, метрика и алерт); refresh и вход проверяют PostgreSQL и отзыв увидят сразу; лимит попыток входа не учитывается (fail-open, как лимиты API в ADR-003) — подтверждено пользователем 2026-10-10.

### 3.8. Shared kernel и boilerplate

Переиспользуется: `auth_user(permissions)`, `check_permissions`, `UserSecuritySchema` (расширяется полями `sid`, `roles`, `client`, `email_verified`, `age_confirmed`), классы permissions модулей, переопределение `get_current_user` в тестах. Заменяется: `AuthService` → `TokenVerifier` (несколько публичных ключей по `kid`, `EdDSA`, `aud`, async-проверка отзыва в Redis) в `app/core/security`; `get_current_user` принимает cookie и Bearer (раздел 3.4); зависимости `auth_user_optional` для роутов с анонимом и `auth_websocket` для handshake. Настройки `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ROLE_PERMISSIONS` удаляются; появляются `JWT_PUBLIC_KEYS` (необязательная), `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_CSRF_SECRET` (shared kernel) и `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID`, `IDENTITY_*`, `OAUTH_*` (секция настроек модуля `identity`). Реестр permissions: каждый модуль объявляет свои permissions в своём `app/modules/<module>/permissions.py` (ADR-002), `identity` держит матрицу «роль → permissions» из SYS-06 в коде (`app/modules/identity/permissions_matrix.py`) и отдаёт её ядру через интерфейс `RolePermissionsProvider` в своём `module.py` (`ModuleDefinition`); ядро берёт провайдера из реестра модулей при старте — это единственная зависимость ядра от модуля, и она идёт через интерфейс, объявленный в ядре (ADR-002 фиксирует механизм регистрации).

### 3.9. Что реализуется на этапе 1

Г.5: таблицы `users`, `credentials`, `roles`, `user_roles`, `consents`, `refresh_tokens`, `one_time_tokens`; `TokenIssuer`, `TokenVerifier`, cookie и Bearer, CSRF, `login`, `refresh`, `logout`, `me`, `jwks.json`, лимит попыток, блокировка через `status`, события `identity.user_registered`, `identity.user_blocked`, `identity.session_revoked`; CLI `issue-token` и `create-user` для тестового пользователя Г.11; тесты на N инстансах: вход на инстансе A, запрос с cookie на инстанс B, refresh на C, `logout-all` на A закрывает WebSocket на B. Этап 2: регистрация, подтверждение email, восстановление пароля, OAuth, сессии, экраны.

## 4. Последствия

### 4.1. Положительные

- Любой инстанс и любой будущий сервис проверяет токен без вызова `identity` и без БД.
- Сбой Redis не разлогинивает: теряется только мгновенный отзыв на ≤ 10 минут.
- Один бэкенд для браузера, мобильных приложений и агента; OAuth-эндпоинт `exchange` зарезервирован для нативных клиентов.
- Повторное использование украденного refresh-токена обнаруживается и отзывает сессию.
- Согласия 152-ФЗ и 18+ — отдельная таблица с версией текста, пригодная для аудита.

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Окно до 10 минут между блокировкой и отказом в доступе при недоступном Redis | Метрика и алерт на `flt_auth_revocation_check_skipped_total` (ADR-010); refresh проверяет PostgreSQL; Redis с репликой и Sentinel в Kubernetes; принято пользователем 2026-10-10 |
| Собственный код OAuth для трёх провайдеров с разными особенностями (VK ID `device_id`) | `authlib` для общей части; контрактные тесты с mock-провайдерами на каждый ответ; ручная проверка к G3 VIS-05 |
| Ротация ключей — ручная процедура из трёх шагов | Описана в 3.3 и в runbook SYS-11; поддержка нескольких `kid` делает ошибку порядка безопасной |
| `SameSite=Lax` у access-cookie допускает top-level GET-переходы с cookie | Изменяющие операции — только `POST`/`PUT`/`PATCH`/`DELETE` с CSRF-токеном; GET не меняет состояние (SYS-03) |
| `__Host-` cookie требуют `Secure`: стенд без TLS и не на `localhost` не работает | Все стенды за HAProxy с TLS (ADR-012); dev — `localhost` |
| Permissions не в токене: проверяющий зависит от матрицы ролей | Матрица — код `identity`, отдаётся ядру через интерфейс; при выделении `identity` в сервис матрица публикуется как часть JWKS-подобного документа (новый ADR) |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Заменить `AuthService` на `TokenVerifier`, `get_current_user` на cookie+Bearer, добавить `auth_user_optional`, `auth_websocket`; удалить `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ROLE_PERMISSIONS`, добавить `JWT_PUBLIC_KEYS`, `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_CSRF_SECRET` | `src/backend/py-monolyth/app/core/security/*`, `configs/settings.py`, `envs/*/*.env`, `.env.template` (этап 1 Г.4) | Claude | не начато |
| Реализовать модуль `identity` в объёме 3.9 | `src/backend/py-monolyth/app/modules/identity/*` по ADR-002 (этап 1 Г.5) | Claude | не начато |
| Перевести `cli issue-token` на `TokenIssuer`, добавить `cli create-user`; генерация Ed25519-пары в `deploy/scripts/gen-secrets.sh` | `cli/main.py`, `deploy/scripts/gen-secrets.sh` (ADR-013) | Claude | не начато |
| Зависимости: `argon2-cffi`, `authlib`, `PyJWT[crypto]` (уже есть `jwt`), `citext` через миграцию | `pyproject.toml` | Claude | не начато |
| Переменные `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID`, `JWT_PUBLIC_KEYS`, `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_CSRF_SECRET` (секрет — добавить в таблицу секретов ADR-013), `OAUTH_<PROVIDER>_ENABLED`, `OAUTH_<PROVIDER>_CLIENT_ID`, `OAUTH_<PROVIDER>_CLIENT_SECRET`, `APP_PUBLIC_URL`, `IDENTITY_ACCESS_TTL_SECONDS`, `IDENTITY_REFRESH_TTL_DAYS_*`, `IDENTITY_SESSION_MAX_DAYS` | `deploy/docker-compose/docker-compose.yml` (`.env`) и `deploy/helm` (Vault, ADR-013) одновременно | Claude | не начато |
| Обновить «Отличия проекта от boilerplate» п. 6 (выпуск токенов → реализовано по ADR-006), «Технологический стек → Аутентификация» (cookie/Bearer, EdDSA), «Ключевые архитектурные требования» (152-ФЗ: таблица `consents`) | CLAUDE.md | Claude после accepted | не начато |
| Матрица «роль × действие», правило доступа без 18+/email, набор санкций (OQ-54), реестр permissions из модулей | SYS-06 | Claude (черновик), человек (G1) | не начато |
| Тексты согласий и чекбокса 18+, версия текста, политика паролей и лимитов, период ротации ключей 180 дней, срок хранения `refresh_tokens` после отзыва (90 дней для аудита) | SYS-02 | Claude | не начато |
| Пути `/api/v1/auth/*` (исключение из правила ADR-002 «префикс роутера = имя модуля»: путь задан OQ-12 для redirect URI и используется ACL HAProxy в ADR-012), коды ошибок `invalid_credentials`, `refresh_reused`, `csrf_invalid`, `user_blocked`, `account_exists_use_password`, `external_account_taken` в `ErrorResponseV1` | SYS-03 | Claude | не начато |
| Аутентификация WebSocket при handshake, проверка `Origin`, код закрытия `4401`, канал Redis pub/sub для отзыва сессий | ADR-004, SYS-04 | Claude | не начато |
| Клиент: интерсепторы cookie/CSRF/refresh, `src/lib/auth.tsx` на сгенерированном клиенте | ADR-005 (сделано в черновике), `src/frontend` (этап 1 Г.7) | Claude | не начато |
| Сопряжение агента и токен `flta_…` описаны в ADR-008 (эндпоинты `/api/v1/local-runtime/pairings`); здесь — отклонение `flta_` в `TokenVerifier` и правило «`/ws/agent` проверяет `local_runtime`» | ADR-008, `app/core/security` | Claude | сделано в 0.2 (ADR), код — этап 4 |
| Контейнер mock OIDC-провайдера для интеграционных тестов и E2E (dev/test-профиль по правилу OQ-11) | SYS-10, `deploy/docker-compose` (профиль `test`) и `deploy/helm` (`values-dev.yaml`) | Claude | не начато |
| Чек-лист регистрации OAuth-приложений Google, Яндекс ID, VK ID (redirect URI, scope, домен из OQ-08) | `Analytics/Specs/identity/oauth-apps-checklist.md` (OQ-12, к началу этапа 1) | Claude | не начато |
| ТЗ VIS-04 и VIS-05: экраны, письма, `complete-profile`, сессии | `Analytics/Specs/identity/VIS-04-registration.md`, `VIS-05-login.md` (этап 2) | Claude | не начато |
| Контракт `identity` | `Analytics/Specs/identity/api/openapi.yaml`, `_module.md` (этап 1 В) | Claude | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-002](ADR-002-module-layout.md) | зависит от | раскладка `app/modules/identity`, исключение `/api/v1/auth` (`extra_prefixes`), регистрация `RolePermissionsProvider` в ядре |
| [ADR-003](ADR-003-state-storage.md) | зависит от | схема PostgreSQL `identity`, префикс Redis `identity:`, таблица поведения без Redis |
| [ADR-004](ADR-004-communication-patterns.md) | дополняет | handshake WebSocket, код `4401`, канал `ws:user:*`, событие `identity.session_revoked`, outbox |
| [ADR-005](ADR-005-frontend-stack.md) | дополняет | клиентская часть: cookie, `X-CSRF-Token`, refresh при 401 |
| [ADR-008](ADR-008-local-agent.md) | ограничен | токен агента `flta_…` — непрозрачный, выдаёт и проверяет `local_runtime`, только для `/ws/agent`; `identity` даёт публичный API для подтверждения сопряжения |
| [ADR-010](ADR-010-observability-stack.md) | дополняет | метрика `flt_auth_revocation_check_skipped_total`, маскирование токенов в логах |
| [ADR-012](ADR-012-haproxy-entry-point.md) | зависит от | TLS (нужен для `Secure`/`__Host-`), один origin |
| [ADR-013](ADR-013-secrets-management.md) | зависит от | имена и хранение `JWT_SIGNING_KEYS`, `JWT_ACTIVE_KID`, `OAUTH_*_CLIENT_SECRET`, `AUTH_CSRF_SECRET`; `gen-secrets.sh` |
| [SYS-02](../Specs/_system/SYS-02-non-functional-requirements.md) | дополняет | тексты согласий, 18+, политика паролей, ротация ключей |
| [SYS-03](../Specs/_system/SYS-03-rest-api-conventions.md) | дополняет | пути и коды ошибок аутентификации |
| [SYS-04](../Specs/_system/SYS-04-async-messaging.md) | дополняет | аутентификация WebSocket |
| [SYS-05](../Specs/_system/SYS-05-state-and-scaling.md) | ограничен | ключи Redis с TTL, поведение без Redis |
| [SYS-06](../Specs/_system/SYS-06-roles-and-permissions.md) | дополняет | роли `learner`, `teacher`, `platform_admin`, матрица прав, блокировка |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Решения пользователя 2026-10-10: fail-open проверки отзыва без Redis, refresh через PostgreSQL, автопривязка OAuth по подтверждённому email (Google, Яндекс ID), для VK ID — явная привязка. Согласование с ADR-008 (токен агента `flta_…` вместо пары access/refresh клиента `agent`, `POST /api/v1/auth/agent/pair` удалён), ADR-010 (имя метрики `flt_auth_revocation_check_skipped_total`), ADR-002 (`app/modules/identity`), ADR-004 (канал `ws:user:*`) | proposed |
| 1.0 | 2026-10-10 | пользователь | Принят без изменений (PR #2, слияние в main) | accepted |
