'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  TrendingUp,
  User,
  Settings,
  LogOut,
  ChevronDown,
  Search,
  Loader2,
  X,
  Menu,
  LayoutDashboard,
  List,
  BarChart3,
  Percent,
  Bell,
  LineChart,
  Calendar,
  Newspaper,
} from 'lucide-react';
import { useAuth } from '@/lib/contexts/AuthContext';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useEquitySearch } from '@/lib/hooks/useEquity';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/watchlists', label: 'Watchlists', icon: List },
  { href: '/market', label: 'Market', icon: BarChart3 },
  { href: '/ratios', label: 'Ratios', icon: Percent },
  { href: '/news', label: 'News', icon: Newspaper },
  { href: '/calendar', label: 'Calendar', icon: Calendar },
  { href: '/alerts', label: 'Alerts', icon: Bell },
  { href: '/trades', label: 'Trades', icon: LineChart },
];

export function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showMobileMenu, setShowMobileMenu] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const debouncedQuery = useDebounce(searchQuery, 300);
  const { data: searchResults, isLoading: searchLoading } = useEquitySearch(
    debouncedQuery,
    searchOpen && debouncedQuery.length > 0
  );

  // Close menus when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowUserMenu(false);
      }
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setSearchOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close mobile menu on route change
  useEffect(() => {
    setShowMobileMenu(false);
  }, [pathname]);

  // Prevent body scroll when mobile menu is open
  useEffect(() => {
    if (showMobileMenu) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [showMobileMenu]);

  // Keyboard shortcut for search (Cmd/Ctrl + K)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setShowSearch(true);
        setTimeout(() => searchInputRef.current?.focus(), 0);
      }
      if (e.key === 'Escape') {
        setShowSearch(false);
        setSearchOpen(false);
        setShowMobileMenu(false);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  const handleSearchSelect = useCallback(
    (symbol: string) => {
      setSearchQuery('');
      setSearchOpen(false);
      setShowSearch(false);
      router.push(`/equity/${symbol}`);
    },
    [router]
  );

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSearchOpen(false);
        setShowSearch(false);
      } else if (e.key === 'Enter' && searchResults && searchResults.length > 0) {
        handleSearchSelect(searchResults[0].symbol);
      }
    },
    [searchResults, handleSearchSelect]
  );

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <>
      <header className="sticky top-0 z-50 w-full border-b border-neutral-200 dark:border-neutral-700 bg-white/95 dark:bg-neutral-800/95 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Hamburger menu button */}
            <button
              onClick={() => setShowMobileMenu(true)}
              className="lg:hidden p-2 -ml-2 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>

            <Link href="/" className="flex items-center gap-2.5 font-semibold text-neutral-900 dark:text-neutral-50">
              <TrendingUp className="h-6 w-6 text-blue-500" />
              <span className="hidden sm:inline text-lg">Investing Companion</span>
            </Link>

            {/* Desktop nav */}
            <nav className="hidden lg:flex items-center gap-1 ml-4">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`px-3 py-2 text-sm rounded-lg transition-colors ${
                    isActive(item.href)
                      ? 'text-neutral-900 dark:text-neutral-50 bg-neutral-100 dark:bg-neutral-700 font-medium'
                      : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 hover:bg-neutral-50 dark:hover:bg-neutral-700/50'
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            {/* Search */}
            <div ref={searchRef} className="relative">
              {showSearch ? (
                <div className="relative flex items-center">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400" />
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setSearchOpen(true);
                    }}
                    onFocus={() => setSearchOpen(true)}
                    onKeyDown={handleSearchKeyDown}
                    placeholder="Search symbols..."
                    className="w-44 sm:w-52 pl-8 pr-6 py-1.5 text-sm rounded-lg border border-neutral-200 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    autoFocus
                  />
                  <button
                    onClick={() => {
                      setShowSearch(false);
                      setSearchQuery('');
                      setSearchOpen(false);
                    }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300"
                  >
                    {searchLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <X className="h-3.5 w-3.5" />
                    )}
                  </button>

                  {/* Search Results Dropdown */}
                  {searchOpen && searchResults && searchResults.length > 0 && (
                    <div className="absolute top-full right-0 mt-1 w-72 bg-white dark:bg-neutral-800 rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 max-h-64 overflow-auto z-50">
                      {searchResults.map((result) => (
                        <button
                          key={result.symbol}
                          onClick={() => handleSearchSelect(result.symbol)}
                          className="w-full px-4 py-2.5 text-left hover:bg-neutral-50 dark:hover:bg-neutral-700 flex justify-between items-center border-b border-neutral-100 dark:border-neutral-700 last:border-b-0 transition-colors"
                        >
                          <div className="flex items-center gap-3">
                            <span className="font-semibold text-neutral-900 dark:text-neutral-50">{result.symbol}</span>
                            <span className="text-neutral-500 dark:text-neutral-400 text-sm truncate max-w-[140px]">
                              {result.name}
                            </span>
                          </div>
                          <span className="text-xs text-neutral-400 uppercase">{result.exchange}</span>
                        </button>
                      ))}
                    </div>
                  )}

                  {searchOpen && debouncedQuery.length > 0 && !searchLoading && searchResults && searchResults.length === 0 && (
                    <div className="absolute top-full right-0 mt-1 w-72 bg-white dark:bg-neutral-800 rounded-lg shadow-lg border border-neutral-200 dark:border-neutral-700 p-4 text-center text-neutral-500 dark:text-neutral-400 text-sm z-50">
                      No results found
                    </div>
                  )}
                </div>
              ) : (
                <button
                  onClick={() => setShowSearch(true)}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 rounded-lg border border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600 transition-colors"
                >
                  <Search className="h-4 w-4" />
                  <span className="hidden sm:inline">Search</span>
                  <kbd className="hidden sm:inline ml-2 px-1.5 py-0.5 text-xs bg-neutral-100 dark:bg-neutral-700 rounded">
                    ⌘K
                  </kbd>
                </button>
              )}
            </div>

            {/* User menu */}
            {!isLoading && (
              isAuthenticated ? (
                <div className="relative" ref={menuRef}>
                  <button
                    onClick={() => setShowUserMenu(!showUserMenu)}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors"
                  >
                    <div className="h-7 w-7 rounded-full bg-blue-500 flex items-center justify-center">
                      <User className="h-4 w-4 text-white" />
                    </div>
                    <ChevronDown className={`hidden sm:block h-4 w-4 text-neutral-500 transition-transform ${showUserMenu ? 'rotate-180' : ''}`} />
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

      {/* Mobile menu overlay */}
      {showMobileMenu && (
        <div className="fixed inset-0 z-50 lg:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setShowMobileMenu(false)}
          />

          {/* Slide-out panel */}
          <div className="absolute inset-y-0 left-0 w-72 bg-white dark:bg-neutral-800 shadow-xl flex flex-col animate-slide-in">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700">
              <Link
                href="/"
                className="flex items-center gap-2 font-semibold text-neutral-900 dark:text-neutral-50"
                onClick={() => setShowMobileMenu(false)}
              >
                <TrendingUp className="h-6 w-6 text-blue-500" />
                <span>Investing Companion</span>
              </Link>
              <button
                onClick={() => setShowMobileMenu(false)}
                className="p-2 -mr-2 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Nav items */}
            <nav className="flex-1 overflow-y-auto p-4">
              <div className="space-y-1">
                {NAV_ITEMS.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                        isActive(item.href)
                          ? 'text-neutral-900 dark:text-neutral-50 bg-neutral-100 dark:bg-neutral-700 font-medium'
                          : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 hover:bg-neutral-50 dark:hover:bg-neutral-700/50'
                      }`}
                    >
                      <Icon className="h-5 w-5" />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </nav>

            {/* User section at bottom */}
            {isAuthenticated && (
              <div className="border-t border-neutral-200 dark:border-neutral-700 p-4 space-y-1">
                <div className="px-3 py-2 text-sm text-neutral-500 dark:text-neutral-400 truncate">
                  {user?.email}
                </div>
                <Link
                  href="/settings"
                  className="flex items-center gap-3 px-3 py-2.5 text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 hover:bg-neutral-50 dark:hover:bg-neutral-700/50 rounded-lg transition-colors"
                >
                  <Settings className="h-5 w-5" />
                  Settings
                </Link>
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                >
                  <LogOut className="h-5 w-5" />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <style jsx>{`
        @keyframes slide-in {
          from {
            transform: translateX(-100%);
          }
          to {
            transform: translateX(0);
          }
        }
        .animate-slide-in {
          animation: slide-in 0.2s ease-out;
        }
      `}</style>
    </>
  );
}
