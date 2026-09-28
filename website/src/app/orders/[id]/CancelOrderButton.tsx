"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function CancelOrderButton({
  orderId,
  deadlineLabel,
  bookCount,
}: {
  orderId: string;
  deadlineLabel: string;
  bookCount: number;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function cancel() {
    setWorking(true);
    setError(null);
    try {
      const res = await fetch(`/api/orders/${orderId}/cancel`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Could not cancel this order");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setWorking(false);
    }
  }

  return (
    <div className="border border-border p-5 mt-8">
      <p className="font-serif text-base font-semibold mb-1">Changed your mind?</p>
      <p className="text-sm text-muted leading-relaxed mb-4">
        You can cancel {bookCount > 1 ? "this order" : "this book"} until{" "}
        <strong className="text-ink">{deadlineLabel}</strong> and get a full refund. After that
        it goes to the printer — every book is made to order, so it can&apos;t be cancelled once
        printing starts.
      </p>

      {confirming ? (
        <div className="flex flex-wrap gap-3 items-center">
          <button onClick={cancel} disabled={working} className="btn-primary disabled:opacity-60">
            {working ? "Cancelling…" : `Yes, cancel and refund${bookCount > 1 ? " all" : ""}`}
          </button>
          <button
            onClick={() => setConfirming(false)}
            disabled={working}
            className="text-xs text-muted underline hover:text-rust cursor-pointer"
          >
            Keep my order
          </button>
        </div>
      ) : (
        <button onClick={() => setConfirming(true)} className="btn-outline">
          Cancel this order
        </button>
      )}

      {error && <p className="text-rust text-xs mt-3">{error}</p>}
    </div>
  );
}
