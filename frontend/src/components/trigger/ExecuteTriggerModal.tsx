'use client';

import { useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { useExecuteTrigger } from '@/lib/hooks/useTrigger';
import { Modal } from '@/components/ui/Modal';
import type { Trigger } from '@/lib/api/types';

interface ExecuteTriggerModalProps {
  trigger: Trigger;
  onClose: () => void;
}

const NOTE_MAX_LENGTH = 2000;

export function ExecuteTriggerModal({ trigger, onClose }: ExecuteTriggerModalProps) {
  const [note, setNote] = useState('');
  const executeTrigger = useExecuteTrigger();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      await executeTrigger.mutateAsync({ id: trigger.id, note: note.trim() || undefined });
      onClose();
    } catch (error) {
      console.error('Failed to execute trigger:', error);
    }
  };

  return (
    <Modal onClose={onClose} title="Mark Executed" maxWidth="lg">
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
        {/* Recap of the standing order being executed */}
        <div className="bg-neutral-50 dark:bg-neutral-700/50 border border-neutral-200 dark:border-neutral-600 rounded-lg p-3 space-y-2">
          <p className="font-semibold text-neutral-900 dark:text-neutral-50">
            {trigger.name}
          </p>
          <div className="flex gap-2 text-sm">
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-neutral-400 mt-0.5">
              If
            </span>
            <span className="text-neutral-600 dark:text-neutral-400">{trigger.rule}</span>
          </div>
          <div className="flex gap-2 text-sm">
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-neutral-400 mt-0.5">
              Then
            </span>
            <span className="text-neutral-900 dark:text-neutral-50">{trigger.action}</span>
          </div>
        </div>

        {/* Execution note - the record this playbook entry leaves behind */}
        <div>
          <label
            htmlFor="execution-note"
            className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
          >
            What did you actually do?
          </label>
          <p className="text-xs text-neutral-500 mb-2">
            Fill price, size, deviations from the plan, how it felt. Future you reviews
            these notes to sharpen the playbook.
          </p>
          <textarea
            id="execution-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={NOTE_MAX_LENGTH}
            placeholder="e.g., Sold the May puts at $4.20 (planned $4+). Slipped 15 min past the trigger waiting for a bounce — don't do that next time."
            rows={5}
            autoFocus
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
          />
          <p className="text-xs text-neutral-400 mt-1 text-right">
            {note.length}/{NOTE_MAX_LENGTH}
          </p>
        </div>

        {/* Submit */}
        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={executeTrigger.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50"
          >
            {executeTrigger.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Mark Executed
          </button>
        </div>
      </form>
    </Modal>
  );
}
