'use client';

import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';
import { Sun, Moon, Monitor } from 'lucide-react';

export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="flex items-center gap-0.5 p-1 rounded-lg bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600">
        <div className="w-8 h-8" />
        <div className="w-8 h-8" />
        <div className="w-8 h-8" />
      </div>
    );
  }

  return (
    <div className="flex items-center gap-0.5 p-1 rounded-lg bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600">
      <button
        onClick={() => setTheme('light')}
        className={`p-2 rounded-md transition-all ${
          theme === 'light'
            ? 'bg-white dark:bg-neutral-600 text-neutral-900 dark:text-neutral-50 shadow-sm'
            : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
        }`}
        title="Light mode"
      >
        <Sun className="h-4 w-4" />
      </button>
      <button
        onClick={() => setTheme('system')}
        className={`p-2 rounded-md transition-all ${
          theme === 'system'
            ? 'bg-white dark:bg-neutral-600 text-neutral-900 dark:text-neutral-50 shadow-sm'
            : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
        }`}
        title="System preference"
      >
        <Monitor className="h-4 w-4" />
      </button>
      <button
        onClick={() => setTheme('dark')}
        className={`p-2 rounded-md transition-all ${
          theme === 'dark'
            ? 'bg-white dark:bg-neutral-600 text-neutral-900 dark:text-neutral-50 shadow-sm'
            : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
        }`}
        title="Dark mode"
      >
        <Moon className="h-4 w-4" />
      </button>
    </div>
  );
}
