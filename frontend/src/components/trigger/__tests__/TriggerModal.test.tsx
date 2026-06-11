import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { TriggerModal } from '../TriggerModal';
import type { Trigger } from '@/lib/api/types';

// Mock hooks
const mockCreateMutateAsync = vi.fn();
const mockUpdateMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useTrigger', () => ({
  useCreateTrigger: () => ({
    mutateAsync: mockCreateMutateAsync,
    isPending: false,
  }),
  useUpdateTrigger: () => ({
    mutateAsync: mockUpdateMutateAsync,
    isPending: false,
  }),
}));

vi.mock('@/lib/hooks/useAlert', () => ({
  useAlerts: () => ({
    data: [
      { id: 10, name: 'SPY % From High 10%', is_active: true },
      { id: 11, name: 'CCJ Below $80', is_active: false },
    ],
  }),
}));

const mockTrigger: Trigger = {
  id: 1,
  name: 'SPY Crisis Tier 1',
  rule: 'SPY closes 10% below its 1y high',
  action: 'Deploy first tranche',
  tier: 'yellow',
  display_order: 3,
  status: 'active',
  signal: 'armed',
  executed_at: null,
  execution_note: null,
  alerts: [
    {
      id: 10,
      name: 'SPY % From High 10%',
      is_active: true,
      distance_percent: 2.5,
      last_triggered_at: null,
    },
  ],
  created_at: '2026-06-11T00:00:00Z',
};

describe('TriggerModal', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateMutateAsync.mockResolvedValue({});
    mockUpdateMutateAsync.mockResolvedValue({});
  });

  it('renders nothing when not open', () => {
    const { container } = render(<TriggerModal isOpen={false} onClose={onClose} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders create modal with title when open', () => {
    render(<TriggerModal isOpen={true} onClose={onClose} />);
    expect(screen.getByRole('heading')).toHaveTextContent('New Trigger');
  });

  it('renders edit modal with prefilled values', () => {
    render(<TriggerModal isOpen={true} onClose={onClose} trigger={mockTrigger} />);
    expect(screen.getByRole('heading')).toHaveTextContent('Edit Trigger');
    expect(screen.getByDisplayValue('SPY Crisis Tier 1')).toBeInTheDocument();
    expect(screen.getByDisplayValue('SPY closes 10% below its 1y high')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Deploy first tranche')).toBeInTheDocument();
    expect(screen.getByDisplayValue('3')).toBeInTheDocument();
  });

  it('lists alerts with linked ones pre-checked in edit mode', () => {
    render(<TriggerModal isOpen={true} onClose={onClose} trigger={mockTrigger} />);
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();
  });

  it('shows Paused badge for inactive alerts', () => {
    render(<TriggerModal isOpen={true} onClose={onClose} />);
    expect(screen.getByText('Paused')).toBeInTheDocument();
  });

  it('filters the alert list', async () => {
    const user = userEvent.setup();
    render(<TriggerModal isOpen={true} onClose={onClose} />);

    await user.type(screen.getByPlaceholderText('Filter alerts...'), 'CCJ');
    expect(screen.getByText('CCJ Below $80')).toBeInTheDocument();
    expect(screen.queryByText('SPY % From High 10%')).not.toBeInTheDocument();
  });

  it('submits create with correct data including selected alerts', async () => {
    const user = userEvent.setup();
    render(<TriggerModal isOpen={true} onClose={onClose} />);

    await user.type(
      screen.getByPlaceholderText('e.g., SPY Crisis Tier 2'),
      'LNG Stop Loss'
    );
    await user.type(
      screen.getByPlaceholderText('e.g., SPY closes 10% below its 1y high'),
      'LNG closes below $170'
    );
    await user.type(
      screen.getByPlaceholderText(
        'e.g., Deploy first tranche: buy 10 shares SPY, no second-guessing'
      ),
      'Sell the full position'
    );
    await user.selectOptions(screen.getByDisplayValue('No tier'), 'red');
    await user.click(screen.getByText('CCJ Below $80'));

    await user.click(screen.getByRole('button', { name: /Create Trigger/i }));

    await waitFor(() => {
      expect(mockCreateMutateAsync).toHaveBeenCalledWith({
        name: 'LNG Stop Loss',
        rule: 'LNG closes below $170',
        action: 'Sell the full position',
        tier: 'red',
        display_order: 0,
        alert_ids: [11],
      });
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('submits update with trigger id in edit mode', async () => {
    const user = userEvent.setup();
    render(<TriggerModal isOpen={true} onClose={onClose} trigger={mockTrigger} />);

    const nameInput = screen.getByDisplayValue('SPY Crisis Tier 1');
    await user.clear(nameInput);
    await user.type(nameInput, 'SPY Crisis Tier 1 (revised)');

    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockUpdateMutateAsync).toHaveBeenCalledWith({
        id: 1,
        data: {
          name: 'SPY Crisis Tier 1 (revised)',
          rule: 'SPY closes 10% below its 1y high',
          action: 'Deploy first tranche',
          tier: 'yellow',
          display_order: 3,
          alert_ids: [10],
        },
      });
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('does not submit when required fields are missing', async () => {
    const user = userEvent.setup();
    render(<TriggerModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: /Create Trigger/i }));
    expect(mockCreateMutateAsync).not.toHaveBeenCalled();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const user = userEvent.setup();
    render(<TriggerModal isOpen={true} onClose={onClose} />);

    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
  });
});
