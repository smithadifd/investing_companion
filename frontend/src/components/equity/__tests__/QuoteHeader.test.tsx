import { describe, it, expect } from 'vitest';
import { render, screen } from '@/test/utils';
import { QuoteHeader } from '../QuoteHeader';
import type { EquityDetail, Quote } from '@/lib/api/types';

function equity(quote: Partial<Quote> | null): EquityDetail {
  return {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    exchange: 'NASDAQ',
    asset_type: 'stock',
    sector: 'Technology',
    industry: 'Consumer Electronics',
    country: 'US',
    currency: 'USD',
    fundamentals: null,
    quote:
      quote === null
        ? null
        : {
            symbol: 'AAPL',
            price: '190.12',
            change: '1.25',
            change_percent: '0.66',
            open: '189.00',
            high: '191.00',
            low: '188.50',
            previous_close: '188.87',
            volume: 1_000_000,
            market_cap: null,
            timestamp: '2026-08-30T18:00:00',
            ...quote,
          },
  };
}

describe('QuoteHeader provenance badge', () => {
  it('renders no badge for a fresh live quote', () => {
    render(<QuoteHeader equity={equity({ source: 'yahoo', stale: false })} />);
    expect(screen.queryByTestId('quote-provenance')).toBeNull();
  });

  it('does not treat a source name as a contractual delay', () => {
    render(<QuoteHeader equity={equity({ source: 'massive', stale: false })} />);
    expect(screen.queryByTestId('quote-provenance')).toBeNull();
  });

  it('still warns when a live primary fell through to a fallback', () => {
    render(<QuoteHeader equity={equity({ source: 'stooq', stale: true })} />);

    const badge = screen.getByTestId('quote-provenance');
    expect(badge).toHaveTextContent('Delayed data');
    expect(badge).toHaveTextContent('stooq');
    expect(badge).not.toHaveTextContent('15-min delayed');
    expect(badge.getAttribute('title')).toMatch(/unavailable/i);
  });

  it('warns for a removed delayed source instead of a neutral delay label', () => {
    render(<QuoteHeader equity={equity({ source: 'massive', stale: true })} />);

    const badge = screen.getByTestId('quote-provenance');
    expect(badge).toHaveTextContent('Delayed data');
    expect(badge).toHaveTextContent('massive');
    expect(badge).not.toHaveTextContent('15-min delayed');
    expect(badge.getAttribute('title')).toMatch(/unavailable/i);
  });

  it('keeps rendering the as-of timestamp alongside the label', () => {
    render(<QuoteHeader equity={equity({ source: 'stooq', stale: true })} />);
    expect(screen.getByText(/^As of /)).toBeInTheDocument();
  });
});
