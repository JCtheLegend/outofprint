"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";

/**
 * The first pages of the interior, as the uploader rendered them. A strip of
 * thumbnails opens into a page-at-a-time viewer (arrow keys, Escape to close).
 */
export function LookInside({ pages, title }: { pages: string[]; title: string }) {
  const [open, setOpen] = useState<number | null>(null);

  const close = useCallback(() => setOpen(null), []);
  const step = useCallback(
    (by: number) =>
      setOpen((current) =>
        current === null ? current : Math.min(pages.length - 1, Math.max(0, current + by))
      ),
    [pages.length]
  );

  useEffect(() => {
    if (open === null) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
      if (event.key === "ArrowRight") step(1);
      if (event.key === "ArrowLeft") step(-1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close, step]);

  return (
    <>
      <ul className="flex gap-3 overflow-x-auto pb-3 -mx-1 px-1">
        {pages.map((url, index) => (
          <li key={url} className="shrink-0">
            <button
              type="button"
              onClick={() => setOpen(index)}
              className="block relative w-28 md:w-32 aspect-[2/3] border border-border bg-white hover:border-rust transition-colors cursor-zoom-in"
              aria-label={`Page ${index + 1}`}
            >
              <Image
                src={url}
                alt={`${title}, page ${index + 1}`}
                fill
                loading="lazy"
                className="object-contain"
                sizes="128px"
              />
            </button>
          </li>
        ))}
      </ul>

      {open !== null && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`${title}, page ${open + 1} of ${pages.length}`}
          className="fixed inset-0 z-50 bg-ink/90 flex items-center justify-center p-4"
          onClick={close}
        >
          <div className="relative h-full max-h-[90vh] aspect-[2/3] max-w-full" onClick={(e) => e.stopPropagation()}>
            <Image
              src={pages[open]}
              alt={`${title}, page ${open + 1}`}
              fill
              className="object-contain bg-white"
              sizes="90vh"
            />
          </div>

          <button
            type="button"
            onClick={close}
            className="absolute top-4 right-4 text-cream text-sm tracking-widest uppercase cursor-pointer"
          >
            Close
          </button>
          <p className="absolute bottom-4 left-0 right-0 text-center text-cream/80 text-xs tracking-widest">
            {open + 1} / {pages.length}
          </p>
          {open > 0 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                step(-1);
              }}
              aria-label="Previous page"
              className="absolute left-2 md:left-6 top-1/2 -translate-y-1/2 text-cream text-4xl px-3 py-2 cursor-pointer"
            >
              ‹
            </button>
          )}
          {open < pages.length - 1 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                step(1);
              }}
              aria-label="Next page"
              className="absolute right-2 md:right-6 top-1/2 -translate-y-1/2 text-cream text-4xl px-3 py-2 cursor-pointer"
            >
              ›
            </button>
          )}
        </div>
      )}
    </>
  );
}
