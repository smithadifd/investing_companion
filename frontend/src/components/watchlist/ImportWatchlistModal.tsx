'use client';

import { useState, useRef } from 'react';
import { Loader2, FileJson } from 'lucide-react';
import { useImportWatchlist } from '@/lib/hooks/useWatchlist';
import { Modal } from '@/components/ui/Modal';
import type { WatchlistImport } from '@/lib/api/types';

interface ImportWatchlistModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

export function ImportWatchlistModal({
  onClose,
  onSuccess,
}: ImportWatchlistModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<WatchlistImport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const importMutation = useImportWatchlist();

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (!selectedFile) return;

    setFile(selectedFile);
    setError(null);

    try {
      const text = await selectedFile.text();
      const data = JSON.parse(text);

      // Validate structure
      if (!data.name || !Array.isArray(data.items)) {
        throw new Error('Invalid watchlist format');
      }

      // Transform to import format
      const importData: WatchlistImport = {
        name: data.name,
        description: data.description,
        items: data.items.map((item: { symbol: string; notes?: string; target_price?: number; thesis?: string }) => ({
          symbol: item.symbol,
          notes: item.notes,
          target_price: item.target_price,
          thesis: item.thesis,
        })),
      };

      setPreview(importData);
    } catch (err) {
      setError('Invalid JSON file. Please upload a valid watchlist export.');
      setPreview(null);
    }
  };

  const handleImport = async () => {
    if (!preview) return;

    try {
      await importMutation.mutateAsync(preview);
      onSuccess();
      onClose();
    } catch (err) {
      setError('Failed to import watchlist. Please try again.');
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile && droppedFile.type === 'application/json') {
      const input = fileInputRef.current;
      if (input) {
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(droppedFile);
        input.files = dataTransfer.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  };

  return (
    <Modal onClose={onClose} title="Import Watchlist">
      <div className="p-4 space-y-4">
        {/* Drop zone */}
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          className="border-2 border-dashed border-neutral-300 dark:border-neutral-600 rounded-lg p-8 text-center hover:border-blue-500/50 transition-colors"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            onChange={handleFileSelect}
            className="hidden"
            id="file-upload"
          />
          <label
            htmlFor="file-upload"
            className="cursor-pointer flex flex-col items-center gap-2"
          >
            <FileJson className="h-10 w-10 text-neutral-500 dark:text-neutral-400" />
            <span className="text-sm text-neutral-500 dark:text-neutral-400">
              {file ? file.name : 'Drop a JSON file or click to browse'}
            </span>
          </label>
        </div>

        {/* Error */}
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm text-red-500">
            {error}
          </div>
        )}

        {/* Preview */}
        {preview && (
          <div className="p-4 bg-neutral-100 dark:bg-neutral-700 rounded-lg">
            <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 mb-2">
              {preview.name}
            </h3>
            {preview.description && (
              <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-2">
                {preview.description}
              </p>
            )}
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              {preview.items.length} equities:{' '}
              {preview.items.map((i) => i.symbol).join(', ')}
            </p>
          </div>
        )}
      </div>

      <div className="flex justify-end gap-3 p-4 border-t border-neutral-200 dark:border-neutral-700">
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleImport}
          disabled={!preview || importMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white rounded-lg font-medium transition-colors"
        >
          {importMutation.isPending && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          {importMutation.isPending ? 'Importing...' : 'Import'}
        </button>
      </div>
    </Modal>
  );
}
