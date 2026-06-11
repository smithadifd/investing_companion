import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@/test/utils';
import { NeedsAttention } from '../NeedsAttention';
import type { NeedsAttentionResponse } from '@/lib/api/types';

// Mock hook
const mockUseNeedsAttention = vi.fn();
vi.mock('@/lib/hooks/useDashboard', () => ({
  useNeedsAttention: () => mockUseNeedsAttention(),
}));

const mockData: NeedsAttentionResponse = {
  items: [
    {
      kind: 'alert_triggered',
      title: 'EQT zone entry',
      symbol: 'EQT',
      detail: 'Run the entry checklist',
      distance_percent: null,
      last_checked_value: null,
      target_price: null,
      last_triggered_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    },
    {
      kind: 'alert_approaching',
      title: 'LNG add level',
      symbol: 'LNG',
      detail: null,
      distance_percent: '-2.3',
      last_checked_value: '178.50',
      target_price: null,
      last_triggered_at: null,
    },
    {
      kind: 'target_near',
      title: 'CCJ',
      symbol: 'CCJ',
      detail: 'Uranium',
      distance_percent: '4.0',
      last_checked_value: null,
      target_price: '100.00',
      last_triggered_at: null,
    },
  ],
};

describe('NeedsAttention', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing while loading', () => {
    mockUseNeedsAttention.mockReturnValue({ data: undefined, isLoading: true, error: null });
    const { container } = render(<NeedsAttention />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when there are no items', () => {
    mockUseNeedsAttention.mockReturnValue({
      data: { items: [] },
      isLoading: false,
      error: null,
    });
    const { container } = render(<NeedsAttention />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing on error', () => {
    mockUseNeedsAttention.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('boom'),
    });
    const { container } = render(<NeedsAttention />);
    expect(container.innerHTML).toBe('');
  });

  it('renders the section header with a link to alerts', () => {
    mockUseNeedsAttention.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<NeedsAttention />);
    expect(screen.getByText('Needs Attention')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /View alerts/i })).toHaveAttribute(
      'href',
      '/alerts'
    );
  });

  it('renders a triggered alert with its action note', () => {
    mockUseNeedsAttention.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<NeedsAttention />);
    expect(screen.getByText('EQT zone entry triggered')).toBeInTheDocument();
    expect(screen.getByText('Run the entry checklist')).toBeInTheDocument();
    expect(screen.getByText('2h ago')).toBeInTheDocument();
  });

  it('renders an approaching alert with distance and last value', () => {
    mockUseNeedsAttention.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<NeedsAttention />);
    expect(screen.getByText('LNG add level')).toBeInTheDocument();
    expect(screen.getByText('-2.3% away')).toBeInTheDocument();
    expect(screen.getByText('last 178.50')).toBeInTheDocument();
  });

  it('renders a near target with target price and watchlist', () => {
    mockUseNeedsAttention.mockReturnValue({ data: mockData, isLoading: false, error: null });
    render(<NeedsAttention />);
    expect(screen.getByText('CCJ')).toBeInTheDocument();
    expect(screen.getByText('target $100.00 · Uranium')).toBeInTheDocument();
    expect(screen.getByText('4.0% to target')).toBeInTheDocument();
  });
});
