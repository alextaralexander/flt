# deploy/config — общие конфигурации docker-compose и Helm

Единственный источник конфигураций инфраструктурных контейнеров (SYS-11-R1, R2; OQ-29).
docker-compose монтирует файлы отсюда bind-mount-ом только для чтения, Helm читает побайтовую
копию в `deploy/helm/flt/files/config/`, которую обновляет `uv run flt-tools deploy sync-config`
и проверяет `flt-tools deploy check-config` в CI. Различия между вариантами развёртывания —
только переменными окружения или парами файлов с суффиксом варианта (`*-compose.*`, `*-kubernetes.*`).

Каталоги появляются вместе с файлами на указанном этапе; пустые каталоги не создаются.

| Каталог | Файлы | Решение | Этап |
|---|---|---|---|
| `haproxy/` | `haproxy.cfg` | ADR-012 | 1 Г.8 |
| `nginx/` | `frontend.conf` (копируется в образ `flt-frontend`) | ADR-005 §3.8 | 1 Г.1 (frontend) |
| `prometheus/` | `prometheus.yml`, `scrape/compose.yml`, `scrape/kubernetes.yml`, `rules/*.yml` | ADR-010 | 1 Г.8, Г.9 |
| `grafana/` | `provisioning/{datasources,dashboards,alerting}/*.yml`, `dashboards/*.json` | ADR-010 | 1 Г.9 |
| `fluent-bit/` | `parsers.conf`, `filters.conf`, `output.conf`, `input-compose.conf`, `input-kubernetes.conf` | ADR-010 | 1 Г.9 |
| `opensearch/` | `Dockerfile`, `opensearch.yml`, `internal_users.yml`, `index-template-logs.json`, `ism-policy-logs.json` | ADR-010, ADR-014 | 1 Г.8, Г.9 |
| `redis/` | `redis.conf` | ADR-003 | 1 Г.8 |
| `postgres/` | `postgresql.conf` | ADR-003 | 1 Г.8 |
| `kafka/` | `server.properties.env` (переменные `KAFKA_*` для compose и Helm) | ADR-004 | 1 Г.8 |
| `livekit/` | `livekit.yaml` | ADR-015 | 6 |

Секреты сюда не попадают: только имена переменных окружения (ADR-013).
