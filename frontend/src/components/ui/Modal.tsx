'use client';

import { useEffect, useCallback, type ReactNode } from 'react';
import { X } from 'lucide-react';

type MaxWidth = 'sm' | 'md' | 'lg' | 'xl';

const MAX_WIDTH_CLASSES: Record<MaxWidth, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

interface ModalProps {
  onClose: () => void;
  title?: string;
  header?: ReactNode;
  maxWidth?: MaxWidth;
  children: ReactNode;
}

export function Modal({
  onClose,
  title,
  header,
  maxWidth = 'md',
  children,
}: ModalProps) {
  const handleEscape = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose]
  );

  useEffect(() => {
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [handleEscape]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={`relative bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-xl w-full ${MAX_WIDTH_CLASSES[maxWidth]} max-h-[90vh] overflow-y-auto`}
      >
        {header ?? (
          <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700 sticky top-0 bg-white dark:bg-neutral-800 rounded-t-xl">
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
              {title}
            </h2>
            <button
              onClick={onClose}
              className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
