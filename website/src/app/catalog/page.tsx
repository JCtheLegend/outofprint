import { supabase, type Book, type BookSet } from "@/lib/supabase";
import { buildCatalogEntries, logSetsError } from "@/lib/sets";
import { CatalogClient } from "./CatalogClient";

async function getAllBooks(): Promise<Book[]> {
  const { data, error } = await supabase
    .from("books")
    .select("*")
    .order("year", { ascending: true });

  if (error) {
    console.error("Failed to fetch books:", error);
    return [];
  }
  return data ?? [];
}

async function getAllSets(): Promise<BookSet[]> {
  const { data, error } = await supabase.from("book_sets").select("*");

  if (error) {
    logSetsError("Failed to fetch book sets", error);
    return [];
  }
  return data ?? [];
}

export default async function CatalogPage() {
  const [books, sets] = await Promise.all([getAllBooks(), getAllSets()]);
  const entries = buildCatalogEntries(books, sets);
  const genres = Array.from(new Set(entries.map((e) => e.genre).filter(Boolean))).sort();

  return (
    <div className="max-w-5xl mx-auto px-6 py-12">
      <div className="border-b border-border pb-8 mb-8">
        <h1 className="font-serif text-4xl font-normal mb-2">The Catalog</h1>
        <p className="text-muted text-sm">
          Physical editions available to order — each lovingly restored and printed to order.
          Multi-volume works are listed once; buy a single volume or the complete set.
        </p>
      </div>
      <CatalogClient entries={entries} genres={genres} />
    </div>
  );
}
