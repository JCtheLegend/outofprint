/**
 * Print formats
 *
 * Every book is a perfect-bound paperback, and most are also a casewrap
 * hardcover. The paperback lives in the columns the books table always had
 * (`price_cents`, `cover_pdf_url`, ...); the hardcover in their `hardcover_`
 * counterparts, which are null for a book with no hardcover cover. Everything
 * that prices or prints a book by format goes through here.
 *
 * Client-safe: no server imports.
 */

import type { Book } from "@/lib/supabase";

export type BookFormat = "paperback" | "hardcover";

export const BOOK_FORMATS: BookFormat[] = ["paperback", "hardcover"];

export const DEFAULT_FORMAT: BookFormat = "paperback";

export const FORMAT_LABELS: Record<BookFormat, string> = {
  paperback: "Paperback",
  hardcover: "Hardcover",
};

export function isBookFormat(value: unknown): value is BookFormat {
  return value === "paperback" || value === "hardcover";
}

/** Whether this book can be bought in this format. */
export function hasFormat(book: Book, format: BookFormat): boolean {
  if (format === "paperback") return true;
  // All three, so a hardcover can never fall back to the paperback's SKU or cover
  return (
    book.hardcover_price_cents != null &&
    book.hardcover_cover_pdf_url != null &&
    book.hardcover_pod_package_id != null
  );
}

/** Formats a book is sold in, paperback first. */
export function formatsOf(book: Book): BookFormat[] {
  return BOOK_FORMATS.filter((format) => hasFormat(book, format));
}

/** Formats every one of these books is sold in — what a whole set can be bought as. */
export function commonFormats(books: Book[]): BookFormat[] {
  return BOOK_FORMATS.filter((format) => books.every((book) => hasFormat(book, format)));
}

/** Retail price of one copy. Only meaningful where `hasFormat` is true. */
export function formatPriceCents(book: Book, format: BookFormat): number {
  return format === "hardcover" ? book.hardcover_price_cents ?? 0 : book.price_cents;
}

/** Lulu's print cost of one copy — the wholesale price — or null if unpriced. */
export function formatPrintCostCents(book: Book, format: BookFormat): number | null {
  return format === "hardcover" ? book.hardcover_print_cost_cents : book.print_cost_cents;
}

/** The book's own Lulu SKU for this format; null falls back to the default product. */
export function formatPodPackageId(book: Book, format: BookFormat): string | null {
  return format === "hardcover" ? book.hardcover_pod_package_id : book.pod_package_id;
}

/** Stored Storage URL of the wraparound cover PDF Lulu prints this format from. */
export function formatCoverPdfUrl(book: Book, format: BookFormat): string | null {
  return format === "hardcover" ? book.hardcover_cover_pdf_url : book.cover_pdf_url;
}

/** "Hardcover" suffix for titles — paperback is the default and goes unsaid. */
export function formatSuffix(format: BookFormat): string {
  return format === "hardcover" ? " (Hardcover)" : "";
}

/**
 * How an ordered book is named to its buyer: "Title — Volume III (Hardcover)".
 * Takes the row shape the order routes select, not a whole Book.
 */
export function orderedBookTitle(
  book: { title: string; volume_label: string | null } | undefined,
  format: BookFormat | null | undefined
): string {
  if (!book) return "your book";
  const title = book.volume_label ? `${book.title} — ${book.volume_label}` : book.title;
  return `${title}${formatSuffix(format ?? DEFAULT_FORMAT)}`;
}
