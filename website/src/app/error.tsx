"use client";

import { useEffect } from "react";
import Link from "next/link";

/**
 * Shown in place of any page that throws while rendering, inside the normal
 * header and footer. The digest is the id Next logs the real error under, so
 * a reader who writes in can point us straight at it.
 */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="max-w-xl mx-auto px-6 py-24 text-center">
      <p className="section-label">Something went wrong</p>
      <h1 className="font-serif text-4xl font-normal mb-4">This page didn&apos;t load</h1>
      <p className="text-muted text-sm leading-relaxed mb-8">
        That&apos;s our fault, not yours — nothing you did caused it, and nothing in your cart
        has been lost. Try again, or keep browsing and come back to it later.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <button type="button" onClick={reset} className="btn-primary">
          Try again
        </button>
        <Link href="/catalog" className="btn-outline">
          Browse the Catalog
        </Link>
      </div>
      {error.digest && (
        <p className="text-xs text-muted mt-10">
          If it keeps happening, let us know and mention reference{" "}
          <code className="text-ink">{error.digest}</code>.
        </p>
      )}
    </div>
  );
}
