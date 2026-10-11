import { HttpResponse, http } from 'msw';

import { useNotifications } from '@/components/ui/notifications/notifications-store';
import { env } from '@/config/env';
import { server } from '@/testing/mocks/server';

import {
  CSRF_HEADER,
  apiClient,
  apiMutator,
  readCookie,
  setSessionExpiredHandler,
} from './api-client';

const url = (path: string) => `${env.API_URL}${path}`;

const errorEnvelope = (code: string, requestId = 'req-1') => ({
  messages: {
    INFO: [],
    WARNING: [],
    ERROR: [{ code, message: 'english text', details: {} }],
  },
  payload: null,
  request_id: requestId,
});

const lastNotification = () => useNotifications.getState().notifications.at(-1);

describe('api-client', () => {
  const sessionExpired = vi.fn();

  beforeEach(() => {
    sessionExpired.mockReset();
    setSessionExpiredHandler(sessionExpired);
  });

  it('[SYS-03-R21] reads cookies by exact name', () => {
    expect(readCookie('__Host-flt_csrf', 'a=1; __Host-flt_csrf=x.y')).toBe(
      'x.y',
    );
    expect(readCookie('__Host-flt_csrf', 'flt_csrf=z')).toBeNull();
  });

  it('[SYS-02-R26][SYS-03-R21] sends X-CSRF-Token from __Host-flt_csrf only for unsafe methods', async () => {
    vi.spyOn(document, 'cookie', 'get').mockReturnValue(
      '__Host-flt_csrf=token.signature',
    );
    const seen: Record<string, string | null> = {};
    server.use(
      http.get(url('/csrf-probe'), ({ request }) => {
        seen.get = request.headers.get(CSRF_HEADER);
        return HttpResponse.json({ ok: true });
      }),
      http.post(url('/csrf-probe'), ({ request }) => {
        seen.post = request.headers.get(CSRF_HEADER);
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiClient.get('/csrf-probe');
    await apiClient.post('/csrf-probe', {});

    expect(seen.get).toBeNull();
    expect(seen.post).toBe('token.signature');
    vi.restoreAllMocks();
  });

  it('[SYS-03-R10] apiMutator returns the response body', async () => {
    server.use(http.get(url('/probe'), () => HttpResponse.json({ id: 1 })));
    await expect(apiMutator({ url: '/probe', method: 'GET' })).resolves.toEqual(
      { id: 1 },
    );
  });

  it('[SYS-03-R21] parallel 401 responses trigger a single refresh and are retried', async () => {
    let refreshCalls = 0;
    let authorized = false;
    server.use(
      http.post(url('/auth/refresh'), () => {
        refreshCalls += 1;
        authorized = true;
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(url('/protected'), () =>
        authorized
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json(errorEnvelope('identity.unauthenticated'), {
              status: 401,
            }),
      ),
    );

    const results = await Promise.all([
      apiMutator({ url: '/protected', method: 'GET' }),
      apiMutator({ url: '/protected', method: 'GET' }),
      apiMutator({ url: '/protected', method: 'GET' }),
    ]);

    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
    expect(sessionExpired).not.toHaveBeenCalled();
  });

  it('[SYS-03-R21] failed refresh leads to the login screen', async () => {
    server.use(
      http.post(url('/auth/refresh'), () =>
        HttpResponse.json(errorEnvelope('identity.refresh_invalid'), {
          status: 401,
        }),
      ),
      http.get(url('/protected'), () =>
        HttpResponse.json(errorEnvelope('identity.unauthenticated'), {
          status: 401,
        }),
      ),
    );

    await expect(
      apiMutator({ url: '/protected', method: 'GET' }),
    ).rejects.toThrow();
    expect(sessionExpired).toHaveBeenCalledTimes(1);
  });

  it('[SYS-07-R12] error notification is translated by code and carries request_id', async () => {
    server.use(
      http.get(url('/boom'), () =>
        HttpResponse.json(errorEnvelope('core.unknown_code', 'req-42'), {
          status: 400,
        }),
      ),
    );

    await expect(apiMutator({ url: '/boom', method: 'GET' })).rejects.toThrow();
    const notification = lastNotification();
    expect(notification?.title).toBe('Ошибка');
    expect(notification?.message).toContain('Не удалось выполнить запрос');
    expect(notification?.message).toContain('req-42');
    expect(notification?.message).not.toContain('english text');
  });

  it('[SYS-03-R19] non-JSON 429 and 503 from HAProxy are shown by status', async () => {
    server.use(
      http.get(url('/limited'), () =>
        HttpResponse.text('Too Many Requests', { status: 429 }),
      ),
      http.get(url('/down'), () =>
        HttpResponse.text('Service Unavailable', { status: 503 }),
      ),
    );

    await expect(
      apiMutator({ url: '/limited', method: 'GET' }),
    ).rejects.toThrow();
    expect(lastNotification()?.message).toBe(
      'Слишком много запросов, повторите позже',
    );

    await expect(apiMutator({ url: '/down', method: 'GET' })).rejects.toThrow();
    expect(lastNotification()?.message).toBe('Сервис временно недоступен');
  });

  it('[SYS-07-R12] meta.notify=false suppresses the notification', async () => {
    server.use(
      http.get(url('/quiet'), () =>
        HttpResponse.json(errorEnvelope('core.not_found'), { status: 404 }),
      ),
    );
    const before = useNotifications.getState().notifications.length;
    await expect(
      apiMutator({ url: '/quiet', method: 'GET', meta: { notify: false } }),
    ).rejects.toThrow();
    expect(useNotifications.getState().notifications).toHaveLength(before);
  });
});
