import { notFound } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { supabaseAdmin, type Book, type Order } from "@/lib/supabase";
import { volumeLabel } from "@/lib/sets";

/**
 * Order status page.
 *
 * Lulu has no page a customer can be sent to, so this stands in for one. The
 * order id is an unguessable UUID and acts as the key — the page deliberately
 * shows only what the customer already knows (their books and where they are),
 * never the shipping address or email.
 */

export const dynamic = "force-dynamic";

const STAGES: { status: Order["status"]; label: string; blurb: string }[] = [
  { status: "paid", label: "Order received", blurb: "We have your order and are preparing it for the printer." },
  { status: "printing", label: "At the printer", blurb: "Your book is being printed and bound to order." },
  { status: "shipped", label: "Shipped", blurb: "On its way to you." },
  { status: "delivered", label: "Delivered", blurb: "Enjoy it." },
];

function stageIndex(status: Order["status"]): number {
  const index = STAGES.findIndex((stage) => stage.status === status);
  return index === -1 ? 0 : index;
}

export default async function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const db = supabaseAdmin();

  const { data: order } = await db.from("orders").select("*").eq("id", id).single();
  if (!order) notFound();

  // Everything bought in the same checkout belongs on the same page
  const { data: siblings } = await db
    .from("orders")
    .select("*")
    .eq("stripe_session_id", order.stripe_session_id);

  const rows = (siblings ?? [order]) as Order[];
  const { data: bookRows } = await db
    .from("books")
    .select("*")
    .in("id", rows.map((row) => row.book_id));
  const books = new Map((bookRows ?? []).map((book: Book) => [book.id, book]));

  const furthest = rows.reduce((max, row) => Math.max(max, stageIndex(row.status)), 0);
  const placed = new Date(order.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="max-w-3xl mx-auto px-6 py-12">
      <div className="border-b border-border pb-8 mb-8">
        <p className="section-label">Order placed {placed}</p>
        <h1 className="font-serif text-4xl font-normal mb-2">Your order</h1>
        <p className="text-muted text-sm">
          Every book here is printed to order. Allow 10–14 days from order to delivery.
        </p>
      </div>

      {/* Progress */}
      <ol className="flex flex-wrap gap-y-4 mb-10">
        {STAGES.map((stage, index) => {
          const reached = index <= furthest;
          return (
            <li key={stage.status} className="flex-1 min-w-[140px]">
              <div className={`h-[3px] mb-3 ${reached ? "bg-rust" : "bg-border"}`} />
              <p className={`font-body text-[11px] tracking-widest uppercase ${reached ? "text-ink" : "text-muted"}`}>
                {stage.label}
              </p>
              {index === furthest && (
                <p className="text-xs text-muted mt-1 leading-relaxed pr-4">{stage.blurb}</p>
              )}
            </li>
          );
        })}
      </ol>

      {/* Books */}
      <ul className="border-t border-border">
        {rows.map((row) => {
          const book = books.get(row.book_id);
          const volume = book ? volumeLabel(book) : "";
          const urls = Array.isArray(row.tracking_urls) ? row.tracking_urls : [];
          return (
            <li key={row.id} className="flex gap-4 py-5 border-b border-border">
              <div className="relative w-16 aspect-[2/3] bg-ink/10 shrink-0">
                {book?.cover_url && (
                  <Image src={book.cover_url} alt={book.title} fill className="object-cover" sizes="64px" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-serif text-base font-semibold">
                  {book ? (volume ? `${book.title} — ${volume}` : book.title) : "Book"}
                </p>
                {book && <p className="text-xs text-muted italic mt-0.5">{book.author}</p>}
                {row.quantity > 1 && <p className="text-xs text-muted mt-1">Quantity: {row.quantity}</p>}
                {urls.length > 0 && (
                  <p className="text-xs mt-2">
                    {row.tracking_carrier ? `${row.tracking_carrier}: ` : ""}
                    {urls.map((url) => (
                      <a
                        key={url}
                        href={url}
                        className="text-rust underline break-all mr-3"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Track this parcel
                      </a>
                    ))}
                  </p>
                )}
              </div>
              <span className="text-[11px] tracking-widest uppercase text-muted shrink-0">
                {STAGES[stageIndex(row.status)].label}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="text-xs text-muted mt-8 leading-relaxed">
        Questions about this order? Reply to your confirmation email and we&apos;ll pick it up.
      </p>
      <p className="mt-6">
        <Link href="/catalog" className="btn-outline">Browse the Catalog</Link>
      </p>
    </div>
  );
}
