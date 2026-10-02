import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { LineSeries, createChart } from 'lightweight-charts';
import { render } from '@/test/utils';
import { RatioChart } from '../RatioChart';
import type { Ratio } from '@/lib/api/types';

vi.mock('lightweight-charts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('lightweight-charts')>();
  return {
    ...actual,
    createChart: vi.fn(),
  };
});

vi.mock('@/lib/hooks/useRatio', () => ({
  useRatioHistory: vi.fn().mockReturnValue({
    data: {
      ratio: {
        id: '1',
        name: 'Gold / Silver',
        numerator_symbol: 'GLD',
        denominator_symbol: 'SLV',
      },
      period: '1y',
      current_value: 12.5,
      change_1d: 0.1,
      change_1w: 0.5,
      change_1m: 1.2,
      history: [
        {
          timestamp: '2026-09-01T00:00:00',
          ratio_value: 12.2,
          numerator_price: 122,
          denominator_price: 10,
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
}));

interface MockChartHandle {
  addSeries: Mock;
  timeScale: Mock;
  applyOptions: Mock;
  remove: Mock;
}

interface MockSeriesHandle {
  setData: Mock;
  createPriceLine: Mock;
}

describe('RatioChart series construction', () => {
  const sampleRatio: Ratio = {
    id: 1,
    name: 'Gold / Silver',
    description: null,
    category: 'Commodities',
    numerator_symbol: 'GLD',
    denominator_symbol: 'SLV',
    is_system: false,
    is_favorite: false,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
  };

  let mockChart: MockChartHandle;
  let mockSeries: MockSeriesHandle;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSeries = {
      setData: vi.fn(),
      createPriceLine: vi.fn(),
    };
    mockChart = {
      addSeries: vi.fn().mockReturnValue(mockSeries as unknown as ISeriesApi<'Line'>),
      timeScale: vi.fn().mockReturnValue({ fitContent: vi.fn() }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
    };
    vi.mocked(createChart).mockReturnValue(mockChart as unknown as IChartApi);
  });

  it('constructs ratio line using addSeries(LineSeries, ...)', () => {
    render(<RatioChart ratio={sampleRatio} />);

    expect(mockChart.addSeries).toHaveBeenCalledWith(
      LineSeries,
      expect.objectContaining({
        color: '#3b82f6',
        lineWidth: 2,
      })
    );
  });
});
