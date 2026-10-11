import { z } from 'zod';

import { server } from '@/testing/mocks/server';
import { serverMessage, wsLink } from '@/testing/mocks/ws/ws-server';

import { WsClient, resolveWsUrl } from './ws-client';

type ClientMessage = {
  type: string;
  channel: string | null;
  seq: number;
  payload: Record<string, unknown>;
};

/** Поднимает мок `/ws`: на каждое соединение вызывает `onConnection`. */
const setupServer = (
  onConnection: (args: {
    index: number;
    send: (data: string) => void;
    close: (code: number, reason: string) => void;
    received: ClientMessage[];
  }) => void,
) => {
  const link = wsLink();
  const connections: { received: ClientMessage[] }[] = [];
  server.use(
    link.addEventListener('connection', ({ client }) => {
      const received: ClientMessage[] = [];
      connections.push({ received });
      client.addEventListener('message', (event) => {
        received.push(JSON.parse(String(event.data)) as ClientMessage);
      });
      onConnection({
        index: connections.length - 1,
        send: (data) => client.send(data),
        close: (code, reason) => client.close(code, reason),
        received,
      });
    }),
  );
  return connections;
};

const createClient = (
  overrides: Partial<ConstructorParameters<typeof WsClient>[0]> = {},
) => {
  const delays: number[] = [];
  const client = new WsClient({
    url: resolveWsUrl('/ws'),
    pingIntervalMs: 0,
    random: () => 0.5,
    schedule: (fn, ms) => {
      delays.push(ms);
      return setTimeout(fn, 0);
    },
    ...overrides,
  });
  return { client, delays };
};

const ack = (
  channel: string,
  seq: number,
  stateUrl = `/api/v1/demo/${channel}`,
) =>
  serverMessage(
    'ws.ack',
    { op: 'subscribe', channel, state_url: stateUrl },
    { seq },
  );

