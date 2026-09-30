"use client";

import { useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import { formatPrice } from "@/lib/format";
import { ShipToFields, shipToDestination, useShipTo } from "@/components/cart/ShipTo";
import { FORMAT_LABELS, type BookFormat } from "@/lib/formats";

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!);

export type SetOption = {
  id: string;
  slug: string;
  /** Per format the whole set can be bought in; missing means not available */
  prices: Partial<Record<BookFormat, { priceCents: number; savingsCents: number }>>;
  volumeCount: number;
};

export function CheckoutButton({
  bookId,
  format,
  setOption,
}: {
  bookId: string;
  format: BookFormat;
  /** Present when this book is one volume of a set — offers the whole set too */
  setOption?: SetOption;
}) {
  const setPrice = setOption?.prices[format];
  const [pending, setPending] = useState<"book" | "set" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shipTo, setShipTo] = useShipTo();

  async function handleCheckout(target: "book" | "set") {
    setPending(target);
    setError(null);

    // Shipping and tax are quoted for the customer's own postcode
    const ship = shipToDestination(shipTo);
    if ("missing" in ship) {
      setError(ship.missing);
      setPending(null);
      return;
    }

    try {
      const body =
        target === "set" && setOption
          ? { setId: setOption.id, setSlug: setOption.slug, format, destination: ship.destination }
          : { bookId, format, destination: ship.destination };

      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
      setPending(null);
    }
  }

  return (
    <div>
      <ShipToFields value={shipTo} onChange={setShipTo} />
      <button
        onClick={() => handleCheckout("book")}
        disabled={pending !== null}
        className="btn-outline w-full disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {pending === "book"
          ? "Preparing checkout…"
          : setOption
            ? "Buy this volume now"
            : "Buy Now — Print to Order"}
      </button>

      {setOption && setPrice && (
        <>
          <button
            onClick={() => handleCheckout("set")}
            disabled={pending !== null}
            className="btn-outline w-full mt-3 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {pending === "set"
              ? "Preparing checkout…"
              : `Buy all ${setOption.volumeCount} volumes in ${FORMAT_LABELS[format].toLowerCase()} — ${formatPrice(setPrice.priceCents)}`}
          </button>
          {setPrice.savingsCents > 0 && (
            <p className="text-xs text-rust mt-2 text-center">
              Save {formatPrice(setPrice.savingsCents)} on the complete set.
            </p>
          )}
        </>
      )}

      {error && <p className="text-rust text-xs mt-2">{error}</p>}

      <p className="text-xs text-muted mt-3 leading-relaxed">
        Secure checkout via Stripe; shipping and sales tax are added there. Allow 10–14 days for printing and delivery.
      </p>
    </div>
  );
}
