import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { ExecuteTriggerModal } from '../ExecuteTriggerModal';
import type { Trigger } from '@/lib/api/types';

// Mock hooks
const mockMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useTrigger', () => ({
  useExecuteTrigger: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

const mockTrigger: Trigger = {
  id: 5,
  name: 'SPY Put Management',
  rule: 'SPY puts double in value',
  action: 'Sell half, let the rest ride',
  tier: 'orange',
  display_order: 2,
  status: 'active',
  signal: 'hit',
  executed_at: null,
  execution_note: null,
  alerts: [],
  created_at: '2026-06-11T00:00:00Z',
};

describe('ExecuteTriggerModal', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
  });

  it('shows the trigger recap (name, rule, action)', () => {
    render(<ExecuteTriggerModal trigger={mockTrigger} onClose={onClose} />);
    expect(screen.getByRole('heading')).toHaveTextContent('Mark Executed');
    expect(screen.getByText('SPY Put Management')).toBeInTheDocument();
    expect(screen.getByText('SPY puts double in value')).toBeInTheDocument();
    expect(screen.getByText('Sell half, let the rest ride')).toBeInTheDocument();
  });

  it('focuses the note field on open', () => {
    render(<ExecuteTriggerModal trigger={mockTrigger} onClose={onClose} />);
    expect(screen.getByLabelText('What did you actually do?')).toHaveFocus();
  });

  it('submits with the trimmed note', async () => {
    const user = userEvent.setup();
    render(<ExecuteTriggerModal trigger={mockTrigger} onClose={onClose} />);

    await user.type(
      screen.getByLabelText('What did you actually do?'),
      '  Sold 2 of 4 puts at $8.40  '
    );
    await user.click(screen.getByRole('button', { name: /Mark Executed/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        id: 5,
        note: 'Sold 2 of 4 puts at $8.40',
      });
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('submits without a note when left empty', async () => {
    const user = userEvent.setup();
    render(<ExecuteTriggerModal trigger={mockTrigger} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: /Mark Executed/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ id: 5, note: undefined });
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('shows a character count for the note', async () => {
    const user = userEvent.setup();
    render(<ExecuteTriggerModal trigger={mockTrigger} onClose={onClose} />);

    expect(screen.getByText('0/2000')).toBeInTheDocument();
    await user.type(screen.getByLabelText('What did you actually do?'), 'Done.');
    expect(screen.getByText('5/2000')).toBeInTheDocument();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const user = userEvent.setup();
    render(<ExecuteTriggerModal trigger={mockTrigger} onClose={onClose} />);

    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalled();
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });
});
