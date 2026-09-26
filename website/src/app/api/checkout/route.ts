import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book, BookSet } from "@/lib/supabase";
import { setPriceCents, sortVolumes, volumeLabel } from "@/lib/sets";

type LineItem = Stripe.Checkout.SessionCreateParams.LineItem;

function bookLineItem(book: Book, unitAmount: number): LineItem {
  const volume = volumeLabel(book);
  return {
    price_data: {
      currency: "usd",
      unit_amount: unitAmount,
      product_data: {
        name: volume ? `${book.title} — ${volume}` : book.title,
        description: `${book.author} · ${book.year} · Printed to order`,
        images: book.cover_url ? [book.cover_url] : [],
      },
    },
    quantity: 1,
  };
}

/**
 * A set is charged as one line item per volume so the customer sees what they
 * are getting. When the set carries a bundle price we spread the discount
 * across the volumes (remainder cents land on the first one) so the session
 * total matches the advertised set price exactly.
 */
function setLineItems(set: BookSet, volumes: Book[]): LineItem[] {
  const target = setPriceCents(set, volumes);
  const subtotal = volumes.reduce((sum, v) => sum + v.price_cents, 0);

  if (target === subtotal || subtotal === 0) {
    return volumes.map((v) => bookLineItem(v, v.price_cents));
  }

  const amounts = volumes.map((v) => Math.round((v.price_cents / subtotal) * target));
  const drift = target - amounts.reduce((sum, a) => sum + a, 0);
  amounts[0] += drift;

  return volumes.map((v, i) => bookLineItem(v, Math.max(1, amounts[i])));
}

export async function POST(req: NextRequest) {
  try {
    const { bookId, setId } = await req.json();

    if (!bookId && !setId) {
      return NextResponse.json(
        { error: "bookId or setId is required" },
        { status: 400 }
      );
    }

    const db = supabaseAdmin();
    const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;

    let lineItems: LineItem[];
    let metadata: Record<string, string>;
    let successUrl: string;
    let cancelUrl: string;

    if (setId) {
      const { data: set, error: setError } = await db
        .from("book_sets")
        .select("*")
        .eq("id", setId)
        .single();

      if (setError || !set) {
        return NextResponse.json({ error: "Set not found" }, { status: 404 });
      }

      const { data: volumeRows } = await db.from("books").select("*").eq("set_id", set.id);
      const volumes = sortVolumes(volumeRows ?? []);

      if (volumes.length === 0) {
        return NextResponse.json({ error: "This set has no volumes yet" }, { status: 404 });
      }

      lineItems = setLineItems(set, volumes);
      // The webhook re-reads the volumes from set_id, so only the set needs to
      // ride along in metadata (Stripe caps each value at 500 characters).
      metadata = {
        setId: set.id,
        setTitle: set.title,
        volumeCount: String(volumes.length),
      };
      successUrl = `${siteUrl}/catalog/set/${set.slug}/success?session_id={CHECKOUT_SESSION_ID}`;
      cancelUrl = `${siteUrl}/catalog/set/${set.slug}`;
    } else {
      const { data: book, error } = await db
        .from("books")
        .select("*")
        .eq("id", bookId)
        .single();

      if (error || !book) {
        return NextResponse.json({ error: "Book not found" }, { status: 404 });
      }

      lineItems = [bookLineItem(book, book.price_cents)];
      metadata = { bookId, bookTitle: book.title };
      successUrl = `${siteUrl}/catalog/${bookId}/success?session_id={CHECKOUT_SESSION_ID}`;
      cancelUrl = `${siteUrl}/catalog/${bookId}`;
    }

    // Create Stripe Checkout session
    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      line_items: lineItems,
      mode: "payment",
      // Collect shipping address
      shipping_address_collection: {
        allowed_countries: ["US", "CA", "GB", "AU"],
      },
      // Pre-fill customer details
      billing_address_collection: "required",
      // Lulu's shipping carriers require a phone number for delivery issues
      phone_number_collection: { enabled: true },
      success_url: successUrl,
      cancel_url: cancelUrl,
      metadata,
    });

    return NextResponse.json({ sessionId: session.id });
  } catch (err: unknown) {
    console.error("Checkout error:", err);
    const message = err instanceof Error ? err.message : "Internal error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
