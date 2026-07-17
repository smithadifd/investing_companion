'use client';

interface Props {
  sentiment: 'positive' | 'negative' | 'neutral' | null;
}

// Each sentiment carries a shape glyph in addition to its color and text label,
// so the status never depends on color alone.
const SENTIMENT_CONFIG = {
  positive: {
    label: 'Positive',
    glyph: '▲',
    className: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400',
  },
  negative: {
    label: 'Negative',
    glyph: '▼',
    className: 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400',
  },
  neutral: {
    label: 'Neutral',
    glyph: '＝',
    className: 'bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-400',
  },
};

export function NewsSentimentBadge({ sentiment }: Props) {
  if (!sentiment) return null;

  const config = SENTIMENT_CONFIG[sentiment];
  if (!config) return null;

  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-xs font-medium rounded ${config.className}`}
      aria-label={`${config.label} sentiment`}
    >
      <span aria-hidden="true">{config.glyph}</span>
      <span>{config.label}</span>
    </span>
  );
}
