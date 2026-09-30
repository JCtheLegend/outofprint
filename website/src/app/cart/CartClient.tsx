"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { loadStripe } from "@stripe/stripe-js";
import { supabase, type Book, type BookSet } from "@/lib/supabase";
import { formatPrice } from "@/lib/format";
import { setPriceCents, sortVolumes, volumeLabel } from "@/lib/sets";
import { useCart } from "@/components/cart/CartProvider";
import { MAX_QUANTITY, cartItemKey, type CartItem } from "@/lib/cart";
import { FORMAT_LABELS, formatPriceCents, hasFormat } from "@/lib/formats";
import { ShipToFields, shipToDestination, useShipTo } from "@/components/cart/ShipTo";

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!);

/** One cart row, resolved against the catalog as it stands right now. */
type ResolvedItem = {
  item: CartItem;
  title: string;
  subtitle: string;
  coverUrl: string | null;
  unitPriceCents: number;
  href: string;
  /** Volume titles, for a set */
  volumes: string[];
};

function resolve(items: CartItem[], books: Book[], sets: BookSet[], volumes: Book[]): ResolvedItem[] {
  const bookById = new Map(books.map((b) => [b.id, b]));
  const setById = new Map(sets.map((s) => [s.id, s]));

  return items.flatMap<ResolvedItem>((item) => {
    if (item.kind === "book") {
      const book = bookById.get(item.id);
      // A format that has since been withdrawn drops out like a deleted book
      if (!book || !hasFormat(book, item.format)) return [];
      const volume = volumeLabel(book);
      return [{
        item,
        title: volume ? `${book.title} — ${volume}` : book.title,
        subtitle: `${book.author}${book.year ? ` · ${book.year}` : ""} · ${FORMAT_LABELS[item.format]}`,
        coverUrl: book.cover_url,
        unitPriceCents: formatPriceCents(book, item.format),
        href: `/catalog/${book.id}`,
        volumes: [],
      }];
    }

    const set = setById.get(item.id);
    if (!set) return [];
    const setVolumes = sortVolumes(volumes.filter((v) => v.set_id === set.id));
    if (setVolumes.some((v) => !hasFormat(v, item.format))) return [];
    return [{
      item,
      title: set.title,
      subtitle: `${set.author} · complete set of ${setVolumes.length} · ${FORMAT_LABELS[item.format]}`,
      coverUrl: set.cover_url ?? setVolumes.find((v) => v.cover_url)?.cover_url ?? null,
      unitPriceCents: setPriceCents(set, setVolumes, item.format),
      href: `/catalog/set/${set.slug}`,
      volumes: setVolumes.map((v) => volumeLabel(v) || v.title),
    }];
  });
}

