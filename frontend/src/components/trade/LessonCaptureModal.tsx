'use client';

import { useState } from 'react';
import { GraduationCap, Loader2 } from 'lucide-react';
import { useCreateLesson } from '@/lib/hooks/useLessons';
import { Modal } from '@/components/ui/Modal';
import type { ThesisOutcome } from '@/lib/api/types';

interface LessonCaptureModalProps {
  symbol: string;
  tradeId: number;
  onClose: () => void;
}

const OUTCOMES: { value: ThesisOutcome; label: string }[] = [
  { value: 'played_out', label: 'Played out' },
  { value: 'partial', label: 'Partially' },
  { value: 'wrong', label: 'Wrong' },
  { value: 'unclear', label: 'Unclear' },
];

const OUTCOME_SELECTED: Record<ThesisOutcome, string> = {
  played_out: 'bg-emerald-600 text-white',
  partial: 'bg-amber-500 text-white',
  wrong: 'bg-red-600 text-white',
  unclear: 'bg-neutral-500 text-white',
};

/**
 * Post-close lesson capture. Entirely optional - the trade is already
 * logged by the time this opens, so skipping never loses anything.
 */
export function LessonCaptureModal({
  symbol,
  tradeId,
  onClose,
}: LessonCaptureModalProps) {
  const [outcome, setOutcome] = useState<ThesisOutcome | null>(null);
  const [lesson, setLesson] = useState('');
  const [tags, setTags] = useState('');

  const createLesson = useCreateLesson();

  const canSave = outcome !== null && lesson.trim().length > 0;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave || outcome === null) return;

    try {
      await createLesson.mutateAsync({
        trade_id: tradeId,
        thesis_outcome: outcome,
        lesson: lesson.trim(),
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      });
      onClose();
    } catch (error) {
      console.error('Failed to save lesson:', error);
    }
  };

  return (
    <Modal onClose={onClose} title={`Position closed: ${symbol}`} maxWidth="md">
      <form onSubmit={handleSave} className="p-4 space-y-4">
        <div className="flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
          <GraduationCap className="h-4 w-4 mt-0.5 flex-shrink-0 text-blue-500" />
          <span>
            Capture what this trade taught you - it resurfaces before similar
            setups. Optional; the trade is already saved.
          </span>
        </div>

        {/* Thesis outcome */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
            Did the thesis play out?
          </label>
          <div className="grid grid-cols-4 gap-2">
            {OUTCOMES.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => setOutcome(o.value)}
                className={`py-2 px-2 rounded-lg text-sm font-medium transition-colors ${
                  outcome === o.value
                    ? OUTCOME_SELECTED[o.value]
                    : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        {/* Lesson */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Lesson
          </label>
          <textarea
            value={lesson}
            onChange={(e) => setLesson(e.target.value)}
            placeholder="What would you tell yourself before the next similar setup?"
            rows={3}
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
          />
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Tags (comma-separated)
          </label>
          <input
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="e.g. natgas, entry-zone, earnings-hold"
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <p className="text-xs text-neutral-500 mt-1">
            Symbols, themes, or setup types - tags drive resurfacing on similar
            setups.
          </p>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
          >
            Skip
          </button>
          <button
            type="submit"
            disabled={!canSave || createLesson.isPending}
            className="flex items-center gap-2 px-4 py-2 text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
          >
            {createLesson.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Save lesson
          </button>
        </div>
      </form>
    </Modal>
  );
}
