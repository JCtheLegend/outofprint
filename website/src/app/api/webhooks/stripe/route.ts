import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe, webhookCryptoProvider } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book } from "@/lib/supabase";
import { sortVolumes, volumeLabel } from "@/lib/sets";
import { orderStatusUrl, resolveSiteUrl } from "@/lib/site";
import { createPrintJob } from "@/lib/print";
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
async function purchasedQuantities(
  session: Stripe.Checkout.Session,
  db: ReturnType<typeof supabaseAdmin>
): Promise<Map<string, number>> {
  const quantities = new Map<string, number>();

  const lineItems = await stripe.checkout.sessions.listLineItems(session.id, {
    limit: 100,
    expand: ["data.price.product"],
  });

  for (const line of lineItems.data) {
    const product = line.price?.product;
    const bookId =
      product && typeof product !== "string" && !("deleted" in product && product.deleted)
        ? product.metadata?.bookId
        : undefined;
    if (!bookId) continue;
    quantities.set(bookId, (quantities.get(bookId) ?? 0) + (line.quantity ?? 1));
  }

  if (quantities.size > 0) return quantities;

  const { bookId, setId } = session.metadata ?? {};
  if (setId) {
    const { data } = await db.from("books").select("id").eq("set_id", setId);
    for (const row of data ?? []) quantities.set(row.id, 1);
  } else if (bookId) {
    quantities.set(bookId, 1);
  }

  return quantities;
}

async function handleSuccessfulPayment(session: Stripe.Checkout.Session, siteUrl: string) {
  const db = supabaseAdmin();
  const { bookId, bookTitle, setId, setTitle } = session.metadata ?? {};

  // Extract shipping address
  const shipping = session.shipping_details?.address;
  const customerName =
    session.shipping_details?.name ?? session.customer_details?.name ?? "Customer";
  const customerEmail = session.customer_details?.email ?? "";

  // One purchase can cover several books and several copies of each — every
  // book is its own order row, and all of them print as one job.
  const quantities = await purchasedQuantities(session, db);

  if (quantities.size === 0) {
    throw new Error(`Could not tell what session ${session.id} bought`);
  }

  const { data: bookRows, error: booksError } = await db
    .from("books")
    .select("*")
    .in("id", Array.from(quantities.keys()));

  if (booksError || !bookRows?.length) {
    throw new Error(
      `Books not found for session ${session.id}: ${booksError?.message ?? "none matched"}`
    );
  }

  const books: Book[] = sortVolumes(bookRows);
  const quantityFor = (book: Book) => quantities.get(book.id) ?? 1;

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
  // Rows are keyed on (stripe_session_id, book_id), so a redelivered event
  // re-uses the rows it already wrote rather than duplicating the order.
  const { error: insertError } = await db.from("orders").upsert(
    books.map((book) => ({
      book_id: book.id,
      set_id: setId ?? null,
      stripe_session_id: session.id,
      customer_email: customerEmail,
      customer_name: customerName,
      shipping_address: shipping ?? {},
      quantity: quantityFor(book),
      status: "paid",
    })),
    { onConflict: "stripe_session_id,book_id", ignoreDuplicates: true }
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

  const booksById = new Map(books.map((b) => [b.id, b]));
  const orders = orderRows
    .map((row) => ({ id: row.id as string, printJobId: row.print_job_id as string | null, book: booksById.get(row.book_id)! }))
    .filter((o) => o.book);

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
      books: orders.map(({ id, book }) => {
        const volume = volumeLabel(book);
        return {
          orderId: id,
          title: volume ? `${book.title} — ${volume}` : book.title,
          interiorUrl: book.pdf_url,
          coverUrl: book.cover_pdf_url,
          podPackageId: book.pod_package_id,
          quantity: quantityFor(book),
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
    const titleOf = (book: Book) => {
      const volume = volumeLabel(book);
      return volume ? `${volume} — ${book.title}` : book.title;
    };

    if (setId) {
      await sendSetOrderConfirmation(
        customerEmail,
        customerName,
        setTitle ?? books[0].title,
        books.map(titleOf),
        orderIds[0],
        orderStatusUrl(siteUrl, orderIds[0])
      );
    } else if (books.length === 1 && quantityFor(books[0]) === 1) {
      await sendOrderConfirmation(
        customerEmail,
        customerName,
        bookTitle ?? books[0].title,
        orderIds[0],
        orderStatusUrl(siteUrl, orderIds[0])
      );
    } else {
      await sendCartOrderConfirmation(
        customerEmail,
        customerName,
        books.map((book) => ({ title: titleOf(book), quantity: quantityFor(book) })),
        orderIds[0],
        orderStatusUrl(siteUrl, orderIds[0])
      );
    }
  } catch (err) {
    console.error("Confirmation email failed:", err);
  }
}
