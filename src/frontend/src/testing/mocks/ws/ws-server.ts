import { ws } from 'msw';

import { env } from '@/config/env';
import { resolveWsUrl } from '@/lib/ws/ws-client';

/**
 * Мок эндпоинта `/ws` через `msw` `ws.link` (ADR-005, 3.5; SYS-10-R9).
 * Обработчики модулей лежат рядом: src/testing/mocks/ws/<module>.ts.
 */
export const wsLink = () => ws.link(resolveWsUrl(env.WS_URL));

/** Сообщение сервера в конверте SYS-04-R3. */
export const serverMessage = (
  type: string,
  payload: Record<string, unknown>,
  { channel = null, seq }: { channel?: string | null; seq: number },
) =>
  JSON.stringify({
    type,
    correlation_id: `00000000-0000-7000-8000-${String(seq).padStart(12, '0')}`,
    channel,
    seq,
    ts: '2026-10-10T12:00:00.000Z',
    payload,
  });
