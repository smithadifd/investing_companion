import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { CreateAlertModal } from '../CreateAlertModal';

// Mock hooks
const mockMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useAlert', () => ({
  useCreateAlert: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

vi.mock('@/lib/hooks/useRatio', () => ({
  useRatios: () => ({
    data: [
      { id: 1, name: 'Gold/Silver', numerator_symbol: 'GLD', denominator_symbol: 'SLV' },
      { id: 2, name: 'SPY/QQQ', numerator_symbol: 'SPY', denominator_symbol: 'QQQ' },
    ],
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
      onChange={(e) => onChange(e.target.value)}
      onFocus={() => {
        if (value === 'AAPL') {
          onSelect({ symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', asset_type: 'stock' });
        }
      }}
    />
  ),
}));

describe('CreateAlertModal', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
  });

  it('renders nothing when not open', () => {
    const { container } = render(
      <CreateAlertModal isOpen={false} onClose={onClose} />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders modal with title when open', () => {
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);
    expect(screen.getByRole('heading')).toHaveTextContent('Create Alert');
  });

  it('renders all condition options', () => {
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);
    const conditionSelect = screen.getByDisplayValue('Above');
    expect(conditionSelect).toBeInTheDocument();
    expect(conditionSelect.querySelectorAll('option')).toHaveLength(6);
  });

  it('shows Equity target type by default', () => {
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);
    expect(screen.getByTestId('equity-search')).toBeInTheDocument();
  });

  it('switches to Ratio target type', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByText('Ratio'));
    expect(screen.getByText('Select a ratio...')).toBeInTheDocument();
    expect(screen.getByText('Gold/Silver (GLD/SLV)')).toBeInTheDocument();
  });

  it('shows comparison period only for percent conditions', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    // Initially no comparison period
    expect(screen.queryByText('Comparison Period')).not.toBeInTheDocument();

    // Change to percent_up
    await user.selectOptions(screen.getByDisplayValue('Above'), 'percent_up');
    expect(screen.getByText('Comparison Period')).toBeInTheDocument();

    // Change back to non-percent
    await user.selectOptions(screen.getByDisplayValue('Percent Up'), 'below');
    expect(screen.queryByText('Comparison Period')).not.toBeInTheDocument();
  });

  it('auto-generates alert name from symbol and condition', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    const searchInput = screen.getByTestId('equity-search');
    await user.type(searchInput, 'AAPL');
    // Trigger onSelect by focusing
    await user.click(searchInput);

    const thresholdInput = screen.getByPlaceholderText('e.g., 200.00');
    await user.type(thresholdInput, '200');

    const nameInput = screen.getByPlaceholderText('Auto-generated from symbol & condition');
    expect(nameInput).toHaveValue('AAPL Above $200');
  });

  it('stops auto-generating name after manual edit', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    const nameInput = screen.getByPlaceholderText('Auto-generated from symbol & condition');
    await user.type(nameInput, 'My Custom Name');
    expect(nameInput).toHaveValue('My Custom Name');

    // Changing threshold shouldn't override the manual name
    const thresholdInput = screen.getByPlaceholderText('e.g., 200.00');
    await user.type(thresholdInput, '300');
    expect(nameInput).toHaveValue('My Custom Name');
  });

  it('calls onClose when Cancel is clicked', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
  });

  it('submits form with correct data', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    // Fill in symbol
    const searchInput = screen.getByTestId('equity-search');
    await user.type(searchInput, 'AAPL');
    await user.click(searchInput); // triggers onSelect

    // Fill in threshold
    const thresholdInput = screen.getByPlaceholderText('e.g., 200.00');
    await user.type(thresholdInput, '200');

    // Submit
    await user.click(screen.getByRole('button', { name: /Create Alert/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        name: 'AAPL Above $200',
        notes: undefined,
        equity_symbol: 'AAPL',
        ratio_id: undefined,
        condition_type: 'above',
        threshold_value: 200,
        comparison_period: undefined,
        cooldown_minutes: 60,
        is_active: true,
      });
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('does not submit when required fields are missing', async () => {
    const user = userEvent.setup();
    render(<CreateAlertModal isOpen={true} onClose={onClose} />);

    // Try to submit without filling anything
    await user.click(screen.getByRole('button', { name: /Create Alert/i }));
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  it('starts with ratio target type when prefillRatioId is provided', () => {
    render(<CreateAlertModal isOpen={true} onClose={onClose} prefillRatioId={1} />);
    expect(screen.getByText('Select a ratio...')).toBeInTheDocument();
  });
});
