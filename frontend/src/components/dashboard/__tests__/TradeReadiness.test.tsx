import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@/test/utils';
import { TradeReadiness } from '../TradeReadiness';
import type { TradeReadinessResponse } from '@/lib/api/types';

// Mock hook
const mockUseTradeReadiness = vi.fn();
vi.mock('@/lib/hooks/useDashboard', () => ({
  useTradeReadiness: () => mockUseTradeReadiness(),
}));

const mockData: TradeReadinessResponse = {
  items: [
    {
      trigger_id: 1,
      name: 'EQT zone entry',
      tier: 'orange',
      rule: 'EQT pulls back into the entry zone',
      action: 'Buy tranche 1 per the plan',
      signal: 'hit',
      distance_percent: null,
      last_triggered_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
      symbols: ['EQT'],
      positions: [{ symbol: 'EQT', quantity: '50', avg_cost_basis: '22.10' }],
      upcoming_events: [
        {
          title: 'EQT Earnings',
          symbol: 'EQT',
          event_date: '2026-06-13',
          days_away: 2,
        },
      ],
      inactive_alert_count: 0,
      lessons: [
        {
          id: 11,
          symbol: 'LNG',
          thesis_outcome: 'wrong',
          lesson: 'Bought the first touch; zone broke.',
          tags: ['natgas'],
          recorded_at: '2026-06-01T12:00:00Z',
        },
      ],
    },
    {
      trigger_id: 2,
      name: 'LNG add level',
      tier: null,
      rule: 'LNG pulls back to the add level',
      action: 'Add half a position',
      signal: 'approaching',
      distance_percent: '-2.3',
      last_triggered_at: null,
      symbols: ['LNG'],
      positions: [],
      upcoming_events: [],
      inactive_alert_count: 1,
      lessons: [],
    },
  ],
};

describe('TradeReadiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing while loading', () => {
    mockUseTradeReadiness.mockReturnValue({ data: undefined, isLoading: true, error: null });
    const { container } = render(<TradeReadiness />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when there are no items', () => {
    mockUseTradeReadiness.mockReturnValue({
      data: { items: [] },
      isLoading: false,
      error: null,
    });
    const { container } = render(<TradeReadiness />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing on error', () => {
    mockUseTradeReadiness.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('boom'),
    });
    const { container } = render(<TradeReadiness />);
    expect(container.innerHTML).toBe('');
  });

  it('renders the section header with a link to the playbook', () => {
    mockUseTradeReadiness.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<TradeReadiness />);
    expect(screen.getByText('Trade Readiness')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open playbook/i })).toHaveAttribute(
      'href',
      '/playbook'
    );
  });

  it('renders a hit trigger as ready with tier, action, and position context', () => {
    mockUseTradeReadiness.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<TradeReadiness />);
    expect(screen.getByText('EQT zone entry')).toBeInTheDocument();
    expect(screen.getByText('orange')).toBeInTheDocument();
    expect(screen.getByText('Buy tranche 1 per the plan')).toBeInTheDocument();
    expect(screen.getByText('Ready · hit 3h ago')).toBeInTheDocument();
    expect(screen.getByText('Holding 50 EQT @ $22.10')).toBeInTheDocument();
  });

  it('renders an upcoming event caution', () => {
    mockUseTradeReadiness.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<TradeReadiness />);
    expect(screen.getByText(/EQT earnings in 2d/)).toBeInTheDocument();
  });

  it('renders an approaching trigger with distance and no-position context', () => {
    mockUseTradeReadiness.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<TradeReadiness />);
    expect(screen.getByText('LNG add level')).toBeInTheDocument();
    expect(screen.getByText('-2.3% away')).toBeInTheDocument();
    expect(screen.getByText('No position')).toBeInTheDocument();
  });

  it('renders resurfaced lessons with outcome label', () => {
    mockUseTradeReadiness.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<TradeReadiness />);
    expect(
      screen.getByText('Bought the first touch; zone broke.', { exact: false })
    ).toBeInTheDocument();
    expect(screen.getByText('(thesis wrong)')).toBeInTheDocument();
  });

  it('flags disabled linked alerts', () => {
    mockUseTradeReadiness.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<TradeReadiness />);
    expect(screen.getByText('1 alert disabled')).toBeInTheDocument();
  });
});
