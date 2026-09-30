"use client";

import { formatPrice } from "@/lib/format";
import { BOOK_FORMATS, FORMAT_LABELS, type BookFormat } from "@/lib/formats";

/**
 * Paperback or hardcover, each with its price. A format this book (or set)
 * isn't sold in shows as unavailable rather than disappearing, so the choice
 * reads the same on every book.
 */
export function FormatPicker({
  prices,
  value,
  onChange,
}: {
  /** Price per format; a missing format is not available */
  prices: Partial<Record<BookFormat, number>>;
  value: BookFormat;
  onChange: (format: BookFormat) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Format" className="grid grid-cols-2 gap-2 mb-4">
      {BOOK_FORMATS.map((format) => {
        const price = prices[format];
        const available = price != null;
        const active = value === format;
        return (
          <button
            key={format}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={!available}
            onClick={() => onChange(format)}
            className={`border px-3 py-2.5 text-left transition-colors ${
              active
                ? "border-rust bg-rust-light/40"
                : available
                  ? "border-border hover:border-ink cursor-pointer"
                  : "border-border opacity-50 cursor-not-allowed"
            }`}
          >
            <span className="block font-body text-[11px] tracking-widest uppercase text-ink">
              {FORMAT_LABELS[format]}
            </span>
            <span className="block font-serif text-lg font-semibold text-rust">
              {available ? formatPrice(price) : <span className="text-sm text-muted font-body font-normal">Not available</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
