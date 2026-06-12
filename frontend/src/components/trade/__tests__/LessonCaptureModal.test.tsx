import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { LessonCaptureModal } from '../LessonCaptureModal';

const mockMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useLessons', () => ({
  useCreateLesson: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

describe('LessonCaptureModal', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
  });

  it('renders the closed-position title and outcome options', () => {
    render(<LessonCaptureModal symbol="EQT" tradeId={7} onClose={onClose} />);
    expect(screen.getByText('Position closed: EQT')).toBeInTheDocument();
    expect(screen.getByText('Played out')).toBeInTheDocument();
    expect(screen.getByText('Partially')).toBeInTheDocument();
    expect(screen.getByText('Wrong')).toBeInTheDocument();
    expect(screen.getByText('Unclear')).toBeInTheDocument();
  });

  it('disables save until an outcome and lesson are provided', async () => {
    const user = userEvent.setup();
    render(<LessonCaptureModal symbol="EQT" tradeId={7} onClose={onClose} />);

    const save = screen.getByRole('button', { name: 'Save lesson' });
    expect(save).toBeDisabled();

    await user.click(screen.getByText('Wrong'));
    expect(save).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText(/What would you tell yourself/),
      'Bought the first touch; zone broke.'
    );
    expect(save).toBeEnabled();
  });

  it('skipping closes without saving anything', async () => {
    const user = userEvent.setup();
    render(<LessonCaptureModal symbol="EQT" tradeId={7} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onClose).toHaveBeenCalled();
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  it('saves the lesson with parsed tags and closes', async () => {
    const user = userEvent.setup();
    render(<LessonCaptureModal symbol="EQT" tradeId={7} onClose={onClose} />);

    await user.click(screen.getByText('Played out'));
    await user.type(
      screen.getByPlaceholderText(/What would you tell yourself/),
      'Zone discipline paid off.'
    );
    await user.type(
      screen.getByPlaceholderText(/natgas, entry-zone/),
      'NatGas, entry-zone , '
    );
    await user.click(screen.getByRole('button', { name: 'Save lesson' }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        trade_id: 7,
        thesis_outcome: 'played_out',
        lesson: 'Zone discipline paid off.',
        tags: ['NatGas', 'entry-zone'],
      });
    });
    expect(onClose).toHaveBeenCalled();
  });
});
