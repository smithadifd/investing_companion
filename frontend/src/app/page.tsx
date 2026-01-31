import { SearchBar } from '@/components/search/SearchBar';

export default function Home() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">
          Investing Companion
        </h1>
        <p className="text-gray-600 mb-8">
          Your self-hosted investing analysis dashboard
        </p>

        {/* Search */}
        <div className="mb-12 p-6 bg-white rounded-lg shadow-sm">
          <h2 className="font-semibold text-gray-900 mb-4">Quick Search</h2>
          <SearchBar />
          <p className="text-sm text-gray-500 mt-3">
            Search for any stock, ETF, or index by symbol or name
          </p>
        </div>

        {/* Feature cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <DashboardCard
            title="Watchlists"
            description="Track equities with notes and targets"
            href="/watchlists"
            status="Coming in Phase 2"
          />
          <DashboardCard
            title="Market Overview"
            description="Indices, sectors, and macro indicators"
            href="/market"
            status="Coming in Phase 3"
          />
          <DashboardCard
            title="Ratios"
            description="Compare assets and track key ratios"
            href="/ratios"
            status="Coming in Phase 3"
          />
          <DashboardCard
            title="Alerts"
            description="Get notified on price movements"
            href="/alerts"
            status="Coming in Phase 4"
          />
        </div>

        {/* Status */}
        <div className="mt-12 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 bg-green-500 rounded-full"></div>
            <span className="text-green-800 font-medium">Phase 1 Complete</span>
          </div>
          <p className="text-green-700 text-sm mt-1">
            Search for equities, view quotes, charts, and fundamentals
          </p>
        </div>
      </div>
    </main>
  );
}

function DashboardCard({
  title,
  description,
  href,
  status,
}: {
  title: string;
  description: string;
  href: string;
  status: string;
}) {
  return (
    <div className="p-6 bg-white border rounded-lg hover:shadow-md transition-shadow">
      <h3 className="text-xl font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-gray-600 mb-4">{description}</p>
      <span className="text-sm text-orange-600 bg-orange-100 px-2 py-1 rounded">
        {status}
      </span>
    </div>
  );
}
