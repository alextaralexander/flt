type HeadProps = {
  title?: string;
  description?: string;
};

const APP_TITLE = 'Bulletproof React';

/**
 * Заголовок и описание страницы. React 19 поднимает `<title>` и `<meta>`
 * в `<head>` документа сам, `react-helmet-async` не нужен (ADR-005, 3.1).
 */
export const Head = ({ title = '', description = '' }: HeadProps = {}) => {
  return (
    <>
      <title>{title ? `${title} | ${APP_TITLE}` : APP_TITLE}</title>
      <meta name="description" content={description} />
    </>
  );
};
