import { supabase, type Book } from "@/lib/supabase";
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

export default async function CatalogPage() {
  const books = await getAllBooks();
  const genres = Array.from(new Set(books.map((b) => b.genre))).sort();

  return (
    <div className="max-w-5xl mx-auto px-6 py-12">
      <div className="border-b border-border pb-8 mb-8">
        <h1 className="font-serif text-4xl font-normal mb-2">The Catalog</h1>
        <p className="text-muted text-sm">
          Physical editions available to order — each lovingly restored and printed to order.
        </p>
      </div>
      <CatalogClient books={books} genres={genres} />
    </div>
  );
}
