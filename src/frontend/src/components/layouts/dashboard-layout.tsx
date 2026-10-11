import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink, useNavigate, useNavigation } from 'react-router';

import logo from '@/assets/logo.svg';
import { Button } from '@/components/ui/button/button';
import {
  Drawer,
  DrawerContent,
  DrawerTrigger,
} from '@/components/ui/drawer/drawer';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown/dropdown';
import { Icon } from '@/components/ui/icon';
import type { IconName } from '@/components/ui/icons/registry';
import { Link } from '@/components/ui/link/link';
import { paths } from '@/config/paths';
import { useLogout, useUser } from '@/lib/auth';
import { ROLES, useAuthorization } from '@/lib/authorization';
import { ExtensionSlot } from '@/lib/extension-points/extension-slot';
import { cn } from '@/utils/cn';

type SideNavigationItem = {
  name: 'dashboard' | 'discussions' | 'users';
  to: string;
  icon: IconName;
};

const Logo = () => {
  const { t } = useTranslation();
  return (
    <Link className="flex items-center text-white" to={paths.home.getHref()}>
      <img className="h-8 w-auto" src={logo} alt={t('layout.logo-alt')} />
      <span className="text-sm font-semibold text-white">{t('app.name')}</span>
    </Link>
  );
};

// Прогресс сбрасывается пересозданием компонента при смене целевого пути
const NavigationProgress = () => {
  const { location } = useNavigation();
  return <Progress key={location?.pathname} />;
};

const Progress = () => {
  const { state } = useNavigation();

  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (state === 'loading') {
      const timer = setInterval(() => {
        setProgress((oldProgress) => {
          if (oldProgress === 100) {
            clearInterval(timer);
            return 100;
          }
          const newProgress = oldProgress + 10;
          return newProgress > 100 ? 100 : newProgress;
        });
      }, 300);

      return () => {
        clearInterval(timer);
      };
    }
  }, [state]);

  if (state !== 'loading') {
    return null;
  }

  return (
    <div
      className="fixed inset-s-0 top-0 h-1 bg-blue-500 transition-all duration-200 ease-in-out"
      style={{ width: `${progress}%` }}
    ></div>
  );
};

const NavItems = ({
  navigation,
  exactMatch,
}: {
  navigation: SideNavigationItem[];
  exactMatch: (item: SideNavigationItem) => boolean;
}) => {
  const { t } = useTranslation();
  return navigation.map((item) => (
    <NavLink
      key={item.name}
      to={item.to}
      end={exactMatch(item)}
      className={({ isActive }) =>
        cn(
          'text-gray-300 hover:bg-gray-700 hover:text-white',
          'group flex w-full flex-1 items-center rounded-md p-2 text-base font-medium',
          isActive && 'bg-gray-900 text-white',
        )
      }
    >
      <Icon
        name={item.icon}
        className={cn(
          'text-gray-400 group-hover:text-gray-300',
          'me-4 size-6 shrink-0',
        )}
      />
      {t(`layout.nav.${item.name}`)}
    </NavLink>
  ));
};

export function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useUser();
  const logout = useLogout({
    onSuccess: () => navigate(paths.auth.login.getHref(location.pathname)),
  });
  const { checkAccess } = useAuthorization();
  const navigation = [
    { name: 'dashboard', to: paths.app.dashboard.getHref(), icon: 'House' },
    {
      name: 'discussions',
      to: paths.app.discussions.getHref(),
      icon: 'Folder',
    },
    checkAccess({ allowedRoles: [ROLES.ADMIN] }) && {
      name: 'users',
      to: paths.app.users.getHref(),
      icon: 'Users',
    },
  ].filter(Boolean) as SideNavigationItem[];

  return (
    <div className="flex min-h-screen w-full flex-col bg-muted/40">
      <aside className="fixed inset-y-0 inset-s-0 z-10 hidden w-60 flex-col border-e bg-black sm:flex">
        <nav className="flex flex-col items-center gap-4 px-2 py-4">
          <div className="flex h-16 shrink-0 items-center px-4">
            <Logo />
          </div>
          <NavItems
            navigation={navigation}
            exactMatch={(item) => item.name !== 'discussions'}
          />
        </nav>
      </aside>
      <div className="flex flex-col sm:gap-4 sm:py-4 sm:ps-60">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b bg-background px-4 sm:static sm:h-auto sm:justify-end sm:border-0 sm:bg-transparent sm:px-6">
          <NavigationProgress />
          <Drawer>
            <DrawerTrigger asChild>
              <Button size="icon" variant="outline" className="sm:hidden">
                <Icon name="PanelLeft" className="size-5" />
                <span className="sr-only">{t('layout.toggle-menu')}</span>
              </Button>
            </DrawerTrigger>
            <DrawerContent
              side="start"
              className="bg-black pt-10 text-white sm:max-w-60"
            >
              <nav className="grid gap-6 text-lg font-medium">
                <div className="flex h-16 shrink-0 items-center px-4">
                  <Logo />
                </div>
                <NavItems navigation={navigation} exactMatch={() => true} />
              </nav>
            </DrawerContent>
          </Drawer>
          <ExtensionSlot
            id="app.header.actions"
            context={{ user: user.data ?? null }}
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                className="overflow-hidden rounded-full"
              >
                <span className="sr-only">{t('layout.user-menu.open')}</span>
                <Icon name="UserRound" className="size-6 rounded-full" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => navigate(paths.app.profile.getHref())}
                className={cn('block px-4 py-2 text-sm text-gray-700')}
              >
                {t('layout.user-menu.profile')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className={cn('block w-full px-4 py-2 text-sm text-gray-700')}
                onClick={() => logout.mutate({})}
              >
                {t('layout.user-menu.sign-out')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main className="grid flex-1 items-start gap-4 p-4 sm:px-6 sm:py-0 md:gap-8">
          {children}
        </main>
      </div>
    </div>
  );
}
