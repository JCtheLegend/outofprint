import { notFound } from "next/navigation";
import Image from "next/image";
import { supabase } from "@/lib/supabase";
import { formatPrice } from "@/lib/stripe";
import { CheckoutButton } from "./CheckoutButton";

export async function generateStaticParams() {
  const { data } = await supabase.from("books").select("id");
  return (data ?? []).map((b) => ({ id: b.id }));
}

async function getBook(id: string) {
  const { data } = await supabase.from("books").select("*").eq("id", id).single();
  return data;
}

export default async function BookPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const book = await getBook(id);
  if (!book) notFound();

  return (
    <div className="max-w-5xl mx-auto px-6 py-12">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
        {/* Cover */}
        <div className="aspect-[2/3] relative bg-ink/10">
          {book.cover_url ? (
            <Image src={book.cover_url} alt={book.title} fill className="object-cover" />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-8 bg-[#2d3a2e]">
              <p className="font-serif text-xl font-semibold text-[#e8dfc0] text-center mb-2">
                {book.title}
              </p>
              <p className="font-body italic text-sm text-[#a89e7a] text-center">
                {book.author}
              </p>
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex flex-col justify-center">
          <p className="section-label">{book.genre}</p>
          <h1 className="font-serif text-4xl font-normal mb-2 leading-tight">{book.title}</h1>
          <p className="text-muted italic text-lg mb-1">{book.author}</p>
          <p className="text-sm text-muted mb-6">Originally published {book.year}</p>
          <p className="text-sm leading-relaxed text-muted mb-8">{book.description}</p>
          <div className="border-t border-border pt-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-2xl font-serif font-semibold text-rust">
                {formatPrice(book.price_cents)}
              </span>
              <span className="text-xs text-muted">Printed & shipped to order</span>
            </div>
            <CheckoutButton bookId={book.id} />
          </div>
        </div>
      </div>
    </div>
  );
}
