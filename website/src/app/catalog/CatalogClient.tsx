"use client";

import { useState } from "react";
import type { CatalogEntry } from "@/lib/sets";
import { BookCard } from "@/components/ui/BookCard";
import { SetCard } from "@/components/ui/SetCard";

export function CatalogClient({
  entries,
  genres,
}: {
  entries: CatalogEntry[];
  genres: string[];
}) {
  const [activeGenre, setActiveGenre] = useState<string | null>(null);

  const filtered = activeGenre
    ? entries.filter((e) => e.genre === activeGenre)
    : entries;

  return (
    <>
      {/* Genre filters */}
      <div className="flex flex-wrap gap-2 mb-10">
        <button
          onClick={() => setActiveGenre(null)}
          className={`font-body text-[11px] tracking-widest uppercase px-4 py-1.5 border transition-colors ${
            activeGenre === null
              ? "bg-ink text-cream border-ink"
              : "bg-transparent text-muted border-border hover:border-ink hover:text-ink"
          }`}
        >
          All
        </button>
        {genres.map((g) => (
          <button
            key={g}
            onClick={() => setActiveGenre(g)}
            className={`font-body text-[11px] tracking-widest uppercase px-4 py-1.5 border transition-colors ${
              activeGenre === g
                ? "bg-ink text-cream border-ink"
                : "bg-transparent text-muted border-border hover:border-ink hover:text-ink"
            }`}
          >
            {g}
          </button>
        ))}
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <p className="text-muted text-sm">No books found in this genre yet.</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
          {filtered.map((entry) =>
            entry.kind === "set" ? (
              <SetCard key={entry.key} set={entry.set} />
            ) : (
              <BookCard key={entry.key} book={entry.book} />
            )
          )}
        </div>
      )}
    </>
  );
}
