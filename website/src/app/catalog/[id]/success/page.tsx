import Link from "next/link";
import { stripe } from "@/lib/stripe";

export default async function SuccessPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ session_id?: string }>;
}) {
  const { session_id } = await searchParams;
  let customerName = "there";

  if (session_id) {
    try {
      const session = await stripe.checkout.sessions.retrieve(
        session_id
      );
      customerName = session.shipping_details?.name ?? session.customer_details?.name ?? "there";
    } catch {
      // Silently ignore — still show success
    }
  }

  return (
    <div className="max-w-xl mx-auto px-6 py-20 text-center">
      <div className="font-serif text-5xl mb-6">✦</div>
      <h1 className="font-serif text-4xl font-normal mb-4">
        Order confirmed, {customerName.split(" ")[0]}.
      </h1>
      <p className="text-muted leading-relaxed mb-8">
        Your book is heading to the printer. We&apos;ll send you a shipping confirmation
        with tracking information once it&apos;s on its way — typically within 5–7 business days.
      </p>
      <div className="flex gap-4 justify-center">
        <Link href="/catalog" className="btn-primary">Browse More Books</Link>
        <Link href="/" className="btn-outline">Back to Home</Link>
      </div>
    </div>
  );
}
