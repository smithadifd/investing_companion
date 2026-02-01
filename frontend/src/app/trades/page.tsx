'use client';

import { useState } from 'react';
import {
  Plus,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Calculator,
  Wallet,
  LineChart,
  ArrowUpRight,
  ArrowDownRight,
  Trash2,
  Pencil,
} from 'lucide-react';
import {
  useTrades,
  usePortfolio,
  usePerformance,
  useDeleteTrade,
  useCalculatePositionSize,
} from '@/lib/hooks/useTrade';
import type { Trade, PositionSummary, PerformanceMetrics } from '@/lib/api/types';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import { LabelWithTooltip } from '@/components/ui/Tooltip';
import { CreateTradeModal } from '@/components/trade/CreateTradeModal';
import { EditTradeModal } from '@/components/trade/EditTradeModal';
import { QuickTradeModal } from '@/components/trade/QuickTradeModal';

// Helper to convert string/number to number
function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format currency
function formatCurrency(value: number | string | null | undefined): string {
  const num = toNumber(value);
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

// Format percentage
function formatPercent(value: number | string | null | undefined): string {
  const num = toNumber(value);
  return `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`;
}

// Format date
function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

// Format datetime
function formatDateTime(dateString: string): string {
  return new Date(dateString).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

// Trade type badge
function TradeTypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    buy: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    sell: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    short: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
    cover: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  };

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium uppercase ${colors[type] || 'bg-neutral-100 text-neutral-700'}`}>
      {type}
    </span>
  );
}

// P&L indicator
function PnLDisplay({ value, showPercent = false, percentValue }: { value: number | string | null; showPercent?: boolean; percentValue?: number | string | null }) {
  const num = toNumber(value);
  const isPositive = num >= 0;

  return (
    <div className={`flex items-center gap-1 ${isPositive ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
      {isPositive ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
      <span className="font-medium">{formatCurrency(num)}</span>
      {showPercent && percentValue !== null && (
        <span className="text-sm">({formatPercent(percentValue)})</span>
      )}
    </div>
  );
}

// Stats card component
function StatsCard({
  label,
  value,
  subValue,
  icon: Icon,
  color,
}: {
  label: string;
  value: string;
  subValue?: string;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-xl font-bold text-neutral-900 dark:text-neutral-50">
            {value}
          </p>
          <p className="text-sm text-neutral-500">{label}</p>
          {subValue && <p className="text-xs text-neutral-400">{subValue}</p>}
        </div>
      </div>
    </div>
  );
}

// Trade row component
function TradeRow({
  trade,
  onEdit,
  onDelete,
}: {
  trade: Trade;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <tr className="border-b border-neutral-100 dark:border-neutral-700 hover:bg-neutral-50 dark:hover:bg-neutral-700/50 transition-colors">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="font-medium text-neutral-900 dark:text-neutral-50">
            {trade.equity.symbol}
          </span>
          <span className="text-sm text-neutral-500 hidden sm:inline truncate max-w-[150px]">
            {trade.equity.name}
          </span>
        </div>
      </td>
      <td className="px-4 py-3">
        <TradeTypeBadge type={trade.trade_type} />
      </td>
      <td className="px-4 py-3 text-right font-medium">
        {toNumber(trade.quantity).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-right">
        {formatCurrency(trade.price)}
      </td>
      <td className="px-4 py-3 text-right font-medium">
        {formatCurrency(trade.total_value)}
      </td>
      <td className="px-4 py-3 text-neutral-500">
        {formatDateTime(trade.executed_at)}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={onEdit}
            className="p-1.5 rounded-lg text-neutral-400 hover:text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
            title="Edit trade"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded-lg text-neutral-400 hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
            title="Delete trade"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </td>
    </tr>
  );
}

// Position card component
function PositionCard({
  position,
  onQuickTrade
}: {
  position: PositionSummary;
  onQuickTrade: (symbol: string, type: 'buy' | 'sell', currentPrice?: number) => void;
}) {
  const hasUnrealized = position.current_price !== null;
  const quantity = toNumber(position.quantity);

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="font-semibold text-neutral-900 dark:text-neutral-50">
            {position.equity.symbol}
          </h3>
          <p className="text-sm text-neutral-500 truncate max-w-[200px]">
            {position.equity.name}
          </p>
        </div>
        <div className="text-right">
          <p className="text-lg font-bold text-neutral-900 dark:text-neutral-50">
            {quantity.toLocaleString()} shares
          </p>
          <p className="text-sm text-neutral-500">
            Avg: {formatCurrency(position.avg_cost_basis)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-neutral-500">Cost Basis</p>
          <p className="font-medium text-neutral-900 dark:text-neutral-50">
            {formatCurrency(position.total_cost)}
          </p>
        </div>
        {hasUnrealized && (
          <div>
            <p className="text-neutral-500">Current Value</p>
            <p className="font-medium text-neutral-900 dark:text-neutral-50">
              {formatCurrency(position.current_value)}
            </p>
          </div>
        )}
        <div>
          <p className="text-neutral-500">Unrealized P&L</p>
          {hasUnrealized ? (
            <PnLDisplay value={position.unrealized_pnl} showPercent percentValue={position.unrealized_pnl_percent} />
          ) : (
            <span className="text-neutral-400">-</span>
          )}
        </div>
        <div>
          <p className="text-neutral-500">Realized P&L</p>
          <PnLDisplay value={position.realized_pnl} />
        </div>
      </div>

      {/* Quick action buttons */}
      <div className="flex gap-2 mt-4 pt-3 border-t border-neutral-100 dark:border-neutral-700">
        <button
          onClick={() => onQuickTrade(position.equity.symbol, 'buy', toNumber(position.current_price))}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 rounded-lg transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          Buy More
        </button>
        {quantity > 0 && (
          <button
            onClick={() => onQuickTrade(position.equity.symbol, 'sell', toNumber(position.current_price))}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors"
          >
            <ArrowDownRight className="h-3.5 w-3.5" />
            Sell
          </button>
        )}
      </div>
    </div>
  );
}

// Performance metrics component
function PerformanceMetricsDisplay({ metrics }: { metrics: PerformanceMetrics }) {
  const winRate = toNumber(metrics.win_rate) * 100;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatsCard
          label="Total Trades"
          value={metrics.total_trades.toString()}
          icon={BarChart3}
          color="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
        />
        <StatsCard
          label="Win Rate"
          value={`${winRate.toFixed(1)}%`}
          subValue={`${metrics.winning_trades}W / ${metrics.losing_trades}L`}
          icon={TrendingUp}
          color="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
        />
        <StatsCard
          label="Realized P&L"
          value={formatCurrency(metrics.total_realized_pnl)}
          icon={Wallet}
          color={toNumber(metrics.total_realized_pnl) >= 0
            ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
            : "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400"
          }
        />
        <StatsCard
          label="Profit Factor"
          value={metrics.profit_factor ? toNumber(metrics.profit_factor).toFixed(2) : '-'}
          icon={LineChart}
          color="bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Win/Loss Stats */}
        <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
          <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">Win/Loss Details</h3>
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-neutral-500">Average Win</span>
              <span className="font-medium text-emerald-600 dark:text-emerald-400">
                {metrics.average_win ? formatCurrency(metrics.average_win) : '-'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Average Loss</span>
              <span className="font-medium text-red-600 dark:text-red-400">
                {metrics.average_loss ? formatCurrency(metrics.average_loss) : '-'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Largest Win</span>
              <span className="font-medium text-emerald-600 dark:text-emerald-400">
                {metrics.largest_win ? formatCurrency(metrics.largest_win) : '-'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Largest Loss</span>
              <span className="font-medium text-red-600 dark:text-red-400">
                {metrics.largest_loss ? formatCurrency(metrics.largest_loss) : '-'}
              </span>
            </div>
          </div>
        </div>

        {/* Streaks */}
        <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
          <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">Streaks</h3>
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-neutral-500">Current Streak</span>
              <span className={`font-medium ${metrics.current_streak >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                {metrics.current_streak > 0 ? `${metrics.current_streak} Wins` : metrics.current_streak < 0 ? `${Math.abs(metrics.current_streak)} Losses` : 'None'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Longest Win Streak</span>
              <span className="font-medium text-emerald-600 dark:text-emerald-400">
                {metrics.longest_winning_streak}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Longest Loss Streak</span>
              <span className="font-medium text-red-600 dark:text-red-400">
                {metrics.longest_losing_streak}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Avg Holding Period</span>
              <span className="font-medium text-neutral-900 dark:text-neutral-50">
                {metrics.average_holding_days ? `${toNumber(metrics.average_holding_days).toFixed(1)} days` : '-'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Position sizer component
function PositionSizer() {
  const [accountSize, setAccountSize] = useState('');
  const [riskPercent, setRiskPercent] = useState('2');
  const [entryPrice, setEntryPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');

  const calculatePositionSize = useCalculatePositionSize();

  const handleCalculate = () => {
    if (!accountSize || !entryPrice || !stopLoss) return;

    calculatePositionSize.mutate({
      account_size: parseFloat(accountSize),
      risk_percent: parseFloat(riskPercent),
      entry_price: parseFloat(entryPrice),
      stop_loss: parseFloat(stopLoss),
    });
  };

  const result = calculatePositionSize.data;

  return (
    <div className="max-w-xl">
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6">
        <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">Position Size Calculator</h3>
        <p className="text-sm text-neutral-500 mb-6">
          Calculate optimal position size based on your risk tolerance.
        </p>

        <div className="space-y-4">
          <div>
            <LabelWithTooltip
              label="Account Size ($)"
              tooltip="Your total trading account value. This is used to calculate the maximum dollar amount you can risk on this trade."
              htmlFor="accountSize"
            />
            <input
              id="accountSize"
              type="number"
              value={accountSize}
              onChange={(e) => setAccountSize(e.target.value)}
              placeholder="10000"
              className="w-full px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <LabelWithTooltip
              label="Risk Per Trade (%)"
              tooltip="The percentage of your account you're willing to lose on this trade if it hits your stop loss. Most traders use 1-2% per trade to manage risk."
              htmlFor="riskPercent"
            />
            <input
              id="riskPercent"
              type="number"
              value={riskPercent}
              onChange={(e) => setRiskPercent(e.target.value)}
              placeholder="2"
              min="0.1"
              max="100"
              step="0.1"
              className="w-full px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <LabelWithTooltip
              label="Entry Price ($)"
              tooltip="The price at which you plan to buy the stock. This is used with the stop loss to calculate your risk per share."
              htmlFor="entryPrice"
            />
            <input
              id="entryPrice"
              type="number"
              value={entryPrice}
              onChange={(e) => setEntryPrice(e.target.value)}
              placeholder="50.00"
              step="0.01"
              className="w-full px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <LabelWithTooltip
              label="Stop Loss ($)"
              tooltip="The price at which you'll exit if the trade goes against you. The difference between entry and stop loss determines your risk per share."
              htmlFor="stopLoss"
            />
            <input
              id="stopLoss"
              type="number"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              placeholder="45.00"
              step="0.01"
              className="w-full px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <button
            onClick={handleCalculate}
            disabled={!accountSize || !entryPrice || !stopLoss || calculatePositionSize.isPending}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Calculator className="h-4 w-4" />
            Calculate
          </button>
        </div>

        {result && (
          <div className="mt-6 p-4 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
            <h4 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-3">Result</h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-neutral-500">Suggested Shares</span>
                <span className="font-bold text-lg text-neutral-900 dark:text-neutral-50">
                  {result.shares.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Position Value</span>
                <span className="font-medium text-neutral-900 dark:text-neutral-50">
                  {formatCurrency(result.position_value)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Risk Amount</span>
                <span className="font-medium text-red-600 dark:text-red-400">
                  {formatCurrency(result.risk_amount)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Risk Per Share</span>
                <span className="font-medium text-neutral-900 dark:text-neutral-50">
                  {formatCurrency(result.risk_per_share)}
                </span>
              </div>
            </div>
            {result.notes && (
              <p className="mt-3 text-sm text-amber-600 dark:text-amber-400">
                {result.notes}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

type TabType = 'trades' | 'portfolio' | 'performance' | 'sizer';

export default function TradesPage() {
  const [activeTab, setActiveTab] = useState<TabType>('trades');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingTrade, setEditingTrade] = useState<Trade | null>(null);
  const [deleteTradeId, setDeleteTradeId] = useState<number | null>(null);
  const [quickTrade, setQuickTrade] = useState<{
    symbol: string;
    type: 'buy' | 'sell';
    price?: number;
  } | null>(null);

  const { data: tradesData, isLoading: tradesLoading } = useTrades({ limit: 100 });
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio();
  const { data: performance, isLoading: performanceLoading } = usePerformance();
  const deleteTrade = useDeleteTrade();

  const trades = tradesData?.trades || [];
  const totalTrades = tradesData?.total || 0;

  if (tradesLoading && portfolioLoading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          <div className="animate-pulse space-y-6">
            <div className="h-8 w-32 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-24 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
              ))}
            </div>
            <div className="h-64 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              Trade Tracker
            </h1>
            <p className="text-sm text-neutral-500">
              Track your trades, analyze performance, and calculate position sizes
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Log Trade
          </button>
        </div>

        {/* Portfolio Summary Stats */}
        {portfolio && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <StatsCard
              label="Total Invested"
              value={formatCurrency(portfolio.total_invested)}
              icon={Wallet}
              color="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
            />
            <StatsCard
              label="Current Value"
              value={portfolio.current_value ? formatCurrency(portfolio.current_value) : '-'}
              icon={LineChart}
              color="bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
            />
            <StatsCard
              label="Unrealized P&L"
              value={portfolio.total_unrealized_pnl ? formatCurrency(portfolio.total_unrealized_pnl) : '-'}
              icon={toNumber(portfolio.total_unrealized_pnl) >= 0 ? TrendingUp : TrendingDown}
              color={toNumber(portfolio.total_unrealized_pnl) >= 0
                ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
                : "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400"
              }
            />
            <StatsCard
              label="Realized P&L"
              value={formatCurrency(portfolio.total_realized_pnl)}
              icon={toNumber(portfolio.total_realized_pnl) >= 0 ? TrendingUp : TrendingDown}
              color={toNumber(portfolio.total_realized_pnl) >= 0
                ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
                : "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400"
              }
            />
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 mb-6 bg-neutral-100 dark:bg-neutral-800 p-1 rounded-lg w-fit overflow-x-auto">
          <button
            onClick={() => setActiveTab('trades')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
              activeTab === 'trades'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <BarChart3 className="h-4 w-4" />
            Trades
          </button>
          <button
            onClick={() => setActiveTab('portfolio')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
              activeTab === 'portfolio'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <Wallet className="h-4 w-4" />
            Positions
          </button>
          <button
            onClick={() => setActiveTab('performance')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
              activeTab === 'performance'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <LineChart className="h-4 w-4" />
            Performance
          </button>
          <button
            onClick={() => setActiveTab('sizer')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
              activeTab === 'sizer'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <Calculator className="h-4 w-4" />
            Position Sizer
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === 'trades' && (
          <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
            {trades.length === 0 ? (
              <div className="text-center py-12">
                <BarChart3 className="h-12 w-12 text-neutral-300 dark:text-neutral-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-50 mb-2">
                  No trades yet
                </h3>
                <p className="text-neutral-500 mb-4">
                  Start logging your trades to track performance
                </p>
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <Plus className="h-4 w-4" />
                  Log Your First Trade
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-neutral-50 dark:bg-neutral-700/50">
                    <tr className="text-left text-sm text-neutral-500">
                      <th className="px-4 py-3 font-medium">Symbol</th>
                      <th className="px-4 py-3 font-medium">Type</th>
                      <th className="px-4 py-3 font-medium text-right">Qty</th>
                      <th className="px-4 py-3 font-medium text-right">Price</th>
                      <th className="px-4 py-3 font-medium text-right">Value</th>
                      <th className="px-4 py-3 font-medium">Date</th>
                      <th className="px-4 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade) => (
                      <TradeRow
                        key={trade.id}
                        trade={trade}
                        onEdit={() => setEditingTrade(trade)}
                        onDelete={() => setDeleteTradeId(trade.id)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {activeTab === 'portfolio' && (
          <div>
            {portfolio && portfolio.positions.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {portfolio.positions
                  .filter((p) => toNumber(p.quantity) !== 0)
                  .map((position) => (
                    <PositionCard
                      key={position.equity_id}
                      position={position}
                      onQuickTrade={(symbol, type, price) =>
                        setQuickTrade({ symbol, type, price })
                      }
                    />
                  ))}
              </div>
            ) : (
              <div className="text-center py-12 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <Wallet className="h-12 w-12 text-neutral-300 dark:text-neutral-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-50 mb-2">
                  No open positions
                </h3>
                <p className="text-neutral-500">
                  Log some trades to see your positions here
                </p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'performance' && (
          <div>
            {performance ? (
              <PerformanceMetricsDisplay metrics={performance.metrics} />
            ) : (
              <div className="text-center py-12 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <LineChart className="h-12 w-12 text-neutral-300 dark:text-neutral-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-50 mb-2">
                  No performance data
                </h3>
                <p className="text-neutral-500">
                  Complete some trades to see your performance metrics
                </p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'sizer' && <PositionSizer />}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateTradeModal
          isOpen={showCreateModal}
          onClose={() => setShowCreateModal(false)}
        />
      )}

      {/* Edit Modal */}
      {editingTrade && (
        <EditTradeModal
          trade={editingTrade}
          onClose={() => setEditingTrade(null)}
        />
      )}

      {/* Delete Confirmation */}
      {deleteTradeId !== null && (
        <ConfirmModal
          title="Delete Trade"
          message="Are you sure you want to delete this trade? This will recalculate your P&L."
          confirmLabel="Delete"
          onConfirm={() => {
            if (deleteTradeId) {
              deleteTrade.mutate(deleteTradeId);
            }
            setDeleteTradeId(null);
          }}
          onCancel={() => setDeleteTradeId(null)}
          variant="danger"
        />
      )}

      {/* Quick Trade Modal */}
      {quickTrade && (
        <QuickTradeModal
          symbol={quickTrade.symbol}
          tradeType={quickTrade.type}
          suggestedPrice={quickTrade.price}
          onClose={() => setQuickTrade(null)}
        />
      )}
    </div>
  );
}
