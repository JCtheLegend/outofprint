"use client";

import { useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import { formatPrice } from "@/lib/format";

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!);

export type VolumeOption = {
  id: string;
  title: string;
  label: string;
  priceCents: number;
};

export function SetPurchasePanel({
  setId,
  setSlug,
  volumes,
  setPriceCents,
  savingsCents,
  initialVolumeId,
}: {
  setId: string;
  setSlug: string;
  volumes: VolumeOption[];
  setPriceCents: number;
  savingsCents: number;
  /** Pre-select a single volume — used when arriving from that volume's page */
  initialVolumeId?: string;
}) {
  // "set" buys every volume; otherwise the selected volume's id
  const [choice, setChoice] = useState<string>(initialVolumeId ?? "set");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buyingSet = choice === "set";
  const selectedVolume = volumes.find((v) => v.id === choice);
  const total = buyingSet ? setPriceCents : selectedVolume?.priceCents ?? 0;

  async function handleCheckout() {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buyingSet ? { setId, setSlug } : { bookId: choice }),
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

  return (
    <div>
      <p className="section-label">Choose your edition</p>

      {/* Complete set */}
      <label
        className={`flex items-start gap-3 border p-4 mb-3 cursor-pointer transition-colors ${
          buyingSet ? "border-rust bg-rust-light/40" : "border-border hover:border-ink"
        }`}
      >
        <input
          type="radio"
          name="edition"
          value="set"
          checked={buyingSet}
          onChange={() => setChoice("set")}
          className="mt-1 accent-[#8B3A2A]"
        />
        <span className="flex-1">
          <span className="flex items-baseline justify-between gap-3">
            <span className="font-serif text-base font-semibold">
              The complete set — {volumes.length} volumes
            </span>
            <span className="font-serif font-semibold text-rust">{formatPrice(setPriceCents)}</span>
          </span>
          <span className="block text-xs text-muted mt-1 leading-relaxed">
            Every volume printed and shipped together.
            {savingsCents > 0 && (
              <span className="text-rust"> Save {formatPrice(savingsCents)} against single volumes.</span>
            )}
          </span>
        </span>
      </label>

      {/* Single volumes */}
      <div className="border border-border divide-y divide-border mb-6">
        <p className="text-[11px] tracking-widest uppercase text-muted px-4 py-2 bg-ink/[0.03]">
          Or a single volume
        </p>
        {volumes.map((v) => {
          const active = choice === v.id;
          return (
            <label
              key={v.id}
              className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors ${
                active ? "bg-rust-light/40" : "hover:bg-ink/[0.03]"
              }`}
            >
              <input
                type="radio"
                name="edition"
                value={v.id}
                checked={active}
                onChange={() => setChoice(v.id)}
                className="accent-[#8B3A2A]"
              />
              <span className="flex-1 flex items-baseline justify-between gap-3">
                <span className="font-body text-sm">
                  {v.label ? <span className="font-semibold">{v.label}</span> : v.title}
                  {v.label && <span className="text-muted"> · {v.title}</span>}
                </span>
                <span className="font-body text-sm text-rust">{formatPrice(v.priceCents)}</span>
              </span>
            </label>
          );
        })}
      </div>

      <div className="flex items-center justify-between mb-4 border-t border-border pt-4">
        <span className="text-xs text-muted">Printed &amp; shipped to order</span>
        <span className="text-2xl font-serif font-semibold text-rust">{formatPrice(total)}</span>
      </div>

      <button
        onClick={handleCheckout}
        disabled={loading}
        className="btn-primary w-full disabled:opacity-60 disabled:cursor-not-allowed"
      >
        {loading
          ? "Preparing checkout…"
          : buyingSet
            ? `Purchase all ${volumes.length} volumes`
            : "Purchase — Print to Order"}
      </button>

      {error && <p className="text-rust text-xs mt-2">{error}</p>}

      <p className="text-xs text-muted mt-3 leading-relaxed">
        Secure checkout via Stripe. Allow 10–14 days for printing and delivery.
        {buyingSet && " Volumes are printed individually and may arrive in more than one parcel."}
      </p>
    </div>
  );
}
