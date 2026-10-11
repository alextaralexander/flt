import { server } from '@/testing/mocks/server';
import { serverMessage, wsLink } from '@/testing/mocks/ws/ws-server';
import { rtlRender, waitFor } from '@/testing/test-utils';

import { useWsSubscription } from './use-ws-subscription';
import { WsClient, resolveWsUrl } from './ws-client';
import { WsClientProvider } from './ws-context';

const Probe = ({
  onMessage,
  onResync,
}: {
  onMessage: (text: unknown) => void;
  onResync: (stateUrl: string | null) => void;
}) => {
  useWsSubscription('demo.items:1', (message) => onMessage(message.payload), {
    onResync,
  });
  return null;
};

describe('useWsSubscription', () => {
  it('[SYS-04-R12] subscribes while mounted, resyncs on ack and unsubscribes on unmount', async () => {
    const received: string[] = [];
    server.use(
      wsLink().addEventListener('connection', ({ client }) => {
        client.addEventListener('message', (event) => {
          const message = JSON.parse(String(event.data)) as { type: string };
          received.push(message.type);
          if (message.type === 'ws.subscribe') {
            client.send(
              serverMessage(
                'ws.ack',
                {
                  op: 'subscribe',
                  channel: 'demo.items:1',
                  state_url: '/api/v1/demo/items/1',
                },
                { seq: 0 },
              ),
            );
            client.send(
              serverMessage(
                'demo.item_changed',
                { id: '1' },
                {
                  channel: 'demo.items:1',
                  seq: 1,
                },
              ),
            );
          }
        });
      }),
    );
    const client = new WsClient({
      url: resolveWsUrl('/ws'),
      pingIntervalMs: 0,
    });
    const onMessage = vi.fn();
    const onResync = vi.fn();

    const { unmount } = rtlRender(
      <WsClientProvider client={client}>
        <Probe onMessage={onMessage} onResync={onResync} />
      </WsClientProvider>,
    );
    client.connect();

    await waitFor(() => expect(onMessage).toHaveBeenCalledWith({ id: '1' }));
    expect(onResync).toHaveBeenCalledWith('/api/v1/demo/items/1');

    unmount();
    await waitFor(() => expect(received).toContain('ws.unsubscribe'));
    client.close();
  });
});
