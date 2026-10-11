/**
 * Единственный HTTP-клиент frontend (ADR-005, 3.5; ADR-006; SYS-03, раздел 4).
 *
 * - `baseURL` относительный (`/api/v1`): одна сборка на всех стендах, запросы
 *   идут через HAProxy на любой инстанс монолита;
 * - браузер аутентифицируется httpOnly-cookie (`withCredentials`), для
 *   изменяющих методов заголовок `X-CSRF-Token` = cookie `__Host-flt_csrf`;
 * - при `401` один single-flight `POST /auth/refresh` и повтор запроса,
 *   при повторном `401` — выход на экран входа;
 * - ошибки показываются уведомлением по коду `ErrorResponseV1` и ключу
 *   `common:errors.<code>` (SYS-07-R12), если `meta.notify !== false`.
 */
import type {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';
import Axios from 'axios';
import i18next from 'i18next';

import { useNotifications } from '@/components/ui/notifications/notifications-store';
import { env } from '@/config/env';
import { paths } from '@/config/paths';

export type ApiRequestMeta = {
  /** Показывать уведомление об ошибке (по умолчанию да). */
  notify?: boolean;
  /** Не выполнять refresh при 401 (сам запрос refresh). */
  skipAuthRefresh?: boolean;
};

declare module 'axios' {
  interface AxiosRequestConfig {
    meta?: ApiRequestMeta;
    /** Запрос уже повторён после refresh. */
    retriedAfterRefresh?: boolean;
  }
}

/** Конверт ошибки монолита (SYS-03-R7). */
export type ErrorResponseV1 = {
  messages?: {
    ERROR?: { code: string; message: string; details?: unknown }[];
  };
  payload?: unknown;
  request_id?: string;
};

export const CSRF_COOKIE = '__Host-flt_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';
export const REFRESH_PATH = '/auth/refresh';
const UNSAFE_METHODS = new Set(['post', 'put', 'patch', 'delete']);

export const readCookie = (
  name: string,
  cookieString: string = document.cookie,
): string | null => {
  for (const part of cookieString.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return null;
};

/** Добавляет CSRF-заголовок к изменяющим запросам (ADR-006, signed double-submit). */
export const csrfInterceptor = (
  config: InternalAxiosRequestConfig,
): InternalAxiosRequestConfig => {
  config.headers.set('Accept', 'application/json');
  if (UNSAFE_METHODS.has((config.method ?? 'get').toLowerCase())) {
    const token = readCookie(CSRF_COOKIE);
    if (token) config.headers.set(CSRF_HEADER, token);
  }
  return config;
};

/** Код ошибки из конверта `ErrorResponseV1`, если ответ — JSON монолита. */
export const errorCodeOf = (error: AxiosError): string | null => {
  const data = error.response?.data as ErrorResponseV1 | undefined;
  return data?.messages?.ERROR?.[0]?.code ?? null;
};

/** Текст ошибки для пользователя: по коду конверта или по статусу (не-JSON ответы HAProxy). */
export const errorMessageOf = (error: AxiosError): string => {
  const code = errorCodeOf(error);
  if (code && i18next.exists(`errors.${code}`)) {
    return i18next.t(`errors.${code}` as never);
  }
  switch (error.response?.status) {
    case 413:
      return i18next.t('errors.app.too-large');
    case 429:
      return i18next.t('errors.app.too-many-requests');
    case 503:
      return i18next.t('errors.app.unavailable');
    case undefined:
      return i18next.t('errors.app.network');
    default:
      return i18next.t('errors.app.request-failed');
  }
};

const notifyError = (error: AxiosError) => {
  if (error.config?.meta?.notify === false) return;
  const data = error.response?.data as ErrorResponseV1 | undefined;
  const requestId =
    data?.request_id ??
    (error.response?.headers?.['x-request-id'] as string | undefined);
  const message = errorMessageOf(error);
  useNotifications.getState().addNotification({
    type: 'error',
    title: i18next.t('errors.app.request-title'),
    message: requestId
      ? `${message} ${i18next.t('errors.app.request-id', { id: requestId })}`
      : message,
  });
};

const warnDeprecation = (response: AxiosResponse) => {
  const deprecation = response.headers?.deprecation;
  if (deprecation && import.meta.env.DEV) {
    console.warn(
      `[api] ${response.config.method?.toUpperCase()} ${response.config.url} is deprecated (${deprecation}), sunset: ${response.headers?.sunset ?? '—'}`,
    );
  }
};

type SessionExpiredHandler = () => void;

let onSessionExpired: SessionExpiredHandler = () => {
  window.location.assign(paths.auth.login.getHref(window.location.pathname));
};

/** Обработчик истёкшей сессии (сброс кэша `me` и переход на вход) задаёт слой аутентификации. */
export const setSessionExpiredHandler = (handler: SessionExpiredHandler) => {
  onSessionExpired = handler;
};

let refreshInFlight: Promise<void> | null = null;

/** Single-flight refresh: все параллельные 401 ждут один запрос. */
export const refreshSession = (): Promise<void> => {
  refreshInFlight ??= apiClient
    .post(REFRESH_PATH, undefined, {
      meta: { notify: false, skipAuthRefresh: true },
    })
    .then(() => undefined)
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
};

const createClient = (unwrapData: boolean): AxiosInstance => {
  const client = Axios.create({
    baseURL: env.API_URL,
    withCredentials: true,
  });
  client.interceptors.request.use(csrfInterceptor);
  client.interceptors.response.use(
    (response) => {
      warnDeprecation(response);
      return unwrapData ? response.data : response;
    },
    async (error: AxiosError) => {
      const config = error.config;
      if (
        error.response?.status === 401 &&
        config &&
        !config.meta?.skipAuthRefresh
      ) {
        if (!config.retriedAfterRefresh) {
          try {
            await refreshSession();
          } catch {
            onSessionExpired();
            return Promise.reject(error);
          }
          config.retriedAfterRefresh = true;
          return client.request(config);
        }
        onSessionExpired();
        return Promise.reject(error);
      }
      notifyError(error);
      return Promise.reject(error);
    },
  );
  return client;
};

/** Клиент FLT: возвращает `AxiosResponse`. */
export const apiClient = createClient(false);

/** Mutator для клиентов, сгенерированных orval (`override.mutator`). */
export const apiMutator = <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> =>
  apiClient
    .request<T>({ ...config, ...options })
    .then((response) => response.data);

/**
 * Клиент демо-фич bulletproof-react (ответ — сразу `data`).
 * Удаляется вместе с демо-фичами в этапе 1 Г.7 (ADR-005, 3.2 шаг 11).
 */
export const api = createClient(true);
