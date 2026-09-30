import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book, BookSet } from "@/lib/supabase";
import { setPriceCents, sortVolumes, volumeLabel } from "@/lib/sets";
import { clampQuantity, normalizeCart, type CartItem } from "@/lib/cart";
import {
  DEFAULT_FORMAT,
  FORMAT_LABELS,
  formatPriceCents,
  formatPrintCostCents,
  formatSuffix,
  hasFormat,
  isBookFormat,
  type BookFormat,
} from "@/lib/formats";
import { resolveSiteUrl } from "@/lib/site";
import { isWholesaleCode } from "@/lib/pricing";
import { quoteOrderCharges } from "@/lib/shipping";
import {
  DEFAULT_SHIPPING_COUNTRY,
  SHIPPING_COUNTRIES,
  describeDestination,
  isCompleteDestination,
  isShippingCountry,
  type ShippingDestination,
} from "@/lib/shipping-countries";

type LineItem = Stripe.Checkout.SessionCreateParams.LineItem;

function bookLineItem(
  book: Book,
  format: BookFormat,
  unitAmount: number,
  quantity = 1
): LineItem {
  const volume = volumeLabel(book);
  const title = volume ? `${book.title} — ${volume}` : book.title;
  return {
    price_data: {
      currency: "usd",
      unit_amount: unitAmount,
      product_data: {
        name: `${title}${formatSuffix(format)}`,
        description: `${book.author} · ${book.year} · ${FORMAT_LABELS[format]} · Printed to order`,
        images: book.cover_url ? [book.cover_url] : [],
        // The webhook reads this back to learn exactly what was bought, which
        // a cart of several items cannot fit in session metadata.
        metadata: { bookId: book.id, format },
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
function setLineItems(
  set: BookSet,
  volumes: Book[],
  format: BookFormat,
  quantity = 1
): LineItem[] {
  const prices = volumes.map((v) => formatPriceCents(v, format));
  const target = setPriceCents(set, volumes, format);
  const subtotal = prices.reduce((sum, p) => sum + p, 0);

  if (target === subtotal || subtotal === 0) {
    return volumes.map((v, i) => bookLineItem(v, format, prices[i], quantity));
  }

  const amounts = prices.map((p) => Math.round((p / subtotal) * target));
  const drift = target - amounts.reduce((sum, a) => sum + a, 0);
  amounts[0] += drift;

  return volumes.map((v, i) => bookLineItem(v, format, Math.max(1, amounts[i]), quantity));
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    // A cart posts `items`; the single "buy this" buttons post one bookId or
    // setId (and a format). They are the same purchase, so normalize to a
    // cart of one.
    const format: BookFormat = isBookFormat(body.format) ? body.format : DEFAULT_FORMAT;
    const items: CartItem[] = body.items
      ? normalizeCart(body.items)
      : body.bookId
        ? [{ kind: "book", id: String(body.bookId), format, quantity: 1 }]
        : body.setId
          ? [{ kind: "set", id: String(body.setId), format, quantity: 1 }]
          : [];

    if (items.length === 0) {
      return NextResponse.json(
        { error: "items, bookId or setId is required" },
        { status: 400 }
      );
    }

    const promoCode = typeof body.promoCode === "string" ? body.promoCode.trim() : "";
    const wholesale = promoCode !== "" && isWholesaleCode(promoCode);
    if (promoCode && !wholesale) {
      return NextResponse.json({ error: "That promo code isn't valid." }, { status: 400 });
    }

    // The destination decides shipping and Lulu's sales tax. Pages cached from
    // before postcodes were asked for still send a bare `country`, which is
    // quoted at a typical address in that country instead.
    const destination: ShippingDestination | null = isCompleteDestination(body.destination)
      ? {
          country: body.destination.country,
          region: body.destination.region || undefined,
          postcode: String(body.destination.postcode).trim().toUpperCase(),
        }
      : null;
    const country = destination?.country ?? body.country ?? DEFAULT_SHIPPING_COUNTRY;
    if (!isShippingCountry(country)) {
      return NextResponse.json({ error: "We don't ship to that country yet." }, { status: 400 });
    }
    if (body.destination && !destination) {
      return NextResponse.json(
        { error: "Choose where to ship, including your state and postcode." },
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
    // Everything being printed, for the shipping quote
    const shipped: Array<{ book: Book; format: BookFormat; quantity: number }> = [];

    for (const item of items) {
      const quantity = clampQuantity(item.quantity);
      let set: BookSet | undefined;
      let books: Book[];

      if (item.kind === "book") {
        const book = booksById.get(item.id);
        if (!book) {
          return NextResponse.json({ error: "Book not found" }, { status: 404 });
        }
        books = [book];
      } else {
        set = setsById.get(item.id);
        if (!set) {
          return NextResponse.json({ error: "Set not found" }, { status: 404 });
        }
        books = sortVolumes(allVolumes.filter((v) => v.set_id === set!.id));
        if (books.length === 0) {
          return NextResponse.json({ error: "This set has no volumes yet" }, { status: 404 });
        }
      }

      const { format } = item;
      const missing = books.find((b) => !hasFormat(b, format));
      if (missing) {
        return NextResponse.json(
          { error: `${missing.title} isn't available in ${format}` },
          { status: 409 }
        );
      }

      shipped.push(...books.map((book) => ({ book, format, quantity })));

      if (wholesale) {
        // At cost, every book is its print cost — sets included, volume by
        // volume, since a bundle discount is a cut of the margin that is gone.
        const unpriced = books.find((b) => formatPrintCostCents(b, format) == null);
        if (unpriced) {
          return NextResponse.json(
            { error: `${unpriced.title} has no print cost on record yet` },
            { status: 409 }
          );
        }
        lineItems.push(
          ...books.map((b) => bookLineItem(b, format, formatPrintCostCents(b, format)!, quantity))
        );
      } else if (set) {
        lineItems.push(...setLineItems(set, books, format, quantity));
      } else {
        lineItems.push(bookLineItem(books[0], format, formatPriceCents(books[0], format), quantity));
      }
    }

    // Shipping and tax are what Lulu charges for this exact order, promo code
    // or not.
    const charges = await quoteOrderCharges(shipped, destination ?? country);
    if (!charges.ok) {
      return "unpriced" in charges
        ? NextResponse.json(
            { error: `${charges.unpriced} can't be shipped yet — it has no page count on record` },
            { status: 409 }
          )
        : NextResponse.json({ error: charges.invalidDestination }, { status: 400 });
    }

    // Lulu's sales tax on the books, shipping and fee, as its own line so the
    // book prices stay the ones the catalog shows. Nothing at all where the
    // rate is zero (Oregon, the UK).
    if (charges.taxCents > 0) {
      lineItems.push({
        price_data: {
          currency: "usd",
          unit_amount: charges.taxCents,
          product_data: {
            name: "Sales tax",
            description: destination
              ? `Charged by our printer for delivery to ${describeDestination(destination)}`
              : "Charged by our printer",
          },
        },
        quantity: 1,
      });
    }

    // Where the customer lands afterwards: back where they started for a
    // single purchase, on the cart's own confirmation for a real cart.
    const single = items.length === 1 && items[0].quantity === 1 ? items[0] : null;
    const singleSet = single?.kind === "set" ? setsById.get(single.id) : undefined;

    let successUrl = `${siteUrl}/cart/success?session_id={CHECKOUT_SESSION_ID}`;
    let cancelUrl = `${siteUrl}/cart`;
    const metadata: Record<string, string> = { itemCount: String(items.length) };
    // Marks the order in Stripe as sold at cost; the code itself is not stored.
    if (wholesale) metadata.pricing = "wholesale";
    // What tax was quoted for, so the webhook can notice an address elsewhere
    if (destination) {
      metadata.taxRegion = destination.region ?? "";
      metadata.taxPostcode = destination.postcode;
    }

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
      // Shipping was quoted for this country, so only accept addresses in it
      shipping_address_collection: { allowed_countries: [country] },
      shipping_options: [
        {
          shipping_rate_data: {
            type: "fixed_amount",
            fixed_amount: { amount: charges.shippingCents, currency: "usd" },
            display_name: `Shipping to ${SHIPPING_COUNTRIES[country]}`,
          },
        },
      ],
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
