import type { PostgrestError } from "@supabase/supabase-js";
import { supabase, type Book, type BookSet, type BookSetWithVolumes } from "@/lib/supabase";

/** PostgREST's code for "that table isn't in the schema cache". */
const TABLE_NOT_FOUND = "PGRST205";

/**
 * Sets are additive: a project whose database predates them still serves the
 * rest of the catalog, so a missing `book_sets` table is a one-line hint about
 * the un-run migration rather than a wall of error output.
 */
export function logSetsError(context: string, error: PostgrestError | null): void {
  if (!error) return;
  if (error.code === TABLE_NOT_FOUND) {
    console.warn(
      `${context}: no book_sets table yet — run website/supabase-schema.sql in the ` +
        "Supabase SQL editor to enable multi-volume sets. Serving books individually."
    );
    return;
  }
  console.error(`${context}:`, error);
}

/** Volumes read best in volume order, with un-numbered stragglers last. */
export function sortVolumes(volumes: Book[]): Book[] {
  return [...volumes].sort((a, b) => {
    const an = a.volume_number ?? Number.MAX_SAFE_INTEGER;
    const bn = b.volume_number ?? Number.MAX_SAFE_INTEGER;
    if (an !== bn) return an - bn;
    return a.title.localeCompare(b.title);
  });
}

/** "Volume III" — the label the pipeline recorded, or one built from the number. */
export function volumeLabel(book: Book): string {
  if (book.volume_label) return book.volume_label;
  if (book.volume_number != null) return `Volume ${book.volume_number}`;
  return "";
}

export function volumesSubtotalCents(volumes: Book[]): number {
  return volumes.reduce((sum, v) => sum + v.price_cents, 0);
}

/**
 * What the complete set costs: the bundle price when one is set, otherwise
 * the volumes added up.
 */
export function setPriceCents(set: BookSet, volumes: Book[]): number {
  return set.price_cents ?? volumesSubtotalCents(volumes);
}

/** How much the bundle price saves against buying every volume separately. */
export function setSavingsCents(set: BookSet, volumes: Book[]): number {
  return Math.max(0, volumesSubtotalCents(volumes) - setPriceCents(set, volumes));
}

/** A set only earns its own page and catalog card once it has real volumes. */
export function isMultiVolume(set: BookSetWithVolumes): boolean {
  return set.volumes.length > 1;
}

export function setGenre(set: BookSetWithVolumes): string {
  return set.genre ?? set.volumes[0]?.genre ?? "";
}

/** Earliest volume year — what the set sorts by in the catalog. */
export function setYear(set: BookSetWithVolumes): number {
  const years = set.volumes.map((v) => v.year).filter((y): y is number => y != null);
  return years.length ? Math.min(...years) : 0;
}

/**
 * The catalog lists one entry per work: a standalone book, or a whole set in
 * place of its individual volumes. A "set" holding a single volume so far is
 * listed as that plain book — there is nothing to choose between yet.
 */
export type CatalogEntry =
  | { kind: "book"; key: string; genre: string; year: number; book: Book }
  | { kind: "set"; key: string; genre: string; year: number; set: BookSetWithVolumes };

export function buildCatalogEntries(books: Book[], sets: BookSet[]): CatalogEntry[] {
  const volumesBySet = new Map<string, Book[]>();
  for (const book of books) {
    if (!book.set_id) continue;
    const list = volumesBySet.get(book.set_id) ?? [];
    list.push(book);
    volumesBySet.set(book.set_id, list);
  }

  const entries: CatalogEntry[] = [];
  const groupedBookIds = new Set<string>();

  for (const set of sets) {
    const volumes = sortVolumes(volumesBySet.get(set.id) ?? []);
    const withVolumes: BookSetWithVolumes = { ...set, volumes };
    if (!isMultiVolume(withVolumes)) continue;
    volumes.forEach((v) => groupedBookIds.add(v.id));
    entries.push({
      kind: "set",
      key: `set:${set.id}`,
      genre: setGenre(withVolumes),
      year: setYear(withVolumes),
      set: withVolumes,
    });
  }

  for (const book of books) {
    if (groupedBookIds.has(book.id)) continue;
    entries.push({ kind: "book", key: `book:${book.id}`, genre: book.genre, year: book.year, book });
  }

  return entries.sort((a, b) => a.year - b.year);
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export async function getSetBySlug(slug: string): Promise<BookSetWithVolumes | null> {
  const { data: set, error } = await supabase
    .from("book_sets")
    .select("*")
    .eq("slug", slug)
    .single();

  if (error || !set) return null;

  const { data: volumes } = await supabase
    .from("books")
    .select("*")
    .eq("set_id", set.id);

  return { ...set, volumes: sortVolumes(volumes ?? []) };
}

export async function getSetForBook(book: Book): Promise<BookSetWithVolumes | null> {
  if (!book.set_id) return null;

  const { data: set } = await supabase
    .from("book_sets")
    .select("*")
    .eq("id", book.set_id)
    .single();

  if (!set) return null;

  const { data: volumes } = await supabase.from("books").select("*").eq("set_id", set.id);
  return { ...set, volumes: sortVolumes(volumes ?? []) };
}
