import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { EditItemModal } from '../EditItemModal';
import type { Alert, WatchlistItem } from '@/lib/api/types';

const mockUpdateItem = vi.fn();
vi.mock('@/lib/hooks/useWatchlist', () => ({
  useUpdateWatchlistItem: () => ({
    mutateAsync: mockUpdateItem,
    isPending: false,
  }),
}));

const mockCreateAlert = vi.fn();
const mockDeleteAlert = vi.fn();
let mockAlerts: Alert[] = [];
vi.mock('@/lib/hooks/useAlert', () => ({
  useAlerts: () => ({ data: mockAlerts }),
  useCreateAlert: () => ({ mutateAsync: mockCreateAlert, isPending: false }),
  useDeleteAlert: () => ({ mutateAsync: mockDeleteAlert, isPending: false }),
}));

const baseItem: WatchlistItem = {
  id: 11,
  watchlist_id: 3,
  equity_id: 7,
  notes: null,
  target_price: '51',
  thesis: 'May-12 tiered framework',
  track_calendar: true,
  entry_zones: [
    { tier: 'Half starter', low: '50', high: '52' },
    { tier: 'Aggressive', low: null, high: '46' },
  ],
  zone_statuses: [],
  catalyst_tags: [],
  added_at: '2026-05-12T00:00:00Z',
  equity: {
    id: 7,
    symbol: 'EQT',
    name: 'EQT Corporation',
    exchange: 'NYSE',
    sector: 'Energy',
  },
  quote: null,
};

const zoneAlert: Alert = {
  id: 99,
  name: 'EQT entry zones',
  notes: null,
  equity_id: 7,
  ratio_id: null,
  watchlist_item_id: 11,
  zone_state: null,
  condition_type: 'entry_zone',
  threshold_value: '0',
  comparison_period: null,
  cooldown_minutes: 60,
  is_active: true,
  last_triggered_at: null,
  last_checked_value: null,
  confirm_checks: null,
  consecutive_met_count: 0,
  created_at: '2026-06-11T00:00:00Z',
  updated_at: '2026-06-11T00:00:00Z',
  target: { type: 'equity', id: 7, symbol: 'EQT', name: 'EQT Corporation' },
};

describe('EditItemModal entry zones', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockAlerts = [];
    mockUpdateItem.mockResolvedValue({});
    mockCreateAlert.mockResolvedValue({});
    mockDeleteAlert.mockResolvedValue({});
  });

  it('prefills existing zones', () => {
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    expect(screen.getByDisplayValue('Half starter')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Aggressive')).toBeInTheDocument();
  });

  it('submits zones in the update payload', async () => {
    const user = userEvent.setup();
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockUpdateItem).toHaveBeenCalledWith({
        watchlistId: 3,
        itemId: 11,
        data: expect.objectContaining({
          entry_zones: [
            { tier: 'Half starter', low: 50, high: 52 },
            { tier: 'Aggressive', low: null, high: 46 },
          ],
        }),
      });
    });
  });

  it('sends explicit null when all zones are removed', async () => {
    const user = userEvent.setup();
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    // Re-query after each click: removal re-renders the list
    while (screen.queryAllByTitle('Remove zone').length > 0) {
      await user.click(screen.queryAllByTitle('Remove zone')[0]);
    }
    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockUpdateItem).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({ entry_zones: null }),
        })
      );
    });
  });

  it('blocks submit on invalid zones', async () => {
    const user = userEvent.setup();
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    const lowInput = screen.getByLabelText('Zone 1 low bound');
    await user.clear(lowInput);
    await user.type(lowInput, '60');
    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /low must be less than high/
    );
    expect(mockUpdateItem).not.toHaveBeenCalled();
  });

  it('creates a zone alert when the toggle is enabled', async () => {
    const user = userEvent.setup();
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    await user.click(
      screen.getByRole('switch', { name: /Alert when price enters a zone/i })
    );
    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockCreateAlert).toHaveBeenCalledWith({
        name: 'EQT entry zones',
        condition_type: 'entry_zone',
        watchlist_item_id: 11,
      });
    });
  });

  it('deletes the zone alert when the toggle is disabled', async () => {
    mockAlerts = [zoneAlert];
    const user = userEvent.setup();
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    const toggle = screen.getByRole('switch', {
      name: /Alert when price enters a zone/i,
    });
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    await user.click(toggle);
    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => {
      expect(mockDeleteAlert).toHaveBeenCalledWith(99);
    });
    expect(mockCreateAlert).not.toHaveBeenCalled();
  });

  it('does not recreate an existing zone alert', async () => {
    mockAlerts = [zoneAlert];
    const user = userEvent.setup();
    render(<EditItemModal watchlistId={3} item={baseItem} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: /Save Changes/i }));

    await waitFor(() => expect(mockUpdateItem).toHaveBeenCalled());
    expect(mockCreateAlert).not.toHaveBeenCalled();
    expect(mockDeleteAlert).not.toHaveBeenCalled();
  });
});
