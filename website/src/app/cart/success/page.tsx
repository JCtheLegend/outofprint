import Link from "next/link";
import { stripe } from "@/lib/stripe";
import { ClearCartOnMount } from "./ClearCartOnMount";

export default async function CartSuccessPage({
  searchParams,
}: {
  searchParams: Promise<{ session_id?: string }>;
}) {
  const { session_id } = await searchParams;
  let customerName = "there";
  let bookCount = 0;

  if (session_id) {
    try {
      const session = await stripe.checkout.sessions.retrieve(session_id, {
        expand: ["line_items"],
      });
      customerName =
        session.shipping_details?.name ?? session.customer_details?.name ?? "there";
      bookCount =
        session.line_items?.data.reduce((total, line) => total + (line.quantity ?? 1), 0) ?? 0;
    } catch {
      // Silently ignore — still show success
    }
  }

  return (
    <div className="max-w-xl mx-auto px-6 py-20 text-center">
      <ClearCartOnMount />
      <div className="font-serif text-5xl mb-6">✦</div>
      <h1 className="font-serif text-4xl font-normal mb-4">
        Order confirmed, {customerName.split(" ")[0]}.
      </h1>
      <p className="text-muted leading-relaxed mb-8">
        {bookCount > 0
          ? `All ${bookCount} ${bookCount === 1 ? "book is" : "books are"} heading to the printer.`
          : "Your order is heading to the printer."}{" "}
        We&apos;ll email you tracking information as it ships — typically within 5–7
        business days.
      </p>
      <div className="flex gap-4 justify-center">
        <Link href="/catalog" className="btn-primary">Browse More Books</Link>
        <Link href="/" className="btn-outline">Back to Home</Link>
      </div>
    </div>
  );
}
