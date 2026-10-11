import { useEffect, useEffectEvent } from 'react';

import type { WsMessageHandler, WsSubscriptionOptions } from './ws-client';
import { useWsClient } from './ws-context';

/**
 * Подписка компонента на канал WebSocket с автоматической отпиской
 * (ADR-005, 3.5). После каждого `ws.ack` (в том числе после
 * переподключения к другому инстансу) вызывается `onResync` — компонент
 * перечитывает состояние канала по REST.
 */
export const useWsSubscription = <P = Record<string, unknown>>(
  channel: string | null,
  handler: WsMessageHandler<P>,
  options: WsSubscriptionOptions<P> = {},
): void => {
  const client = useWsClient();
  const onMessage = useEffectEvent(handler);
  const onResync = useEffectEvent((stateUrl: string | null) =>
    options.onResync?.(stateUrl),
  );
  const onError = useEffectEvent((code: string) => options.onError?.(code));
  const { schema } = options;

  useEffect(() => {
    if (!client || !channel) return undefined;
    return client.subscribe<P>(channel, (message) => onMessage(message), {
      schema,
      onResync: (stateUrl) => onResync(stateUrl),
      onError: (code) => onError(code),
    });
  }, [client, channel, schema]);
};
