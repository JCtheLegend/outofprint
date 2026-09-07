"use client";

import { useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import { formatPrice } from "@/lib/format";

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!);

export type SetOption = {
  id: string;
  slug: string;
  priceCents: number;
  savingsCents: number;
  volumeCount: number;
};

export function CheckoutButton({
  bookId,
  setOption,
}: {
  bookId: string;
  /** Present when this book is one volume of a set — offers the whole set too */
  setOption?: SetOption;
}) {
  const [pending, setPending] = useState<"book" | "set" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleCheckout(target: "book" | "set") {
    setPending(target);
    setError(null);

    try {
      const body =
        target === "set" && setOption
          ? { setId: setOption.id, setSlug: setOption.slug }
          : { bookId };

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
      <button
        onClick={() => handleCheckout("book")}
        disabled={pending !== null}
        className="btn-primary w-full disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {pending === "book"
          ? "Preparing checkout…"
          : setOption
            ? "Purchase this volume"
            : "Purchase — Print to Order"}
      </button>

      {setOption && (
        <>
          <button
            onClick={() => handleCheckout("set")}
            disabled={pending !== null}
            className="btn-outline w-full mt-3 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {pending === "set"
              ? "Preparing checkout…"
              : `Buy all ${setOption.volumeCount} volumes — ${formatPrice(setOption.priceCents)}`}
          </button>
          {setOption.savingsCents > 0 && (
            <p className="text-xs text-rust mt-2 text-center">
              Save {formatPrice(setOption.savingsCents)} on the complete set.
            </p>
          )}
        </>
      )}

      {error && <p className="text-rust text-xs mt-2">{error}</p>}

      <p className="text-xs text-muted mt-3 leading-relaxed">
        Secure checkout via Stripe. Allow 10–14 days for printing and delivery.
      </p>
    </div>
  );
}
