import { notFound } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { supabase, type Book, type BookDetails } from "@/lib/supabase";
import { getSetForBook, setPriceCents, setSavingsCents, volumeLabel } from "@/lib/sets";
import { commonFormats, formatPriceCents, formatsOf, type BookFormat } from "@/lib/formats";
import type { SetOption } from "./CheckoutButton";
import { BookPurchasePanel } from "./BookPurchasePanel";
import { LookInside } from "./LookInside";
import { readBookDetails } from "@/lib/details";
import { displayGenre } from "@/lib/genres";

export async function generateStaticParams() {
  const { data } = await supabase.from("books").select("id");
  return (data ?? []).map((b) => ({ id: b.id }));
}

/** PostgREST's code for `.single()` matching no row. */
const NO_ROWS = "PGRST116";

/**
 * The book, or null when there is no such book. Any other failure throws:
 * swallowing it would bake a working book into the build as a 404.
 */
async function getBook(id: string): Promise<Book | null> {
  const { data, error } = await supabase.from("books").select("*").eq("id", id).single();
  if (error?.code === NO_ROWS) return null;
  if (error) throw new Error(`Could not load book ${id}: ${error.message} (${error.code})`);
  return data;
}

/** "6 x 9 in" → "6 × 9 in" */
function trimLabel(trim: string | undefined): string | null {
  return trim ? trim.replace(/\s*x\s*/i, " × ") : null;
}

/** The facts worth a row in "About this edition", in reading order. */
function editionFacts(book: Book, details: BookDetails): [string, string][] {
  const facts: [string, string | null | undefined][] = [
    ["Original publication", details.original_publication],
    ["Language", details.language],
    ["Translated by", details.translator],
    ["Edited by", details.editor],
    // A single sentence reads as a fact; a list of works gets its own section
    ["Includes", details.included_scope?.length === 1 ? details.included_scope[0] : null],
    ["Pages", book.page_count ? String(book.page_count) : null],
    ["Trim size", trimLabel(details.trim_size)],
    ["Restored from", details.source_editions?.join("; ")],
  ];
  return facts.filter((fact): fact is [string, string] => Boolean(fact[1]));
}

