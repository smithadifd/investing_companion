'use client';

import { useId } from 'react';
import { useAccounts } from '@/lib/hooks/useAccount';

interface AccountSelectProps {
  value: number | null;
  onChange: (accountId: number | null) => void;
  /** Render a label above the select */
  label?: string;
}

/**
 * Account picker for trade forms. Renders nothing until the user has created
 * at least one account (multi-account is opt-in), so single-account users
 * never see clutter.
 */
export function AccountSelect({
  value,
  onChange,
  label = 'Account',
}: AccountSelectProps) {
  const { data: accounts } = useAccounts();
  const selectId = useId();

  if (!accounts || accounts.length === 0) return null;

  return (
    <div>
      <label
        htmlFor={selectId}
        className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
      >
        {label}
      </label>
      <select
        id={selectId}
        value={value ?? ''}
        onChange={(e) =>
          onChange(e.target.value ? parseInt(e.target.value, 10) : null)
        }
        className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
      >
        <option value="">Unassigned</option>
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
            {a.account_type ? ` (${a.account_type})` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
