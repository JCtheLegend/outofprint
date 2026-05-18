"use client";

import { useState } from "react";
import type { Book } from "@/lib/supabase";
import { BookCard } from "@/components/ui/BookCard";

export function CatalogClient({
  books,
  genres,
}: {
  books: Book[];
  genres: string[];
}) {
  const [activeGenre, setActiveGenre] = useState<string | null>(null);

  const filtered = activeGenre
    ? books.filter((b) => b.genre === activeGenre)
    : books;

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
          {filtered.map((book) => (
            <BookCard key={book.id} book={book} />
          ))}
        </div>
      )}
    </>
  );
}
