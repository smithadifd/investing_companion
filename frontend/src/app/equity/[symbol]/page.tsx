'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { Loader2, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { useEquity, useHistory } from '@/lib/hooks/useEquity';
import { PriceChart } from '@/components/charts/PriceChart';
import { QuoteHeader } from '@/components/equity/QuoteHeader';
import { FundamentalsCard } from '@/components/equity/FundamentalsCard';
import { PeriodSelector } from '@/components/equity/PeriodSelector';

export default function EquityPage() {
  const params = useParams();
  const symbol = (params.symbol as string).toUpperCase();
  const [period, setPeriod] = useState('1y');

  const {
    data: equity,
    isLoading: equityLoading,
    error: equityError,
  } = useEquity(symbol);

  const {
    data: history,
    isLoading: historyLoading,
  } = useHistory(symbol, period);

  if (equityLoading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="text-muted-foreground">Loading {symbol}...</span>
        </div>
      </div>
    );
  }

  if (equityError || !equity) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-background">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-foreground">Symbol Not Found</h1>
          <p className="text-muted-foreground mt-2">
            Could not find data for &quot;{symbol}&quot;
          </p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 mt-4 text-blue-500 hover:text-blue-400"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-background">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>

        {/* Quote header */}
        <div className="bg-card border border-border rounded-xl shadow-sm p-6 mb-6">
          <QuoteHeader equity={equity} />
        </div>

        {/* Price chart */}
        <div className="bg-card border border-border rounded-xl shadow-sm p-6 mb-6">
          <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-4">
            <h2 className="text-xl font-semibold text-card-foreground">Price Chart</h2>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>

          {historyLoading ? (
            <div className="h-[400px] flex items-center justify-center bg-muted rounded-lg">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
            </div>
          ) : history ? (
            <PriceChart data={history.history} />
          ) : (
            <div className="h-[400px] flex items-center justify-center bg-muted rounded-lg">
              <span className="text-muted-foreground">No chart data available</span>
            </div>
          )}
        </div>

        {/* Fundamentals */}
        {equity.fundamentals && (
          <div className="bg-card border border-border rounded-xl shadow-sm p-6">
            <h2 className="text-xl font-semibold text-card-foreground mb-4">
              Fundamentals
            </h2>
            <FundamentalsCard fundamentals={equity.fundamentals} />
          </div>
        )}
      </div>
    </div>
  );
}
