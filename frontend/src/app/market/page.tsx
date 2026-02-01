'use client';

import Link from 'next/link';
import { useMarketOverview } from '@/lib/hooks/useMarket';
import type {
  IndexQuote,
  SectorPerformance,
  MarketMover,
  CurrencyCommodity
} from '@/lib/api/types';

// Helper to convert string/number to number
function toNumber(value: number | string | null): number {
  if (value === null) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format large numbers
function formatNumber(value: number | null): string {
  if (value === null) return '-';
  if (Math.abs(value) >= 1e12) return (value / 1e12).toFixed(2) + 'T';
  if (Math.abs(value) >= 1e9) return (value / 1e9).toFixed(2) + 'B';
  if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(2) + 'M';
  if (Math.abs(value) >= 1e3) return (value / 1e3).toFixed(2) + 'K';
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// Format price
function formatPrice(value: number | string | null): string {
  const num = toNumber(value);
  return num.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

// Format percent
function formatPercent(value: number | string | null): string {
  const num = toNumber(value);
  const sign = num >= 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

// Get color class for change
function getChangeColor(value: number | string | null): string {
  const num = toNumber(value);
  if (num > 0) return 'text-emerald-600 dark:text-emerald-400';
  if (num < 0) return 'text-red-600 dark:text-red-400';
  return 'text-neutral-500';
}

// Get background color for heatmap
function getHeatmapBg(value: number | string | null): string {
  const num = toNumber(value);
  if (num >= 2) return 'bg-emerald-600 text-white';
  if (num >= 1) return 'bg-emerald-500 text-white';
  if (num >= 0.5) return 'bg-emerald-400 text-white';
  if (num > 0) return 'bg-emerald-300 text-emerald-900';
  if (num === 0) return 'bg-neutral-200 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300';
  if (num > -0.5) return 'bg-red-300 text-red-900';
  if (num > -1) return 'bg-red-400 text-white';
  if (num > -2) return 'bg-red-500 text-white';
  return 'bg-red-600 text-white';
}

function IndexCard({ index }: { index: IndexQuote }) {
  const change = toNumber(index.change_percent);

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg p-4 border border-neutral-200 dark:border-neutral-700">
      <div className="flex justify-between items-start mb-2">
        <div>
          <h3 className="font-semibold text-neutral-900 dark:text-neutral-50">
            {index.name}
          </h3>
          <p className="text-xs text-neutral-500">{index.symbol}</p>
        </div>
        <div className={`text-sm font-medium px-2 py-0.5 rounded ${
          change >= 0
            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
            : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
        }`}>
          {formatPercent(index.change_percent)}
        </div>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
          {formatPrice(index.price)}
        </span>
        <span className={`text-sm ${getChangeColor(index.change)}`}>
          {toNumber(index.change) >= 0 ? '+' : ''}{formatPrice(index.change)}
        </span>
      </div>
    </div>
  );
}

function SectorHeatmap({ sectors }: { sectors: SectorPerformance[] }) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg p-4 border border-neutral-200 dark:border-neutral-700">
      <h2 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">
        Sector Performance
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {sectors.map((sector) => (
          <Link
            key={sector.symbol}
            href={`/equity/${sector.symbol}`}
            className={`p-3 rounded-lg text-center transition-transform hover:scale-105 ${getHeatmapBg(sector.change_percent)}`}
          >
            <p className="text-sm font-medium truncate">{sector.sector}</p>
            <p className="text-lg font-bold">{formatPercent(sector.change_percent)}</p>
            <p className="text-xs opacity-75">{sector.symbol}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

function MoversList({
  title,
  movers,
  isGainers
}: {
  title: string;
  movers: MarketMover[];
  isGainers: boolean;
}) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg p-4 border border-neutral-200 dark:border-neutral-700">
      <h2 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">
        {title}
      </h2>
      <div className="space-y-2">
        {movers.map((mover) => (
          <Link
            key={mover.symbol}
            href={`/equity/${mover.symbol}`}
            className="flex items-center justify-between p-2 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
          >
            <div className="flex-1 min-w-0">
              <p className="font-medium text-neutral-900 dark:text-neutral-50">
                {mover.symbol}
              </p>
              <p className="text-xs text-neutral-500 truncate">{mover.name}</p>
            </div>
            <div className="text-right ml-2">
              <p className="font-medium text-neutral-900 dark:text-neutral-50">
                ${formatPrice(mover.price)}
              </p>
              <p className={`text-sm font-medium ${isGainers ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                {formatPercent(mover.change_percent)}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function CurrencyCommodityList({ items }: { items: CurrencyCommodity[] }) {
  const currencies = items.filter((i) => i.category === 'currency');
  const commodities = items.filter((i) => i.category === 'commodity');
  const crypto = items.filter((i) => i.category === 'crypto');

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg p-4 border border-neutral-200 dark:border-neutral-700">
      <h2 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">
        Currencies, Commodities & Crypto
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Currencies */}
        <div>
          <h3 className="text-xs font-medium text-neutral-500 uppercase tracking-wider mb-2">
            Currencies
          </h3>
          <div className="space-y-2">
            {currencies.map((item) => (
              <div key={item.symbol} className="flex justify-between items-center">
                <span className="text-sm text-neutral-700 dark:text-neutral-300">
                  {item.name}
                </span>
                <div className="text-right">
                  <span className="text-sm font-medium text-neutral-900 dark:text-neutral-50">
                    {formatPrice(item.price)}
                  </span>
                  <span className={`text-xs ml-2 ${getChangeColor(item.change_percent)}`}>
                    {formatPercent(item.change_percent)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Commodities */}
        <div>
          <h3 className="text-xs font-medium text-neutral-500 uppercase tracking-wider mb-2">
            Commodities
          </h3>
          <div className="space-y-2">
            {commodities.map((item) => (
              <div key={item.symbol} className="flex justify-between items-center">
                <span className="text-sm text-neutral-700 dark:text-neutral-300">
                  {item.name}
                </span>
                <div className="text-right">
                  <span className="text-sm font-medium text-neutral-900 dark:text-neutral-50">
                    ${formatPrice(item.price)}
                  </span>
                  <span className={`text-xs ml-2 ${getChangeColor(item.change_percent)}`}>
                    {formatPercent(item.change_percent)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Crypto */}
        <div>
          <h3 className="text-xs font-medium text-neutral-500 uppercase tracking-wider mb-2">
            Crypto
          </h3>
          <div className="space-y-2">
            {crypto.map((item) => (
              <Link
                key={item.symbol}
                href={`/equity/${item.symbol}`}
                className="flex justify-between items-center hover:bg-neutral-100 dark:hover:bg-neutral-700/50 rounded p-1 -m-1 transition-colors"
              >
                <span className="text-sm text-neutral-700 dark:text-neutral-300">
                  {item.name}
                </span>
                <div className="text-right">
                  <span className="text-sm font-medium text-neutral-900 dark:text-neutral-50">
                    ${formatPrice(item.price)}
                  </span>
                  <span className={`text-xs ml-2 ${getChangeColor(item.change_percent)}`}>
                    {formatPercent(item.change_percent)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MarketOverviewPage() {
  const { data, isLoading, error } = useMarketOverview();

  if (isLoading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
          <div className="animate-pulse space-y-6">
            <div className="h-8 w-48 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-28 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
              ))}
            </div>
            <div className="h-64 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50 mb-2">
            Failed to load market data
          </h1>
          <p className="text-neutral-500">Please try again later</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              Market Overview
            </h1>
            <p className="text-sm text-neutral-500">
              Last updated: {new Date(data.timestamp).toLocaleTimeString()}
            </p>
          </div>
        </div>

        {/* Major Indices */}
        <div className="mb-6">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-3">
            Major Indices
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {data.indices.map((index) => (
              <IndexCard key={index.symbol} index={index} />
            ))}
          </div>
        </div>

        {/* Sector Heatmap */}
        <div className="mb-6">
          <SectorHeatmap sectors={data.sectors} />
        </div>

        {/* Movers and Currencies/Commodities */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <MoversList
            title="Top Gainers"
            movers={data.gainers}
            isGainers={true}
          />
          <MoversList
            title="Top Losers"
            movers={data.losers}
            isGainers={false}
          />
          <CurrencyCommodityList items={data.currencies_commodities} />
        </div>
      </div>
    </div>
  );
}
