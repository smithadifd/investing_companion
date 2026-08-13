'use client';

import { useRef, useState } from 'react';
import { Loader2, Upload } from 'lucide-react';
import { useImportBrokerCsv } from '@/lib/hooks/useReconciliation';
import { ApiError } from '@/lib/api/client';
import type { CsvImportResult } from '@/lib/api/types';

interface BrokerCsvUploadProps {
  accountId: number | null;
  /** Compact rendering for use inside the history-gap banner. */
  compact?: boolean;
}

/** Mirrors MAX_CSV_BYTES in backend/app/services/broker_csv.py. */
const MAX_CSV_BYTES = 5_000_000;

function fmtDate(value: string | null): string {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

/**
 * Upload a broker transaction CSV.
 *
 * This is the ONLY way to get activity older than Schwab's 60-day API
 * transaction horizon into the ledger comparison — the pull physically cannot
 * reach it. The file is read in the browser and sent as text, so nothing but
 * the CSV's own contents leaves the page.
 */
export function BrokerCsvUpload({ accountId, compact }: BrokerCsvUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const importCsv = useImportBrokerCsv();
  const [result, setResult] = useState<CsvImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFile = async (file: File | undefined) => {
    if (!file || accountId === null) return;
    setError(null);
    setResult(null);
    // Checked BEFORE reading: file.text() pulls the whole thing into a JS
    // string, so a huge (or wrong) file would hang the tab long before the
    // server got a chance to return its 422.
    if (file.size > MAX_CSV_BYTES) {
      setError(
        `That file is ${(file.size / 1_000_000).toFixed(1)}MB — the limit is ` +
          `${MAX_CSV_BYTES / 1_000_000}MB. Export a narrower date range.`
      );
      if (inputRef.current) inputRef.current.value = '';
      return;
    }
    try {
      const content = await file.text();
      const imported = await importCsv.mutateAsync({
        accountId,
        content,
        filename: file.name,
      });
      setResult(imported);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : 'Could not read that file. Export transactions as CSV and try again.'
      );
    } finally {
      // Allow re-selecting the same file (a corrected re-export).
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          data-testid="broker-csv-input"
          aria-label="Broker transaction CSV"
          onChange={(e) => handleFile(e.target.files?.[0])}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={importCsv.isPending || accountId === null}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-neutral-300 dark:border-neutral-600 hover:bg-neutral-100 dark:hover:bg-neutral-700 disabled:opacity-50 text-sm font-medium text-neutral-700 dark:text-neutral-200 transition-colors"
        >
          {importCsv.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
          Upload broker CSV
        </button>
        {!compact && (
          <span className="text-xs text-neutral-500">
            Schwab: History → Transactions → Export
          </span>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="text-sm text-red-600 dark:text-red-300"
          data-testid="csv-upload-error"
        >
          {error}
        </p>
      )}

      {result && (
        <div
          className="text-sm text-emerald-700 dark:text-emerald-300"
          data-testid="csv-upload-result"
        >
          Recovered {result.imported_count} transaction
          {result.imported_count === 1 ? '' : 's'}
          {result.earliest_occurred_at && result.latest_occurred_at && (
            <>
              {' '}
              from {fmtDate(result.earliest_occurred_at)} to{' '}
              {fmtDate(result.latest_occurred_at)}
            </>
          )}
          {result.skipped.length > 0 && (
            <>
              {' '}
              · {result.skipped.length} row
              {result.skipped.length === 1 ? '' : 's'} skipped (
              {result.skipped[0].reason.replace(/_/g, ' ')}
              {result.skipped.length > 1 ? ', …' : ''})
            </>
          )}
          .
        </div>
      )}
    </div>
  );
}
