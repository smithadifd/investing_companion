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

  it('labels a contractually delayed source neutrally, not as a failure', () => {
    render(<QuoteHeader equity={equity({ source: 'massive', stale: true })} />);

    const badge = screen.getByTestId('quote-provenance');
    expect(badge).toHaveTextContent('15-min delayed');
    expect(badge).toHaveTextContent('massive');
    // The neutral label must not carry the degraded-fallback framing.
    expect(badge.textContent).not.toMatch(/fallback/i);
    expect(badge.getAttribute('title')).not.toMatch(/unavailable/i);
  });

  it('still warns when a live primary fell through to a fallback', () => {
    render(<QuoteHeader equity={equity({ source: 'stooq', stale: true })} />);

    const badge = screen.getByTestId('quote-provenance');
    expect(badge).toHaveTextContent('Delayed data');
    expect(badge).toHaveTextContent('stooq');
    expect(badge.getAttribute('title')).toMatch(/unavailable/i);
  });

  it('labels the delayed source even if the stale flag never arrived', () => {
    // Defence in depth: the delay is a fact about the plan, so the label is
    // driven by provenance and does not depend on an upstream flag surviving.
    render(<QuoteHeader equity={equity({ source: 'massive', stale: false })} />);
    expect(screen.getByTestId('quote-provenance')).toHaveTextContent(
      '15-min delayed',
    );
  });

  it('keeps rendering the as-of timestamp alongside the label', () => {
    render(<QuoteHeader equity={equity({ source: 'massive', stale: true })} />);
    expect(screen.getByText(/^As of /)).toBeInTheDocument();
  });
});
