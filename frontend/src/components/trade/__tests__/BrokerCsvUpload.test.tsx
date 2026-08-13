import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@/test/utils';
import userEvent from '@testing-library/user-event';
import { BrokerCsvUpload } from '../BrokerCsvUpload';

const mockImportCsv = vi.fn();
let pending = false;

vi.mock('@/lib/hooks/useReconciliation', () => ({
  useImportBrokerCsv: () => ({
    mutateAsync: mockImportCsv,
    isPending: pending,
  }),
}));

vi.mock('@/lib/api/client', () => {
  class ApiError extends Error {
    code: string;
    status: number;
    constructor(message: string, code: string, status: number) {
      super(message);
      this.code = code;
      this.status = status;
    }
  }
  return { ApiError };
});

import { ApiError } from '@/lib/api/client';

const CSV = 'Date,Action,Symbol,Quantity,Price\n08/01/2026,Buy,AAPL,10,150\n';

function csvFile(name = 'Transactions.csv') {
  return new File([CSV], name, { type: 'text/csv' });
}

describe('BrokerCsvUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pending = false;
  });

  it('sends the file contents and name for the given account', async () => {
    mockImportCsv.mockResolvedValue({
      account_id: 1,
      run: {},
      imported_count: 12,
      skipped: [],
      earliest_occurred_at: '2024-01-02T00:00:00Z',
      latest_occurred_at: '2026-08-01T00:00:00Z',
    });
    render(<BrokerCsvUpload accountId={1} />);

    await userEvent.upload(
      screen.getByTestId('broker-csv-input'),
      csvFile('Transactions_1234.csv')
    );

    await waitFor(() =>
      expect(mockImportCsv).toHaveBeenCalledWith({
        accountId: 1,
        content: CSV,
        filename: 'Transactions_1234.csv',
      })
    );
  });

  it('reports how much history was recovered', async () => {
    mockImportCsv.mockResolvedValue({
      account_id: 1,
      run: {},
      imported_count: 12,
      skipped: [{ row_number: 3, reason: 'unparseable_date', detail: null }],
      earliest_occurred_at: '2024-01-02T00:00:00Z',
      latest_occurred_at: '2026-08-01T00:00:00Z',
    });
    render(<BrokerCsvUpload accountId={1} />);

    await userEvent.upload(screen.getByTestId('broker-csv-input'), csvFile());

    await waitFor(() =>
      expect(screen.getByTestId('csv-upload-result')).toHaveTextContent(
        /Recovered 12 transactions/i
      )
    );
    // Skipped rows are surfaced, never hidden.
    expect(screen.getByTestId('csv-upload-result')).toHaveTextContent(
      /1 row skipped \(unparseable date\)/i
    );
  });

  it('surfaces the server reason when the file is rejected', async () => {
    mockImportCsv.mockRejectedValue(
      new ApiError('Could not find a transaction header row.', 'X', 422)
    );
    render(<BrokerCsvUpload accountId={1} />);

    await userEvent.upload(screen.getByTestId('broker-csv-input'), csvFile());

    await waitFor(() =>
      expect(screen.getByTestId('csv-upload-error')).toHaveTextContent(
        /transaction header row/i
      )
    );
  });

  it('is disabled without an account', () => {
    render(<BrokerCsvUpload accountId={null} />);
    expect(
      screen.getByRole('button', { name: /upload broker csv/i })
    ).toBeDisabled();
  });
});

describe('BrokerCsvUpload size guard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pending = false;
  });

  it('refuses an oversized file before reading it', async () => {
    render(<BrokerCsvUpload accountId={1} />);
    const big = new File(['x'], 'huge.csv', { type: 'text/csv' });
    // File.size is read-only; define it rather than allocating 6MB.
    Object.defineProperty(big, 'size', { value: 6_000_000 });

    await userEvent.upload(screen.getByTestId('broker-csv-input'), big);

    await waitFor(() =>
      expect(screen.getByTestId('csv-upload-error')).toHaveTextContent(/limit/i)
    );
    // Never read, never sent — the tab would have hung otherwise.
    expect(mockImportCsv).not.toHaveBeenCalled();
  });
});
