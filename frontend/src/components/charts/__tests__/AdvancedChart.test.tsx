import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { LineSeries, CandlestickSeries, HistogramSeries, createChart } from 'lightweight-charts';
import { render } from '@/test/utils';
import { AdvancedChart } from '../AdvancedChart';
import type { OHLCVData } from '@/lib/api/types';

vi.mock('lightweight-charts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('lightweight-charts')>();
  return {
    ...actual,
    createChart: vi.fn(),
  };
});

interface MockChartHandle {
  addSeries: Mock;
  timeScale: Mock;
  applyOptions: Mock;
  remove: Mock;
}

interface MockSeriesHandle {
  setData: Mock;
  priceScale: Mock;
}

describe('AdvancedChart series construction', () => {
  const sampleData: OHLCVData[] = [
    {
      timestamp: '2026-09-01T10:00:00',
      open: '150.00',
      high: '155.00',
      low: '149.00',
      close: '154.00',
      volume: 10000,
    },
  ];

  let mockChart: MockChartHandle;
  let mockSeries: MockSeriesHandle;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSeries = {
      setData: vi.fn(),
      priceScale: vi.fn().mockReturnValue({ applyOptions: vi.fn() }),
    };
    mockChart = {
      addSeries: vi.fn().mockReturnValue(mockSeries as unknown as ISeriesApi<'Line'>),
      timeScale: vi.fn().mockReturnValue({ fitContent: vi.fn() }),
      applyOptions: vi.fn(),
      remove: vi.fn(),
    };
    vi.mocked(createChart).mockReturnValue(mockChart as unknown as IChartApi);
  });

  it('adds LineSeries and HistogramSeries when chartType is line', () => {
    render(<AdvancedChart data={sampleData} chartType="line" showRSI={false} showMACD={false} />);

    expect(mockChart.addSeries).toHaveBeenCalledWith(
      LineSeries,
      expect.objectContaining({ color: '#3b82f6', lineWidth: 2 })
    );
    expect(mockChart.addSeries).toHaveBeenCalledWith(
      HistogramSeries,
      expect.objectContaining({ priceScaleId: 'volume' })
    );
    expect(mockChart.addSeries).not.toHaveBeenCalledWith(CandlestickSeries, expect.anything());
  });

  it('adds CandlestickSeries and HistogramSeries when chartType is candlestick', () => {
    render(<AdvancedChart data={sampleData} chartType="candlestick" showRSI={false} showMACD={false} />);

    expect(mockChart.addSeries).toHaveBeenCalledWith(
      CandlestickSeries,
      expect.objectContaining({ upColor: '#22c55e', downColor: '#ef4444' })
    );
    expect(mockChart.addSeries).toHaveBeenCalledWith(
      HistogramSeries,
      expect.objectContaining({ priceScaleId: 'volume' })
    );
    expect(mockChart.addSeries).not.toHaveBeenCalledWith(LineSeries, expect.anything());
  });
});
