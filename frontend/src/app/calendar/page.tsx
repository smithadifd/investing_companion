'use client';

import { useState, useMemo } from 'react';
import {
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Filter,
  RefreshCw,
  Plus,
  List,
  Grid3X3,
  TrendingUp,
  Landmark,
  DollarSign,
  Scissors,
  Clock,
  AlertCircle,
} from 'lucide-react';
import { useCalendarMonth, useEventStats, useRefreshWatchlistEvents } from '@/lib/hooks/useEvents';
import { useAuth } from '@/lib/contexts/AuthContext';
import type { EconomicEvent, EventType, CalendarDay, EventStats } from '@/lib/api/types';
import { CreateEventModal } from '@/components/event/CreateEventModal';
import { EventDetailModal } from '@/components/event/EventDetailModal';

// Event type configuration
const EVENT_TYPE_CONFIG: Record<EventType, { label: string; color: string; icon: React.ReactNode; category: 'equity' | 'macro' | 'other' }> = {
  earnings: { label: 'Earnings', color: 'bg-blue-500', icon: <TrendingUp className="h-3 w-3" />, category: 'equity' },
  ex_dividend: { label: 'Ex-Dividend', color: 'bg-teal-500', icon: <DollarSign className="h-3 w-3" />, category: 'equity' },
  dividend_pay: { label: 'Dividend Pay', color: 'bg-teal-400', icon: <DollarSign className="h-3 w-3" />, category: 'equity' },
  stock_split: { label: 'Stock Split', color: 'bg-pink-500', icon: <Scissors className="h-3 w-3" />, category: 'equity' },
  fomc: { label: 'FOMC', color: 'bg-purple-500', icon: <Landmark className="h-3 w-3" />, category: 'macro' },
  cpi: { label: 'CPI', color: 'bg-orange-500', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  ppi: { label: 'PPI', color: 'bg-orange-400', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  nfp: { label: 'Jobs Report', color: 'bg-green-500', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  gdp: { label: 'GDP', color: 'bg-yellow-500', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  pce: { label: 'PCE', color: 'bg-amber-500', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  retail_sales: { label: 'Retail Sales', color: 'bg-lime-500', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  unemployment: { label: 'Unemployment', color: 'bg-red-400', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  ism_manufacturing: { label: 'ISM Mfg', color: 'bg-indigo-400', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  ism_services: { label: 'ISM Services', color: 'bg-indigo-300', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  housing_starts: { label: 'Housing', color: 'bg-cyan-500', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  consumer_confidence: { label: 'Consumer Conf.', color: 'bg-emerald-400', icon: <TrendingUp className="h-3 w-3" />, category: 'macro' },
  custom: { label: 'Custom', color: 'bg-gray-500', icon: <CalendarIcon className="h-3 w-3" />, category: 'other' },
  ipo: { label: 'IPO', color: 'bg-rose-500', icon: <TrendingUp className="h-3 w-3" />, category: 'equity' },
};

// Month names
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

// Days of week
const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// Format date for display
function formatDate(dateStr: string): string {
  const date = new Date(dateStr + 'T00:00:00');
  return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

// Check if date is today
function isToday(dateStr: string): boolean {
  const today = new Date();
  const date = new Date(dateStr + 'T00:00:00');
  return (
    date.getDate() === today.getDate() &&
    date.getMonth() === today.getMonth() &&
    date.getFullYear() === today.getFullYear()
  );
}

// Event badge component
function EventBadge({ event, compact = false }: { event: EconomicEvent; compact?: boolean }) {
  const config = EVENT_TYPE_CONFIG[event.event_type] || EVENT_TYPE_CONFIG.custom;

  if (compact) {
    return (
      <div
        className={`${config.color} w-2 h-2 rounded-full`}
        title={event.title}
      />
    );
  }

  return (
    <div
      className={`${config.color} text-white text-xs px-2 py-0.5 rounded flex items-center gap-1 truncate`}
      title={event.title}
    >
      {config.icon}
      <span className="truncate">
        {event.equity?.symbol ? `${event.equity.symbol}` : event.title}
      </span>
    </div>
  );
}

// Calendar day cell component
function CalendarDayCell({
  day,
  isCurrentMonth,
  onEventClick,
  onDayClick,
}: {
  day: CalendarDay | null;
  isCurrentMonth: boolean;
  onEventClick: (event: EconomicEvent) => void;
  onDayClick: (date: string) => void;
}) {
  if (!day) {
    return <div className="h-24 bg-neutral-50 dark:bg-neutral-900/50" />;
  }

  const today = isToday(day.date);
  const dayNum = new Date(day.date + 'T00:00:00').getDate();

  return (
    <div
      className={`h-24 border-b border-r border-neutral-200 dark:border-neutral-700 p-1 overflow-hidden cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors ${
        !isCurrentMonth ? 'bg-neutral-50 dark:bg-neutral-900/50' : ''
      }`}
      onClick={() => onDayClick(day.date)}
    >
      <div className="flex justify-between items-start mb-1">
        <span
          className={`text-sm font-medium w-6 h-6 flex items-center justify-center rounded-full ${
            today
              ? 'bg-blue-600 text-white'
              : isCurrentMonth
              ? 'text-neutral-900 dark:text-neutral-100'
              : 'text-neutral-400 dark:text-neutral-600'
          }`}
        >
          {dayNum}
        </span>
        {day.event_count > 0 && (
          <span className="text-xs text-neutral-500 dark:text-neutral-400">
            {day.event_count}
          </span>
        )}
      </div>
      <div className="space-y-0.5 overflow-hidden">
        {day.events.slice(0, 3).map((event) => (
          <div
            key={event.id}
            onClick={(e) => {
              e.stopPropagation();
              onEventClick(event);
            }}
            className="cursor-pointer hover:opacity-80"
          >
            <EventBadge event={event} />
          </div>
        ))}
        {day.events.length > 3 && (
          <div className="text-xs text-neutral-500 dark:text-neutral-400 pl-1">
            +{day.events.length - 3} more
          </div>
        )}
      </div>
    </div>
  );
}

// List view component
function EventListView({
  events,
  onEventClick,
}: {
  events: EconomicEvent[];
  onEventClick: (event: EconomicEvent) => void;
}) {
  // Group events by date
  const grouped = useMemo(() => {
    const groups: Record<string, EconomicEvent[]> = {};
    events.forEach((event) => {
      if (!groups[event.event_date]) {
        groups[event.event_date] = [];
      }
      groups[event.event_date].push(event);
    });
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [events]);

  if (events.length === 0) {
    return (
      <div className="text-center py-12 text-neutral-500 dark:text-neutral-400">
        <CalendarIcon className="h-12 w-12 mx-auto mb-3 opacity-50" />
        <p>No events found for the selected filters</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {grouped.map(([date, dayEvents]) => (
        <div key={date}>
          <h3 className={`font-semibold mb-2 ${isToday(date) ? 'text-blue-600' : 'text-neutral-900 dark:text-neutral-100'}`}>
            {formatDate(date)}
            {isToday(date) && (
              <span className="ml-2 text-xs font-normal bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-2 py-0.5 rounded">
                Today
              </span>
            )}
          </h3>
          <div className="space-y-2">
            {dayEvents.map((event) => {
              const config = EVENT_TYPE_CONFIG[event.event_type] || EVENT_TYPE_CONFIG.custom;
              return (
                <div
                  key={event.id}
                  onClick={() => onEventClick(event)}
                  className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-3 cursor-pointer hover:border-neutral-300 dark:hover:border-neutral-600 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <div className={`${config.color} p-2 rounded-lg text-white`}>
                      {config.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-neutral-900 dark:text-neutral-100 truncate">
                          {event.title}
                        </span>
                        {event.equity && (
                          <span className="text-xs bg-neutral-100 dark:bg-neutral-700 px-1.5 py-0.5 rounded">
                            {event.equity.symbol}
                          </span>
                        )}
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          event.importance === 'high'
                            ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                            : event.importance === 'medium'
                            ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                            : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400'
                        }`}>
                          {event.importance}
                        </span>
                      </div>
                      {event.description && (
                        <p className="text-sm text-neutral-500 dark:text-neutral-400 truncate mt-0.5">
                          {event.description}
                        </p>
                      )}
                      {event.event_time && !event.all_day && (
                        <div className="flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                          <Clock className="h-3 w-3" />
                          {event.event_time}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// Filter panel component
function FilterPanel({
  selectedTypes,
  setSelectedTypes,
  watchlistOnly,
  setWatchlistOnly,
  isAuthenticated,
}: {
  selectedTypes: EventType[];
  setSelectedTypes: (types: EventType[]) => void;
  watchlistOnly: boolean;
  setWatchlistOnly: (value: boolean) => void;
  isAuthenticated: boolean;
}) {
  const macroTypes: EventType[] = ['fomc', 'cpi', 'ppi', 'nfp', 'gdp', 'pce', 'retail_sales'];
  const equityTypes: EventType[] = ['earnings', 'ex_dividend', 'dividend_pay', 'stock_split'];

  const toggleType = (type: EventType) => {
    if (selectedTypes.includes(type)) {
      setSelectedTypes(selectedTypes.filter(t => t !== type));
    } else {
      setSelectedTypes([...selectedTypes, type]);
    }
  };

  const toggleCategory = (types: EventType[]) => {
    const allSelected = types.every(t => selectedTypes.includes(t));
    if (allSelected) {
      setSelectedTypes(selectedTypes.filter(t => !types.includes(t)));
    } else {
      setSelectedTypes([...new Set([...selectedTypes, ...types])]);
    }
  };

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
      <h3 className="font-semibold text-neutral-900 dark:text-neutral-100 mb-3 flex items-center gap-2">
        <Filter className="h-4 w-4" />
        Filters
      </h3>

      {isAuthenticated && (
        <div className="mb-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={watchlistOnly}
              onChange={(e) => setWatchlistOnly(e.target.checked)}
              className="rounded border-neutral-300 dark:border-neutral-600"
            />
            <span className="text-sm text-neutral-700 dark:text-neutral-300">
              Watchlist equities only
            </span>
          </label>
        </div>
      )}

      <div className="space-y-3">
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              Macro Events
            </span>
            <button
              onClick={() => toggleCategory(macroTypes)}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
            >
              {macroTypes.every(t => selectedTypes.includes(t)) ? 'Deselect all' : 'Select all'}
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {macroTypes.map((type) => {
              const config = EVENT_TYPE_CONFIG[type];
              const isSelected = selectedTypes.includes(type);
              return (
                <button
                  key={type}
                  onClick={() => toggleType(type)}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    isSelected
                      ? `${config.color} text-white`
                      : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                  }`}
                >
                  {config.label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              Equity Events
            </span>
            <button
              onClick={() => toggleCategory(equityTypes)}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
            >
              {equityTypes.every(t => selectedTypes.includes(t)) ? 'Deselect all' : 'Select all'}
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {equityTypes.map((type) => {
              const config = EVENT_TYPE_CONFIG[type];
              const isSelected = selectedTypes.includes(type);
              return (
                <button
                  key={type}
                  onClick={() => toggleType(type)}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    isSelected
                      ? `${config.color} text-white`
                      : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                  }`}
                >
                  {config.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// Stats card component
function StatsCard({ stats }: { stats: EventStats }) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
      <h3 className="font-semibold text-neutral-900 dark:text-neutral-100 mb-3 flex items-center gap-2">
        <AlertCircle className="h-4 w-4" />
        This Week
      </h3>
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-neutral-600 dark:text-neutral-400">Earnings</span>
          <span className="font-medium text-neutral-900 dark:text-neutral-100">
            {stats.earnings_this_week}
          </span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-neutral-600 dark:text-neutral-400">Macro Events</span>
          <span className="font-medium text-neutral-900 dark:text-neutral-100">
            {stats.macro_events_this_week}
          </span>
        </div>
        {stats.next_fomc_date && (
          <div className="flex justify-between text-sm">
            <span className="text-neutral-600 dark:text-neutral-400">Next FOMC</span>
            <span className="font-medium text-neutral-900 dark:text-neutral-100">
              {new Date(stats.next_fomc_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
            </span>
          </div>
        )}
        {stats.watchlist_earnings_upcoming > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-neutral-600 dark:text-neutral-400">Watchlist Earnings</span>
            <span className="font-medium text-blue-600 dark:text-blue-400">
              {stats.watchlist_earnings_upcoming}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// Main calendar page component
export default function CalendarPage() {
  const { isAuthenticated } = useAuth();
  const [currentDate, setCurrentDate] = useState(() => new Date());
  const [viewMode, setViewMode] = useState<'month' | 'list'>('month');
  const [selectedTypes, setSelectedTypes] = useState<EventType[]>([
    'earnings', 'fomc', 'cpi', 'nfp', 'gdp',
  ]);
  const [watchlistOnly, setWatchlistOnly] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<EconomicEvent | null>(null);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth() + 1;

  // Fetch calendar data - memoize filters to ensure React Query detects changes
  const filters = useMemo(() => ({
    event_types: selectedTypes.length > 0 ? selectedTypes : undefined,
    watchlist_only: watchlistOnly,
  }), [selectedTypes, watchlistOnly]);

  const { data: calendarData, isLoading, refetch } = useCalendarMonth(year, month, filters);
  const { data: stats } = useEventStats();
  const refreshMutation = useRefreshWatchlistEvents();

  // Navigation
  const goToPreviousMonth = () => {
    setCurrentDate(new Date(year, month - 2, 1));
  };

  const goToNextMonth = () => {
    setCurrentDate(new Date(year, month, 1));
  };

  const goToToday = () => {
    setCurrentDate(new Date());
  };

  // Build calendar grid
  const calendarGrid = useMemo(() => {
    if (!calendarData) return [];

    const firstDay = new Date(year, month - 1, 1).getDay();
    const daysInMonth = new Date(year, month, 0).getDate();
    const grid: (CalendarDay | null)[] = [];

    // Add empty cells for days before the first of the month
    for (let i = 0; i < firstDay; i++) {
      grid.push(null);
    }

    // Add days from calendar data
    const dayMap = new Map(calendarData.days.map(d => [d.date, d]));
    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      grid.push(dayMap.get(dateStr) || { date: dateStr, events: [], has_earnings: false, has_macro: false, event_count: 0 });
    }

    return grid;
  }, [calendarData, year, month]);

  // Get all events for list view
  const allEvents = useMemo(() => {
    if (!calendarData) return [];
    return calendarData.days.flatMap(d => d.events);
  }, [calendarData]);

  const handleRefresh = () => {
    if (isAuthenticated) {
      refreshMutation.mutate(undefined, {
        onSuccess: () => refetch(),
      });
    } else {
      refetch();
    }
  };

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50 flex items-center gap-2">
              <CalendarIcon className="h-7 w-7" />
              Economic Calendar
            </h1>
            <p className="text-neutral-600 dark:text-neutral-400 mt-1">
              Track earnings, FOMC meetings, and economic releases
            </p>
          </div>
          <div className="flex items-center gap-2">
            {isAuthenticated && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <Plus className="h-4 w-4" />
                Add Event
              </button>
            )}
            <button
              onClick={handleRefresh}
              disabled={refreshMutation.isPending}
              className="flex items-center gap-2 px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        <div className="flex flex-col lg:flex-row gap-6">
          {/* Main calendar area */}
          <div className="flex-1">
            {/* Calendar controls */}
            <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4 mb-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <button
                    onClick={goToPreviousMonth}
                    className="p-2 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
                  >
                    <ChevronLeft className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
                  </button>
                  <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 min-w-[140px] sm:min-w-[160px] text-center">
                    {MONTHS[month - 1]} {year}
                  </h2>
                  <button
                    onClick={goToNextMonth}
                    className="p-2 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
                  >
                    <ChevronRight className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
                  </button>
                  <button
                    onClick={goToToday}
                    className="ml-2 px-3 py-1 text-sm border border-neutral-300 dark:border-neutral-600 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors hidden sm:block"
                  >
                    Today
                  </button>
                </div>
                <div className="flex items-center gap-1 bg-neutral-100 dark:bg-neutral-700 rounded-lg p-1 flex-shrink-0">
                  <button
                    onClick={() => setViewMode('month')}
                    className={`p-2 rounded transition-colors ${
                      viewMode === 'month'
                        ? 'bg-white dark:bg-neutral-600 shadow-sm'
                        : 'hover:bg-neutral-200 dark:hover:bg-neutral-600'
                    }`}
                  >
                    <Grid3X3 className="h-4 w-4 text-neutral-700 dark:text-neutral-300" />
                  </button>
                  <button
                    onClick={() => setViewMode('list')}
                    className={`p-2 rounded transition-colors ${
                      viewMode === 'list'
                        ? 'bg-white dark:bg-neutral-600 shadow-sm'
                        : 'hover:bg-neutral-200 dark:hover:bg-neutral-600'
                    }`}
                  >
                    <List className="h-4 w-4 text-neutral-700 dark:text-neutral-300" />
                  </button>
                </div>
              </div>
            </div>

            {/* Calendar content */}
            {isLoading ? (
              <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-8">
                <div className="flex items-center justify-center">
                  <RefreshCw className="h-6 w-6 animate-spin text-neutral-400" />
                  <span className="ml-2 text-neutral-500 dark:text-neutral-400">Loading calendar...</span>
                </div>
              </div>
            ) : viewMode === 'month' ? (
              <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
                {/* Day headers */}
                <div className="grid grid-cols-7 border-b border-neutral-200 dark:border-neutral-700">
                  {DAYS_OF_WEEK.map((day) => (
                    <div
                      key={day}
                      className="text-center text-sm font-medium text-neutral-600 dark:text-neutral-400 py-2 bg-neutral-50 dark:bg-neutral-800/50"
                    >
                      {day}
                    </div>
                  ))}
                </div>
                {/* Calendar grid */}
                <div className="grid grid-cols-7">
                  {calendarGrid.map((day, index) => (
                    <CalendarDayCell
                      key={index}
                      day={day}
                      isCurrentMonth={true}
                      onEventClick={setSelectedEvent}
                      onDayClick={() => {}}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
                <EventListView events={allEvents} onEventClick={setSelectedEvent} />
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="lg:w-72 space-y-4">
            {stats && <StatsCard stats={stats} />}
            <FilterPanel
              selectedTypes={selectedTypes}
              setSelectedTypes={setSelectedTypes}
              watchlistOnly={watchlistOnly}
              setWatchlistOnly={setWatchlistOnly}
              isAuthenticated={isAuthenticated}
            />
          </div>
        </div>
      </div>

      {/* Modals */}
      {showCreateModal && (
        <CreateEventModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            refetch();
          }}
        />
      )}

      {selectedEvent && (
        <EventDetailModal
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </div>
  );
}
