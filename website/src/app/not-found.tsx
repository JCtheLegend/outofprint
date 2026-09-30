import Link from "next/link";

export const metadata = {
  title: "Not found · Out of Print Press",
};

/** A book, set or order that doesn't exist — or no longer does. */
export default function NotFound() {
  return (
    <div className="max-w-xl mx-auto px-6 py-24 text-center">
      <p className="section-label">Not found</p>
      <h1 className="font-serif text-4xl font-normal mb-4">Out of print, perhaps</h1>
      <p className="text-muted text-sm leading-relaxed mb-8">
        We couldn&apos;t find that page. The book may have been withdrawn from the catalog,
        or the link may be mistyped. If you&apos;re looking for a book we don&apos;t have yet,
        you can ask us to restore it.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link href="/catalog" className="btn-primary">
          Browse the Catalog
        </Link>
        <Link href="/submit" className="btn-outline">
          Request a Book
        </Link>
      </div>
    </div>
  );
}