export default async function BookPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const book = await getBook(id);
  if (!book) notFound();

  const set = await getSetForBook(book);
  const inSet = set !== null && set.volumes.length > 1;
  const volume = volumeLabel(book);

  const prices: Partial<Record<BookFormat, number>> = Object.fromEntries(
    formatsOf(book).map((format) => [format, formatPriceCents(book, format)])
  );

  const setOption: SetOption | undefined =
    inSet && set
      ? {
          id: set.id,
          slug: set.slug,
          prices: Object.fromEntries(
            commonFormats(set.volumes).map((format) => [
              format,
              {
                priceCents: setPriceCents(set, set.volumes, format),
                savingsCents: setSavingsCents(set, set.volumes, format),
              },
            ])
          ),
          volumeCount: set.volumes.length,
        }
      : undefined;

  const details: BookDetails = readBookDetails(book.details);
  // A collection's own list of works (with subtitles and dates) says more than
  // its bookmarks, so it takes the contents' place when there is one
  const includedWorks = (details.included_scope?.length ?? 0) > 1 ? details.included_scope! : [];
  const listing = includedWorks.length > 0
    ? { label: "Works in this volume", entries: includedWorks }
    : { label: "Contents", entries: details.contents ?? [] };
  const facts = editionFacts(book, details);
  const previews = Array.isArray(book.preview_urls)
    ? book.preview_urls.filter((url): url is string => typeof url === "string")
    : [];

  return (
    <div className="max-w-5xl mx-auto px-6 py-12">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
        {/* Cover */}
        <div className="aspect-[2/3] relative bg-ink/10">
          {book.cover_url ? (
            <Image src={book.cover_url} alt={book.title} fill className="object-cover" />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-8 bg-[#2d3a2e]">
              <p className="font-serif text-xl font-semibold text-[#e8dfc0] text-center mb-2">
                {book.title}
              </p>
              <p className="font-body italic text-sm text-[#a89e7a] text-center">
                {book.author}
              </p>
            </div>
          )}
          {volume && (
            <span className="absolute bottom-0 right-0 bg-ink/85 text-cream font-body text-[11px] tracking-widest uppercase px-3 py-1.5">
              {volume}
            </span>
          )}
        </div>

        {/* Info */}
        <div className="flex flex-col justify-center">
          {/* A volume uploaded before it carried its own genre takes its set's */}
          <p className="section-label">{displayGenre(book.genre || set?.genre)}</p>
          <h1 className="font-serif text-4xl font-normal mb-2 leading-tight">{book.title}</h1>
          {details.subtitle && (
            <p className="font-serif text-xl text-muted mb-2 leading-snug">{details.subtitle}</p>
          )}
          {inSet && set && (
            <p className="text-sm text-muted mb-2">
              {volume ? `${volume} of ` : "Part of "}
              <Link href={`/catalog/set/${set.slug}`} className="text-rust hover:underline">
                {set.title}
              </Link>{" "}
              — a {set.volumes.length}-volume set
            </p>
          )}
          <p className="text-muted italic text-lg mb-1">{book.author}</p>
          <p className="text-sm text-muted mb-6">
            {book.year ? `Originally published ${book.year}` : null}
            {book.year && book.page_count ? " · " : null}
            {book.page_count ? `${book.page_count} pages` : null}
          </p>
          {book.description?.trim() && (
            <p className="text-sm leading-relaxed text-muted mb-8">{book.description}</p>
          )}
          <div className="border-t border-border pt-6">
            <p className="text-xs text-muted mb-3">Printed &amp; shipped to order</p>
            <BookPurchasePanel bookId={book.id} prices={prices} setOption={setOption} />
            {inSet && set && (
              <p className="text-xs text-muted mt-4">
                <Link href={`/catalog/set/${set.slug}?volume=${book.id}`} className="hover:text-rust">
                  See all {set.volumes.length} volumes →
                </Link>
              </p>
            )}
          </div>
        </div>
      </div>

      {previews.length > 0 && (
        <section className="mt-16">
          <p className="section-label">Look inside</p>
          <p className="text-sm text-muted mb-4">
            The first {previews.length} pages, exactly as they are printed.
          </p>
          <LookInside pages={previews} title={book.title} />
        </section>
      )}

      {book.full_cover_url && (
        <section className="mt-16">
          <p className="section-label">The full cover</p>
          <p className="text-sm text-muted mb-4">Back, spine and front, as it wraps the book.</p>
          <a href={book.full_cover_url} target="_blank" rel="noopener noreferrer" className="block">
            {/* The wraparound's proportions vary with the spine, so it sizes to its own width */}
            <Image
              src={book.full_cover_url}
              alt={`The full cover of ${book.title}`}
              width={1400}
              height={1000}
              className="w-full h-auto border border-border"
            />
          </a>
        </section>
      )}

      {(facts.length > 0 || listing.entries.length > 0) && (
        <section className="mt-16 grid grid-cols-1 md:grid-cols-2 gap-12">
          {facts.length > 0 && (
            <div>
              <p className="section-label">About this edition</p>
              <dl className="border-t border-border text-sm">
                {facts.map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[9rem_1fr] gap-4 py-3 border-b border-border">
                    <dt className="text-muted">{label}</dt>
                    <dd className="text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
              {details.omitted && details.omitted.length > 0 && (
                <details className="mt-6 text-sm">
                  <summary className="cursor-pointer text-rust hover:underline">
                    What this edition leaves out
                  </summary>
                  <ul className="mt-3 space-y-2 text-muted leading-relaxed list-disc pl-5">
                    {details.omitted.map((item, index) => (
                      <li key={`${index}-${item}`}>{item}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}

          {listing.entries.length > 0 && (
            <div>
              <p className="section-label">{listing.label}</p>
              <ol className="border-t border-border text-sm max-h-[32rem] overflow-y-auto">
                {listing.entries.map((entry, index) => (
                  <li key={`${index}-${entry}`} className="py-2 border-b border-border text-ink">
                    {entry}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
