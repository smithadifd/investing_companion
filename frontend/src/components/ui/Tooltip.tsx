'use client';

import { useState, useRef, useEffect } from 'react';
import { HelpCircle } from 'lucide-react';

interface TooltipProps {
  content: string;
  children?: React.ReactNode;
}

export function Tooltip({ content, children }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<'top' | 'bottom'>('top');
  const tooltipRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isVisible && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const spaceAbove = rect.top;
      const spaceBelow = window.innerHeight - rect.bottom;

      // Show below if not enough space above
      setPosition(spaceAbove < 100 && spaceBelow > spaceAbove ? 'bottom' : 'top');
    }
  }, [isVisible]);

  return (
    <div className="relative inline-flex items-center">
      <div
        ref={triggerRef}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        onFocus={() => setIsVisible(true)}
        onBlur={() => setIsVisible(false)}
        tabIndex={0}
        className="cursor-help"
      >
        {children || (
          <HelpCircle className="h-4 w-4 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors" />
        )}
      </div>

      {isVisible && (
        <div
          ref={tooltipRef}
          className={`absolute z-50 px-3 py-2 text-sm bg-neutral-900 dark:bg-neutral-700 text-white rounded-lg shadow-lg max-w-xs whitespace-normal ${
            position === 'top'
              ? 'bottom-full mb-2 left-1/2 -translate-x-1/2'
              : 'top-full mt-2 left-1/2 -translate-x-1/2'
          }`}
        >
          {content}
          <div
            className={`absolute left-1/2 -translate-x-1/2 border-4 border-transparent ${
              position === 'top'
                ? 'top-full border-t-neutral-900 dark:border-t-neutral-700'
                : 'bottom-full border-b-neutral-900 dark:border-b-neutral-700'
            }`}
          />
        </div>
      )}
    </div>
  );
}

interface LabelWithTooltipProps {
  label: string;
  tooltip: string;
  htmlFor?: string;
}

export function LabelWithTooltip({ label, tooltip, htmlFor }: LabelWithTooltipProps) {
  return (
    <div className="flex items-center gap-1.5 mb-1">
      <label
        htmlFor={htmlFor}
        className="text-sm font-medium text-neutral-700 dark:text-neutral-300"
      >
        {label}
      </label>
      <Tooltip content={tooltip} />
    </div>
  );
}
