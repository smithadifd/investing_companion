import { describe, it, expect, vi } from 'vitest';
import { render, screen, userEvent } from '@/test/utils';

// --- SearchBar combobox needs router + debounce + search-hook stubs ---------
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('@/lib/hooks/useDebounce', () => ({
  useDebounce: (value: string) => value, // pass through, no timer in tests
}));
const mockResults = [
  { symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ' },
  { symbol: 'AMD', name: 'Advanced Micro Devices', exchange: 'NASDAQ' },
];
vi.mock('@/lib/hooks/useEquity', () => ({
  useEquitySearch: (query: string, enabled: boolean) => ({
    data: enabled && query ? mockResults : undefined,
    isLoading: false,
  }),
}));

import { SearchBar } from '@/components/search/SearchBar';
import { PeriodSelector } from '@/components/equity/PeriodSelector';
import { PriceChange } from '@/components/ui/PriceChange';
import { NewsSentimentBadge } from '@/components/news/NewsSentimentBadge';

describe('SearchBar combobox a11y', () => {
  it('exposes combobox semantics and a labelled listbox of options', async () => {
    const user = userEvent.setup();
    render(<SearchBar />);

    const input = screen.getByRole('combobox', { name: /search for a stock symbol/i });
    // Collapsed on mount.
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(input).toHaveAttribute('aria-autocomplete', 'list');

    await user.click(input);
    await user.keyboard('AA');

    const listbox = await screen.findByRole('listbox', { name: /symbol search results/i });
    expect(listbox).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(input).toHaveAttribute('aria-controls', listbox.id);

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);

    // Arrow-down activates the first option and points aria-activedescendant at it.
    await user.keyboard('{ArrowDown}');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(input).toHaveAttribute('aria-activedescendant', options[0].id);
  });
});

describe('PeriodSelector segmented control a11y', () => {
  it('is a labelled group of toggle buttons with a pressed selection', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<PeriodSelector value="1mo" onChange={onChange} />);

    expect(screen.getByRole('group', { name: /chart time period/i })).toBeInTheDocument();

    const selected = screen.getByRole('button', { name: /show 1M chart/i });
    expect(selected).toHaveAttribute('aria-pressed', 'true');

    const other = screen.getByRole('button', { name: /show 1Y chart/i });
    expect(other).toHaveAttribute('aria-pressed', 'false');

    await user.click(other);
    expect(onChange).toHaveBeenCalledWith('1y');
  });
});

describe('non-color status cues', () => {
  it('PriceChange spells out direction for assistive tech', () => {
    const { rerender } = render(<PriceChange value={2.5} />);
    expect(screen.getByLabelText('up 2.50%')).toBeInTheDocument();

    rerender(<PriceChange value={-3.1} />);
    expect(screen.getByLabelText('down 3.10%')).toBeInTheDocument();
  });

  it('NewsSentimentBadge carries a text label + glyph, not color alone', () => {
    render(<NewsSentimentBadge sentiment="negative" />);
    const badge = screen.getByLabelText('Negative sentiment');
    expect(badge).toHaveTextContent('Negative');
    expect(badge).toHaveTextContent('▼');
  });
});
