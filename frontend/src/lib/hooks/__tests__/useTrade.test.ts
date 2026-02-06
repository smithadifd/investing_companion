import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import {
  useTrades,
  useTrade,
  useCreateTrade,
  useUpdateTrade,
  useDeleteTrade,
  usePortfolio,
  usePerformance,
  useTradePairs,
  usePosition,
  useCalculatePositionSize,
} from '../useTrade';
import type { Trade, TradeCreate, PortfolioSummary } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    getTrades: vi.fn(),
    getTrade: vi.fn(),
    createTrade: vi.fn(),
    updateTrade: vi.fn(),
    deleteTrade: vi.fn(),
    getPortfolio: vi.fn(),
    getPerformance: vi.fn(),
    getTradePairs: vi.fn(),
    getPosition: vi.fn(),
    calculatePositionSize: vi.fn(),
  },
}));

import { api } from '../../api/client';

const mockedApi = vi.mocked(api);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

const mockTrade: Trade = {
  id: 1,
  user_id: 'user-1',
  equity_id: 1,
  trade_type: 'buy',
  quantity: 100,
  price: 150.0,
  fees: 0,
  executed_at: '2026-01-15T10:00:00Z',
  notes: null,
  watchlist_item_id: null,
  equity: { id: 1, symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', sector: 'Technology' },
  total_value: 15000,
  total_cost: 15000,
  created_at: '2026-01-15T10:00:00Z',
  updated_at: '2026-01-15T10:00:00Z',
};

describe('useTrades', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches trades with no filters', async () => {
    mockedApi.getTrades.mockResolvedValue({ trades: [mockTrade], total: 1 });
    const { result } = renderHook(() => useTrades(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTrades).toHaveBeenCalledWith(undefined);
    expect(result.current.data).toEqual({ trades: [mockTrade], total: 1 });
  });

  it('passes filter params', async () => {
    mockedApi.getTrades.mockResolvedValue({ trades: [], total: 0 });
    const params = { equity_id: 1, trade_type: 'buy' as const, limit: 10 };
    const { result } = renderHook(() => useTrades(params), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTrades).toHaveBeenCalledWith(params);
  });
});

describe('useTrade', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches single trade', async () => {
    mockedApi.getTrade.mockResolvedValue(mockTrade);
    const { result } = renderHook(() => useTrade(1), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTrade).toHaveBeenCalledWith(1);
  });

  it('does not fetch when id is falsy', () => {
    renderHook(() => useTrade(0), { wrapper: createWrapper() });
    expect(mockedApi.getTrade).not.toHaveBeenCalled();
  });
});

describe('useCreateTrade', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls createTrade and invalidates related queries', async () => {
    const newTrade: TradeCreate = {
      symbol: 'AAPL',
      trade_type: 'buy',
      quantity: 50,
      price: 155.0,
      fees: 0,
      executed_at: '2026-01-20T10:00:00Z',
    };
    mockedApi.createTrade.mockResolvedValue({ ...mockTrade, ...newTrade, id: 2 });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);

    const { result } = renderHook(() => useCreateTrade(), { wrapper });

    result.current.mutate(newTrade);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockedApi.createTrade).toHaveBeenCalledWith(newTrade);
    // Verify it invalidates trades, portfolio, performance, and trade-pairs
    const invalidatedKeys = invalidateSpy.mock.calls.map((c) => c[0]?.queryKey);
    expect(invalidatedKeys).toContainEqual(['trades']);
    expect(invalidatedKeys).toContainEqual(['portfolio']);
    expect(invalidatedKeys).toContainEqual(['performance']);
    expect(invalidatedKeys).toContainEqual(['trade-pairs']);
  });
});

describe('useUpdateTrade', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls updateTrade with id and data', async () => {
    mockedApi.updateTrade.mockResolvedValue({ ...mockTrade, quantity: 200 });

    const { result } = renderHook(() => useUpdateTrade(), { wrapper: createWrapper() });

    result.current.mutate({ id: 1, data: { quantity: 200 } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.updateTrade).toHaveBeenCalledWith(1, { quantity: 200 });
  });
});

describe('useDeleteTrade', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls deleteTrade with id', async () => {
    mockedApi.deleteTrade.mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeleteTrade(), { wrapper: createWrapper() });

    result.current.mutate(1);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.deleteTrade).toHaveBeenCalledWith(1);
  });
});

describe('usePortfolio', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches portfolio summary', async () => {
    const mockPortfolio: PortfolioSummary = {
      total_invested: 50000,
      current_value: 55000,
      total_unrealized_pnl: 5000,
      total_realized_pnl: 2000,
      positions: [],
      position_count: 3,
      total_trades: 10,
    };
    mockedApi.getPortfolio.mockResolvedValue(mockPortfolio);

    const { result } = renderHook(() => usePortfolio(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockPortfolio);
  });
});

describe('usePerformance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes date range params', async () => {
    mockedApi.getPerformance.mockResolvedValue({
      metrics: {} as any,
      by_sector: [],
      by_equity: [],
      period_start: '2026-01-01',
      period_end: '2026-01-31',
    });

    const { result } = renderHook(
      () => usePerformance('2026-01-01', '2026-01-31'),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getPerformance).toHaveBeenCalledWith('2026-01-01', '2026-01-31');
  });
});

describe('useTradePairs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches trade pairs with params', async () => {
    mockedApi.getTradePairs.mockResolvedValue([]);

    const { result } = renderHook(
      () => useTradePairs(1, 50),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTradePairs).toHaveBeenCalledWith(1, 50);
  });
});

describe('usePosition', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches position for equity', async () => {
    mockedApi.getPosition.mockResolvedValue({
      equity_id: 1,
      equity: mockTrade.equity,
      quantity: 100,
      avg_cost_basis: 150,
      total_cost: 15000,
      current_price: 155,
      current_value: 15500,
      unrealized_pnl: 500,
      unrealized_pnl_percent: 3.33,
      realized_pnl: 0,
      first_trade_at: '2026-01-15T10:00:00Z',
      last_trade_at: '2026-01-15T10:00:00Z',
    });

    const { result } = renderHook(() => usePosition(1), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getPosition).toHaveBeenCalledWith(1);
  });

  it('does not fetch when equityId is falsy', () => {
    renderHook(() => usePosition(0), { wrapper: createWrapper() });
    expect(mockedApi.getPosition).not.toHaveBeenCalled();
  });
});

describe('useCalculatePositionSize', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls calculatePositionSize with request data', async () => {
    const request = {
      account_size: 100000,
      risk_percent: 2,
      entry_price: 150,
      stop_loss: 145,
    };
    const response = {
      shares: 266,
      position_value: 39900,
      risk_amount: 2000,
      risk_per_share: 5,
      method: 'fixed_percent',
      notes: null,
    };
    mockedApi.calculatePositionSize.mockResolvedValue(response);

    const { result } = renderHook(() => useCalculatePositionSize(), { wrapper: createWrapper() });

    result.current.mutate(request);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.calculatePositionSize).toHaveBeenCalledWith(request);
    expect(result.current.data).toEqual(response);
  });
});
