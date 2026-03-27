'use client';

interface Props {
  sentiment: 'positive' | 'negative' | 'neutral' | null;
}

const SENTIMENT_CONFIG = {
  positive: {
    label: 'Positive',
    className: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400',
  },
  negative: {
    label: 'Negative',
    className: 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400',
  },
  neutral: {
    label: 'Neutral',
    className: 'bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-400',
  },
};

export function NewsSentimentBadge({ sentiment }: Props) {
  if (!sentiment) return null;

  const config = SENTIMENT_CONFIG[sentiment];
  if (!config) return null;

  return (
    <span className={`px-1.5 py-0.5 text-xs font-medium rounded ${config.className}`}>
      {config.label}
    </span>
  );
}
