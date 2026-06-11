import { describe, it, expect } from 'vitest';
import { render, screen } from '@/test/utils';
import { ZoneStatusChips } from '../ZoneStatusChips';
import type { EntryZoneStatus } from '@/lib/api/types';

const zones: EntryZoneStatus[] = [
  {
    tier: 'Half starter',
    low: '50',
    high: '52',
    status: 'approaching',
    distance_percent: '-1.16',
  },
  {
    tier: 'Aggressive',
    low: null,
    high: '46',
    status: 'above',
    distance_percent: '-12.57',
  },
  {
    tier: 'Taxable add',
    low: '230',
    high: '235',
    status: 'in_zone',
    distance_percent: null,
  },
];

describe('ZoneStatusChips', () => {
  it('renders nothing without zones', () => {
    const { container } = render(<ZoneStatusChips zones={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a chip per zone with its status', () => {
    render(<ZoneStatusChips zones={zones} />);

    expect(screen.getByText('Half starter')).toBeInTheDocument();
    expect(screen.getByText('near')).toBeInTheDocument();
    expect(screen.getByText('above')).toBeInTheDocument();
    expect(screen.getByText('in zone')).toBeInTheDocument();
  });

  it('describes the band in the tooltip, handling open bounds', () => {
    render(<ZoneStatusChips zones={zones} />);

    expect(screen.getByText('Aggressive').parentElement).toHaveAttribute(
      'title',
      expect.stringContaining('≤')
    );
  });
});
