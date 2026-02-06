'use client';

import { useState } from 'react';
import { X, Calendar, Clock, AlertCircle } from 'lucide-react';
import { useCreateEvent } from '@/lib/hooks/useEvents';
import { Modal } from '@/components/ui/Modal';
import type { EventType, EventImportance, EconomicEventCreate } from '@/lib/api/types';

interface Props {
  onClose: () => void;
  onSuccess: () => void;
  defaultDate?: string;
}

export function CreateEventModal({ onClose, onSuccess, defaultDate }: Props) {
  const createEvent = useCreateEvent();
  const [error, setError] = useState<string | null>(null);

  const today = new Date().toISOString().split('T')[0];
  const [formData, setFormData] = useState({
    event_type: 'custom' as EventType,
    event_date: defaultDate || today,
    event_time: '',
    all_day: true,
    title: '',
    description: '',
    equity_symbol: '',
    importance: 'medium' as EventImportance,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!formData.title.trim()) {
      setError('Title is required');
      return;
    }

    const data: EconomicEventCreate = {
      event_type: formData.event_type,
      event_date: formData.event_date,
      title: formData.title.trim(),
      importance: formData.importance,
      all_day: formData.all_day,
    };

    if (!formData.all_day && formData.event_time) {
      data.event_time = formData.event_time;
    }

    if (formData.description.trim()) {
      data.description = formData.description.trim();
    }

    if (formData.equity_symbol.trim()) {
      data.equity_symbol = formData.equity_symbol.trim().toUpperCase();
    }

    try {
      await createEvent.mutateAsync(data);
      onSuccess();
    } catch (err: any) {
      setError(err.message || 'Failed to create event');
    }
  };

  const headerContent = (
    <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-200 dark:border-neutral-700">
      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-2">
        <Calendar className="h-5 w-5" />
        Add Custom Event
      </h2>
      <button
        onClick={onClose}
        className="p-1 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
      >
        <X className="h-5 w-5 text-neutral-500" />
      </button>
    </div>
  );

  return (
    <Modal onClose={onClose} header={headerContent} maxWidth="lg">
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              {error}
            </div>
          )}

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Title *
            </label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              placeholder="Quarterly portfolio review"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              autoFocus
            />
          </div>

          {/* Date and Time */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Date *
              </label>
              <input
                type="date"
                value={formData.event_date}
                onChange={(e) => setFormData({ ...formData, event_date: e.target.value })}
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Time
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="time"
                  value={formData.event_time}
                  onChange={(e) => setFormData({ ...formData, event_time: e.target.value, all_day: !e.target.value })}
                  disabled={formData.all_day}
                  className="flex-1 px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
                />
              </div>
              <label className="flex items-center gap-2 mt-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.all_day}
                  onChange={(e) => setFormData({ ...formData, all_day: e.target.checked, event_time: e.target.checked ? '' : formData.event_time })}
                  className="rounded border-neutral-300 dark:border-neutral-600"
                />
                <span className="text-sm text-neutral-600 dark:text-neutral-400">All day</span>
              </label>
            </div>
          </div>

          {/* Equity Symbol (optional) */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Equity Symbol (optional)
            </label>
            <input
              type="text"
              value={formData.equity_symbol}
              onChange={(e) => setFormData({ ...formData, equity_symbol: e.target.value })}
              placeholder="AAPL"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
              Link this event to a specific equity
            </p>
          </div>

          {/* Importance */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Importance
            </label>
            <div className="flex gap-2">
              {(['low', 'medium', 'high'] as const).map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => setFormData({ ...formData, importance: level })}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                    formData.importance === level
                      ? level === 'high'
                        ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 ring-2 ring-red-500'
                        : level === 'medium'
                        ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 ring-2 ring-yellow-500'
                        : 'bg-neutral-200 text-neutral-700 dark:bg-neutral-600 dark:text-neutral-300 ring-2 ring-neutral-500'
                      : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                  }`}
                >
                  {level.charAt(0).toUpperCase() + level.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description (optional)
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Add notes or details about this event..."
              rows={3}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createEvent.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {createEvent.isPending ? 'Creating...' : 'Create Event'}
            </button>
          </div>
        </form>
    </Modal>
  );
}
