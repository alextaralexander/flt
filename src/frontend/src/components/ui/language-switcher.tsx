import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown/dropdown';
import { Icon } from '@/components/ui/icon';
import { changeLanguage } from '@/lib/i18n/i18n';
import {
  DEFAULT_UI_LANGUAGE,
  SUPPORTED_UI_LANGUAGES,
  isUiLanguage,
} from '@/lib/i18n/languages';

/**
 * Переключатель языка интерфейса app_shell (SYS-07-R5): смена языка без
 * перезагрузки страницы, выбор сохраняется в cookie `flt_ui_language`.
 * Названия языков — на самих языках (атрибут `lang` у пункта).
 */
export const LanguageSwitcher = () => {
  const { t, i18n } = useTranslation();
  const current = isUiLanguage(i18n.resolvedLanguage)
    ? i18n.resolvedLanguage
    : DEFAULT_UI_LANGUAGE;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={t('language.switcher.label')}
        >
          <Icon name="Languages" className="size-4" />
          <span lang={current}>{t(`language.native.${current}`)}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup
          value={current}
          onValueChange={(value) => {
            if (isUiLanguage(value)) void changeLanguage(value);
          }}
        >
          {SUPPORTED_UI_LANGUAGES.map((code) => (
            <DropdownMenuRadioItem key={code} value={code} lang={code}>
              {t(`language.native.${code}`)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
