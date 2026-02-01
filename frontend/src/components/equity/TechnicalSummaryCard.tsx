'use client';

import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { formatCurrency, formatNumber } from '@/lib/utils/format';
import type { TechnicalSummary } from '@/lib/api/types';

interface TechnicalSummaryCardProps {
  summary: TechnicalSummary;
}

export function TechnicalSummaryCard({ summary }: TechnicalSummaryCardProps) {
  const getRsiColor = (signal: string | null) => {
    if (signal === 'overbought') return 'text-red-500';
    if (signal === 'oversold') return 'text-emerald-500';
    return 'text-muted-foreground';
  };

  const getTrendIcon = (isAbove: boolean | null) => {
    if (isAbove === null) return <Minus className="h-4 w-4 text-muted-foreground" />;
    if (isAbove) return <TrendingUp className="h-4 w-4 text-emerald-500" />;
    return <TrendingDown className="h-4 w-4 text-red-500" />;
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {/* RSI */}
      <div className="p-4 bg-muted/50 rounded-lg">
        <div className="text-sm text-muted-foreground mb-1">RSI (14)</div>
        <div className="flex items-center gap-2">
          <span className={`text-lg font-semibold ${getRsiColor(summary.rsi_signal)}`}>
            {summary.rsi ? formatNumber(summary.rsi) : '--'}
          </span>
          {summary.rsi_signal && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              summary.rsi_signal === 'overbought'
                ? 'bg-red-500/10 text-red-500'
                : summary.rsi_signal === 'oversold'
                ? 'bg-emerald-500/10 text-emerald-500'
                : 'bg-muted text-muted-foreground'
            }`}>
              {summary.rsi_signal}
            </span>
          )}
        </div>
      </div>

      {/* MACD */}
      <div className="p-4 bg-muted/50 rounded-lg">
        <div className="text-sm text-muted-foreground mb-1">MACD</div>
        <div className="flex items-center gap-2">
          <span className={`text-lg font-semibold ${
            summary.macd && summary.macd_signal
              ? summary.macd > summary.macd_signal
                ? 'text-emerald-500'
                : 'text-red-500'
              : 'text-foreground'
          }`}>
            {summary.macd ? formatNumber(summary.macd) : '--'}
          </span>
          {summary.macd && summary.macd_signal && (
            <span className="text-xs text-muted-foreground">
              vs {formatNumber(summary.macd_signal)}
            </span>
          )}
        </div>
      </div>

      {/* SMA 50 */}
      <div className="p-4 bg-muted/50 rounded-lg">
        <div className="text-sm text-muted-foreground mb-1">SMA 50</div>
        <div className="flex items-center justify-between">
          <span className="text-lg font-semibold text-foreground">
            {summary.sma_50 ? formatCurrency(summary.sma_50) : '--'}
          </span>
          {getTrendIcon(summary.above_sma_50)}
        </div>
      </div>

      {/* SMA 200 */}
      <div className="p-4 bg-muted/50 rounded-lg">
        <div className="text-sm text-muted-foreground mb-1">SMA 200</div>
        <div className="flex items-center justify-between">
          <span className="text-lg font-semibold text-foreground">
            {summary.sma_200 ? formatCurrency(summary.sma_200) : '--'}
          </span>
          {getTrendIcon(summary.above_sma_200)}
        </div>
      </div>
    </div>
  );
}
