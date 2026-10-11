/**
 * Клиент WebSocket shared-слоя (ADR-004, 3.3; ADR-005, 3.5; SYS-04-R3…R12).
 *
 * Одно соединение `/ws` на вкладку; каналы мультиплексируются через
 * `ws.subscribe`/`ws.unsubscribe`. При разрыве клиент переподключается
 * (к любому инстансу за HAProxy) по правилам кодов закрытия, повторно
 * подписывается на каналы и после каждого `ws.ack` вызывает `onResync`
 * с `state_url` — состояние канала перечитывается по REST, потому что
 * события WebSocket — уведомления, а не источник истины. Пропуск `seq`
 * конверта трактуется как потеря и тоже приводит к перечитыванию.
 */
import type { ZodType } from 'zod';

import { decideReconnect } from './backoff';
import type { BinaryFrame, WsEnvelope } from './envelope';
import {
  WS_MAX_MESSAGE_BYTES,
  decodeBinaryFrame,
  encodeBinaryFrame,
  parseEnvelope,
} from './envelope';

export type WsMessageHandler<P = Record<string, unknown>> = (
  message: WsEnvelope<P>,
) => void;

export type WsSubscriptionOptions<P = Record<string, unknown>> = {
  /** zod-схема payload (из src/features/<module>/ws/generated); невалидные сообщения отбрасываются. */
  schema?: ZodType<P>;
  /** Перечитать состояние канала по REST (`state_url` из `ws.ack`). */
  onResync?: (stateUrl: string | null) => void;
  /** Ошибка подписки `ws.error` (`ws.forbidden`, `ws.unknown_channel`, …). */
  onError?: (code: string) => void;
};

export type WsClientEvent = 'open' | 'close' | 'reconnect';
type Listener = (detail: { code?: number }) => void;
type Unsubscribe = () => void;

export type WsClientOptions = {
  /** Абсолютный адрес `ws(s)://<host>/ws` (см. `resolveWsUrl`). */
  url: string;
  /** Обновление сессии перед переподключением после `4401` (ADR-006). */
  refreshSession?: () => Promise<void>;
  /** Сессия не восстановлена: переход на экран входа. */
  onSessionExpired?: () => void;
  /** `4429`: пользователю предлагается закрыть лишние вкладки. */
  onTooManyConnections?: () => void;
  /** Интервал прикладного `ws.ping` клиента; `0` — выключен (SYS-04-R11). */
  pingIntervalMs?: number;
  random?: () => number;
  schedule?: (fn: () => void, ms: number) => unknown;
  cancel?: (handle: unknown) => void;
  now?: () => Date;
  createId?: () => string;
};

type HandlerEntry = {
  handler: WsMessageHandler<never>;
  options: WsSubscriptionOptions<never>;
};

type Subscription = {
  handlers: Set<HandlerEntry>;
  stateUrl: string | null;
  acked: boolean;
};

export const DEFAULT_PING_INTERVAL_MS = 30_000;