describe('WsClient', () => {
  let client: WsClient | undefined;
  afterEach(() => client?.close());

  it('[SYS-04-R3] resolves /ws to the same-origin ws:// URL', () => {
    expect(resolveWsUrl('/ws', { href: 'https://flt.example/app' })).toBe(
      'wss://flt.example/ws',
    );
    expect(resolveWsUrl('/ws', { href: 'http://flt.localhost/' })).toBe(
      'ws://flt.localhost/ws',
    );
  });

  it('[SYS-04-R6] subscribes after open, delivers channel messages after ack and resyncs by state_url', async () => {
    const connections = setupServer(({ send, received }) => {
      const timer = setInterval(() => {
        if (received.some((m) => m.type === 'ws.subscribe')) {
          clearInterval(timer);
          send(ack('demo.items:1', 0));
          send(
            serverMessage(
              'demo.item_changed',
              { id: '1' },
              { channel: 'demo.items:1', seq: 1 },
            ),
          );
        }
      }, 5);
    });
    ({ client } = createClient());
    const handler = vi.fn();
    const onResync = vi.fn();
    client.subscribe('demo.items:1', handler, { onResync });
    client.connect();

    await vi.waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(onResync).toHaveBeenCalledWith('/api/v1/demo/demo.items:1');
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      type: 'demo.item_changed',
      payload: { id: '1' },
    });
    const subscribe = connections[0]?.received.find(
      (m) => m.type === 'ws.subscribe',
    );
    expect(subscribe).toMatchObject({
      channel: null,
      payload: { channel: 'demo.items:1' },
    });
  });

  it('[SYS-04-R3] drops messages with an invalid envelope or payload', async () => {
    setupServer(({ send, received }) => {
      const timer = setInterval(() => {
        if (received.length > 0) {
          clearInterval(timer);
          send(ack('demo.items:1', 0));
          send(JSON.stringify({ type: 'demo.item_changed', extra: true }));
          send(
            serverMessage(
              'demo.item_changed',
              { id: 42 },
              { channel: 'demo.items:1', seq: 1 },
            ),
          );
          send(
            serverMessage(
              'demo.item_changed',
              { id: 'ok' },
              { channel: 'demo.items:1', seq: 2 },
            ),
          );
        }
      }, 5);
    });
    ({ client } = createClient());
    const handler = vi.fn();
    client.subscribe('demo.items:1', handler, {
      schema: z.object({ id: z.string() }),
    });
    client.connect();

    await vi.waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0].payload).toEqual({ id: 'ok' });
    expect(client.invalidMessages).toBe(2);
  });

  it('[SYS-04-R11] answers ws.ping with ws.pong', async () => {
    const connections = setupServer(({ send }) => {
      send(
        serverMessage(
          'ws.ping',
          { server_ts: '2026-10-10T12:00:00Z' },
          { seq: 0 },
        ),
      );
    });
    ({ client } = createClient());
    client.connect();

    await vi.waitFor(() =>
      expect(connections[0]?.received.some((m) => m.type === 'ws.pong')).toBe(
        true,
      ),
    );
    const pong = connections[0]?.received.find((m) => m.type === 'ws.pong');
    expect(pong?.payload.server_ts).toBe('2026-10-10T12:00:00Z');
    expect(pong?.payload.client_ts).toEqual(expect.any(String));
  });

  it('[SYS-04-R10][SYS-04-R12] 1012: reconnects immediately, resubscribes and resyncs', async () => {
    setupServer(({ index, send, close, received }) => {
      const timer = setInterval(() => {
        if (received.some((m) => m.type === 'ws.subscribe')) {
          clearInterval(timer);
          send(ack('demo.items:1', 0));
          if (index === 0)
            setTimeout(() => close(1012, 'instance_shutdown'), 20);
        }
      }, 5);
    });
    ({ client } = createClient());
    const onResync = vi.fn();
    const reconnected = vi.fn();
    client.on('reconnect', reconnected);
    client.subscribe('demo.items:1', vi.fn(), { onResync });
    client.connect();

    await vi.waitFor(() => expect(onResync).toHaveBeenCalledTimes(2));
    expect(reconnected).toHaveBeenCalledTimes(1);
  });

  it('[SYS-04-R10] close codes choose the reconnect delay', async () => {
    const codes = [1011, 1013, 1008];
    setupServer(({ index, close }) => {
      const code = codes[index];
      if (code) setTimeout(() => close(code, 'test'), 5);
    });
    let delays: number[] = [];
    ({ client, delays } = createClient());
    client.connect();

    await vi.waitFor(() => expect(delays).toHaveLength(3));
    // backoff 1–30 с с полным джиттером (random = 0.5); 1008 — не раньше 30 с
    expect(delays[0]).toBe(1000);
    expect(delays[1]).toBe(1500);
    expect(delays[2]).toBe(30000);
  });

  it('[SYS-04-R10] 1000 does not reconnect', async () => {
    setupServer(({ close }) =>
      setTimeout(() => close(1000, 'client_close'), 5),
    );
    let delays: number[] = [];
    ({ client, delays } = createClient());
    const closed = vi.fn();
    client.on('close', closed);
    client.connect();

    await vi.waitFor(() => expect(closed).toHaveBeenCalledWith({ code: 1000 }));
    expect(delays).toEqual([]);
  });

  it('[SYS-04-R10] 4429: asks to close extra tabs and reconnects after 10 s', async () => {
    setupServer(({ index, close }) => {
      if (index === 0) setTimeout(() => close(4429, 'too_many_connections'), 5);
    });
    const onTooManyConnections = vi.fn();
    let delays: number[] = [];
    ({ client, delays } = createClient({ onTooManyConnections }));
    client.connect();

    await vi.waitFor(() =>
      expect(onTooManyConnections).toHaveBeenCalledTimes(1),
    );
    expect(delays).toEqual([10000]);
  });

  it('[SYS-04-R10][SYS-04-R12] 4401: refresh then reconnect; second 4401 leads to login', async () => {
    setupServer(({ close }) =>
      setTimeout(() => close(4401, 'session_revoked'), 5),
    );
    const refreshSession = vi.fn().mockResolvedValue(undefined);
    const onSessionExpired = vi.fn();
    ({ client } = createClient({ refreshSession, onSessionExpired }));
    client.connect();

    await vi.waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });

  it('[SYS-04-R10] 4401 with a failed refresh leads to login', async () => {
    setupServer(({ close }) =>
      setTimeout(() => close(4401, 'unauthenticated'), 5),
    );
    const refreshSession = vi.fn().mockRejectedValue(new Error('expired'));
    const onSessionExpired = vi.fn();
    ({ client } = createClient({ refreshSession, onSessionExpired }));
    client.connect();

    await vi.waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
  });

  it('[SYS-04-R12] a gap in envelope seq triggers resync of subscribed channels', async () => {
    setupServer(({ send, received }) => {
      const timer = setInterval(() => {
        if (received.some((m) => m.type === 'ws.subscribe')) {
          clearInterval(timer);
          send(ack('demo.items:1', 0));
          send(
            serverMessage(
              'demo.item_changed',
              { id: '1' },
              { channel: 'demo.items:1', seq: 5 },
            ),
          );
        }
      }, 5);
    });
    ({ client } = createClient());
    const onResync = vi.fn();
    const handler = vi.fn();
    client.subscribe('demo.items:1', handler, { onResync });
    client.connect();

    await vi.waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(onResync).toHaveBeenCalledTimes(2);
  });

  it('[SYS-04-R6] the last unsubscribe sends ws.unsubscribe; send() without connection returns null', async () => {
    const connections = setupServer(() => undefined);
    ({ client } = createClient());
    expect(client.send('demo.ping')).toBeNull();
    const unsubscribe = client.subscribe('demo.items:1', vi.fn());
    client.connect();
    await vi.waitFor(() => expect(client?.isOpen).toBe(true));

    unsubscribe();
    await vi.waitFor(() =>
      expect(
        connections[0]?.received.some((m) => m.type === 'ws.unsubscribe'),
      ).toBe(true),
    );
  });
});
