import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, userEvent, waitFor, within } from '@/test/utils';
import { NavPanel } from '../NavPanel';
import type { NavSummary } from '@/lib/api/types';

/**
 * SEAM UNDER TEST: the NAV panel's rendering contract over `NavSummary`.
 *
 * The two properties that matter are the ones a wrong UI would quietly break:
 * the headline is the ABSOLUTE DOLLAR figure (not the percentage), and an
 * `is_estimated` response must SHOW its gaps rather than render a confident
 * number. A NAV missing an input is not a smaller NAV — it is short by an
 * unknown amount, and the panel has to say so.
 *
 * Hooks are stubbed at the data boundary, which is where the component's own
 * interface ends.
 */

const mockNav = vi.fn();
const mockCash = vi.fn();
const mockBackfill = vi.fn();

vi.mock('@/lib/hooks/useCash', () => ({
  useNav: () => mockNav(),
  useCashTransactions: () => mockCash(),
  useBackfillCash: () => ({ mutateAsync: mockBackfill, isPending: false }),
  useCreateCashTransaction: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteCashTransaction: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('@/lib/hooks/useAccount', () => ({
  useAccounts: () => ({
    data: [{ id: 7, name: 'Roth', account_type: 'roth' }],
  }),
}));

function navSummary(overrides: Partial<NavSummary> = {}): NavSummary {
  return {
    account_id: null,
    account: null,
    cash_balance: '9000.00',
    positions_market_value: '1500.00',
    nav: '10500.00',
    net_contributions: '10000.00',
    realized_pnl: '0.00',
    unrealized_pnl: '500.00',
    dividends_received: '0.00',
    fees_paid: '0.00',
    total_return_amount: '500.00',
    total_return_percent: '5.00',
    as_of: new Date().toISOString(),
    is_estimated: false,
    estimate_reasons: [],
    coverage: {
      cash_starts_at: new Date().toISOString(),
      first_activity_at: new Date().toISOString(),
      complete_from: null,
      is_true_origin: true,
      provenance_source: null,
      provenance_note: null,
      opening_balance_is_known: true,
    },
    ...overrides,
  };
}

describe('NavPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCash.mockReturnValue({ data: [] });
    mockNav.mockReturnValue({ data: navSummary(), isLoading: false });
  });

  it('leads with the absolute dollar total return', () => {
    render(<NavPanel />);
    // Scoped to the headline card: the same figure also appears in the
    // breakdown grid, and the point of this assertion is WHERE it leads.
    const headline = screen.getByText('Total return').closest('div');
    expect(headline).not.toBeNull();
    expect(within(headline as HTMLElement).getByText('$500.00')).toBeInTheDocument();
    expect(
      within(headline as HTMLElement).getByText(/NAV/),
    ).toBeInTheDocument();
  });

  it('shows the percentage only as a subordinate, labelled line', () => {
    render(<NavPanel />);
    expect(
      screen.getByText(/5\.00% of \$10,000\.00 contributed/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/a simple return, not time-weighted/),
    ).toBeInTheDocument();
  });

  it('says so plainly when there is no percentage to show', () => {
    mockNav.mockReturnValue({
      data: navSummary({
        total_return_percent: null,
        net_contributions: '0.00',
      }),
      isLoading: false,
    });
    render(<NavPanel />);
    expect(
      screen.getByText(/No contributions recorded/),
    ).toBeInTheDocument();
  });

  it('renders every estimate reason when the NAV is estimated', () => {
    mockNav.mockReturnValue({
      data: navSummary({
        is_estimated: true,
        estimate_reasons: [
          'no quote for AAPL: its market value is missing from NAV, not counted as zero',
          'opening cash balance before 2026-07-01 is unknown',
        ],
        coverage: {
          cash_starts_at: new Date().toISOString(),
          first_activity_at: new Date().toISOString(),
          complete_from: '2026-07-01T00:00:00Z',
          is_true_origin: false,
          provenance_source: 'schwab_api',
          provenance_note: 'HISTORY GAP: requested window start predates ...',
          opening_balance_is_known: false,
        },
      }),
      isLoading: false,
    });
    render(<NavPanel />);

    expect(
      screen.getByText(/Estimated — some inputs are missing/),
    ).toBeInTheDocument();
    expect(screen.getByText(/no quote for AAPL/)).toBeInTheDocument();
    expect(
      screen.getByText(/opening cash balance before 2026-07-01 is unknown/),
    ).toBeInTheDocument();
    // REVIEW FINDING 2: the boundary itself is shown, so "estimated" reads as
    // "complete only from this date" rather than a vague warning.
    expect(
      screen.getByText(/Cash history is complete only from/),
    ).toBeInTheDocument();
    expect(screen.getByText(/schwab_api/)).toBeInTheDocument();
  });

  it('shows no estimate banner when nothing is missing', () => {
    render(<NavPanel />);
    expect(screen.queryByText(/Estimated/)).not.toBeInTheDocument();
  });

  it('offers the broker backfill only once an account is chosen', async () => {
    const user = userEvent.setup();
    render(<NavPanel />);
    // Scope defaults to "All accounts" — there is no single account to
    // backfill into, so the action is not offered.
    expect(
      screen.queryByRole('button', { name: /Backfill from broker/ }),
    ).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Account'), '7');
    expect(
      screen.getByRole('button', { name: /Backfill from broker/ }),
    ).toBeInTheDocument();
  });

  it('reports what a backfill adopted, and what it declined', async () => {
    mockBackfill.mockResolvedValue({
      account_id: 7,
      created: [],
      already_present: 3,
      skipped: [
        {
          external_transaction_id: 'schwab:aa:9',
          broker_type: 'DIVIDEND_OR_INTEREST',
          occurred_at: new Date().toISOString(),
          net_amount: '120.00',
          reason: 'dividend/interest income is manual-entry only',
        },
      ],
      coverage: {
        cash_starts_at: null,
        first_activity_at: null,
        complete_from: null,
        is_true_origin: false,
        provenance_source: 'schwab_api',
        provenance_note: null,
        opening_balance_is_known: true,
      },
      history_gap_note: 'HISTORY GAP: requested window start predates ...',
      transaction_history_limit_days: 60,
    });
    const user = userEvent.setup();
    render(<NavPanel />);

    await user.selectOptions(screen.getByLabelText('Account'), '7');
    await user.click(
      screen.getByRole('button', { name: /Backfill from broker/ }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Adopted 0 cash movements; 3 already recorded\./),
      ).toBeInTheDocument();
    });
    // The 60-day boundary must be visible, not implied by an empty ledger.
    expect(screen.getByText(/HISTORY GAP/)).toBeInTheDocument();
    // Nothing is silently dropped.
    expect(
      screen.getByText(/1 broker row not adopted/),
    ).toBeInTheDocument();
  });

  it('explains an empty ledger rather than showing a bare zero', () => {
    render(<NavPanel />);
    expect(
      screen.getByText(/total return is reported as an estimate/),
    ).toBeInTheDocument();
  });
});
