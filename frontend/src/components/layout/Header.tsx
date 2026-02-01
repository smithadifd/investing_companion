'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { TrendingUp, User, Settings, LogOut, ChevronDown } from 'lucide-react';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { useAuth } from '@/lib/contexts/AuthContext';

export function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowUserMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  return (
    <header className="sticky top-0 z-50 w-full border-b border-neutral-200 dark:border-neutral-700 bg-white/95 dark:bg-neutral-800/95 backdrop-blur-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2.5 font-semibold text-neutral-900 dark:text-neutral-50">
            <TrendingUp className="h-6 w-6 text-blue-500" />
            <span className="hidden sm:inline text-lg">Investing Companion</span>
          </Link>
          <nav className="hidden md:flex items-center gap-6 text-sm">
            <NavLink href="/" active={pathname === '/'}>
              Dashboard
            </NavLink>
            <NavLink href="/watchlists" active={pathname.startsWith('/watchlists')}>
              Watchlists
            </NavLink>
            <NavLink href="/market" active={pathname.startsWith('/market')}>
              Market
            </NavLink>
            <NavLink href="/ratios" active={pathname.startsWith('/ratios')}>
              Ratios
            </NavLink>
            <NavLink href="/alerts" active={pathname.startsWith('/alerts')}>
              Alerts
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />

          {/* User menu */}
          {!isLoading && (
            isAuthenticated ? (
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors"
                >
                  <div className="h-7 w-7 rounded-full bg-blue-500 flex items-center justify-center">
                    <User className="h-4 w-4 text-white" />
                  </div>
                  <ChevronDown className={`h-4 w-4 text-neutral-500 transition-transform ${showUserMenu ? 'rotate-180' : ''}`} />
                </button>

                {showUserMenu && (
                  <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-neutral-800 rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 py-1 z-50">
                    <div className="px-4 py-2 border-b border-neutral-200 dark:border-neutral-700">
                      <div className="text-sm font-medium text-neutral-900 dark:text-neutral-50 truncate">
                        {user?.email}
                      </div>
                    </div>
                    <Link
                      href="/settings"
                      onClick={() => setShowUserMenu(false)}
                      className="flex items-center gap-2 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700"
                    >
                      <Settings className="h-4 w-4" />
                      Settings
                    </Link>
                    <button
                      onClick={handleLogout}
                      className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-neutral-100 dark:hover:bg-neutral-700"
                    >
                      <LogOut className="h-4 w-4" />
                      Sign out
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <Link
                href="/login"
                className="px-4 py-1.5 text-sm font-medium text-white bg-blue-500 hover:bg-blue-600 rounded-lg transition-colors"
              >
                Sign in
              </Link>
            )
          )}
        </div>
      </div>
    </header>
  );
}

function NavLink({
  href,
  active,
  disabled,
  children,
}: {
  href: string;
  active: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span className="text-neutral-400 dark:text-neutral-500 cursor-not-allowed">
        {children}
      </span>
    );
  }

  return (
    <Link
      href={href}
      className={`transition-colors hover:text-neutral-900 dark:hover:text-neutral-50 ${
        active ? 'text-neutral-900 dark:text-neutral-50 font-medium' : 'text-neutral-500 dark:text-neutral-400'
      }`}
    >
      {children}
    </Link>
  );
}
