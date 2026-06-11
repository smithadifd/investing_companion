import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { EditAlertModal } from '../EditAlertModal';
import type { Alert } from '@/lib/api/types';

// Mock hooks
const mockMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useAlert', () => ({
  useUpdateAlert: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

const baseAlert: Alert = {
  id: 7,
  name: 'U sustained sub-$60',
  notes: null,
  equity_id: 1,
  ratio_id: null,
  condition_type: 'crosses_below',
  threshold_value: '60',
  comparison_period: null,
  cooldown_minutes: 60,
  is_active: true,
  last_triggered_at: null,
  last_checked_value: '62.5',
  confirm_checks: 4,
  consecutive_met_count: 1,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  target: {
    type: 'equity',
    id: 1,
    symbol: 'SRUUF',
    name: 'Sprott Physical Uranium Trust',
  },
};

describe('EditAlertModal', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
  });

  it('prefills the sustained confirmation for a crossing alert', () => {
    render(<EditAlertModal alert={baseAlert} onClose={onClose} />);
    expect(screen.getByText(/Sustained for/)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Fire on the cross (default)')
    ).toHaveValue(4);
  });

  it('submits the updated confirm_checks value', async () => {
    const user = userEvent.setup();
    render(<EditAlertModal alert={baseAlert} onClose={onClose} />);

    const confirmInput = screen.getByPlaceholderText('Fire on the cross (default)');
    await user.clear(confirmInput);
    await user.type(confirmInput, '6');

    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        id: 7,
        data: expect.objectContaining({ confirm_checks: 6 }),
      });
    });
  });

  it('sends explicit null when the confirmation is cleared', async () => {
    const user = userEvent.setup();
    render(<EditAlertModal alert={baseAlert} onClose={onClose} />);

    const confirmInput = screen.getByPlaceholderText('Fire on the cross (default)');
    await user.clear(confirmInput);

    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        id: 7,
        data: expect.objectContaining({ confirm_checks: null }),
      });
    });
  });

  it('hides the sustained input for non-crossing alerts', () => {
    render(
      <EditAlertModal
        alert={{ ...baseAlert, condition_type: 'below', confirm_checks: null }}
        onClose={onClose}
      />
    );
    expect(screen.queryByText(/Sustained for/)).not.toBeInTheDocument();
  });
});