export function CartClient() {
  const { items, ready, setQuantity, remove } = useCart();
  const [catalog, setCatalog] = useState<{ books: Book[]; sets: BookSet[]; volumes: Book[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [promoCode, setPromoCode] = useState("");
  const [shipTo, setShipTo] = useShipTo();

  const bookIds = useMemo(
    () => items.filter((i) => i.kind === "book").map((i) => i.id),
    [items]
  );
  const setIds = useMemo(
    () => items.filter((i) => i.kind === "set").map((i) => i.id),
    [items]
  );

  // Re-read titles and prices from the catalog rather than trusting whatever
  // the cart was written with, which may be weeks old.
  useEffect(() => {
    if (!ready) return;
    if (bookIds.length === 0 && setIds.length === 0) {
      setCatalog({ books: [], sets: [], volumes: [] });
      return;
    }

    let cancelled = false;
    (async () => {
      const [booksRes, setsRes, volumesRes] = await Promise.all([
        bookIds.length
          ? supabase.from("books").select("*").in("id", bookIds)
          : Promise.resolve({ data: [] as Book[] }),
        setIds.length
          ? supabase.from("book_sets").select("*").in("id", setIds)
          : Promise.resolve({ data: [] as BookSet[] }),
        setIds.length
          ? supabase.from("books").select("*").in("set_id", setIds)
          : Promise.resolve({ data: [] as Book[] }),
      ]);
      if (cancelled) return;
      setCatalog({
        books: (booksRes.data ?? []) as Book[],
        sets: (setsRes.data ?? []) as BookSet[],
        volumes: (volumesRes.data ?? []) as Book[],
      });
    })();

    return () => {
      cancelled = true;
    };
  }, [ready, bookIds, setIds]);

  const resolved = useMemo(
    () => (catalog ? resolve(items, catalog.books, catalog.sets, catalog.volumes) : []),
    [items, catalog]
  );

  const subtotal = resolved.reduce(
    (total, row) => total + row.unitPriceCents * row.item.quantity,
    0
  );

  async function handleCheckout() {
    setLoading(true);
    setError(null);

    // Shipping and tax are quoted for the customer's own postcode
    const ship = shipToDestination(shipTo);
    if ("missing" in ship) {
      setError(ship.missing);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Checked, and priced, only on the server
        body: JSON.stringify({ items, destination: ship.destination, promoCode: promoCode.trim() || undefined }),
      });
      if (!res.ok) {
        const { error: msg } = await res.json();
        throw new Error(msg ?? "Checkout failed");
      }
      const { sessionId } = await res.json();
      const stripe = await stripePromise;
      await stripe?.redirectToCheckout({ sessionId });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (!ready || !catalog) {
    return <p className="text-muted text-sm">Loading your cart…</p>;
  }

  if (resolved.length === 0) {
    return (
      <div className="border border-border p-10 text-center">
        <p className="font-serif text-xl mb-2">Your cart is empty.</p>
        <p className="text-muted text-sm mb-6">
          Every book is printed to order — add as many as you like and they ship together.
        </p>
        <Link href="/catalog" className="btn-primary">Browse the Catalog</Link>
      </div>
    );
  }

  return (
    <>
      <ul className="border-t border-border mb-8">
        {resolved.map((row) => (
          <li
            key={cartItemKey(row.item)}
            className="flex gap-4 py-5 border-b border-border"
          >
            <Link href={row.href} className="relative w-16 md:w-20 aspect-[2/3] bg-ink/10 shrink-0">
              {row.coverUrl ? (
                <Image src={row.coverUrl} alt={row.title} fill className="object-cover" sizes="80px" />
              ) : (
                <span className="absolute inset-0 flex items-center justify-center p-1 text-[9px] font-serif text-center text-muted">
                  {row.title}
                </span>
              )}
            </Link>

            <div className="flex-1 min-w-0">
              <Link href={row.href} className="font-serif text-base font-semibold hover:text-rust transition-colors">
                {row.title}
              </Link>
              <p className="text-xs text-muted italic mt-0.5">{row.subtitle}</p>
              {row.volumes.length > 0 && (
                <p className="text-xs text-muted mt-1 leading-relaxed">{row.volumes.join(" · ")}</p>
              )}

              <div className="flex items-center gap-4 mt-3">
                <label className="flex items-center gap-2 text-xs text-muted">
                  Qty
                  <select
                    value={row.item.quantity}
                    onChange={(e) => setQuantity(row.item, Number(e.target.value))}
                    className="border border-border bg-white px-2 py-1 text-sm text-ink outline-none focus:border-rust"
                  >
                    {Array.from({ length: MAX_QUANTITY }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => remove(row.item)}
                  className="text-xs text-muted underline hover:text-rust transition-colors cursor-pointer"
                >
                  Remove
                </button>
              </div>
            </div>

            <div className="text-right shrink-0">
              <p className="font-serif font-semibold text-rust">
                {formatPrice(row.unitPriceCents * row.item.quantity)}
              </p>
              {row.item.quantity > 1 && (
                <p className="text-xs text-muted mt-0.5">{formatPrice(row.unitPriceCents)} each</p>
              )}
            </div>
          </li>
        ))}
      </ul>

      <div className="flex items-baseline justify-between mb-2">
        <span className="font-serif text-lg">Subtotal</span>
        <span className="font-serif text-2xl font-semibold text-rust">{formatPrice(subtotal)}</span>
      </div>
      <p className="text-xs text-muted mb-6">
        Shipping and sales tax are added at checkout, at exactly what our printer
        charges us for your postcode. Everything in one order is printed and shipped
        together.
      </p>

      <ShipToFields value={shipTo} onChange={setShipTo} />

      <label className="block mb-4">
        <span className="section-label block mb-1">Promo code</span>
        <input
          type="text"
          value={promoCode}
          onChange={(e) => setPromoCode(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="input-field"
        />
      </label>

      <button
        onClick={handleCheckout}
        disabled={loading}
        className="btn-primary w-full disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {loading ? "Preparing checkout…" : "Proceed to Checkout"}
      </button>
      {error && <p className="text-rust text-xs mt-2">{error}</p>}

      <p className="text-center mt-4">
        <Link href="/catalog" className="text-xs text-muted hover:text-rust transition-colors">
          Continue browsing the catalog
        </Link>
      </p>
    </>
  );
}
