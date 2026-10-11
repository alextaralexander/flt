# ADR-012 — HAProxy как единая точка входа

| Поле | Значение |
|---|---|
| Статус | accepted |
| Версия | 1.1 |
| Дата | 2026-10-10 |
| Автор | Claude (черновик) |
| Утвердил | пользователь, 2026-10-10 (PR #2) |
| Пункт(ы) BRD | все |
| Модуль | все; конфигурация — `deploy/config/haproxy/` |
| Зависимости | ADR-004 (роли монолита и имена сервисов `api`/`worker`, WebSocket-эндпоинты `/ws` и `/ws/agent`, пути `/api/v1/<module>` без переписывания) |
| Связанные ADR/SYS | ADR-005 (CSP задаёт frontend), ADR-006 (пути аутентификации для лимитов), ADR-007 (файлы MinIO по путям `/flt-*`), ADR-008 (WebSocket агента), ADR-009 (таймауты туннеля, graceful shutdown), ADR-010 (`X-Request-ID`, readiness, метрики), ADR-011 (smoke-тесты), ADR-013 (сертификаты и секреты), ADR-015 (сигнализация LiveKit, TURN/TLS), SYS-02, SYS-03, SYS-11 |

## 1. Контекст

- **Проблема**: снаружи к платформе обращаются браузер (REST, WebSocket, статика), локальный агент ученика (WebSocket, ADR-008), позже — клиенты видеосвязи (сигнализация, ADR-015) и, возможно, прямые загрузки в MinIO (ADR-007). Монолит работает в N инстансах без sticky-сессий, инстансы появляются и исчезают (`--scale`, HPA, остановка посреди сценария). Нужна одна точка входа, которая завершает TLS, распределяет запросы по живым инстансам, различает REST и WebSocket по таймаутам, закрывает служебные эндпоинты и одинаково настраивается в docker-compose и Helm. CLAUDE.md даёт предварительную схему («Маршрутизация через HAProxy», TODO: ADR-012), OQ-22 перечисляет, что уточнить: сертификаты, таймауты WebSocket, заголовки `X-Forwarded-*` и `X-Request-ID`, ACL на служебные пути, маршруты для MinIO и медиасервера, лимиты частоты.
- **Почему сейчас**: этап 1, Г.3 (стенд из N инстансов за HAProxy для тестов масштабируемости), Г.8 (развёртывание), Г.11 (E2E с остановкой инстанса). Без HAProxy тесты на N инстансах невозможны.
- **Ограничения**:
  - CLAUDE.md, «Состав контейнеров» и «Маршрутизация через HAProxy»: HAProxy в отдельном контейнере (поде), TLS на нём, `/api/*` и `/ws/*` → монолит, остальное → Nginx, медиатрафик WebRTC мимо HAProxy, health-check по readiness, метрики и health наружу не публикуются; в Kubernetes — Service типа LoadBalancer с той же конфигурацией;
  - CLAUDE.md, «Масштабирование и состояние»: без sticky-сессий, корректность не зависит от инстанса; лимиты действуют глобально (в Redis) — HAProxy может быть только первым рубежом;
  - OQ-07 (решён): prod — docker-compose на VPS в РФ, Helm — в kind в CI; OQ-08 (отложен): dev — `flt.localhost`, домен prod выбирается до этапа 2;
  - OQ-11 (решён): Mailpit — dev-only сервис по профилю;
  - OQ-21 (решён): проверка по `/v1/ready`, служебные эндпоинты закрыты снаружи;
  - boilerplate: uvicorn запускается без `proxy_headers`, `ROOT_PATH` поддерживается; CORS настроен на `["*"]` для local.
- **Если не решить**: тесты масштабируемости и E2E Г.11 не на чем выполнять; compose и Helm получат разные прокси (Nginx против Ingress), и правило паритета нарушится с первого дня.
- **Ссылки**: CLAUDE.md «Маршрутизация через HAProxy», «Развёртывание», «Состав контейнеров»; SDD_plan.md этап 1 А.12, Г.3, Г.8, Г.11; OQ-18, OQ-22, OQ-23, OQ-28, OQ-29; ADR-004, ADR-007, ADR-010, ADR-013, ADR-015.

## 2. Рассматриваемые варианты

### Вариант A. HAProxy с одним `haproxy.cfg`, обнаружение инстансов через DNS-resolver-ы, Service LoadBalancer в Kubernetes

- **Описание**: контейнер `haproxy` (официальный образ `haproxy:3.2-alpine`, LTS) с конфигурацией `deploy/config/haproxy/haproxy.cfg`, одинаковой для compose (bind mount) и Helm (ConfigMap). Адреса backend-ов — переменные окружения (`API_HOST`, `FRONTEND_HOST`), резолвятся секцией `resolvers` с `parse-resolv-conf` (compose — `127.0.0.11`, Kubernetes — kube-dns): `server-template api 1-10 "${API_HOST}":8000 check resolvers platform init-addr libc,none`. В Kubernetes монолит публикуется headless Service (`clusterIP: None`), чтобы DNS отдавал IP подов, а не один ClusterIP, и балансировал HAProxy, а не kube-proxy. HAProxy публикуется Service типа LoadBalancer (в kind — NodePort с `extraPortMappings` 80/443 в конфигурации kind для CI).
- **Плюсы**:
  - один файл конфигурации, различия — только значения переменных окружения; паритет compose и Helm буквальный;
  - `server-template` подхватывает новые инстансы при `--scale` и HPA без перезагрузки;
  - активные проверки `/v1/ready` исключают инстанс за ~4 с, WebSocket и REST различаются таймаутами в одном frontend;
  - встроенный `prometheus-exporter` и stats page — без дополнительных контейнеров (ADR-010).
- **Минусы**:
  - HAProxy не умеет отдавать статику и выполнять ACME-челлендж сам (в 3.2 ACME-клиент экспериментальный): для сертификатов нужен certbot-контейнер, для статики — Nginx (он и так в составе);
  - в Kubernetes HAProxy дублирует роль ingress controller-а: при переходе prod на Kubernetes облачный балансировщик будет направлять трафик в HAProxy, а не в Ingress — лишний hop, зато та же конфигурация;
  - `init-addr libc,none` при старте без доступного DNS оставляет серверы в состоянии `MAINT` до первого успешного резолва (штатно).
- **Масштабирование на N инстансах**: round-robin по живым инстансам, без sticky; WebSocket-соединение привязано к одному инстансу на время жизни, события между инстансами идут через Redis pub/sub (SYS-05), после обрыва клиент переподключается к любому; остановка инстанса — HAProxy снимает его с балансировки по проверке или по ошибке соединения (`option redispatch`, `retries 2` для идемпотентных запросов). HAProxy сам без состояния, кроме stick-table лимитов в памяти (теряются при перезапуске — допустимо, глобальные лимиты в Redis).
- **Выделение модулей в микросервисы**: помогает — новый сервис получает свой `backend` и ACL по префиксу пути (`/api/v1/<module>/*`) без изменения клиентов.
- **Трудоёмкость и риски**: низкая; риски — обновление сертификатов без простоя (решено runtime API), поведение DNS compose при `--scale` (smoke-тест Г.8).

### Вариант B. Nginx как единая точка входа

- **Описание**: контейнер Nginx раздаёт статику и проксирует `/api`, `/ws` на `upstream` монолита; TLS на Nginx; certbot с webroot в том же контейнере или рядом.
- **Плюсы**:
  - один контейнер вместо двух (HAProxy + Nginx), статика и ACME-челлендж в нём же;
  - Nginx уже выбран для статики в CLAUDE.md, конфигурация Nginx нужна в любом случае.
- **Минусы**:
  - `upstream` с DNS-обнаружением реплик: Nginx open source резолвит имя один раз при старте (динамический `resolve` в `server` — только в Nginx Plus); для compose при `--scale` нужны перезагрузки или шаблонизация списка серверов;
  - активные health-check-и — только в Nginx Plus; open source снимает upstream пассивно, после ошибок реальных запросов (`max_fails`), то есть часть запросов пользователей уходит на мёртвый инстанс;
  - нет stick-table для лимитов по IP на уровне L7 с учётом состояния серверов (есть `limit_req`, достаточный, но без дашборда состояния backend-ов);
  - противоречит CLAUDE.md («Состав контейнеров»: HAProxy — единая точка входа, Nginx — статика).
- **Масштабирование на N инстансах**: работает при фиксированном списке; `--scale` и HPA требуют перезагрузки или `ngx_http_js`-резолва.
- **Выделение модулей в микросервисы**: нейтрально.
- **Трудоёмкость и риски**: низкая на старте, выше при росте N; изменение утверждённого состава контейнеров.

### Вариант C. Traefik

- **Описание**: Traefik с provider-ами `docker` (compose) и `kubernetesIngress` (Helm), автоматический ACME.
- **Плюсы**: встроенный ACME без certbot; обнаружение сервисов по меткам контейнеров и Ingress без списка серверов.
- **Минусы**: конфигурации для compose и Kubernetes разные по природе (метки контейнеров против Ingress-ресурсов) — паритет только по смыслу, не по файлам; Traefik в compose требует доступа к Docker-сокету; health-check-и backend-ов и stick-table-лимиты слабее; противоречит CLAUDE.md.
- **Масштабирование на N инстансах**: работает через provider-ы.
- **Выделение модулей в микросервисы**: помогает (метки на новый сервис).
- **Трудоёмкость и риски**: средняя; Docker-сокет в прокси — риск безопасности на VPS.

## 3. Решение

- **Выбран**: Вариант A.
- **Решение**: единственная точка входа снаружи — контейнер HAProxy с одним `deploy/config/haproxy/haproxy.cfg` для compose и Helm; он завершает TLS, маршрутизирует `/api/*` (без переписывания пути: монолит сам обслуживает `/api/v1/<module>/...`, ADR-004) и `/ws/*` (включая `/ws/agent`, `timeout tunnel 1h`) на инстансы монолита роли `api` (round-robin, без sticky-сессий, обнаружение через DNS и `server-template`, исключение по `/v1/ready`), `/flt-*` — на MinIO без переписывания пути и `Host` (ADR-007), `/livekit/*` — на сигнализацию LiveKit (зарезервировано, ADR-015), всё остальное — на Nginx со статикой; закрывает документацию API снаружи (`/api/docs`, `/api/openapi.json` — ACL, на local и dev открывается переменной `FLT_EXPOSE_DOCS`), генерирует `X-Request-ID`, задаёт `X-Forwarded-*`, применяет первый рубеж лимитов по IP и отдаёт метрики Prometheus на внутреннем порту `8404`; в Kubernetes публикуется Service типа LoadBalancer. Единственное исключение из правила «TLS только на HAProxy» — TURN/TLS на порту 5349 у LiveKit (ADR-015).
- **Обоснование**: только HAProxy даёт активные проверки readiness, DNS-обнаружение реплик и единый файл конфигурации в обоих вариантах развёртывания в open-source версии; это соответствует утверждённому составу контейнеров. Недостаток (ACME и статика вне HAProxy) закрывается уже имеющимся Nginx и небольшим certbot-контейнером.
- **Отвергнуты**:
  - Вариант B — пассивные health-check-и и статический upstream в Nginx open source не удовлетворяют тестам масштабируемости (остановка инстанса посреди сценария).
  - Вариант C — конфигурации compose и Kubernetes не совпадают по файлам, нужен Docker-сокет.
- **Границы решения**: ADR не выбирает медиасервер и его порты (ADR-015), не решает способ доступа к файлам MinIO (ADR-007; здесь только зарезервирован маршрут и указано ограничение presigned URL), не задаёт Content-Security-Policy frontend-а (ADR-005), не выбирает формат токена и путь входа (ADR-006), не описывает структуру Helm chart (SYS-11, OQ-28).

### 3.1. Маршруты

| Маршрут (ACL) | Backend | Назначение | Условие включения |
|---|---|---|---|
| `path_beg /api/` | `be_api` — инстансы монолита роли `api`, порт 8000 | REST `/api/v1/<module>/...` (ADR-004); путь не переписывается | всегда |
| `path_beg /ws/` или `path /ws` | `be_api_ws` — те же инстансы, таймауты tunnel | WebSocket фронтенда `/ws` и локального агента `/ws/agent` (ADR-004, ADR-008) | всегда |
| `path_beg /.well-known/acme-challenge/` | `be_frontend` (Nginx отдаёт webroot certbot) | ACME HTTP-01 | `.if defined(FLT_TLS_DOMAIN)` |
| `path_beg /api/docs`, `path_beg /api/redoc`, `path /api/openapi.json` | — | документация API: `http-request deny deny_status 404` | всегда на prod; на local и dev открыты (`.if defined(FLT_EXPOSE_DOCS)`) |
| `path_beg /flt-` | `be_minio` — `${MINIO_HOST}:9000`, таймауты 600 с | presigned URL и публичные объекты MinIO path-style: все бакеты называются `flt-<module>` (ADR-007); путь и `Host` не переписываются, поэтому подпись SigV4 остаётся валидной; ACL: методы `GET HEAD PUT POST`, на уровне бакета — только `POST` | `.if defined(MINIO_HOST)` |
| `path_beg /livekit/` | `be_livekit` — `${LIVEKIT_HOST}:7880`, таймауты tunnel | сигнализация LiveKit (WebSocket) со снятием префикса `/livekit` (единственный маршрут с переписыванием пути: подписи в нём нет, а сервер LiveKit ожидает `/rtc` в корне); `/livekit/twirp/*` снаружи — 403; медиа (UDP/TCP порты LiveKit) публикуются напрямую, мимо HAProxy | `.if defined(LIVEKIT_HOST)` — зарезервировано до этапа 6 (ADR-015) |
| всё остальное | `be_frontend` — `${FRONTEND_HOST}:8080` (Nginx) | статика frontend, SPA fallback делает Nginx | всегда |

Правила:
- путь `/api/...` передаётся монолиту без изменений: монолит сам обслуживает `/api/v1/<module>/...`, `/api/docs`, `/api/openapi.json` (ADR-004); `ROOT_PATH` и `replace-path` не используются, поэтому OpenAPI совпадает с внешними URL без настройки. Для `/ws` префикс тоже сохраняется: монолит монтирует `/ws` и `/ws/agent` (ADR-004);
- служебные эндпоинты монолита `/v1/health`, `/v1/ready`, `/v1/metrics` (api на `:8000`, worker на `:8001`) и `/asyncapi/kafka` лежат вне `/api` и `/ws`, поэтому через HAProxy недостижимы без отдельных ACL (запрос `/v1/...` уходит на Nginx и получает SPA-страницу или 404); доступны только во внутренней сети (Prometheus, HAProxy, probes); порт 8000 монолита на хост не публикуется (текущее `ports: "8000:8000"` в compose убирается; для `make dev` на хосте монолит запускается без HAProxy). Роль `worker` за HAProxy не стоит, health-check выполняется только по инстансам `api`;
- **presigned URL**: подпись S3 покрывает хост и канонический путь, поэтому маршрут хранилища не переписывает ни путь, ни `Host`. Вариант `/s3/*` со снятием префикса отвергнут (ломает подпись), вариант отдельного имени `s3.<домен>` отвергнут (требует DNS-записи и SAN в сертификате до выбора домена, делает загрузку cross-origin). Принято: ACL `path_beg /flt-` → `be_minio` (ADR-007, 3.5); монолит подписывает URL с публичным адресом `S3_PUBLIC_BASE_URL` = origin приложения;
- Mailpit UI (dev-only, OQ-11) публикуется собственным портом `8025` на loopback хоста в профиле `dev`, через HAProxy не проходит;
- TLS завершается на HAProxy; единственное исключение — TURN/TLS LiveKit на порту 5349, который завершает TLS сам тем же сертификатом с тома только для чтения (ADR-015).

### 3.2. Фрагмент `haproxy.cfg`

```haproxy
global
    log stdout format raw local0 info
    stats socket /var/run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    maxconn 4096
    ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets
    ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256
    tune.ssl.default-dh-param 2048

resolvers platform
    parse-resolv-conf              # compose: 127.0.0.11; Kubernetes: kube-dns
    resolve_retries 3
    timeout resolve 1s
    timeout retry   1s
    hold valid      10s
    hold obsolete   30s

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    option  forwardfor except 127.0.0.0/8
    option  redispatch
    retries 2
    timeout connect      5s
    timeout check        1s
    timeout client       30s
    timeout server       60s
    timeout http-request 10s
    timeout http-keep-alive 10s
    timeout queue        10s
    timeout tunnel       1h
    timeout client-fin   30s
    log-format '{"@timestamp":"%Tl","request_id":"%ID","client_ip":"%ci","method":"%HM","path":"%HPO","status":%ST,"backend":"%b","server":"%s","duration_ms":%Ta,"bytes":%B,"ssl":"%sslv","termination":"%ts"}'

frontend fe_http
    bind :80
    http-request return status 200 content-type text/plain string ok if { path /healthz }
    .if defined(FLT_TLS_DOMAIN)
    acl acme path_beg /.well-known/acme-challenge/
    use_backend be_frontend if acme
    http-request redirect scheme https code 301 unless acme
    .else
    default_backend be_frontend
    use_backend be_api_ws if { path_beg /ws/ } || { path /ws }
    use_backend be_api    if { path_beg /api/ }
    .endif

.if defined(FLT_TLS_DOMAIN)
frontend fe_https
    bind :443 ssl crt /etc/haproxy/certs/ alpn h2,http/1.1
    http-request set-header X-Forwarded-Proto https
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains"
.else
frontend fe_plain
    bind :8080
    http-request set-header X-Forwarded-Proto http
.endif
    # общая часть обоих frontend-ов вынесена в defaults/ACL-файлы при реализации; здесь — по смыслу
    unique-id-format %[uuid()]
    unique-id-header X-Request-ID
    http-request set-header X-Request-ID %[unique-id]
    http-request set-header X-Forwarded-For %[src]
    http-request set-header X-Real-IP %[src]
    http-request del-header Proxy
    http-response set-header X-Content-Type-Options nosniff
    http-response set-header Referrer-Policy strict-origin-when-cross-origin
    http-response set-header X-Frame-Options DENY
    http-response set-header Permissions-Policy "camera=(self), microphone=(self), geolocation=()"

    # документация API закрыта снаружи (служебные /v1/* лежат вне /api и до монолита не доходят)
    acl docs_paths path_beg /api/docs /api/redoc /api/openapi.json
    .if !defined(FLT_EXPOSE_DOCS)
    http-request deny deny_status 404 if docs_paths
    .endif

    # размер тела: 25 МБ для REST (загрузки файлов — presigned POST/PUT в MinIO по /flt-*, ADR-007)
    http-request deny deny_status 413 if { path_beg /api/ } { req.hdr_val(content-length) gt 26214400 }

    # хранилище: path-style S3, бакеты flt-<module> (ADR-007)
    .if defined(MINIO_HOST)
    acl is_s3            path_beg /flt-
    acl s3_method_ok     method GET HEAD PUT POST
    acl s3_bucket_level  path_reg ^/flt-[a-z0-9-]+/?$
    http-request deny deny_status 405 if is_s3 !s3_method_ok
    http-request deny deny_status 403 if is_s3 s3_bucket_level !METH_POST
    .endif

    # первый рубеж лимитов по IP (глобальные лимиты — в Redis, SYS-05)
    stick-table type ipv6 size 100k expire 10m store http_req_rate(10s)
    acl auth_paths path_beg /api/v1/auth/
    acl quick_test_paths path_beg /api/v1/assessment/quick-test
    http-request track-sc0 src if auth_paths || quick_test_paths
    http-request deny deny_status 429 if auth_paths { sc_http_req_rate(0) gt 20 }
    http-request deny deny_status 429 if quick_test_paths { sc_http_req_rate(0) gt 30 }

    # сжатие ответов REST; статику Nginx сжимает сам
    compression algo gzip
    compression type application/json text/plain

    use_backend be_api_ws if { path_beg /ws/ } || { path /ws }
    use_backend be_api    if { path_beg /api/ }
    .if defined(LIVEKIT_HOST)
    use_backend be_livekit if { path_beg /livekit/ }
    .endif
    .if defined(MINIO_HOST)
    use_backend be_minio if is_s3
    .endif
    default_backend be_frontend

backend be_api
    balance roundrobin
    option httpchk GET /v1/ready
    http-check expect status 200
    default-server inter 2s fastinter 500ms fall 3 rise 2 resolvers platform init-addr libc,none
    # путь не переписывается: монолит обслуживает /api/v1/<module>/... сам (ADR-004)
    server-template api 1-10 "${API_HOST}":8000 check

backend be_api_ws
    balance roundrobin
    option httpchk GET /v1/ready
    http-check expect status 200
    timeout server 1h
    default-server inter 2s fastinter 500ms fall 3 rise 2 resolvers platform init-addr libc,none
    server-template api 1-10 "${API_HOST}":8000 check

backend be_frontend
    balance roundrobin
    option httpchk GET /healthz
    default-server inter 5s fall 3 rise 2 resolvers platform init-addr libc,none
    server-template web 1-3 "${FRONTEND_HOST}":8080 check

.if defined(MINIO_HOST)
backend be_minio
    # путь и Host не меняются — подпись SigV4 presigned URL остаётся валидной (ADR-007)
    http-response set-header X-Content-Type-Options nosniff
    http-response set-header Content-Security-Policy "default-src 'none'; sandbox"
    timeout server 600s
    timeout client 600s
    server minio1 "${MINIO_HOST}":9000 check
.endif

.if defined(LIVEKIT_HOST)
backend be_livekit
    # единственный маршрут со снятием префикса (ADR-015); /livekit/twirp/* снаружи запрещён
    http-request deny deny_status 403 if { path_beg /livekit/twirp/ }
    http-request replace-path /livekit(/.*) \1
    timeout tunnel 1h
    server livekit1 "${LIVEKIT_HOST}":7880 check
.endif

listen stats
    bind :8404
    stats enable
    stats uri /stats
    stats refresh 10s
    http-request use-service prometheus-exporter if { path /metrics }
```

Порт `8404` не публикуется наружу: в compose — только внутренняя сеть (Prometheus обращается по `haproxy:8404`), в Kubernetes — отдельный Service ClusterIP с аннотациями `prometheus.io/*` (ADR-010). В реализации (Г.8) общая часть frontend-ов оформляется без дублирования; фрагмент выше задаёт смысл, а не дословный файл.

### 3.3. TLS и сертификаты

- **prod (compose на VPS)**: Let's Encrypt через контейнер `certbot/certbot` в режиме webroot: webroot — volume `acme-webroot`, который Nginx отдаёт по `/.well-known/acme-challenge/` (маршрут выше). Выпуск — `certbot certonly --webroot -w /var/www/acme -d ${FLT_TLS_DOMAIN}` (одно имя: хранилище и сигнализация LiveKit работают на том же хосте по путям, отдельных SAN не нужно); тот же `fullchain.pem`/`privkey.pem` монтируется только для чтения в контейнер LiveKit для TURN/TLS 5349 (ADR-015); обновление — контейнер `certbot` запускает `certbot renew` каждые 12 ч; deploy-hook собирает `fullchain.pem` + `privkey.pem` в `/etc/haproxy/certs/${FLT_TLS_DOMAIN}.pem` (volume `haproxy-certs`) и загружает его в HAProxy без перезапуска через runtime API по сокету на общем volume: `set ssl cert`, `commit ssl cert` (`socat` в образе certbot-hook). Первый выпуск до запуска HAProxy с TLS — скрипт `deploy/scripts/tls-bootstrap.sh`: поднимает HAProxy без `FLT_TLS_DOMAIN` (только :80), получает сертификат, затем перезапускает с TLS.
- **dev и local**: `FLT_TLS_DOMAIN` не задан — HAProxy слушает `:80` и `:8080` без TLS на `flt.localhost` (разрешается в `127.0.0.1` браузерами без записи в hosts); HSTS не выставляется. Самоподписанный сертификат не используется: он требует исключений в браузере и Playwright без пользы для тестов.
- **CI (kind)**: как dev — без TLS; проверка TLS-ветки конфигурации — `haproxy -c -f haproxy.cfg` с заданной `FLT_TLS_DOMAIN` и тестовым самоподписанным `.pem`, сгенерированным в job.
- **Kubernetes (при переходе prod)**: cert-manager с `ClusterIssuer` Let's Encrypt HTTP-01 (solver через тот же маршрут) создаёт Secret `flt-tls`; Helm монтирует его в под HAProxy как `/etc/haproxy/certs/`; обновление подхватывается перезапуском пода (аннотация stakater Reloader или `kubectl rollout restart` из CD) — допустимый кратковременный перезапуск при 2 репликах HAProxy. Деталь фиксируется в SYS-11 при переходе (OQ-07).
- Политика: TLS 1.2 и 1.3, HTTP/2 через ALPN, редирект HTTP → HTTPS 301 (кроме ACME), HSTS 1 год с `includeSubDomains` (без `preload` до стабилизации домена, OQ-08).

### 3.4. Заголовки безопасности и доверие прокси

- HAProxy выставляет HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`. **Content-Security-Policy задаёт Nginx** для HTML-ответов (`deploy/config/nginx/`): политика зависит от сборки frontend (хэши inline-скриптов Vite, `connect-src` для `/api` и `/ws`, источники шрифтов) и принадлежит ADR-005; HAProxy CSP не трогает, чтобы не держать два источника одной политики.
- HAProxy перезаписывает `X-Forwarded-For` и `X-Real-IP` значением `src` (клиентские значения отбрасываются) и выставляет `X-Forwarded-Proto`. Монолит доверяет этим заголовкам: точка входа `python -m app` (роль `api`, ADR-004) запускает uvicorn с `proxy_headers=True`, `forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS` (новая настройка; по умолчанию `*`, так как порт 8000 доступен только из внутренней сети; на стенде local при запуске без HAProxy — `127.0.0.1`). Лимиты в Redis и логи используют IP из `request.client.host`, который uvicorn заполняет из `X-Forwarded-For`.
- `X-Request-ID` генерируется HAProxy (`uuid()`), пишется в его лог и передаётся монолиту; монолит возвращает его в ответе (ADR-010). Клиентский `X-Request-ID` не принимается (перезаписывается).
- CORS: frontend, API и хранилище на одном origin, поэтому `ALLOW_ORIGINS` монолита на prod — пустой список, CORS на MinIO не настраивается; `["*"]` остаётся только на local для `pnpm dev` на порту 3000 (dev-прокси Vite проксирует `/api`, `/ws`, `/flt-*` — ADR-005).

### 3.5. Балансировка, проверки и таймауты

- `balance roundrobin`, без `cookie` и `stick on` — sticky-сессий нет.
- Проверка `GET /v1/ready` каждые 2 с, после первой неудачи — каждые 0,5 с (`fastinter 500ms`), таймаут проверки 1 с (`timeout check 1s`); инстанс снимается после 3 неудач (`fall 3`, ≈ 4 с, в пределах 10 с SYS-05-R41) и возвращается после 2 успехов (`rise 2`); ответ 503 readiness (ADR-010) считается неудачей. Без `fastinter` и `timeout check` остановленный инстанс снимался за 9–12 с (выявлено на стенде N3, PR #5).
- Таймауты: `connect 5s`, `client 30s`, `server 60s` для REST (длительные операции идут через Kafka и WebSocket, SYS-04), `tunnel 1h` для WebSocket `/ws`, `/ws/agent` и `/livekit/*` (клиент и агент шлют ping раз в 30 с — SYS-04; `timeout tunnel` сбрасывается трафиком), `server 600s` для `/flt-*` (крупные загрузки), `http-request 10s` против slowloris.
- При остановке инстанса: readiness отвечает 503 и инстанс снимается с балансировки, активным стримам даётся `SHUTDOWN_GRACE_SECONDS=30` (ADR-009), затем WebSocket-соединения закрываются кодом 1012 — клиент переподключается к другому инстансу и восстанавливает состояние (SYS-04, SYS-05); REST-запросы в полёте к мёртвому инстансу повторяются HAProxy (`option redispatch`, `retries 2`) только если соединение не установилось; запросы с уже отправленным телом не повторяются (идемпотентность — зона SYS-03).
- `maxconn 4096` в `global` (OQ-13: 300 WebSocket и 100 пользователей — запас десятикратный); лимит на backend — `maxconn 1000` на сервер (uvicorn без воркеров-процессов, `--limit-concurrency` задаёт SYS-11).

### 3.6. Обнаружение инстансов

- **compose**: сервис монолита роли `api` называется `api` (ADR-004), `deploy.replicas: 3` (по умолчанию стенда из N инстансов) или `docker compose up --scale api=3`; `API_HOST=api`, `FRONTEND_HOST=frontend`. Встроенный DNS Docker (`127.0.0.11`) возвращает A-записи всех контейнеров сервиса; `server-template api 1-10` резервирует 10 слотов, незанятые остаются `MAINT`. Проверка — smoke-тест Г.8: после `--scale api=3` на `http://haproxy:8404/stats;csv` три сервера `be_api` в состоянии `UP`; после `docker compose stop` одного контейнера — через 10 с `DOWN`, E2E Г.11 завершается успешно.
- **Kubernetes**: headless Service `flt-api` (`clusterIP: None`, `publishNotReadyAddresses: false`), `API_HOST=flt-api.<namespace>.svc.cluster.local`; kube-dns отдаёт IP готовых подов, HAProxy дополнительно проверяет `/v1/ready` сам. HAProxy — Deployment с 2 репликами (`values-ci.yaml` — 1), Service типа LoadBalancer (`values-prod`), NodePort 30080/30443 с `extraPortMappings` kind (`values-ci.yaml`). Ingress controller не устанавливается: HAProxy и есть точка входа, конфигурация одна с compose. MetalLB на kind не нужен для smoke; при переходе на собственный кластер (OQ-07, вариант 2) — MetalLB, при managed — облачный балансировщик, оба за пределами chart-а.

### 3.7. Наблюдаемость HAProxy

- Логи — JSON в stdout (формат выше) с `request_id`, собирает Fluent Bit (ADR-010), в OpenSearch поле `request_id` совпадает с логами монолита.
- Метрики — встроенный `prometheus-exporter` на `:8404/metrics` (`haproxy_backend_up`, `haproxy_server_check_status`, `haproxy_frontend_http_responses_total`, `haproxy_backend_response_time_average_seconds`); дашборд `flt-haproxy.json` и алерт `FltReadinessFailing` — ADR-010.
- Stats page `:8404/stats` — внутренняя сеть; на VPS доступ через SSH-туннель.

## 4. Последствия

### 4.1. Положительные

- Стенд из N инстансов для тестов масштабируемости и E2E с остановкой инстанса работает одинаково локально, в CI и на VPS.
- Один `haproxy.cfg` в `deploy/config/haproxy/` — паритет compose и Helm по файлу, а не по смыслу.
- Служебные эндпоинты, Swagger и AsyncAPI на prod недоступны снаружи без изменений в коде монолита.
- `request_id` появляется до монолита и связывает логи HAProxy и инстансов.
- Первый рубеж против перебора паролей и злоупотребления быстрым тестом не нагружает Redis и монолит.

### 4.2. Отрицательные и их смягчение

| Последствие | Смягчение |
|---|---|
| Два контейнера на входе (HAProxy и Nginx) вместо одного | Nginx и так нужен для статики по CLAUDE.md; его конфигурация минимальна (статика, SPA fallback, CSP, webroot ACME) |
| Лимиты stick-table — на инстанс HAProxy, не глобальны при 2 репликах HAProxy в Kubernetes | Это первый рубеж; глобальные лимиты — в Redis (SYS-05, OQ-09, OQ-10); peers-синхронизация stick-table добавляется при переходе на Kubernetes, если понадобится |
| Обновление сертификата зависит от certbot-контейнера и runtime API | Алерт на срок действия сертификата (`haproxy_frontend_ssl_*` нет; используется `probe` blackbox-exporter — добавляется в ADR-010 как вспомогательный контейнер при появлении TLS на prod, этап 2); ручная команда `make tls-renew` |
| Пространство путей `/flt-*` на хосте приложения отдано хранилищу | имена бакетов фиксированы (`flt-<module>`), фронтенд не создаёт маршруты с таким префиксом (ADR-005, ADR-007); smoke-тест проверяет, что `/flt-materials/` снаружи даёт 403 |
| При старте HAProxy раньше DNS-записей backend-ы в `MAINT` до первого резолва | `hold valid 10s`, `init-addr libc,none`; compose `depends_on` с `condition: service_healthy` на `api` |
| WebSocket-соединения рвутся при остановке инстанса | Это требование CLAUDE.md «Инстанс можно остановить в любой момент»; переподключение с восстановлением состояния — SYS-04 |

### 4.3. Что нужно сделать

| Действие | Где | Кто | Статус |
|---|---|---|---|
| Заменить предварительную схему на утверждённую: таблица маршрутов 3.1, служебные пути закрыты, `request_id` от HAProxy, CSP у Nginx, TLS через certbot и runtime API, headless Service и DNS-обнаружение, порт 8000 не публикуется | CLAUDE.md, раздел «Маршрутизация через HAProxy»; «Развёртывание» (пункт о Service LoadBalancer дополнить kind NodePort); «Состав контейнеров» (строки HAProxy и Nginx, добавить certbot как вспомогательный контейнер prod) | Claude | не начато |
| Добавить настройку `FORWARDED_ALLOW_IPS`, запуск uvicorn с `proxy_headers=True` в точке входа `python -m app`; удалить `ROOT_PATH` из настроек и всех `envs/*` (в том числе `ROOT_PATH=/api/flt-ba-as-de-ms-py-my-service` из `envs/dev/dev.env`); `ALLOW_ORIGINS` по стендам; OpenAPI на `/api/docs`, `/api/openapi.json` | `src/backend/py-monolyth` (`configs/settings.py`, `app/__main__.py`, `envs/*`) | Claude, этап 1 Г.1 | не начато |
| Монтировать REST под `/api/v1/<module>` и WebSocket под `/ws`, `/ws/agent` без снятия префикса; роль `api` обслуживает оба | ADR-004 (сделано в 0.2), спецификация shared kernel | Claude | ADR — сделано; спецификация — не начато |
| Создать `deploy/config/haproxy/haproxy.cfg`, `deploy/config/nginx/frontend.conf` (имя файла — ADR-005: статика, SPA fallback, CSP, `/healthz`, webroot ACME), `deploy/scripts/tls-bootstrap.sh`, deploy-hook certbot | `deploy/config/`, `deploy/scripts/` | Claude, этап 1 Г.8 | не начато |
| Добавить сервисы `haproxy` (порты 80, 443 наружу; 8404 внутри), `frontend` (Nginx), `certbot` (профиль `prod`), volume-ы `haproxy-certs`, `acme-webroot`, `haproxy-socket`; `api` с `deploy.replicas: 3` и без `ports`; переменные `FLT_TLS_DOMAIN`, `FLT_EXPOSE_DOCS`, `API_HOST`, `FRONTEND_HOST`, `MINIO_HOST` | `deploy/docker-compose/docker-compose.yml` и `deploy/helm` (Deployment и Service LoadBalancer HAProxy, ConfigMap из `haproxy.cfg`, headless Service `flt-api`, `values-ci.yaml` с NodePort) одновременно | Claude, этап 1 Г.8 | не начато |
| Smoke-тесты: `haproxy -c` для обеих веток конфигурации; три сервера `UP` после `--scale api=3`; `DOWN` после остановки; снаружи `GET /v1/metrics` и `GET /v1/ready` не достигают монолита (ответ Nginx), `GET /api/docs` — 404 без `FLT_EXPOSE_DOCS`; `GET /api/v1/auth/.well-known/jwks.json` — 200; `GET /flt-materials/` — 403; `429` после 21 запроса на `/api/v1/auth/login` за 10 с; `X-Request-ID` в ответе совпадает с логом | SYS-10 (методика), CI (ADR-011), этап 1 Г.8 и Г.11 | Claude | не начато |
| Требования: внешние пути `/api/v1/<module>/...` без переписывания, исключение `/api/v1/auth`, идемпотентность и повтор запросов, коды 413 и 429 в конверте ошибок или без него (ответы HAProxy — без конверта, задокументировать) | SYS-03 | Claude, этап 1 Б.3 | не начато |
| Требования: ping WebSocket раз в 30 с, переподключение при обрыве, `request_id` в сообщениях | SYS-04 | Claude, этап 1 Б.4 | не начато |
| Требования: стенд из N инстансов — compose с `--scale api=3` за HAProxy; остановка инстанса в тестах через `docker compose stop` | SYS-05, SYS-10 | Claude, этап 1 Б.5, Б.10 | не начато |
| Требования: порты VPS (80, 443, SSH), kind `extraPortMappings`, реплики HAProxy, `--limit-concurrency` uvicorn, размещение `.env` и volume-ов | SYS-11 | Claude, этап 1 Б.11 | не начато |
| Требования: лимиты HAProxy как первый рубеж, значения 20/10 с для auth и 30/10 с для быстрого теста (параметры), HSTS, заголовки безопасности, срок хранения логов HAProxy | SYS-02 | Claude, этап 1 Б.2 | не начато |
| ADR-007: маршрут хранилища `/flt-*` без переписывания пути и `Host` | `Analytics/ADR/ADR-007-file-storage.md` | Claude | сделано в 0.2 обоих ADR |
| ADR-015: маршрут `/livekit/` зарезервирован со снятием префикса; порты медиа и TURN/TLS 5349 публикуются мимо HAProxy | `Analytics/ADR/ADR-015-media-server.md` | Claude | сделано в 0.2 обоих ADR |
| ADR-005: CSP формируется Nginx из `deploy/config/nginx/`, значения — из сборки frontend | `Analytics/ADR/ADR-005-frontend-stack.md` | Claude (автор ADR-005) | не начато |
| Отметить в Г.8: certbot и Nginx-конфигурация входят в этап 1; TLS на prod включается при появлении домена (OQ-08, до этапа 2) | SDD_plan.md, этап 1 Г.8 | Claude | не начато |

## 5. Связанные решения

| Документ | Связь | Пояснение |
|---|---|---|
| [ADR-004](ADR-004-communication-patterns.md) | зависит от | Имена сервисов `api`/`worker`, пути `/api/v1/<module>` без переписывания, монтирование WebSocket под `/ws` и `/ws/agent`, роль, обслуживающая WebSocket |
| [ADR-005](ADR-005-frontend-stack.md) | ограничивает | CSP и статика — Nginx из сборки frontend; относительные пути `/api/v1`, `/ws`; dev-прокси `/flt-*` |
| [ADR-006](ADR-006-authentication-and-authorization.md) | дополняет | Пути `/api/v1/auth/*` под лимитами HAProxy; токен не зависит от инстанса |
| [ADR-007](ADR-007-file-storage.md) | ограничивает | Хранилище через HAProxy по путям `/flt-*` без переписывания пути и `Host`; ACL методов и уровня бакета |
| [ADR-008](ADR-008-local-agent.md) | дополняет | Агент подключается к `/ws/agent` через HAProxy, `timeout tunnel 1h` |
| [ADR-009](ADR-009-llm-streaming-and-voice.md) | дополняет | `timeout tunnel` для стримов и голоса, вывод инстанса из балансировки при остановке (`SHUTDOWN_GRACE_SECONDS`) |
| [ADR-010](ADR-010-observability-stack.md) | дополняет | `X-Request-ID`, проверка `/v1/ready`, метрики `8404`, JSON-логи HAProxy, алерты |
| [ADR-011](ADR-011-ci-cd.md) | дополняет | Smoke-тесты HAProxy в CI, kind с NodePort |
| [ADR-013](ADR-013-secrets-management.md) | зависит от | Приватный ключ сертификата на volume `haproxy-certs`, не в `.env`; права доступа |
| [ADR-015](ADR-015-media-server.md) | ограничивает | Сигнализация через `/livekit/` (единственный маршрут со снятием префикса), медиа мимо HAProxy, TURN/TLS 5349 — исключение из «TLS только на HAProxy» |
| [SYS-02](../Specs/_system/SYS-02-non-functional-requirements.md) | дополняет | Лимиты, заголовки безопасности, TLS-политика |
| [SYS-03](../Specs/_system/SYS-03-rest-api-conventions.md) | дополняет | Внешние пути `/api/v1/<module>`, исключение `/api/v1/auth`, коды 413 и 429 от прокси |
| [SYS-04](../Specs/_system/SYS-04-async-messaging.md) | дополняет | Ping и переподключение WebSocket под `timeout tunnel` |
| [SYS-11](../Specs/_system/SYS-11-deployment-and-environments.md) | дополняет | Порты, реплики, volume-ы, `values-ci.yaml`, переход на Kubernetes |
| OQ-22 | закрывает | Схема маршрутизации и TLS |
| OQ-18, OQ-23 | учитывает | Зарезервированы маршруты для MinIO и сигнализации |
| OQ-08 | зависит от | Домен prod нужен для первого выпуска сертификата |

## 6. История изменений

| Версия | Дата | Автор | Что изменилось | Статус |
|---|---|---|---|---|
| 0.1 | 2026-10-10 | Claude | Черновик | proposed |
| 0.2 | 2026-10-10 | Claude | Решения оркестратора: `/api/*` без переписывания пути и без `ROOT_PATH` (монолит обслуживает `/api/v1/<module>`, `/api/docs`, `/api/openapi.json`); служебные `/v1/*` вне `/api`; MinIO по путям `/flt-*` без переписывания (вместо `s3.<домен>`); `/ws/*` включает `/ws/agent`; `/livekit/*` — единственный маршрут со снятием префикса; исключение TURN/TLS 5349 (ADR-015); health-check только по `api`. Согласование с ADR-004 (`python -m app`), ADR-005 (`pnpm dev`, прокси `/flt-*`), ADR-007, ADR-009 (graceful shutdown), ADR-011 (smoke-проверки) | proposed |
| 1.0 | 2026-10-10 | пользователь | Принят без изменений (PR #2, слияние в main) | accepted |
| 1.1 | 2026-10-11 | пользователь | Без изменения решения, уточнения по стенду N3 (PR #5): маршрут WebSocket покрывает и `/ws` без завершающего слеша; `timeout check 1s` и `fastinter 500ms` — исключение остановленного инстанса за ≈ 4 с (SYS-05-R41) | accepted |
