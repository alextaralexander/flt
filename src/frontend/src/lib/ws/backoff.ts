/**
 * Задержки переподключения WebSocket (SYS-04-R10, R12; app_shell, раздел 7.2).
 */

export const BACKOFF_MIN_MS = 1_000;
export const BACKOFF_MAX_MS = 30_000;
/** Не раньше 30 с после закрытия 1008 (нарушение политики). */
export const POLICY_VIOLATION_DELAY_MS = 30_000;
/** Через 10 с после 4429 (лишние вкладки). */
export const TOO_MANY_CONNECTIONS_DELAY_MS = 10_000;

/**
 * Экспоненциальная задержка от 1 до 30 с с полным джиттером:
 * случайное значение в [1 с, min(30 с, 1 с × 2^attempt)].
 */
export const backoffDelay = (
  attempt: number,
  random: () => number = Math.random,
): number => {
  const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** attempt);
  return Math.round(BACKOFF_MIN_MS + random() * (ceiling - BACKOFF_MIN_MS));
};

/** Коды закрытия (SYS-04-R10). */
export const WsCloseCode = {
  NORMAL: 1000,
  POLICY_VIOLATION: 1008,
  MESSAGE_TOO_BIG: 1009,
  INTERNAL_ERROR: 1011,
  INSTANCE_SHUTDOWN: 1012,
  OUTBOX_OVERFLOW: 1013,
  UNAUTHENTICATED: 4401,
  TOO_MANY_CONNECTIONS: 4429,
} as const;

export type ReconnectDecision =
  | { kind: 'none' }
  | { kind: 'delay'; ms: number }
  | { kind: 'refresh' }
  | { kind: 'too-many-connections'; ms: number };

/** Поведение клиента по коду закрытия (таблица SYS-04-R10). */
export const decideReconnect = (
  code: number,
  attempt: number,
  random: () => number = Math.random,
): ReconnectDecision => {
  switch (code) {
    case WsCloseCode.NORMAL:
      return { kind: 'none' };
    case WsCloseCode.INSTANCE_SHUTDOWN:
      // Инстанс останавливается: сразу к другому инстансу за HAProxy
      return { kind: 'delay', ms: 0 };
    case WsCloseCode.UNAUTHENTICATED:
      return { kind: 'refresh' };
    case WsCloseCode.TOO_MANY_CONNECTIONS:
      return {
        kind: 'too-many-connections',
        ms: TOO_MANY_CONNECTIONS_DELAY_MS,
      };
    case WsCloseCode.POLICY_VIOLATION:
      return {
        kind: 'delay',
        ms: Math.max(POLICY_VIOLATION_DELAY_MS, backoffDelay(attempt, random)),
      };
    default:
      // 1009, 1011, 1013 и обрыв сети (1006): экспоненциальная задержка
      return { kind: 'delay', ms: backoffDelay(attempt, random) };
  }
};
