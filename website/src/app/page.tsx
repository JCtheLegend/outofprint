import Link from "next/link";
import Image from "next/image";
import { supabase, type Book } from "@/lib/supabase";
import { BookCard } from "@/components/ui/BookCard";
import logo from "@/public/ooplogo_black.png";

async function getFeaturedBooks(): Promise<Book[]> {
  const { data, error } = await supabase
    .from("books")
    .select("*")
    .eq("featured", true)
    .order("created_at", { ascending: false })
    .limit(6);

  if (error) {
    console.error("Failed to fetch featured books:", error);
    return [];
  }
  return data ?? [];
}

export default async function HomePage() {
  const books = await getFeaturedBooks();

  return (
    <>
      {/* Hero */}
      <section className="max-w-5xl mx-auto px-6 py-20 text-center relative overflow-hidden">
        <div className="absolute inset-0 flex justify-center items-center -z-10 pointer-events-none">
          <Image
            src={logo}
            alt="Background Logo"
            width={600}
            height={600}
            className="opacity-10 object-contain"
          />
        </div>
        <p className="section-label">Preserving Literature</p>
        <h1 className="font-serif text-5xl md:text-6xl font-normal leading-tight mb-6">
          Bringing <em className="italic text-rust">forgotten books</em>
          <br />back to life
        </h1>
        <p className="text-muted text-lg max-w-3xl mx-auto mb-10 leading-relaxed">
          We restore and reprint out-of-circulation books — from rare Victorian novels
          to mid-century obscurities. Request a title or browse what we&apos;ve already revived.
        </p>
        <div className="flex gap-4 justify-center flex-wrap">
          <Link href="/catalog" className="btn-primary">Browse Catalog</Link>
          <Link href="/submit" className="btn-outline">Request a Title</Link>
        </div>
      </section>

      {/* How It Works */}
      <section className="border-y border-border py-16">
        <div className="max-w-5xl mx-auto px-6">
          <p className="section-label text-center">How It Works</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10 mt-2">
            {[
              {
                n: "01",
                title: "Submit a Request",
                body: "Tell us the title, author, and any source material you have. We'll evaluate availability and feasibility.",
              },
              {
                n: "02",
                title: "We Restore It",
                body: "Our pipeline digitally restores old scans into clean, properly typeset editions ready for print.",
              },
              {
                n: "03",
                title: "It Ships to You",
                body: "Once printed, your book arrives — a proper physical volume, made to last another century.",
              },
            ].map(({ n, title, body }) => (
              <div key={n} className="text-center">
                <div className="font-serif text-5xl text-border leading-none mb-3">{n}</div>
                <h3 className="font-serif text-base font-semibold mb-2">{title}</h3>
                <p className="text-sm text-muted leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Best Sellers */}
      <section className="max-w-5xl mx-auto px-6 py-16">
        <p className="section-label">Best Sellers</p>
        <h2 className="font-serif text-3xl font-normal mb-8">Recently Revived</h2>
        {books.length === 0 ? (
          <p className="text-muted text-sm">No featured books yet — add some in your Supabase dashboard.</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}
