import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { sessionShipping, stripe, webhookCryptoProvider } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book } from "@/lib/supabase";
import { sortVolumes, volumeLabel } from "@/lib/sets";
import { orderStatusUrl, resolveSiteUrl } from "@/lib/site";
import { createPrintJob } from "@/lib/print";
import {
  BOOK_FORMATS,
  DEFAULT_FORMAT,
  formatCoverPdfUrl,
  formatPodPackageId,
  formatSuffix,
  isBookFormat,
  type BookFormat,
} from "@/lib/formats";
import {
  sendCartOrderConfirmation,
  sendOrderConfirmation,
  sendPrintJobFailureAlert,
  sendSetOrderConfirmation,
} from "@/lib/email";

// Disable body parsing — Stripe needs the raw body for signature verification
export const config = { api: { bodyParser: false } };

export async function POST(req: NextRequest) {
  const body = await req.text();
  const sig = req.headers.get("stripe-signature");

  let event: Stripe.Event;

  try {
    // Async + WebCrypto: the synchronous form needs Node's crypto module,
    // which the Workers runtime does not provide.
    event = await stripe.webhooks.constructEventAsync(
      body,
      sig!,
      process.env.STRIPE_WEBHOOK_SECRET!,
      undefined,
      webhookCryptoProvider
    );
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Webhook error";
    console.error("Webhook signature failed:", message);
    return NextResponse.json({ error: message }, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    try {
      await handleSuccessfulPayment(session, resolveSiteUrl(req));
    } catch (err) {
      // The customer has paid. Acknowledging a failure here would drop the
      // order on the floor, so report it and let Stripe redeliver — the
      // handler is idempotent, so a retry picks up wherever this left off.
      const reason = err instanceof Error ? err.message : String(err);
      console.error(`Failed to fulfil session ${session.id}:`, err);
      return NextResponse.json({ error: reason }, { status: 500 });
    }
  }

  return NextResponse.json({ received: true });
}

/**
 * How many of each book a session bought.
 *
 * Every line item carries its book id in the product metadata, which is the
 * only place a cart of several books fits — session metadata is capped at 500
 * characters per value. Sessions created before carts existed have no such
 * metadata, so fall back to the bookId/setId they did carry.
 */
type Purchase = { bookId: string; format: BookFormat; quantity: number };

async function purchasedItems(
  session: Stripe.Checkout.Session,
  db: ReturnType<typeof supabaseAdmin>
): Promise<Purchase[]> {
  // Keyed on book and format: a paperback and a hardcover of one book are two
  // purchases, while the same one on two line items (never expected) adds up.
  const purchases = new Map<string, Purchase>();

  const lineItems = await stripe.checkout.sessions.listLineItems(session.id, {
    limit: 100,
    expand: ["data.price.product"],
  });

  for (const line of lineItems.data) {
    const product = line.price?.product;
    const metadata =
      product && typeof product !== "string" && !("deleted" in product && product.deleted)
        ? product.metadata
        : undefined;
    const bookId = metadata?.bookId;
    if (!bookId) continue;
    // Sessions from before hardcovers existed carry no format: paperback
    const format = isBookFormat(metadata?.format) ? metadata.format : DEFAULT_FORMAT;
    const key = `${bookId}:${format}`;
    const quantity = (purchases.get(key)?.quantity ?? 0) + (line.quantity ?? 1);
    purchases.set(key, { bookId, format, quantity });
  }

  if (purchases.size > 0) return Array.from(purchases.values());

  const { bookId, setId } = session.metadata ?? {};
  if (setId) {
    const { data } = await db.from("books").select("id").eq("set_id", setId);
    return (data ?? []).map((row) => ({ bookId: row.id, format: DEFAULT_FORMAT, quantity: 1 }));
  }
  return bookId ? [{ bookId, format: DEFAULT_FORMAT, quantity: 1 }] : [];
}

async function handleSuccessfulPayment(session: Stripe.Checkout.Session, siteUrl: string) {
  const db = supabaseAdmin();
  const { bookId, bookTitle, setId, setTitle } = session.metadata ?? {};

  // Extract shipping address
  const shippingSnapshot = sessionShipping(session);
  const shipping = shippingSnapshot.address;
  const customerName =
    shippingSnapshot.name ?? session.customer_details?.name ?? "Customer";
  const customerEmail = session.customer_details?.email ?? "";

  // Tax was quoted for the postcode chosen before checkout. Stripe can't hold
  // the customer to it, so note when the address typed in differs — Lulu will
  // charge that address's rate, not the one the customer paid.
  const { taxRegion, taxPostcode } = session.metadata ?? {};
  const shippedPostcode = shipping?.postal_code?.trim().toUpperCase();
  if (
    taxPostcode &&
    shippedPostcode &&
    (shippedPostcode.slice(0, 3) !== taxPostcode.slice(0, 3) ||
      (taxRegion && shipping?.state && shipping.state !== taxRegion))
  ) {
    console.warn(
      `Session ${session.id}: tax quoted for ${taxRegion} ${taxPostcode}, ` +
        `but shipping to ${shipping?.state ?? ""} ${shippedPostcode}`
    );
  }

  // One purchase can cover several books and several copies of each — every
  // book is its own order row, and all of them print as one job.
  const purchases = await purchasedItems(session, db);

  if (purchases.length === 0) {
    throw new Error(`Could not tell what session ${session.id} bought`);
  }

  const { data: bookRows, error: booksError } = await db
    .from("books")
    .select("*")
    .in("id", Array.from(new Set(purchases.map((p) => p.bookId))));

  if (booksError || !bookRows?.length) {
    throw new Error(
      `Books not found for session ${session.id}: ${booksError?.message ?? "none matched"}`
    );
  }

  // Volume order, and paperback before hardcover within a book
  const bookOrder = new Map(sortVolumes(bookRows).map((b, i) => [b.id, i]));
  const booksById = new Map<string, Book>(bookRows.map((b: Book) => [b.id, b]));
  const lines = purchases
    .filter((p) => booksById.has(p.bookId))
    .map((p) => ({ ...p, book: booksById.get(p.bookId)! }))
    .sort(
      (a, b) =>
        bookOrder.get(a.bookId)! - bookOrder.get(b.bookId)! ||
        BOOK_FORMATS.indexOf(a.format) - BOOK_FORMATS.indexOf(b.format)
    );

  const shippingAddress = {
    line1: shipping?.line1 ?? "",
    line2: shipping?.line2 ?? undefined,
    city: shipping?.city ?? "",
    state: shipping?.state ?? "",
    postal_code: shipping?.postal_code ?? "",
    country: shipping?.country ?? "US",
  };

  // All the books in this checkout print and ship together as one Lulu job,
  // but each keeps its own order row so a volume can be tracked individually.
  // Rows are keyed on (stripe_session_id, book_id, format), so a redelivered
  // event re-uses the rows it already wrote rather than duplicating the order.
  const { error: insertError } = await db.from("orders").upsert(
    lines.map(({ book, format, quantity }) => ({
      book_id: book.id,
      format,
      set_id: setId ?? null,
      stripe_session_id: session.id,
      customer_email: customerEmail,
      customer_name: customerName,
      shipping_address: shipping ?? {},
      quantity,
      status: "paid",
    })),
    { onConflict: "stripe_session_id,book_id,format", ignoreDuplicates: true }
  );

  if (insertError) {
    // Almost always a credentials problem: writing orders needs the service
    // role key, since RLS gives the anon key no access to the table.
    throw new Error(
      `Could not record the order for session ${session.id}: ${insertError.message} ` +
        `(code ${insertError.code}). Check SUPABASE_SERVICE_ROLE_KEY.`
    );
  }

  const { data: orderRows, error: readError } = await db
    .from("orders")
    .select("*")
    .eq("stripe_session_id", session.id);

  if (readError || !orderRows?.length) {
    throw new Error(
      `No order rows for session ${session.id} after writing them: ${readError?.message ?? "none found"}`
    );
  }

  const lineFor = (row: { book_id: string; format: string | null }) =>
    lines.find((l) => l.bookId === row.book_id && l.format === (row.format ?? DEFAULT_FORMAT));
  const orders = orderRows
    .map((row) => ({
      id: row.id as string,
      printJobId: row.print_job_id as string | null,
      line: lineFor(row)!,
    }))
    .filter((o) => o.line)
    .sort((a, b) => lines.indexOf(a.line) - lines.indexOf(b.line));

  const orderIds = orders.map((o) => o.id);

  // A redelivery after the print job already went through must not order a
  // second copy of the book.
  if (orders.every((o) => o.printJobId)) {
    console.log(`Session ${session.id} already has print job ${orders[0].printJobId}; nothing to do`);
    return;
  }

  try {
    // Send the print request to Lulu
    const printJob = await createPrintJob({
      externalId: session.id,
      customerName,
      customerEmail,
      customerPhone: session.customer_details?.phone,
      shippingAddress,
      books: orders.map(({ id, line: { book, format, quantity } }) => {
        const volume = volumeLabel(book);
        const title = volume ? `${book.title} — ${volume}` : book.title;
        return {
          orderId: id,
          title: `${title}${formatSuffix(format)}`,
          interiorUrl: book.pdf_url,
          // The hardcover prints from its own wraparound and SKU
          coverUrl: formatCoverPdfUrl(book, format),
          podPackageId: formatPodPackageId(book, format),
          quantity,
        };
      }),
    });

    // Record the print job against every order it covers
    await db
      .from("orders")
      .update({ print_job_id: printJob.printJobId, status: "printing" })
      .in("id", orderIds);

    console.log(
      `Lulu print job ${printJob.printJobId} (${printJob.status}) created for session ${session.id}`
    );
  } catch (err) {
    // The orders are saved and paid — leaving them in "paid" marks them as
    // needing a print job, which can be resubmitted without charging again.
    const reason = err instanceof Error ? err.message : String(err);
    console.error(`Lulu print job failed for session ${session.id}:`, err);
    try {
      await sendPrintJobFailureAlert(orderIds, customerEmail, reason);
    } catch (alertErr) {
      console.error("Could not send the print-job failure alert:", alertErr);
    }
    // Let Stripe redeliver: the orders are already recorded, so a retry only
    // repeats the print request.
    throw new Error(`Lulu print job failed: ${reason}`);
  }

  try {
    // Send confirmation email — one bought a set, one bought a single book,
    // and anything else came from a cart.
    const titleOf = ({ book, format }: { book: Book; format: BookFormat }) => {
      const volume = volumeLabel(book);
      return `${volume ? `${volume} — ${book.title}` : book.title}${formatSuffix(format)}`;
    };

    if (setId) {
      await sendSetOrderConfirmation(
        customerEmail,
        customerName,
        `${setTitle ?? lines[0].book.title}${formatSuffix(lines[0].format)}`,
        lines.map(titleOf),
        orderIds[0],
        orderStatusUrl(siteUrl, orderIds[0])
      );
    } else if (lines.length === 1 && lines[0].quantity === 1) {
      await sendOrderConfirmation(
        customerEmail,
        customerName,
        `${bookTitle ?? lines[0].book.title}${formatSuffix(lines[0].format)}`,
        orderIds[0],
        orderStatusUrl(siteUrl, orderIds[0])
      );
    } else {
      await sendCartOrderConfirmation(
        customerEmail,
        customerName,
        lines.map((line) => ({ title: titleOf(line), quantity: line.quantity })),
        orderIds[0],
        orderStatusUrl(siteUrl, orderIds[0])
      );
    }
  } catch (err) {
    console.error("Confirmation email failed:", err);
  }
}
