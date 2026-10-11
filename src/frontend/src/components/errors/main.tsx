import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button/button';

export const MainErrorFallback = () => {
  const { t } = useTranslation();
  return (
    <div
      className="flex h-screen w-screen flex-col items-center justify-center text-red-500"
      role="alert"
    >
      <h2 className="text-lg font-semibold">{t('errors.app.title')}</h2>
      <Button
        className="mt-4"
        onClick={() => window.location.assign(window.location.origin)}
      >
        {t('errors.app.refresh')}
      </Button>
    </div>
  );
};
