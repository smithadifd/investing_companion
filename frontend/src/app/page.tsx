import Link from 'next/link';
import { SearchBar } from '@/components/search/SearchBar';

export default function Home() {
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        <h1 className="text-3xl sm:text-4xl font-bold text-neutral-900 dark:text-neutral-50 mb-2">
          Investing Companion
        </h1>
        <p className="text-neutral-500 dark:text-neutral-400 mb-8">
          Your self-hosted investing analysis dashboard
        </p>

        {/* Search */}
        <div className="mb-10 p-6 bg-white dark:bg-neutral-800 rounded-xl shadow-sm border border-neutral-200 dark:border-neutral-700">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">Quick Search</h2>
          <SearchBar />
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-3">
            Search for any stock, ETF, or index by symbol or name
          </p>
        </div>

        {/* Feature cards */}
        <h2 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-4">Features</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Link href="/watchlists">
            <DashboardCard
              title="Watchlists"
              description="Track equities with notes and targets"
              status="Available"
              active
            />
          </Link>
          <Link href="/market">
            <DashboardCard
              title="Market Overview"
              description="Indices, sectors, and macro indicators"
              status="Available"
              active
            />
          </Link>
          <Link href="/ratios">
            <DashboardCard
              title="Ratios"
              description="Compare assets and track key ratios"
              status="Available"
              active
            />
          </Link>
          <DashboardCard
            title="Alerts"
            description="Get notified on price movements"
            status="Phase 4"
          />
        </div>

        {/* Status */}
        <div className="mt-10 p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl">
          <div className="flex items-center gap-2">
            <div className="h-2.5 w-2.5 bg-emerald-500 rounded-full animate-pulse"></div>
            <span className="text-emerald-600 dark:text-emerald-400 font-medium">Phase 1 Complete</span>
          </div>
          <p className="text-emerald-700 dark:text-emerald-300/80 text-sm mt-1">
            Search for equities, view quotes, charts, and fundamentals
          </p>
        </div>
      </div>
    </div>
  );
}

function DashboardCard({
  title,
  description,
  status,
  active,
}: {
  title: string;
  description: string;
  status: string;
  active?: boolean;
}) {
  return (
    <div className={`p-5 bg-white dark:bg-neutral-800 border rounded-xl hover:shadow-md transition-all ${
      active
        ? 'border-blue-500/50 hover:border-blue-500'
        : 'border-neutral-200 dark:border-neutral-700'
    }`}>
      <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-1.5">{title}</h3>
      <p className="text-neutral-500 dark:text-neutral-400 text-sm mb-3">{description}</p>
      <span className={`inline-block text-xs font-medium px-2.5 py-1 rounded-full ${
        active
          ? 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/10'
          : 'text-amber-600 dark:text-amber-400 bg-amber-500/10'
      }`}>
        {status}
      </span>
    </div>
  );
}
