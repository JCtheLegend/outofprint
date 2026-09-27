import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book, BookSet } from "@/lib/supabase";
import { setPriceCents, sortVolumes, volumeLabel } from "@/lib/sets";
import { clampQuantity, normalizeCart, type CartItem } from "@/lib/cart";

type LineItem = Stripe.Checkout.SessionCreateParams.LineItem;

/**
 * Absolute base URL for the URLs Stripe sends the customer back to.
 *
 * NEXT_PUBLIC_* values are inlined at build time, so a deploy built without
 * NEXT_PUBLIC_SITE_URL leaves Stripe with "undefined/catalog/..." and it
 * refuses the session: "Invalid URL: An explicit scheme (such as https) must
 * be provided". The request always knows the real origin, so fall back to it
 * and only trust the configured value when it is a usable absolute URL.
 */
function resolveSiteUrl(req: NextRequest): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL;
  if (configured && /^https?:\/\//i.test(configured)) {
    return configured.replace(/\/+$/, "");
  }
  return new URL(req.url).origin;
}

function bookLineItem(book: Book, unitAmount: number, quantity = 1): LineItem {
  const volume = volumeLabel(book);
  return {
    price_data: {
      currency: "usd",
      unit_amount: unitAmount,
      product_data: {
        name: volume ? `${book.title} — ${volume}` : book.title,
        description: `${book.author} · ${book.year} · Printed to order`,
        images: book.cover_url ? [book.cover_url] : [],
        // The webhook reads this back to learn exactly which books were bought,
        // which a cart of several items cannot fit in session metadata.
        metadata: { bookId: book.id },
      },
    },
    quantity,
  };
}

/**
 * A set is charged as one line item per volume so the customer sees what they
 * are getting. When the set carries a bundle price we spread the discount
 * across the volumes (remainder cents land on the first one) so the session
 * total matches the advertised set price exactly.
 */
function setLineItems(set: BookSet, volumes: Book[], quantity = 1): LineItem[] {
  const target = setPriceCents(set, volumes);
  const subtotal = volumes.reduce((sum, v) => sum + v.price_cents, 0);

  if (target === subtotal || subtotal === 0) {
    return volumes.map((v) => bookLineItem(v, v.price_cents, quantity));
  }

  const amounts = volumes.map((v) => Math.round((v.price_cents / subtotal) * target));
  const drift = target - amounts.reduce((sum, a) => sum + a, 0);
  amounts[0] += drift;

  return volumes.map((v, i) => bookLineItem(v, Math.max(1, amounts[i]), quantity));
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // A cart posts `items`; the single "buy this" buttons post one bookId or
    // setId. They are the same purchase, so normalize to a cart of one.
    const items: CartItem[] = body.items
      ? normalizeCart(body.items)
      : body.bookId
        ? [{ kind: "book", id: String(body.bookId), quantity: 1 }]
        : body.setId
          ? [{ kind: "set", id: String(body.setId), quantity: 1 }]
          : [];

    if (items.length === 0) {
      return NextResponse.json(
        { error: "items, bookId or setId is required" },
        { status: 400 }
      );
    }

    const db = supabaseAdmin();
    const siteUrl = resolveSiteUrl(req);

    const bookIds = items.filter((i) => i.kind === "book").map((i) => i.id);
    const setIds = items.filter((i) => i.kind === "set").map((i) => i.id);

    const [booksRes, setsRes, volumesRes] = await Promise.all([
      bookIds.length
        ? db.from("books").select("*").in("id", bookIds)
        : Promise.resolve({ data: [] as Book[], error: null }),
      setIds.length
        ? db.from("book_sets").select("*").in("id", setIds)
        : Promise.resolve({ data: [] as BookSet[], error: null }),
      setIds.length
        ? db.from("books").select("*").in("set_id", setIds)
        : Promise.resolve({ data: [] as Book[], error: null }),
    ]);

    const booksById = new Map<string, Book>((booksRes.data ?? []).map((b: Book) => [b.id, b]));
    const setsById = new Map<string, BookSet>((setsRes.data ?? []).map((s: BookSet) => [s.id, s]));
    const allVolumes = (volumesRes.data ?? []) as Book[];

    const lineItems: LineItem[] = [];

    for (const item of items) {
      const quantity = clampQuantity(item.quantity);

      if (item.kind === "book") {
        const book = booksById.get(item.id);
        if (!book) {
          return NextResponse.json({ error: "Book not found" }, { status: 404 });
        }
        lineItems.push(bookLineItem(book, book.price_cents, quantity));
        continue;
      }

      const set = setsById.get(item.id);
      if (!set) {
        return NextResponse.json({ error: "Set not found" }, { status: 404 });
      }
      const volumes = sortVolumes(allVolumes.filter((v) => v.set_id === set.id));
      if (volumes.length === 0) {
        return NextResponse.json({ error: "This set has no volumes yet" }, { status: 404 });
      }
      lineItems.push(...setLineItems(set, volumes, quantity));
    }

    // Where the customer lands afterwards: back where they started for a
    // single purchase, on the cart's own confirmation for a real cart.
    const single = items.length === 1 && items[0].quantity === 1 ? items[0] : null;
    const singleSet = single?.kind === "set" ? setsById.get(single.id) : undefined;

    let successUrl = `${siteUrl}/cart/success?session_id={CHECKOUT_SESSION_ID}`;
    let cancelUrl = `${siteUrl}/cart`;
    const metadata: Record<string, string> = { itemCount: String(items.length) };

    if (single?.kind === "book") {
      successUrl = `${siteUrl}/catalog/${single.id}/success?session_id={CHECKOUT_SESSION_ID}`;
      cancelUrl = `${siteUrl}/catalog/${single.id}`;
      metadata.bookId = single.id;
      metadata.bookTitle = booksById.get(single.id)?.title ?? "";
    } else if (singleSet) {
      successUrl = `${siteUrl}/catalog/set/${singleSet.slug}/success?session_id={CHECKOUT_SESSION_ID}`;
      cancelUrl = `${siteUrl}/catalog/set/${singleSet.slug}`;
      metadata.setId = singleSet.id;
      metadata.setTitle = singleSet.title;
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
