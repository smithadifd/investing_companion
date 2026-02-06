'use client';

import { useState, useRef, useEffect } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { useEquitySearch } from '@/lib/hooks/useEquity';
import type { EquitySearchResult } from '@/lib/api/types';

interface EquitySearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onSelect: (result: EquitySearchResult) => void;
  placeholder?: string;
  required?: boolean;
  autoFocus?: boolean;
}

export function EquitySearchInput({
  value,
  onChange,
  onSelect,
  placeholder = 'Search symbol or name...',
  required = false,
  autoFocus = false,
}: EquitySearchInputProps) {
  const [showResults, setShowResults] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: searchResults, isLoading } = useEquitySearch(value, value.length >= 1);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowResults(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
    setShowResults(true);
  };

  const handleSelect = (result: EquitySearchResult) => {
    onSelect(result);
    setShowResults(false);
  };

  return (
    <div className="relative" ref={containerRef}>
      <div className="relative">
        <input
          type="text"
          value={value}
          onChange={handleChange}
          onFocus={() => searchResults && searchResults.length > 0 && setShowResults(true)}
          placeholder={placeholder}
          className="w-full px-3 py-2 pl-10 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          required={required}
          autoFocus={autoFocus}
        />
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400" />
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400 animate-spin" />
        )}
      </div>

      {showResults && searchResults && searchResults.length > 0 && (
        <div className="absolute z-10 w-full mt-1 bg-white dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {searchResults.map((result) => (
            <button
              key={result.symbol}
              type="button"
              onClick={() => handleSelect(result)}
              className="w-full px-3 py-2 text-left hover:bg-neutral-100 dark:hover:bg-neutral-600 transition-colors"
            >
              <span className="font-medium text-neutral-900 dark:text-neutral-50">
                {result.symbol}
              </span>
              <span className="text-sm text-neutral-500 ml-2">
                {result.name}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
