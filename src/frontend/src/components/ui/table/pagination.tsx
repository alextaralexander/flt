import { DotsHorizontalIcon } from '@radix-ui/react-icons';
import * as React from 'react';
import { useTranslation } from 'react-i18next';

import type { ButtonProps } from '@/components/ui/button/button';
import { buttonVariants } from '@/components/ui/button/button';
import { Icon } from '@/components/ui/icon';
import { Link } from '@/components/ui/link/link';
import { cn } from '@/utils/cn';

const Pagination = ({ className, ...props }: React.ComponentProps<'nav'>) => {
  const { t } = useTranslation();
  return (
    <nav
      role="navigation"
      aria-label={t('ui.pagination.label')}
      className={cn('mx-auto flex w-full justify-center', className)}
      {...props}
    />
  );
};
Pagination.displayName = 'Pagination';

const PaginationContent = React.forwardRef<
  HTMLUListElement,
  React.ComponentProps<'ul'>
>(({ className, ...props }, ref) => (
  <ul
    ref={ref}
    className={cn('flex flex-row items-center gap-1', className)}
    {...props}
  />
));
PaginationContent.displayName = 'PaginationContent';

const PaginationItem = React.forwardRef<
  HTMLLIElement,
  React.ComponentProps<'li'>
>(({ className, ...props }, ref) => (
  <li ref={ref} className={cn('', className)} {...props} />
));
PaginationItem.displayName = 'PaginationItem';

type PaginationLinkProps = {
  isActive?: boolean;
} & Pick<ButtonProps, 'size'> &
  React.ComponentProps<'a'>;

const PaginationLink = ({
  className,
  isActive,
  size = 'icon',
  children,
  href,
  ...props
}: PaginationLinkProps) => (
  <Link
    to={href as string}
    aria-current={isActive ? 'page' : undefined}
    className={cn(
      buttonVariants({
        variant: isActive ? 'outline' : 'ghost',
        size,
      }),
      className,
    )}
    {...props}
  >
    {children}
  </Link>
);
PaginationLink.displayName = 'PaginationLink';

const PaginationPrevious = ({
  className,
  ...props
}: React.ComponentProps<typeof PaginationLink>) => {
  const { t } = useTranslation();
  return (
    <PaginationLink
      aria-label={t('ui.pagination.previous-label')}
      size="default"
      className={cn('gap-1 ps-2.5', className)}
      {...props}
    >
      <Icon name="ChevronLeft" className="size-4" />
      <span>{t('ui.pagination.previous')}</span>
    </PaginationLink>
  );
};
PaginationPrevious.displayName = 'PaginationPrevious';

const PaginationNext = ({
  className,
  ...props
}: React.ComponentProps<typeof PaginationLink>) => {
  const { t } = useTranslation();
  return (
    <PaginationLink
      aria-label={t('ui.pagination.next-label')}
      size="default"
      className={cn('gap-1 pe-2.5', className)}
      {...props}
    >
      <span>{t('ui.pagination.next')}</span>
      <Icon name="ChevronRight" className="size-4" />
    </PaginationLink>
  );
};
PaginationNext.displayName = 'PaginationNext';

const PaginationEllipsis = ({
  className,
  ...props
}: React.ComponentProps<'span'>) => {
  const { t } = useTranslation();
  return (
    <span
      aria-hidden
      className={cn('flex size-9 items-center justify-center', className)}
      {...props}
    >
      <DotsHorizontalIcon className="size-4" />
      <span className="sr-only">{t('ui.pagination.more')}</span>
    </span>
  );
};
PaginationEllipsis.displayName = 'PaginationEllipsis';

export {
  Pagination,
  PaginationContent,
  PaginationLink,
  PaginationItem,
  PaginationPrevious,
  PaginationNext,
  PaginationEllipsis,
};

export type TablePaginationProps = {
  totalPages: number;
  currentPage: number;
  rootUrl: string;
};

export const TablePagination = ({
  totalPages,
  currentPage,
  rootUrl,
}: TablePaginationProps) => {
  const createHref = (page: number) => `${rootUrl}?page=${page}`;

  return (
    <Pagination className="justify-end py-8">
      <PaginationContent>
        {currentPage > 1 && (
          <PaginationItem>
            <PaginationPrevious href={createHref(currentPage - 1)} />
          </PaginationItem>
        )}
        {currentPage > 2 && (
          <PaginationItem>
            <PaginationEllipsis />
          </PaginationItem>
        )}
        {currentPage > 1 && (
          <PaginationItem>
            <PaginationLink href={createHref(currentPage - 1)}>
              {currentPage - 1}
            </PaginationLink>
          </PaginationItem>
        )}
        <PaginationItem className="rounded-sm bg-gray-200">
          <PaginationLink href={createHref(currentPage)}>
            {currentPage}
          </PaginationLink>
        </PaginationItem>
        {totalPages > currentPage && (
          <PaginationItem>
            <PaginationLink href={createHref(currentPage + 1)}>
              {currentPage + 1}
            </PaginationLink>
          </PaginationItem>
        )}
        {totalPages > currentPage + 1 && (
          <PaginationItem>
            <PaginationEllipsis />
          </PaginationItem>
        )}
        {currentPage < totalPages && (
          <PaginationItem>
            <PaginationNext href={createHref(totalPages)} />
          </PaginationItem>
        )}
      </PaginationContent>
    </Pagination>
  );
};
