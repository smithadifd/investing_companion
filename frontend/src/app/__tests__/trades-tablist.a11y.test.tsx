import { describe, it, expect, vi } from 'vitest';
import { render, screen, userEvent } from '@/test/utils';

// Data hooks stubbed so the page renders to the tablist without a backend.
vi.mock('@/lib/hooks/useTrade', () => ({
  useTrades: () => ({ data: { trades: [], total: 0 }, isLoading: false }),
  usePortfolio: () => ({ data: undefined, isLoading: false }),
  usePerformance: () => ({ data: undefined, isLoading: false }),
  useDeleteTrade: () => ({ mutate: vi.fn(), isPending: false }),
  useCalculatePositionSize: () => ({ mutate: vi.fn(), data: undefined, isPending: false }),
}));
vi.mock('@/lib/hooks/useAccount', () => ({
  useAccounts: () => ({ data: [] }),
}));

import TradesPage from '@/app/trades/page';

describe('Trades tablist keyboard a11y (WAI-ARIA tabs pattern)', () => {
  it('arrow / Home / End move selection and focus together', async () => {
    const user = userEvent.setup();
    render(<TradesPage />);

    const tabs = screen.getAllByRole('tab');
    // Count-agnostic on purpose: this asserts the roving-focus BEHAVIOUR, and
    // a hard-coded length turns "a tab was added" into an a11y failure. The
    // tab set itself is asserted by name below.
    expect(tabs.length).toBeGreaterThanOrEqual(4);
    const last = tabs.length - 1;
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    // Non-selected tabs are out of the tab sequence (roving tabindex).
    expect(tabs[1]).toHaveAttribute('tabindex', '-1');

    tabs[0].focus();
    await user.keyboard('{ArrowRight}');
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[1]).toHaveFocus();

    await user.keyboard('{End}');
    expect(tabs[last]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[last]).toHaveFocus();

    await user.keyboard('{Home}');
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[0]).toHaveFocus();

    // Wraps from the first tab back to the last.
    await user.keyboard('{ArrowLeft}');
    expect(tabs[last]).toHaveAttribute('aria-selected', 'true');
    expect(tabs[last]).toHaveFocus();
  });

  it('exposes every view as a tab, including Total Return', () => {
    render(<TradesPage />);
    expect(
      screen.getAllByRole('tab').map((t) => t.textContent?.trim()),
    ).toEqual([
      'Trades',
      'Positions',
      'Total Return',
      'Performance',
      'Position Sizer',
    ]);
  });

  it('the selected tab controls a labelled tabpanel', () => {
    render(<TradesPage />);
    const selectedTab = screen.getByRole('tab', { selected: true });
    const panel = screen.getByRole('tabpanel');
    expect(selectedTab).toHaveAttribute('aria-controls', panel.id);
    expect(panel).toHaveAttribute('aria-labelledby', selectedTab.id);
  });
});
