import { DirectionProvider } from '@radix-ui/react-direction';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import * as React from 'react';
import { ErrorBoundary } from 'react-error-boundary';

import { MainErrorFallback } from '@/components/errors/main';
import { Notifications } from '@/components/ui/notifications/notifications';
import { Spinner } from '@/components/ui/spinner/spinner';
import { AuthLoader } from '@/lib/auth';
import { useDirection } from '@/lib/i18n/use-direction';
import { queryConfig } from '@/lib/react-query';

type AppProviderProps = {
  children: React.ReactNode;
};

/** Направление для компонентов Radix по языку интерфейса (ADR-005, 3.4). */
const DirectionRoot = ({ children }: { children: React.ReactNode }) => {
  const direction = useDirection();
  return <DirectionProvider dir={direction}>{children}</DirectionProvider>;
};

export const AppProvider = ({ children }: AppProviderProps) => {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: queryConfig,
      }),
  );

  return (
    <React.Suspense
      fallback={
        <div className="flex h-screen w-screen items-center justify-center">
          <Spinner size="xl" />
        </div>
      }
    >
      <DirectionRoot>
        <ErrorBoundary FallbackComponent={MainErrorFallback}>
          <QueryClientProvider client={queryClient}>
            {import.meta.env.DEV && <ReactQueryDevtools />}
            <Notifications />
            <AuthLoader
              renderLoading={() => (
                <div className="flex h-screen w-screen items-center justify-center">
                  <Spinner size="xl" />
                </div>
              )}
            >
              {children}
            </AuthLoader>
          </QueryClientProvider>
        </ErrorBoundary>
      </DirectionRoot>
    </React.Suspense>
  );
};
