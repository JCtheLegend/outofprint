import Link from "next/link";
import Image from "next/image";
import type { Book } from "@/lib/supabase";
import { formatPrice } from "@/lib/format";

// Deterministic cover colors from book id
const COVER_PALETTES = [
  { bg: "#2d3a2e", text: "#e8dfc0", sub: "#a89e7a" },
  { bg: "#3a2a1e", text: "#f0e4c8", sub: "#b09060" },
  { bg: "#1e2a3a", text: "#c8d8f0", sub: "#7090b0" },
  { bg: "#2a1e3a", text: "#dcc8f0", sub: "#9070b0" },
  { bg: "#1e3a2a", text: "#c8f0dc", sub: "#60b080" },
  { bg: "#3a1e2a", text: "#f0c8d8", sub: "#b06080" },
];

function palette(id: string) {
  const i = id.charCodeAt(0) % COVER_PALETTES.length;
  return COVER_PALETTES[i];
}

export function BookCard({ book }: { book: Book }) {
  const p = palette(book.id);
  return (
    <Link href={`/catalog/${book.id}`} className="group">
      <div
        className="relative w-full aspect-[2/3] overflow-hidden mb-3 book-cover-spine"
        style={{ backgroundColor: p.bg }}
      >
        {book.cover_url ? (
          <Image
            src={book.cover_url}
            alt={book.title}
            fill
            className="object-cover"
            sizes="(max-width: 768px) 50vw, 33vw"
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-4">
            <p
              className="font-serif text-sm font-semibold text-center mb-1 leading-snug"
              style={{ color: p.text }}
            >
              {book.title}
            </p>
            <p
              className="font-body italic text-[10px] text-center"
              style={{ color: p.sub }}
            >
              {book.author}
            </p>
          </div>
        )}
      </div>
      <h3 className="font-serif text-sm font-semibold leading-snug mb-0.5 group-hover:text-rust transition-colors">
        {book.title}
      </h3>
      <p className="text-xs text-muted italic mb-1">
        {book.author} · {book.year}
      </p>
      <p className="text-sm font-semibold text-rust">{formatPrice(book.price_cents)}</p>
    </Link>
  );
}
