# Образ flt-frontend (ADR-005, 3.8; SYS-11): сборка статики и Nginx.
# Контекст сборки — корень репозитория:
#   docker build -f src/frontend/Dockerfile -t flt-frontend .
# Одна сборка для всех стендов: адреса бэкенда относительные (/api/v1, /ws),
# моки MSW выключены, служебные страницы этапа 1 выключены.

FROM node:24-alpine AS build
RUN corepack enable
WORKDIR /repo/src/frontend
COPY src/frontend/package.json src/frontend/pnpm-lock.yaml src/frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY src/frontend/ ./
# Контракты — для api:check: образ не собирается из устаревшего клиента
COPY Analytics/Specs /repo/Analytics/Specs
ENV VITE_APP_ENABLE_API_MOCKING=false \
    VITE_APP_ENABLE_DEV_PAGES=false
RUN pnpm api:check && pnpm build && rm -f dist/mockServiceWorker.js

FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY deploy/config/nginx/frontend.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/src/frontend/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
