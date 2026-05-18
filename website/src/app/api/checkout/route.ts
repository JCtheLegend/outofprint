import { NextRequest, NextResponse } from "next/server";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";

export async function POST(req: NextRequest) {
  try {
    const { bookId } = await req.json();

    if (!bookId) {
      return NextResponse.json({ error: "bookId is required" }, { status: 400 });
    }

    // Fetch book from Supabase
    const { data: book, error } = await supabaseAdmin()
      .from("books")
      .select("*")
      .eq("id", bookId)
      .single();

    if (error || !book) {
      return NextResponse.json({ error: "Book not found" }, { status: 404 });
    }

    const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;

    // Create Stripe Checkout session
    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      line_items: [
        {
          price_data: {
            currency: "usd",
            unit_amount: book.price_cents,
            product_data: {
              name: book.title,
              description: `${book.author} · ${book.year} · Printed to order`,
              images: book.cover_url ? [book.cover_url] : [],
            },
          },
          quantity: 1,
        },
      ],
      mode: "payment",
      // Collect shipping address
      shipping_address_collection: {
        allowed_countries: ["US", "CA", "GB", "AU"],
      },
      // Pre-fill customer details
      billing_address_collection: "required",
      success_url: `${siteUrl}/catalog/${bookId}/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${siteUrl}/catalog/${bookId}`,
      metadata: { bookId, bookTitle: book.title },
    });

    return NextResponse.json({ sessionId: session.id });
  } catch (err: unknown) {
    console.error("Checkout error:", err);
    const message = err instanceof Error ? err.message : "Internal error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
