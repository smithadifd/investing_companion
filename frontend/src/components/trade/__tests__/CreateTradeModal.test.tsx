import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { CreateTradeModal } from '../CreateTradeModal';

const mockMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useTrade', () => ({
  useCreateTrade: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

vi.mock('@/components/equity/EquitySearchInput', () => ({
  EquitySearchInput: ({
    value,
    onChange,
    onSelect,
  }: {
    value: string;
    onChange: (v: string) => void;
    onSelect: (r: { symbol: string; name: string; exchange: string | null; asset_type: string }) => void;
  }) => (
    <input
      data-testid="equity-search"
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
        if (e.target.value === 'AAPL') {
          onSelect({ symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', asset_type: 'stock' });
        }
      }}
    />
  ),
}));

describe('CreateTradeModal', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
  });

  it('renders nothing when not open', () => {
    const { container } = render(
      <CreateTradeModal isOpen={false} onClose={onClose} />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders modal with title when open', () => {
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);
    expect(screen.getByText('Log Trade')).toBeInTheDocument();
  });

  it('renders all trade type buttons', () => {
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);
    expect(screen.getByText('Buy')).toBeInTheDocument();
    expect(screen.getByText('Sell')).toBeInTheDocument();
    expect(screen.getByText('Short')).toBeInTheDocument();
    expect(screen.getByText('Cover')).toBeInTheDocument();
  });

  it('defaults to Buy trade type', () => {
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);
    expect(screen.getByText('Purchase shares (long position)')).toBeInTheDocument();
    expect(screen.getByText('Log Buy')).toBeInTheDocument();
  });

  it('changes trade type when clicking a button', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByText('Sell'));
    expect(screen.getByText('Sell shares you own')).toBeInTheDocument();
    expect(screen.getByText('Log Sell')).toBeInTheDocument();
  });

  it('shows total value when quantity and price are entered', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    await user.type(screen.getByPlaceholderText('100'), '50');
    await user.type(screen.getByPlaceholderText('50.00'), '200');

    expect(screen.getByText('Trade Value:')).toBeInTheDocument();
    expect(screen.getByText('$10,000.00')).toBeInTheDocument();
  });

  it('shows fees breakdown when fees are entered', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    await user.type(screen.getByPlaceholderText('100'), '50');
    await user.type(screen.getByPlaceholderText('50.00'), '200');

    // Clear default fees value and type new
    const feesInput = screen.getByPlaceholderText('0.00');
    await user.clear(feesInput);
    await user.type(feesInput, '9.99');

    expect(screen.getByText('Fees:')).toBeInTheDocument();
    expect(screen.getByText('Total:')).toBeInTheDocument();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
  });

  it('submits form with correct data', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    // Fill symbol
    const searchInput = screen.getByTestId('equity-search');
    await user.type(searchInput, 'AAPL');

    // Fill quantity
    await user.type(screen.getByPlaceholderText('100'), '50');

    // Fill price
    await user.type(screen.getByPlaceholderText('50.00'), '155');

    // Submit
    await user.click(screen.getByText('Log Buy'));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: 'AAPL',
          trade_type: 'buy',
          quantity: 50,
          price: 155,
          fees: 0,
        }),
      );
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('does not submit when required fields are missing', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByText('Log Buy'));
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  it('prefills symbol when prefillSymbol is provided', () => {
    render(<CreateTradeModal isOpen={true} onClose={onClose} prefillSymbol="TSLA" />);
    const searchInput = screen.getByTestId('equity-search');
    expect(searchInput).toHaveValue('TSLA');
  });

  it('changes submit button text based on trade type', async () => {
    const user = userEvent.setup();
    render(<CreateTradeModal isOpen={true} onClose={onClose} />);

    expect(screen.getByText('Log Buy')).toBeInTheDocument();
    await user.click(screen.getByText('Short'));
    expect(screen.getByText('Log Short')).toBeInTheDocument();
    await user.click(screen.getByText('Cover'));
    expect(screen.getByText('Log Cover')).toBeInTheDocument();
  });
});
