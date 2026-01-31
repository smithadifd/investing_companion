'use client';

import { useEffect, useRef } from 'react';
import { createChart, IChartApi, ColorType, Time } from 'lightweight-charts';
import type { OHLCVData } from '@/lib/api/types';

interface PriceChartProps {
  data: OHLCVData[];
  height?: number;
}

export function PriceChart({ data, height = 400 }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    // Create chart
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#333333',
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: '#e0e0e0',
      },
      timeScale: {
        borderColor: '#e0e0e0',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Add candlestick series
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      wickUpColor: '#22c55e',
    });

    // Convert data to chart format
    const chartData = data.map((item) => ({
      time: item.timestamp.split('T')[0] as Time,
      open: Number(item.open),
      high: Number(item.high),
      low: Number(item.low),
      close: Number(item.close),
    }));

    candlestickSeries.setData(chartData);

    // Add volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    const volumeData = data
      .filter((item) => item.volume != null)
      .map((item) => ({
        time: item.timestamp.split('T')[0] as Time,
        value: item.volume as number,
        color: Number(item.close) >= Number(item.open) ? '#22c55e80' : '#ef444480',
      }));

    volumeSeries.setData(volumeData);

    // Fit content
    chart.timeScale().fitContent();

    chartRef.current = chart;

    // Handle resize
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, height]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 rounded-lg"
        style={{ height }}
      >
        <span className="text-gray-500">No data available</span>
      </div>
    );
  }

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />;
}
