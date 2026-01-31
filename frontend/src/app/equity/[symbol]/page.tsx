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
      <div className="flex items-center justify-center min-h-screen">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="text-gray-600">Loading {symbol}...</span>
        </div>
      </div>
    );
  }

  if (equityError || !equity) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-800">Symbol Not Found</h1>
          <p className="text-gray-600 mt-2">
            Could not find data for &quot;{symbol}&quot;
          </p>
          <Link
            href="/"
            className="inline-flex items-center gap-2 mt-4 text-blue-600 hover:text-blue-800"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>

        {/* Quote header */}
        <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
          <QuoteHeader equity={equity} />
        </div>

        {/* Price chart */}
        <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-semibold text-gray-900">Price Chart</h2>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>

          {historyLoading ? (
            <div className="h-[400px] flex items-center justify-center bg-gray-50 rounded-lg">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
            </div>
          ) : history ? (
            <PriceChart data={history.history} />
          ) : (
            <div className="h-[400px] flex items-center justify-center bg-gray-50 rounded-lg">
              <span className="text-gray-500">No chart data available</span>
            </div>
          )}
        </div>

        {/* Fundamentals */}
        {equity.fundamentals && (
          <div className="bg-white rounded-lg shadow-sm p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">
              Fundamentals
            </h2>
            <FundamentalsCard fundamentals={equity.fundamentals} />
          </div>
        )}
      </div>
    </main>
  );
}
