import * as React from 'react';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button/button';
import { Icon } from '@/components/ui/icon';
import { useDisclosure } from '@/hooks/use-disclosure';

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../dialog';

export type ConfirmationDialogProps = {
  triggerButton: React.ReactElement;
  confirmButton: React.ReactElement;
  title: string;
  body?: string;
  cancelButtonText?: string;
  icon?: 'danger' | 'info';
  isDone?: boolean;
};

export const ConfirmationDialog = ({
  triggerButton,
  confirmButton,
  title,
  body = '',
  cancelButtonText,
  icon = 'danger',
  isDone = false,
}: ConfirmationDialogProps) => {
  const { t } = useTranslation();
  const { close, open, isOpen } = useDisclosure();
  const cancelButtonRef = React.useRef(null);

  useEffect(() => {
    if (isDone) {
      close();
    }
  }, [isDone, close]);

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(isOpen) => {
        if (!isOpen) {
          close();
        } else {
          open();
        }
      }}
    >
      <DialogTrigger asChild>{triggerButton}</DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader className="flex">
          <DialogTitle className="flex items-center gap-2">
            {' '}
            {icon === 'danger' && (
              <Icon name="CircleAlert" className="size-6 text-red-600" />
            )}
            {icon === 'info' && (
              <Icon name="Info" className="size-6 text-blue-600" />
            )}
            {title}
          </DialogTitle>
        </DialogHeader>

        <div className="mt-3 text-center sm:ms-4 sm:mt-0 sm:text-start">
          {body && (
            <div className="mt-2">
              <p>{body}</p>
            </div>
          )}
        </div>

        <DialogFooter>
          {confirmButton}
          <Button ref={cancelButtonRef} variant="outline" onClick={close}>
            {cancelButtonText ?? t('ui.cancel')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
