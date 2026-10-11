import type { ReactNode } from 'react';
import { createContext, useContext } from 'react';

import type { WsClient } from './ws-client';

const WsClientContext = createContext<WsClient | null>(null);

/** Даёт feature-модулям общий WsClient вкладки (подключается в src/app/provider.tsx). */
export const WsClientProvider = ({
  client,
  children,
}: {
  client: WsClient | null;
  children: ReactNode;
}) => (
  <WsClientContext.Provider value={client}>{children}</WsClientContext.Provider>
);

export const useWsClient = (): WsClient | null => useContext(WsClientContext);
