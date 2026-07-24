'use client';

import { useState } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import {
  useAccounts,
  useCreateAccount,
  useDeleteAccount,
} from '@/lib/hooks/useAccount';
import { Modal } from '@/components/ui/Modal';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import { ReconciliationView } from './ReconciliationView';

interface AccountManagerProps {
  onClose: () => void;
}

type AccountManagerTab = 'accounts' | 'reconciliation';

/**
 * Add/list/delete brokerage accounts. Deleting an account leaves its trades
 * unassigned (the backend FK is SET NULL), never destroying trade history.
 */
export function AccountManager({ onClose }: AccountManagerProps) {
  const { data: accounts, isLoading } = useAccounts();
  const createAccount = useCreateAccount();
  const deleteAccount = useDeleteAccount();

  const [name, setName] = useState('');
  const [broker, setBroker] = useState('');
  const [accountType, setAccountType] = useState('');
  const [riskProfile, setRiskProfile] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [tab, setTab] = useState<AccountManagerTab>('accounts');

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    try {
      await createAccount.mutateAsync({
        name: name.trim(),
        broker: broker.trim() || null,
        account_type: accountType.trim() || null,
        risk_profile: riskProfile.trim() || null,
        display_order: accounts?.length ?? 0,
      });
      setName('');
      setBroker('');
      setAccountType('');
      setRiskProfile('');
    } catch {
      setError('Could not add account — is the name already used?');
    }
  };

  const inputClass =
    'w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent';

  return (
    <Modal onClose={onClose} title="Manage Accounts" maxWidth="lg">
      <div className="p-4 space-y-5">
        {/* Tabs */}
        <div
          role="tablist"
          aria-label="Account management"
          className="flex gap-1 border-b border-neutral-200 dark:border-neutral-700"
        >
          <button
            role="tab"
            aria-selected={tab === 'accounts'}
            onClick={() => setTab('accounts')}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === 'accounts'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
            }`}
          >
            Accounts
          </button>
          <button
            role="tab"
            aria-selected={tab === 'reconciliation'}
            onClick={() => setTab('reconciliation')}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === 'reconciliation'
                ? 'border-blue-600 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
            }`}
          >
            Reconciliation
          </button>
        </div>

        {tab === 'reconciliation' ? (
          <ReconciliationView accounts={accounts} />
        ) : (
        <>
        {/* Existing accounts */}
        <div>
          <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
            Your Accounts
          </h3>
          {isLoading ? (
            <p className="text-sm text-neutral-500">Loading…</p>
          ) : accounts && accounts.length > 0 ? (
            <ul className="divide-y divide-neutral-100 dark:divide-neutral-700 border border-neutral-200 dark:border-neutral-700 rounded-lg">
              {accounts.map((a) => (
                <li
                  key={a.id}
                  className="flex items-center justify-between px-3 py-2"
                >
                  <div>
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">
                      {a.name}
                    </span>
                    <span className="text-sm text-neutral-500 ml-2">
                      {[a.account_type, a.broker, a.risk_profile]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </div>
                  <button
                    onClick={() => setDeleteId(a.id)}
                    className="p-1.5 rounded-lg text-neutral-400 hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
                    title="Delete account"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-neutral-500">
              No accounts yet. Add one below (e.g. Roth, Taxable, 401k).
            </p>
          )}
        </div>

        {/* Add form */}
        <form onSubmit={handleAdd} className="space-y-3">
          <h3 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
            Add Account
          </h3>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. Roth)"
            className={inputClass}
            required
          />
          <div className="grid grid-cols-3 gap-2">
            <input
              type="text"
              value={accountType}
              onChange={(e) => setAccountType(e.target.value)}
              placeholder="Type (roth)"
              className={inputClass}
            />
            <input
              type="text"
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              placeholder="Broker (Schwab)"
              className={inputClass}
            />
            <input
              type="text"
              value={riskProfile}
              onChange={(e) => setRiskProfile(e.target.value)}
              placeholder="Risk (aggressive)"
              className={inputClass}
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!name.trim() || createAccount.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {createAccount.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Add Account
            </button>
          </div>
        </form>
        </>
        )}
      </div>

      {deleteId !== null && (
        <ConfirmModal
          title="Delete Account"
          message="Delete this account? Its trades stay, but become unassigned."
          confirmLabel="Delete"
          onConfirm={() => {
            deleteAccount.mutate(deleteId);
            setDeleteId(null);
          }}
          onCancel={() => setDeleteId(null)}
          variant="danger"
        />
      )}
    </Modal>
  );
}
