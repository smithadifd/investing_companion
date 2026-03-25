'use client';

import { DEMO_MODE, DEMO_REPO_URL } from '@/lib/demo';
import { ExternalLink } from 'lucide-react';

export function DemoBanner() {
  if (!DEMO_MODE) return null;

  return (
    <div className="bg-amber-600 text-white text-sm text-center py-1.5 px-4 flex items-center justify-center gap-2 shrink-0">
      <span>Demo Mode — data resets weekly.</span>
      <a
        href={DEMO_REPO_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-amber-100"
      >
        View source on GitHub <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  );
}
