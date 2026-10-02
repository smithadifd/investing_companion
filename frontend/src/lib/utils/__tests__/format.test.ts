import { describe, expect, it } from 'vitest';
import {
  formatCurrency,
  formatDate,
  formatLargeNumber,
  formatNumber,
  formatPercent,
  formatRatio,
  formatTimestamp,
} from '../format';

process.env.TZ = 'America/New_York';

describe('number formatters', () => {
  it('converts decimal strings for every numeric formatter', () => {
    expect(formatCurrency('1234.5')).toBe('$1,234.50');
    expect(formatPercent('12.5')).toBe('+12.50%');
    expect(formatNumber('1234.5')).toBe('1,234.5');
    expect(formatLargeNumber('1234.5')).toBe('1.23K');
    expect(formatRatio('12.5')).toBe('12.50');
  });

  it('shows a placeholder for null, undefined, and invalid numeric strings', () => {
    const formatters = [
      formatCurrency,
      formatPercent,
      formatNumber,
      formatLargeNumber,
      formatRatio,
    ];
    for (const formatter of formatters) {
      expect(formatter(null)).toBe('--');
      expect(formatter(undefined)).toBe('--');
      expect(formatter('invalid')).toBe('--');
    }
  });

  it('keeps negative signs across numeric formats', () => {
    expect(formatCurrency('-1234.5')).toBe('-$1,234.50');
    expect(formatPercent('-12.5')).toBe('-12.50%');
    expect(formatNumber('-1234.5')).toBe('-1,234.5');
    expect(formatLargeNumber('-1234.5')).toBe('-1.23K');
    expect(formatRatio('-12.5')).toBe('-12.50');
  });

  it('abbreviates at each magnitude boundary, including negative values', () => {
    expect(formatLargeNumber(999)).toBe('999');
    expect(formatLargeNumber(1_000)).toBe('1.00K');
    expect(formatLargeNumber(999_999)).toBe('1000.00K');
    expect(formatLargeNumber(1_000_000)).toBe('1.00M');
    expect(formatLargeNumber(1_000_000_000)).toBe('1.00B');
    expect(formatLargeNumber(1_000_000_000_000)).toBe('1.00T');
    expect(formatLargeNumber(-1_000_000)).toBe('-1.00M');
  });
});

describe('date formatters', () => {
  it('formats a date for display', () => {
    expect(formatDate('2026-10-01T12:00:00Z')).toBe('Oct 1, 2026');
  });

  it('treats naive timestamps as UTC', () => {
    expect(formatTimestamp('2026-10-01T01:30:00')).toBe('Sep 30, 9:30 PM');
  });

  it('preserves Z and offset timestamps as instants', () => {
    expect(formatTimestamp('2026-10-01T01:30:00Z')).toBe('Sep 30, 9:30 PM');
    expect(formatTimestamp('2026-09-30T21:30:00-04:00')).toBe('Sep 30, 9:30 PM');
  });

  it('returns an invalid timestamp unchanged', () => {
    expect(formatTimestamp('not-a-date')).toBe('not-a-date');
  });
});
