import Link from "next/link";
import { productionDelayMinutes } from "@/lib/print";

export const metadata = {
  title: "Cancellations & Returns · Out of Print Press",
};

export default function PoliciesPage() {
  const hours = Math.round(productionDelayMinutes() / 60);
  const window = hours === 24 ? "24 hours" : `${hours} hours`;

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <div className="border-b border-border pb-8 mb-8">
        <p className="section-label">Policies</p>
        <h1 className="font-serif text-4xl font-normal mb-2">Cancellations &amp; Returns</h1>
        <p className="text-muted text-sm">
          Every book we sell is printed when you order it, which shapes everything below.
        </p>
      </div>

      <div className="space-y-8 text-sm leading-relaxed text-muted">
        <section>
          <h2 className="font-serif text-xl text-ink mb-2">Cancelling an order</h2>
          <p>
            You have <strong className="text-ink">{window}</strong> from the moment you order to
            cancel it for a full refund, with no reason needed. Use the &ldquo;Cancel this
            order&rdquo; button on your order page — the link is in your confirmation email — and
            the refund is issued immediately to the card you paid with. It usually appears on your
            statement within 5–10 business days.
          </p>
          <p className="mt-3">
            After {window} your book goes to the printer and can no longer be cancelled. An order
            covering several books cancels as a whole, because they are printed together.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-xl text-ink mb-2">Returns</h2>
          <p>
            Because each copy is made for you rather than picked off a shelf, we don&apos;t accept
            returns for change of mind once printing has started.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-xl text-ink mb-2">Damaged, faulty or wrong books</h2>
          <p>
            If your book arrives damaged, misprinted, mis-bound or simply isn&apos;t what you
            ordered, we will reprint and reship it at our cost, or refund you in full — whichever
            you prefer. Reply to your confirmation email within 30 days of delivery with a photo
            and we&apos;ll sort it out. You don&apos;t need to send the faulty copy back.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-xl text-ink mb-2">Delivery</h2>
          <p>
            Printing takes a few days, and delivery a few more — allow 10–14 days in total. We
            email tracking as soon as your parcel leaves the printer, and your order page shows
            where things stand at any time.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-xl text-ink mb-2">Getting in touch</h2>
          <p>
            Reply to any email we&apos;ve sent you about your order and it reaches us. If you
            don&apos;t have one to hand, use the{" "}
            <Link href="/submit" className="text-rust hover:underline">submission form</Link> and
            mention your order.
          </p>
        </section>
      </div>
    </div>
  );
}
