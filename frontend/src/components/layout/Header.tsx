'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { TrendingUp } from 'lucide-react';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

export function Header() {
  const pathname = usePathname();

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
          </nav>
        </div>
        <ThemeToggle />
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