/** `/ws` → `wss://<host>/ws` на https и `ws://` на http (тот же origin, ADR-012). */
export const resolveWsUrl = (
  path: string,
  location: Pick<Location, 'href'> = window.location,
): string => {
  const url = new URL(path, location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
};

export class WsClient {
  private readonly options: Required<
    Omit<
      WsClientOptions,
      'refreshSession' | 'onSessionExpired' | 'onTooManyConnections'
    >
  > &
    Pick<
      WsClientOptions,
      'refreshSession' | 'onSessionExpired' | 'onTooManyConnections'
    >;
  private socket: WebSocket | null = null;
  private running = false;
  private everOpened = false;
  private attempt = 0;
  private refreshUsed = false;
  private clientSeq = 0;
  private lastServerSeq = -1;
  private reconnectHandle: unknown = null;
  private pingHandle: unknown = null;
  private readonly subscriptions = new Map<string, Subscription>();
  private readonly typeHandlers = new Map<
    string,
    Set<WsMessageHandler<never>>
  >();
  private readonly binaryHandlers = new Set<(frame: BinaryFrame) => void>();
  private readonly listeners: Record<WsClientEvent, Set<Listener>> = {
    open: new Set(),
    close: new Set(),
    reconnect: new Set(),
  };
  /** Отброшенные невалидные сообщения (счётчик для dev-режима). */
  invalidMessages = 0;

  constructor(options: WsClientOptions) {
    this.options = {
      pingIntervalMs: DEFAULT_PING_INTERVAL_MS,
      random: Math.random,
      schedule: (fn, ms) => setTimeout(fn, ms),
      cancel: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
      now: () => new Date(),
      createId: () => crypto.randomUUID(),
      ...options,
    };
  }

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  /** Открывает соединение (после успешного `GET /auth/me`). */
  connect(): void {
    if (this.running) return;
    this.running = true;
    this.openSocket();
  }

  /** Закрывает соединение без переподключения (выход пользователя). */
  close(): void {
    this.running = false;
    this.clearTimers();
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, 'client_close');
  }

  /** Подписка на канал `<module>.<channel>[:<id>]`; возвращает функцию отписки. */
  subscribe<P = Record<string, unknown>>(
    channel: string,
    handler: WsMessageHandler<P>,
    options: WsSubscriptionOptions<P> = {},
  ): Unsubscribe {
    const entry: HandlerEntry = {
      handler: handler as WsMessageHandler<never>,
      options: options as WsSubscriptionOptions<never>,
    };
    let subscription = this.subscriptions.get(channel);
    if (!subscription) {
      subscription = { handlers: new Set(), stateUrl: null, acked: false };
      this.subscriptions.set(channel, subscription);
      this.send('ws.subscribe', { channel });
    }
    subscription.handlers.add(entry);
    return () => {
      const current = this.subscriptions.get(channel);
      if (!current) return;
      current.handlers.delete(entry);
      if (current.handlers.size === 0) {
        this.subscriptions.delete(channel);
        this.send('ws.unsubscribe', { channel });
      }
    };
  }

  /** Сообщения без канала (адресные события пользователя, например `identity.session.revoked`). */
  onMessageType<P = Record<string, unknown>>(
    type: string,
    handler: WsMessageHandler<P>,
  ): Unsubscribe {
    const handlers = this.typeHandlers.get(type) ?? new Set();
    handlers.add(handler as WsMessageHandler<never>);
    this.typeHandlers.set(type, handlers);
    return () => handlers.delete(handler as WsMessageHandler<never>);
  }

  /** Бинарные кадры (аудио, SYS-04-R9). */
  onBinary(handler: (frame: BinaryFrame) => void): Unsubscribe {
    this.binaryHandlers.add(handler);
    return () => this.binaryHandlers.delete(handler);
  }

  on(event: WsClientEvent, listener: Listener): Unsubscribe {
    this.listeners[event].add(listener);
    return () => this.listeners[event].delete(listener);
  }

  /** Отправляет команду в конверте; возвращает `correlation_id` или `null`, если соединения нет. */
  send(
    type: string,
    payload: Record<string, unknown> = {},
    channel: string | null = null,
  ): string | null {
    if (!this.isOpen || !this.socket) return null;
    const correlationId = this.options.createId();
    const message: WsEnvelope = {
      type,
      correlation_id: correlationId,
      channel,
      seq: this.clientSeq++,
      ts: this.options.now().toISOString(),
      payload,
    };
    const data = JSON.stringify(message);
    if (data.length > WS_MAX_MESSAGE_BYTES) {
      throw new Error(
        `WebSocket message ${type} exceeds ${WS_MAX_MESSAGE_BYTES} bytes`,
      );
    }
    this.socket.send(data);
    return correlationId;
  }

  sendBinary(frame: BinaryFrame): boolean {
    if (!this.isOpen || !this.socket) return false;
    this.socket.send(encodeBinaryFrame(frame));
    return true;
  }

  private emit(event: WsClientEvent, detail: { code?: number } = {}) {
    for (const listener of this.listeners[event]) listener(detail);
  }

  private openSocket() {
    const socket = new WebSocket(this.options.url);
    socket.binaryType = 'arraybuffer';
    this.socket = socket;
    socket.addEventListener('open', () => this.handleOpen(socket));
    socket.addEventListener('message', (event) =>
      this.handleMessage(event.data as string | ArrayBuffer),
    );
    socket.addEventListener('close', (event) =>
      this.handleClose(socket, event.code),
    );
  }

  private handleOpen(socket: WebSocket) {
    if (socket !== this.socket) return;
    const isReconnect = this.everOpened;
    this.everOpened = true;
    this.clientSeq = 0;
    this.lastServerSeq = -1;
    this.startPing();
    // Переподписка на все каналы; состояние перечитывается после ws.ack
    for (const [channel, subscription] of this.subscriptions) {
      subscription.acked = false;
      this.send('ws.subscribe', { channel });
    }
    this.emit('open');
    if (isReconnect) this.emit('reconnect');
  }

  private handleMessage(data: string | ArrayBuffer) {
    if (typeof data !== 'string') {
      const frame = decodeBinaryFrame(data);
      if (frame) for (const handler of this.binaryHandlers) handler(frame);
      return;
    }
    const message = parseEnvelope(data);
    if (!message) {
      this.dropInvalid('envelope');
      return;
    }
    // Сервер принял соединение: backoff начинается заново, следующий 4401
    // снова допускает один refresh (повторные обрывы сразу после open
    // не сбрасывают задержку)
    this.attempt = 0;
    this.refreshUsed = false;
    if (this.lastServerSeq >= 0 && message.seq !== this.lastServerSeq + 1) {
      this.resyncAll();
    }
    this.lastServerSeq = message.seq;

    switch (message.type) {
      case 'ws.ping':
        this.send('ws.pong', {
          server_ts: message.payload.server_ts,
          client_ts: this.options.now().toISOString(),
        });
        return;
      case 'ws.pong':
        return;
      case 'ws.ack':
        this.handleAck(message);
        return;
      case 'ws.error':
        this.handleError(message);
        return;
      default:
        this.dispatch(message);
    }
  }

  private handleAck(message: WsEnvelope) {
    const {
      op,
      channel,
      state_url: stateUrl,
    } = message.payload as {
      op?: string;
      channel?: string;
      state_url?: string | null;
    };
    if (op !== 'subscribe' || !channel) return;
    const subscription = this.subscriptions.get(channel);
    if (!subscription) return;
    subscription.acked = true;
    subscription.stateUrl = stateUrl ?? null;
    for (const { options } of subscription.handlers) {
      options.onResync?.(subscription.stateUrl);
    }
  }

  private handleError(message: WsEnvelope) {
    const { code, channel } = message.payload as {
      code?: string;
      channel?: string;
    };
    const subscription = channel ? this.subscriptions.get(channel) : undefined;
    if (!subscription || !code) return;
    for (const { options } of subscription.handlers) options.onError?.(code);
  }

  private dispatch(message: WsEnvelope) {
    if (message.channel) {
      const subscription = this.subscriptions.get(message.channel);
      if (!subscription) return;
      for (const { handler, options } of subscription.handlers) {
        if (options.schema) {
          const parsed = options.schema.safeParse(message.payload);
          if (!parsed.success) {
            this.dropInvalid(message.type);
            continue;
          }
          handler({ ...message, payload: parsed.data } as never);
        } else {
          handler(message as never);
        }
      }
      return;
    }
    for (const handler of this.typeHandlers.get(message.type) ?? []) {
      handler(message as never);
    }
  }

  private resyncAll() {
    for (const subscription of this.subscriptions.values()) {
      if (!subscription.acked) continue;
      for (const { options } of subscription.handlers) {
        options.onResync?.(subscription.stateUrl);
      }
    }
  }

  private dropInvalid(reason: string) {
    this.invalidMessages += 1;
    if (import.meta.env.DEV) {
      console.warn(
        `[ws] dropped invalid message (${reason}), total: ${this.invalidMessages}`,
      );
    }
  }

  private handleClose(socket: WebSocket, code: number) {
    if (socket !== this.socket) return;
    this.socket = null;
    this.stopPing();
    for (const subscription of this.subscriptions.values())
      subscription.acked = false;
    this.emit('close', { code });
    if (!this.running) return;

    const decision = decideReconnect(code, this.attempt, this.options.random);
    switch (decision.kind) {
      case 'none':
        this.running = false;
        return;
      case 'delay':
        this.attempt += 1;
        this.scheduleReconnect(decision.ms);
        return;
      case 'too-many-connections':
        this.options.onTooManyConnections?.();
        this.scheduleReconnect(decision.ms);
        return;
      case 'refresh':
        this.refreshAndReconnect();
    }
  }

  private refreshAndReconnect() {
    const { refreshSession, onSessionExpired } = this.options;
    if (this.refreshUsed || !refreshSession) {
      this.running = false;
      onSessionExpired?.();
      return;
    }
    this.refreshUsed = true;
    refreshSession().then(
      () => this.scheduleReconnect(0),
      () => {
        this.running = false;
        onSessionExpired?.();
      },
    );
  }

  private scheduleReconnect(ms: number) {
    this.reconnectHandle = this.options.schedule(() => {
      this.reconnectHandle = null;
      if (this.running) this.openSocket();
    }, ms);
  }

  private startPing() {
    if (this.options.pingIntervalMs <= 0) return;
    const tick = () => {
      this.send('ws.ping', { client_ts: this.options.now().toISOString() });
      this.pingHandle = this.options.schedule(
        tick,
        this.options.pingIntervalMs,
      );
    };
    this.pingHandle = this.options.schedule(tick, this.options.pingIntervalMs);
  }

  private stopPing() {
    if (this.pingHandle !== null) this.options.cancel(this.pingHandle);
    this.pingHandle = null;
  }

  private clearTimers() {
    this.stopPing();
    if (this.reconnectHandle !== null)
      this.options.cancel(this.reconnectHandle);
    this.reconnectHandle = null;
  }
}
