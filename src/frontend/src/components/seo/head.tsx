import { useTranslation } from 'react-i18next';

type HeadProps = {
  title?: string;
  description?: string;
};

/**
 * Заголовок и описание страницы. React 19 поднимает `<title>` и `<meta>`
 * в `<head>` документа сам, `react-helmet-async` не нужен (ADR-005, 3.1).
 * Отображаемое название — ключ `common:app.name` (OQ-08).
 */
export const Head = ({ title = '', description = '' }: HeadProps = {}) => {
  const { t } = useTranslation();
  const appName = t('app.name');
  return (
    <>
      <title>{title ? `${title} | ${appName}` : appName}</title>
      <meta name="description" content={description} />
    </>
  );
};
