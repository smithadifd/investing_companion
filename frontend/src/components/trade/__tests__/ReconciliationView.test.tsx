import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@/test/utils';
import userEvent from '@testing-library/user-event';
import { ReconciliationView } from '../ReconciliationView';
import type { Account, AccountReconciliation } from '@/lib/api/types';

const mockUseReconciliation = vi.fn();
const mockTriggerImport = vi.fn();
const mockAdopt = vi.fn();
const mockUseTransactionReconciliation = vi.fn();
vi.mock('@/lib/hooks/useReconciliation', () => ({
  useAccountReconciliation: (...args: unknown[]) =>
    mockUseReconciliation(...args),
  useAccountTransactionReconciliation: (...args: unknown[]) =>
    mockUseTransactionReconciliation(...args),
  useTriggerBrokerImport: () => ({
    mutateAsync: mockTriggerImport,
    isPending: false,
    isSuccess: false,
    data: undefined,
  }),
  useAdoptReconciliation: () => ({
    mutateAsync: mockAdopt,
    isPending: false,
  }),
  // The Activity tab renders BrokerCsvUpload, which consumes this hook.
  useImportBrokerCsv: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

// Mock the client module with a real ApiError class (defined inside the
// factory so it isn't hoisted out of scope), so the component's
// `error instanceof ApiError` 409 branch works against the same class.
vi.mock('@/lib/api/client', () => {
  class ApiError extends Error {
    code: string;
    status: number;
    constructor(message: string, code: string, status: number) {
      super(message);
      this.code = code;
      this.status = status;
    }
  }
  return { ApiError };
});

import { ApiError } from '@/lib/api/client';

const accounts: Account[] = [
  {
    id: 1,
    name: 'Roth',
    broker: 'Schwab',
    account_type: 'roth',
    risk_profile: 'aggressive',
    display_order: 0,
    created_at: '2026-06-12T00:00:00Z',
    updated_at: '2026-06-12T00:00:00Z',
  },
];

const populated: AccountReconciliation = {
  last_import_at: '2026-07-23T00:00:00Z',
  never_imported: false,
  newer_failed_import_at: null,
  positions: [
    {
      symbol: 'AAPL',
      asset_type: 'EQUITY',
      eligible: true,
      ineligible_reason: null,
      schwab_quantity: '10',
      ic_quantity: '8',
      quantity_delta: '2',
      schwab_basis: '150',
      ic_basis: '100',
      basis_delta: '50',
      ledger_inconsistent: false,
    },
    {
      symbol: 'OPT',
      asset_type: 'OPTION',
      eligible: false,
      ineligible_reason: 'asset_type OPTION not supported',
      schwab_quantity: '2',
      ic_quantity: null,
      quantity_delta: '2',
      schwab_basis: null,
      ic_basis: null,
      basis_delta: null,
      ledger_inconsistent: false,
    },
  ],
};

describe('ReconciliationView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTransactionReconciliation.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
    });
  });

  it('renders both eligible and ineligible rows, greying (not hiding) ineligible', () => {
    mockUseReconciliation.mockReturnValue({
      data: populated,
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);

    // Both symbols present — ineligible row is NOT hidden.
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('OPT')).toBeInTheDocument();

    // Ineligible row is greyed and shows its reason.
    const optRow = screen.getByTestId('recon-row-OPT');
    expect(optRow.className).toContain('opacity-50');
    expect(
      screen.getByText('asset_type OPTION not supported')
    ).toBeInTheDocument();

    // Eligible row is not greyed.
    expect(screen.getByTestId('recon-row-AAPL').className).not.toContain(
      'opacity-50'
    );
  });

  it('offers Adopt for the eligible non-zero deltas only', async () => {
    mockUseReconciliation.mockReturnValue({
      data: populated,
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);

    // AAPL is eligible with a non-zero delta; OPT is ineligible and excluded.
    const adoptButton = screen.getByRole('button', { name: /adopt \(1\)/i });
    expect(adoptButton).toBeEnabled();

    // Adoption is confirmation-gated — clicking does not mutate immediately.
    await userEvent.click(adoptButton);
    expect(mockAdopt).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Adopt Schwab positions\?/i)
    ).toBeInTheDocument();
  });

  it('disables Adopt when nothing is adoptable', () => {
    mockUseReconciliation.mockReturnValue({
      data: {
        ...populated,
        positions: [{ ...populated.positions[0], quantity_delta: '0' }],
      },
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);
    expect(screen.getByRole('button', { name: /adopt/i })).toBeDisabled();
  });

  it('triggers a Schwab import from the Import button', async () => {
    mockUseReconciliation.mockReturnValue({
      data: populated,
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);

    await userEvent.click(
      screen.getByRole('button', { name: /import from schwab/i })
    );
    expect(mockTriggerImport).toHaveBeenCalledWith({ accountId: 1 });
  });

  it('switches to the activity tab and renders its view', async () => {
    mockUseReconciliation.mockReturnValue({
      data: populated,
      isLoading: false,
      error: null,
    });
    mockUseTransactionReconciliation.mockReturnValue({
      data: {
        window_start: '2026-05-01T00:00:00Z',
        window_end: '2026-08-01T00:00:00Z',
        last_import_at: '2026-07-31T00:00:00Z',
        never_imported: false,
        newer_failed_import_at: null,
        history_gap: false,
        history_gap_note: null,
        transaction_history_limit_days: 60,
        matched_count: 1,
        broker_only_count: 2,
        ic_only_count: 0,
        transactions: [],
      },
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);

    await userEvent.click(screen.getByRole('tab', { name: /activity/i }));
    expect(screen.getByTestId('txn-broker-only-count')).toHaveTextContent(
      '2 not in your ledger'
    );
    // The CSV recovery path is reachable from the activity tab even without a
    // flagged history gap — a first-ever import of an old account needs it too.
    expect(
      screen.getByRole('button', { name: /upload broker csv/i })
    ).toBeInTheDocument();
  });

  it('shows a never-imported banner instead of drift rows', () => {
    mockUseReconciliation.mockReturnValue({
      data: {
        last_import_at: null,
        never_imported: true,
        newer_failed_import_at: null,
        positions: [],
      } satisfies AccountReconciliation,
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);
    expect(
      screen.getByText(/no Schwab positions have been imported yet/i)
    ).toBeInTheDocument();
  });

  it('warns when the latest import attempt failed', () => {
    mockUseReconciliation.mockReturnValue({
      data: {
        ...populated,
        newer_failed_import_at: '2026-07-23T01:00:00Z',
      },
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={accounts} />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      /most recent Schwab pull failed/i
    );
  });

  it('prompts to link when the account has no active Schwab link (409)', () => {
    mockUseReconciliation.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new ApiError('conflict', 'CONFLICT', 409),
    });
    render(<ReconciliationView accounts={accounts} />);
    expect(
      screen.getByText(/isn.t linked to a Schwab account yet/i)
    ).toBeInTheDocument();
  });

  it('tells the user to add an account first when there are none', () => {
    mockUseReconciliation.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
    });
    render(<ReconciliationView accounts={[]} />);
    expect(screen.getByText(/Add an account first/i)).toBeInTheDocument();
  });
});
