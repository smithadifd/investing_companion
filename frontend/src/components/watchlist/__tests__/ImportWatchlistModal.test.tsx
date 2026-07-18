import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, userEvent } from '@/test/utils';
import { ImportWatchlistModal } from '../ImportWatchlistModal';
import type { WatchlistExport } from '@/lib/api/types';

const mockMutateAsync = vi.fn();
vi.mock('@/lib/hooks/useWatchlist', () => ({
  useImportWatchlist: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

// A realistic payload shaped exactly like the backend's real
// GET /watchlists/{id}/export response (see WatchlistExportItem in
// backend/app/schemas/watchlist.py / services/watchlist.py). This is what a
// round-trip actually exports today.
const exportedWatchlist: WatchlistExport = {
  name: 'Uranium & Nuclear',
  description: 'Restart thesis names',
  exported_at: '2026-07-18T00:00:00Z',
  items: [
    {
      symbol: 'CCJ',
      name: 'Cameco Corporation',
      notes: 'Watching for restart catalysts',
      target_price: '45.50',
      thesis: 'Utility restocking + SMR tailwind',
      entry_zones: [
        { tier: 'Half starter', low: 40, high: 44 },
        { tier: 'Aggressive', low: null, high: 36 },
      ],
      catalyst_tags: ['uranium restart', 'carry unwind'],
      track_calendar: false,
      added_at: '2026-01-05T00:00:00Z',
    },
  ],
};

// Shaped like an export produced *before* catalyst_tags/track_calendar
// existed (or PR #207-era backend): both keys are simply absent, exactly
// like an old on-disk export file a user re-uploads today.
const oldFormatExportedWatchlist: WatchlistExport = {
  name: 'Uranium & Nuclear',
  description: 'Restart thesis names',
  exported_at: '2026-07-18T00:00:00Z',
  items: [
    {
      symbol: 'CCJ',
      name: 'Cameco Corporation',
      notes: 'Watching for restart catalysts',
      target_price: '45.50',
      thesis: 'Utility restocking + SMR tailwind',
      entry_zones: null,
      added_at: '2026-01-05T00:00:00Z',
      // catalyst_tags / track_calendar intentionally absent.
    },
  ],
};

function makeExportFile(data: WatchlistExport): File {
  return new File([JSON.stringify(data)], 'watchlist.json', {
    type: 'application/json',
  });
}

describe('ImportWatchlistModal round-trip', () => {
  const onClose = vi.fn();
  const onSuccess = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockMutateAsync.mockResolvedValue({});
  });

  it('preserves entry_zones (and the existing notes/target_price/thesis fields) on import', async () => {
    const user = userEvent.setup();
    render(<ImportWatchlistModal onClose={onClose} onSuccess={onSuccess} />);

    const file = makeExportFile(exportedWatchlist);
    const input = document.getElementById('file-upload') as HTMLInputElement;
    await user.upload(input, file);

    // Preview renders once the file is parsed.
    await screen.findByText('Uranium & Nuclear');

    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));

    const payload = mockMutateAsync.mock.calls[0][0];
    expect(payload.items).toHaveLength(1);
    const item = payload.items[0];

    // Fields the import already carried through.
    expect(item.symbol).toBe('CCJ');
    expect(item.notes).toBe('Watching for restart catalysts');
    expect(item.target_price).toBe('45.50');
    expect(item.thesis).toBe('Utility restocking + SMR tailwind');

    // Regression: entry_zones must survive the export -> import round-trip.
    // Without the fix, this key is dropped entirely by the modal's mapping.
    expect(item.entry_zones).toEqual([
      { tier: 'Half starter', low: 40, high: 44 },
      { tier: 'Aggressive', low: null, high: 36 },
    ]);

    // Regression: catalyst_tags + track_calendar must also survive the
    // export -> import round-trip (previously dropped, same bug class as
    // entry_zones above).
    expect(item.catalyst_tags).toEqual(['uranium restart', 'carry unwind']);
    expect(item.track_calendar).toBe(false);
  });

  it('leaves catalyst_tags/track_calendar absent for an old-format export missing both keys', async () => {
    const user = userEvent.setup();
    render(<ImportWatchlistModal onClose={onClose} onSuccess={onSuccess} />);

    const input = document.getElementById('file-upload') as HTMLInputElement;
    await user.upload(input, makeExportFile(oldFormatExportedWatchlist));

    await screen.findByText('Uranium & Nuclear');
    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    const item = mockMutateAsync.mock.calls[0][0].items[0];

    // The transform must not invent values for keys the old file never had -
    // they stay undefined so the backend schema can apply its own defaults
    // (catalyst_tags -> NULL, track_calendar -> True).
    expect(item.catalyst_tags).toBeUndefined();
    expect(item.track_calendar).toBeUndefined();
  });

  it('does not lose a null entry_zones value', async () => {
    const user = userEvent.setup();
    render(<ImportWatchlistModal onClose={onClose} onSuccess={onSuccess} />);

    const noZones: WatchlistExport = {
      ...exportedWatchlist,
      items: [{ ...exportedWatchlist.items[0], entry_zones: null }],
    };
    const input = document.getElementById('file-upload') as HTMLInputElement;
    await user.upload(input, makeExportFile(noZones));

    await screen.findByText('Uranium & Nuclear');
    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    const item = mockMutateAsync.mock.calls[0][0].items[0];
    expect(item.entry_zones).toBeNull();
  });

  it('passes an explicit null catalyst_tags through unmodified', async () => {
    const user = userEvent.setup();
    render(<ImportWatchlistModal onClose={onClose} onSuccess={onSuccess} />);

    const nullTags: WatchlistExport = {
      ...exportedWatchlist,
      items: [{ ...exportedWatchlist.items[0], catalyst_tags: null }],
    };
    const input = document.getElementById('file-upload') as HTMLInputElement;
    await user.upload(input, makeExportFile(nullTags));

    await screen.findByText('Uranium & Nuclear');
    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    const item = mockMutateAsync.mock.calls[0][0].items[0];
    // The modal must not collapse/rewrite this - null-vs-[] canonicalization
    // is the backend's job (data.catalyst_tags or None), not the client's.
    expect(item.catalyst_tags).toBeNull();
  });

  it('passes an explicit empty catalyst_tags array through unmodified', async () => {
    const user = userEvent.setup();
    render(<ImportWatchlistModal onClose={onClose} onSuccess={onSuccess} />);

    const emptyTags: WatchlistExport = {
      ...exportedWatchlist,
      items: [{ ...exportedWatchlist.items[0], catalyst_tags: [] }],
    };
    const input = document.getElementById('file-upload') as HTMLInputElement;
    await user.upload(input, makeExportFile(emptyTags));

    await screen.findByText('Uranium & Nuclear');
    await user.click(screen.getByRole('button', { name: /^Import$/i }));

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledTimes(1));
    const item = mockMutateAsync.mock.calls[0][0].items[0];
    // Same: the client sends [] as-is and lets the backend canonicalize it
    // to NULL, matching the CRUD create/update paths.
    expect(item.catalyst_tags).toEqual([]);
  });
});
