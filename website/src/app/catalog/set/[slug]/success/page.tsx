import Link from "next/link";
import { stripe } from "@/lib/stripe";
import { getSetBySlug } from "@/lib/sets";

export default async function SetSuccessPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ session_id?: string }>;
}) {
  const { slug } = await params;
  const { session_id } = await searchParams;
  const set = await getSetBySlug(slug);

  let customerName = "there";
  if (session_id) {
    try {
      const session = await stripe.checkout.sessions.retrieve(session_id);
      customerName =
        session.shipping_details?.name ?? session.customer_details?.name ?? "there";
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
        {set
          ? `All ${set.volumes.length} volumes of ${set.title} are heading to the printer.`
          : "Your books are heading to the printer."}{" "}
        Each volume is printed individually, so they may arrive in more than one parcel — we&apos;ll
        send tracking for each as it ships, typically within 5–7 business days.
      </p>
      <div className="flex gap-4 justify-center">
        <Link href="/catalog" className="btn-primary">Browse More Books</Link>
        <Link href="/" className="btn-outline">Back to Home</Link>
      </div>
    </div>
  );
}
