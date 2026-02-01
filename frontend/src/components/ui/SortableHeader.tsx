'use client';

import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';

export type SortDirection = 'asc' | 'desc' | null;

export interface SortConfig<T> {
  key: T;
  direction: SortDirection;
}

interface SortableHeaderProps<T> {
  label: string;
  sortKey: T;
  currentSort: SortConfig<T>;
  onSort: (key: T) => void;
  align?: 'left' | 'right' | 'center';
  className?: string;
}

/**
 * Reusable sortable table header component.
 * Click to toggle between ascending, descending, and unsorted states.
 */
export function SortableHeader<T extends string>({
  label,
  sortKey,
  currentSort,
  onSort,
  align = 'left',
  className = '',
}: SortableHeaderProps<T>) {
  const isActive = currentSort.key === sortKey;
  const direction = isActive ? currentSort.direction : null;

  const alignClasses = {
    left: 'justify-start',
    right: 'justify-end',
    center: 'justify-center',
  };

  return (
    <button
      onClick={() => onSort(sortKey)}
      className={`flex items-center gap-1 text-sm font-medium transition-colors hover:text-neutral-900 dark:hover:text-neutral-100 ${
        isActive
          ? 'text-neutral-900 dark:text-neutral-100'
          : 'text-neutral-500 dark:text-neutral-400'
      } ${alignClasses[align]} ${className}`}
    >
      {label}
      <span className="w-4 h-4 flex items-center justify-center">
        {direction === 'asc' ? (
          <ChevronUp className="h-4 w-4" />
        ) : direction === 'desc' ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronsUpDown className="h-3 w-3 opacity-50" />
        )}
      </span>
    </button>
  );
}

/**
 * Hook for managing sort state with cycling behavior.
 * asc -> desc -> null (unsorted) -> asc ...
 */
export function useSortState<T extends string>(
  initialKey: T | null = null,
  initialDirection: SortDirection = null
) {
  const [sortConfig, setSortConfig] = useState<SortConfig<T>>({
    key: initialKey as T,
    direction: initialDirection,
  });

  const handleSort = (key: T) => {
    setSortConfig((current) => {
      if (current.key !== key) {
        // New column, start with descending (most useful for numbers/changes)
        return { key, direction: 'desc' };
      }

      // Same column, cycle through: desc -> asc -> null
      if (current.direction === 'desc') {
        return { key, direction: 'asc' };
      }
      if (current.direction === 'asc') {
        return { key: key, direction: null };
      }
      return { key, direction: 'desc' };
    });
  };

  return { sortConfig, handleSort };
}

/**
 * Generic sort function for arrays.
 */
export function sortData<T>(
  data: T[],
  sortConfig: SortConfig<keyof T>,
  defaultSort?: (a: T, b: T) => number
): T[] {
  if (!sortConfig.direction || !sortConfig.key) {
    return defaultSort ? [...data].sort(defaultSort) : data;
  }

  return [...data].sort((a, b) => {
    const aVal = a[sortConfig.key];
    const bVal = b[sortConfig.key];

    // Handle null/undefined
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;

    // Handle numbers (including string numbers)
    const aNum = typeof aVal === 'string' ? parseFloat(aVal) : aVal;
    const bNum = typeof bVal === 'string' ? parseFloat(bVal) : bVal;

    if (typeof aNum === 'number' && typeof bNum === 'number' && !isNaN(aNum) && !isNaN(bNum)) {
      return sortConfig.direction === 'asc' ? aNum - bNum : bNum - aNum;
    }

    // Handle strings
    const aStr = String(aVal).toLowerCase();
    const bStr = String(bVal).toLowerCase();
    const comparison = aStr.localeCompare(bStr);
    return sortConfig.direction === 'asc' ? comparison : -comparison;
  });
}

// Need to import useState for the hook
import { useState } from 'react';
