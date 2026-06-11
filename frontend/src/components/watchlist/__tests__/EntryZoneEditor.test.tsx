import { describe, it, expect, vi } from 'vitest';
import { render, screen, userEvent } from '@/test/utils';
import {
  EntryZoneEditor,
  validateZoneDrafts,
  zoneDraftsToApi,
  type ZoneDraft,
} from '../EntryZoneEditor';

const EQT_DRAFTS: ZoneDraft[] = [
  { tier: 'Half starter', low: '50', high: '52' },
  { tier: 'Full add', low: '47', high: '48' },
  { tier: 'Aggressive', low: '', high: '46' },
];

describe('EntryZoneEditor', () => {
  it('renders a row per zone with bounds', () => {
    render(<EntryZoneEditor zones={EQT_DRAFTS} onChange={vi.fn()} />);

    expect(screen.getByDisplayValue('Half starter')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Aggressive')).toBeInTheDocument();
    expect(screen.getByLabelText('Zone 3 low bound')).toHaveValue(null);
    expect(screen.getByLabelText('Zone 3 high bound')).toHaveValue(46);
  });

  it('adds an empty row', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<EntryZoneEditor zones={EQT_DRAFTS} onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: /Add zone/i }));

    expect(onChange).toHaveBeenCalledWith([
      ...EQT_DRAFTS,
      { tier: '', low: '', high: '' },
    ]);
  });

  it('removes a row', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<EntryZoneEditor zones={EQT_DRAFTS} onChange={onChange} />);

    await user.click(screen.getAllByTitle('Remove zone')[1]);

    expect(onChange).toHaveBeenCalledWith([EQT_DRAFTS[0], EQT_DRAFTS[2]]);
  });

  it('hides the add button at the zone cap', () => {
    const many: ZoneDraft[] = Array.from({ length: 8 }, (_, i) => ({
      tier: `t${i}`,
      low: String(i),
      high: String(i + 1),
    }));
    render(<EntryZoneEditor zones={many} onChange={vi.fn()} />);

    expect(screen.queryByRole('button', { name: /Add zone/i })).toBeNull();
  });
});

describe('validateZoneDrafts', () => {
  it('accepts valid zones including one-bound tiers', () => {
    expect(validateZoneDrafts(EQT_DRAFTS)).toBeNull();
  });

  it('ignores fully empty rows', () => {
    expect(validateZoneDrafts([{ tier: '', low: '', high: '' }])).toBeNull();
  });

  it('requires a tier name', () => {
    expect(validateZoneDrafts([{ tier: '', low: '50', high: '52' }])).toMatch(
      /tier name/
    );
  });

  it('requires at least one bound', () => {
    expect(validateZoneDrafts([{ tier: 'x', low: '', high: '' }])).toMatch(
      /at least one bound/
    );
  });

  it('rejects low >= high', () => {
    expect(validateZoneDrafts([{ tier: 'x', low: '52', high: '50' }])).toMatch(
      /low must be less than high/
    );
  });

  it('rejects duplicate tier names', () => {
    expect(
      validateZoneDrafts([
        { tier: 'x', low: '50', high: '52' },
        { tier: ' X ', low: '40', high: '42' },
      ])
    ).toMatch(/Duplicate/);
  });
});

describe('zoneDraftsToApi', () => {
  it('converts bounds to numbers and empty strings to null', () => {
    expect(zoneDraftsToApi(EQT_DRAFTS)).toEqual([
      { tier: 'Half starter', low: 50, high: 52 },
      { tier: 'Full add', low: 47, high: 48 },
      { tier: 'Aggressive', low: null, high: 46 },
    ]);
  });

  it('drops empty rows', () => {
    expect(zoneDraftsToApi([{ tier: '', low: '', high: '' }])).toEqual([]);
  });
});
