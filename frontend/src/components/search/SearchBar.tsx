'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Loader2, X } from 'lucide-react';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useEquitySearch } from '@/lib/hooks/useEquity';

export function SearchBar() {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  const debouncedQuery = useDebounce(query, 300);
  const { data: results, isLoading } = useEquitySearch(debouncedQuery, isOpen && debouncedQuery.length > 0);

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
      router.push(`/equity/${symbol}`);
    },
    [router]
  );

  const handleClear = useCallback(() => {
    setQuery('');
    inputRef.current?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
        inputRef.current?.blur();
      } else if (e.key === 'Enter' && results && results.length > 0) {
        handleSelect(results[0].symbol);
      }
    },
    [results, handleSelect]
  );

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search for a symbol (e.g., AAPL, CCJ)..."
          className="w-full pl-10 pr-10 py-3 rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-shadow"
        />
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
        )}
        {!isLoading && query && (
          <button
            onClick={handleClear}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {isOpen && results && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-card rounded-lg border border-border shadow-lg max-h-64 overflow-auto">
          {results.map((result) => (
            <button
              key={result.symbol}
              onClick={() => handleSelect(result.symbol)}
              className="w-full px-4 py-3 text-left hover:bg-muted flex justify-between items-center border-b border-border last:border-b-0 transition-colors"
            >
              <div className="flex items-center gap-3">
                <span className="font-semibold text-card-foreground">{result.symbol}</span>
                <span className="text-muted-foreground text-sm truncate max-w-[200px]">
                  {result.name}
                </span>
              </div>
              <span className="text-xs text-muted-foreground uppercase">{result.exchange}</span>
            </button>
          ))}
        </div>
      )}

      {isOpen && debouncedQuery.length > 0 && !isLoading && results && results.length === 0 && (
        <div className="absolute z-50 w-full mt-1 bg-card rounded-lg border border-border shadow-lg p-4 text-center text-muted-foreground">
          No results found for &quot;{debouncedQuery}&quot;
        </div>
      )}
    </div>
  );
}
