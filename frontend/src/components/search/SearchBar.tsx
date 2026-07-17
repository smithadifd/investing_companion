'use client';

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Loader2, X } from 'lucide-react';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useEquitySearch } from '@/lib/hooks/useEquity';

const LISTBOX_ID = 'symbol-search-listbox';
const optionId = (index: number) => `symbol-search-option-${index}`;

export function SearchBar() {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  const debouncedQuery = useDebounce(query, 300);
  const { data: results, isLoading } = useEquitySearch(debouncedQuery, isOpen && debouncedQuery.length > 0);
  const options = useMemo(() => results ?? [], [results]);
  const listboxOpen = isOpen && options.length > 0;

  // Reset the keyboard highlight whenever the result set changes.
  useEffect(() => {
    setActiveIndex(-1);
  }, [debouncedQuery, results]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = useCallback(
    (symbol: string) => {
      setQuery('');
      setIsOpen(false);
      setActiveIndex(-1);
      router.push(`/equity/${symbol}`);
    },
    [router]
  );

  const handleClear = useCallback(() => {
    setQuery('');
    setActiveIndex(-1);
    inputRef.current?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
        setActiveIndex(-1);
        inputRef.current?.blur();
        return;
      }
      if (e.key === 'ArrowDown' && options.length > 0) {
        e.preventDefault();
        setIsOpen(true);
        setActiveIndex((i) => (i + 1) % options.length);
        return;
      }
      if (e.key === 'ArrowUp' && options.length > 0) {
        e.preventDefault();
        setIsOpen(true);
        setActiveIndex((i) => (i <= 0 ? options.length - 1 : i - 1));
        return;
      }
      if (e.key === 'Enter' && options.length > 0) {
        const chosen = activeIndex >= 0 ? options[activeIndex] : options[0];
        handleSelect(chosen.symbol);
      }
    },
    [options, activeIndex, handleSelect]
  );

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="relative">
        <Search
          aria-hidden="true"
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground"
        />
        <input
          ref={inputRef}
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
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search for a symbol (e.g., AAPL, CCJ)..."
          className="w-full pl-10 pr-10 py-3 rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
        />
        {isLoading && (
          <Loader2
            aria-hidden="true"
            className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground"
          />
        )}
        {!isLoading && query && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={handleClear}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        )}
      </div>

      {listboxOpen && (
        <ul
          id={LISTBOX_ID}
          role="listbox"
          aria-label="Symbol search results"
          className="absolute z-50 w-full mt-1 bg-card rounded-lg border border-border shadow-lg max-h-64 overflow-auto"
        >
          {options.map((result, index) => (
            <li
              key={result.symbol}
              id={optionId(index)}
              role="option"
              aria-selected={index === activeIndex}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(e) => {
                // Prevent the input blur from closing the list before select.
                e.preventDefault();
                handleSelect(result.symbol);
              }}
              className={`w-full px-4 py-3 text-left flex justify-between items-center border-b border-border last:border-b-0 cursor-pointer transition-colors ${
                index === activeIndex ? 'bg-muted' : 'hover:bg-muted'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="font-semibold text-card-foreground">{result.symbol}</span>
                <span className="text-muted-foreground text-sm truncate max-w-[200px]">
                  {result.name}
                </span>
              </div>
              <span className="text-xs text-muted-foreground uppercase">{result.exchange}</span>
            </li>
          ))}
        </ul>
      )}

      {isOpen && debouncedQuery.length > 0 && !isLoading && results && results.length === 0 && (
        <div
          role="status"
          className="absolute z-50 w-full mt-1 bg-card rounded-lg border border-border shadow-lg p-4 text-center text-muted-foreground"
        >
          No results found for &quot;{debouncedQuery}&quot;
        </div>
      )}
    </div>
  );
}
