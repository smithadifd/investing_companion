'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { Loader2, ArrowLeft, BarChart3, FileText, TrendingUp, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { useEquity, useHistory, useTechnicals, useTechnicalsSummary } from '@/lib/hooks/useEquity';
import { AdvancedChart } from '@/components/charts/AdvancedChart';
import { ChartControls } from '@/components/charts/ChartControls';
import { QuoteHeader } from '@/components/equity/QuoteHeader';
import { FundamentalsCard } from '@/components/equity/FundamentalsCard';
import { PeriodSelector } from '@/components/equity/PeriodSelector';
import { TechnicalSummaryCard } from '@/components/equity/TechnicalSummaryCard';
import { PeerComparison } from '@/components/equity/PeerComparison';
import { AddToWatchlistButton } from '@/components/watchlist/AddToWatchlistButton';
import { AIAnalysisPanel } from '@/components/ai/AIAnalysisPanel';

type TabType = 'chart' | 'fundamentals' | 'ai';

export default function EquityPage() {
  const params = useParams();
  const symbol = (params.symbol as string).toUpperCase();
  const [period, setPeriod] = useState('1y');
  const [activeTab, setActiveTab] = useState<TabType>('chart');

  // Chart indicator toggles
  const [showSMA, setShowSMA] = useState(true);
  const [showEMA, setShowEMA] = useState(false);
  const [showBollingerBands, setShowBollingerBands] = useState(false);
  const [showRSI, setShowRSI] = useState(true);
  const [showMACD, setShowMACD] = useState(true);

  const {
    data: equity,
    isLoading: equityLoading,
    error: equityError,
  } = useEquity(symbol);

  const { data: history, isLoading: historyLoading } = useHistory(symbol, period);
  const { data: technicals } = useTechnicals(symbol, period);
  const { data: technicalsSummary } = useTechnicalsSummary(symbol);

  if (equityLoading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="text-neutral-500 dark:text-neutral-400">Loading {symbol}...</span>
        </div>
      </div>
    );
  }

  if (equityError || !equity) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">Symbol Not Found</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-2">
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
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>

        {/* Quote header */}
        <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-sm p-6 mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <QuoteHeader equity={equity} />
            <AddToWatchlistButton symbol={symbol} />
          </div>
        </div>

        {/* Tab navigation */}
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setActiveTab('chart')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === 'chart'
                ? 'bg-blue-500 text-white'
                : 'bg-white dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 border border-neutral-200 dark:border-neutral-700'
            }`}
          >
            <BarChart3 className="h-4 w-4" />
            Technical Analysis
          </button>
          <button
            onClick={() => setActiveTab('fundamentals')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === 'fundamentals'
                ? 'bg-blue-500 text-white'
                : 'bg-white dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 border border-neutral-200 dark:border-neutral-700'
            }`}
          >
            <FileText className="h-4 w-4" />
            Fundamentals
          </button>
          <button
            onClick={() => setActiveTab('ai')}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${
              activeTab === 'ai'
                ? 'bg-blue-500 text-white'
                : 'bg-white dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 border border-neutral-200 dark:border-neutral-700'
            }`}
          >
            <Sparkles className="h-4 w-4" />
            AI Analysis
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'chart' && (
          <>
            {/* Price chart with indicators */}
            <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-sm p-6 mb-6">
              <div className="flex flex-col gap-4 mb-4">
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4">
                  <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50">
                    Price Chart
                  </h2>
                  <PeriodSelector value={period} onChange={setPeriod} />
                </div>

                {/* Chart controls */}
                <ChartControls
                  showSMA={showSMA}
                  showEMA={showEMA}
                  showBollingerBands={showBollingerBands}
                  showRSI={showRSI}
                  showMACD={showMACD}
                  onToggleSMA={() => setShowSMA(!showSMA)}
                  onToggleEMA={() => setShowEMA(!showEMA)}
                  onToggleBollingerBands={() => setShowBollingerBands(!showBollingerBands)}
                  onToggleRSI={() => setShowRSI(!showRSI)}
                  onToggleMACD={() => setShowMACD(!showMACD)}
                />
              </div>

              {historyLoading ? (
                <div className="h-[400px] flex items-center justify-center bg-neutral-100 dark:bg-neutral-700 rounded-lg">
                  <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
                </div>
              ) : history ? (
                <AdvancedChart
                  data={history.history}
                  technicals={technicals}
                  showSMA={showSMA}
                  showEMA={showEMA}
                  showBollingerBands={showBollingerBands}
                  showRSI={showRSI}
                  showMACD={showMACD}
                />
              ) : (
                <div className="h-[400px] flex items-center justify-center bg-neutral-100 dark:bg-neutral-700 rounded-lg">
                  <span className="text-neutral-500 dark:text-neutral-400">No chart data available</span>
                </div>
              )}
            </div>

            {/* Technical Indicators Summary */}
            {technicalsSummary && (
              <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-sm p-6 mb-6">
                <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50 mb-4">
                  Indicator Summary
                </h2>
                <TechnicalSummaryCard summary={technicalsSummary} />
              </div>
            )}

            {/* Chart Legend */}
            <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-sm p-6">
              <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-50 mb-3">
                Indicator Guide
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-sm">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-3 h-0.5 bg-amber-500" />
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">SMA (20, 50, 200)</span>
                  </div>
                  <p className="text-neutral-500 dark:text-neutral-400 text-xs">
                    Simple Moving Averages. Price above SMA = bullish trend.
                  </p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-3 h-0.5 bg-emerald-500" />
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">EMA (12, 26)</span>
                  </div>
                  <p className="text-neutral-500 dark:text-neutral-400 text-xs">
                    Exponential Moving Averages. More responsive to recent prices.
                  </p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-3 h-0.5 bg-indigo-500 border-dashed" />
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">Bollinger Bands</span>
                  </div>
                  <p className="text-neutral-500 dark:text-neutral-400 text-xs">
                    Volatility bands. Price near upper = overbought, near lower = oversold.
                  </p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-3 h-0.5 bg-amber-500" />
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">RSI (14)</span>
                  </div>
                  <p className="text-neutral-500 dark:text-neutral-400 text-xs">
                    Relative Strength Index. Above 70 = overbought, below 30 = oversold.
                  </p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-3 h-0.5 bg-blue-500" />
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">MACD (12, 26, 9)</span>
                  </div>
                  <p className="text-neutral-500 dark:text-neutral-400 text-xs">
                    Moving Average Convergence Divergence. Signal line crossovers indicate momentum shifts.
                  </p>
                </div>
              </div>
            </div>
          </>
        )}

        {activeTab === 'fundamentals' && (
          <>
            {/* Key Metrics */}
            {equity.fundamentals && (
              <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-sm p-6 mb-6">
                <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50 mb-4">
                  Key Metrics
                </h2>
                <FundamentalsCard fundamentals={equity.fundamentals} />
              </div>
            )}

            {/* Peer Comparison */}
            <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-sm p-6">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="h-5 w-5 text-blue-500" />
                <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50">
                  Peer Comparison
                </h2>
              </div>
              <PeerComparison symbol={symbol} currentEquity={equity} />
            </div>
          </>
        )}

        {activeTab === 'ai' && (
          <AIAnalysisPanel
            analysisType="equity"
            symbol={symbol}
            contextLabel={`${symbol} - ${equity.name}`}
          />
        )}
      </div>
    </div>
  );
}
