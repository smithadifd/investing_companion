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

const LISTBOX_ID = 'equity-search-listbox';
const optionId = (index: number) => `equity-search-option-${index}`;

export function EquitySearchInput({
  value,
  onChange,
  onSelect,
  placeholder = 'Search symbol or name...',
  required = false,
  autoFocus = false,
}: EquitySearchInputProps) {
  const [showResults, setShowResults] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: searchResults, isLoading } = useEquitySearch(value, value.length >= 1);
  const options = searchResults ?? [];
  const listboxOpen = showResults && options.length > 0;

  // Reset the keyboard highlight whenever the result set changes.
  useEffect(() => {
    setActiveIndex(-1);
  }, [searchResults]);

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
    setActiveIndex(-1);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowResults(false);
      setActiveIndex(-1);
      return;
    }
    if (options.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setShowResults(true);
      setActiveIndex((i) => (i + 1) % options.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setShowResults(true);
      setActiveIndex((i) => (i <= 0 ? options.length - 1 : i - 1));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(options[activeIndex]);
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <div className="relative">
        <input
          type="text"
          role="combobox"
          aria-label="Search for a stock symbol"
          aria-expanded={listboxOpen}
          aria-controls={LISTBOX_ID}
          aria-autocomplete="list"
          aria-activedescendant={
            listboxOpen && activeIndex >= 0 ? optionId(activeIndex) : undefined
          }
          aria-busy={isLoading}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => searchResults && searchResults.length > 0 && setShowResults(true)}
          placeholder={placeholder}
          className="w-full px-3 py-2 pl-10 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          required={required}
          autoFocus={autoFocus}
        />
        <Search aria-hidden="true" className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400" />
        {isLoading && (
          <Loader2 aria-hidden="true" className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400 animate-spin" />
        )}
      </div>

      {listboxOpen && (
        <ul
          id={LISTBOX_ID}
          role="listbox"
          aria-label="Symbol search results"
          className="absolute z-10 w-full mt-1 bg-white dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg shadow-lg max-h-48 overflow-y-auto"
        >
          {options.map((result, index) => (
            <li
              key={result.symbol}
              id={optionId(index)}
              role="option"
              aria-selected={index === activeIndex}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                handleSelect(result);
              }}
              className={`w-full px-3 py-2 text-left cursor-pointer transition-colors ${
                index === activeIndex
                  ? 'bg-neutral-100 dark:bg-neutral-600'
                  : 'hover:bg-neutral-100 dark:hover:bg-neutral-600'
              }`}
            >
              <span className="font-medium text-neutral-900 dark:text-neutral-50">
                {result.symbol}
              </span>
              <span className="text-sm text-neutral-500 ml-2">
                {result.name}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
