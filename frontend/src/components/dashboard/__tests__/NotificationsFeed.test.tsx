import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@/test/utils';
import { NotificationsFeed } from '../NotificationsFeed';
import type { Alert, AlertHistory } from '@/lib/api/types';

const mockAlert: Alert = {
  id: 1,
  name: 'AAPL Above $200',
  notes: null,
  equity_id: 1,
  ratio_id: null,
  condition_type: 'above',
  threshold_value: 200,
  comparison_period: null,
  cooldown_minutes: 60,
  is_active: true,
  last_triggered_at: '2026-08-10T15:00:00Z',
  last_checked_value: 205,
  confirm_checks: null,
  consecutive_met_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  target: { type: 'equity', id: 1, symbol: 'AAPL', name: 'Apple Inc.' },
};

const mockHistory: AlertHistory[] = [
  {
    id: 11,
    alert_id: 1,
    triggered_at: '2026-08-10T15:00:00Z',
    triggered_value: 205,
    threshold_value: 200,
    notification_sent: true,
    notification_channel: 'discord',
    notification_error: null,
  },
];

vi.mock('@/lib/hooks/useAlert', () => ({
  useAlerts: () => ({ data: [mockAlert], isLoading: false }),
  useAllAlertHistory: () => ({
    data: mockHistory,
    isLoading: false,
    error: null,
  }),
}));

describe('NotificationsFeed provenance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not label a triggered observation as Current or now', () => {
    render(<NotificationsFeed />);
    expect(screen.queryByText(/^Current:/)).not.toBeInTheDocument();
    expect(screen.getByText(/Triggered: \$205\.00/)).toBeInTheDocument();
  });
});
