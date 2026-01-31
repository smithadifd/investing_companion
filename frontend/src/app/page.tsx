export default function Home() {
  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold mb-4">
          Investing Companion
        </h1>
        <p className="text-gray-600 mb-8">
          Your self-hosted investing analysis dashboard
        </p>

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

        <div className="mt-12 p-4 bg-gray-100 rounded-lg">
          <h2 className="font-semibold mb-2">Quick Search</h2>
          <input
            type="text"
            placeholder="Search for a symbol (e.g., AAPL, CCJ)..."
            className="w-full p-3 rounded border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled
          />
          <p className="text-sm text-gray-500 mt-2">
            Search functionality coming in Phase 1
          </p>
        </div>
      </div>
    </main>
  )
}

function DashboardCard({
  title,
  description,
  href,
  status,
}: {
  title: string
  description: string
  href: string
  status: string
}) {
  return (
    <div className="p-6 border rounded-lg hover:shadow-md transition-shadow">
      <h3 className="text-xl font-semibold mb-2">{title}</h3>
      <p className="text-gray-600 mb-4">{description}</p>
      <span className="text-sm text-orange-600 bg-orange-100 px-2 py-1 rounded">
        {status}
      </span>
    </div>
  )
}
