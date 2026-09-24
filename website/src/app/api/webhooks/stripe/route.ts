import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book } from "@/lib/supabase";
import { sortVolumes, volumeLabel } from "@/lib/sets";
import { createPrintJob } from "@/lib/print";
import {
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
    event = stripe.webhooks.constructEvent(
      body,
      sig!,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Webhook error";
    console.error("Webhook signature failed:", message);
    return NextResponse.json({ error: message }, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    await handleSuccessfulPayment(session);
  }

  return NextResponse.json({ received: true });
}

async function handleSuccessfulPayment(session: Stripe.Checkout.Session) {
  const db = supabaseAdmin();
  const { bookId, bookTitle, setId, setTitle } = session.metadata ?? {};

  if (!bookId && !setId) {
    console.error("No bookId or setId in session metadata");
    return;
  }

  // Extract shipping address
  const shipping = session.shipping_details?.address;
  const customerName =
    session.shipping_details?.name ?? session.customer_details?.name ?? "Customer";
  const customerEmail = session.customer_details?.email ?? "";

  // One purchase can cover several volumes — each is its own book, order row
  // and print job.
  let books: Book[];

  if (setId) {
    const { data, error } = await db.from("books").select("*").eq("set_id", setId);
    if (error || !data?.length) {
      console.error("No volumes found for set:", setId, error);
      return;
    }
    books = sortVolumes(data);
  } else {
    const { data, error } = await db.from("books").select("*").eq("id", bookId).single();
    if (error || !data) {
      console.error("Book not found for order:", bookId, error);
      return;
    }
    books = [data];
  }

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
  const orders: { id: string; book: Book }[] = [];

  for (const book of books) {
    // Create order record in Supabase
    const { data: order, error: orderError } = await db
      .from("orders")
      .insert({
        book_id: book.id,
        set_id: setId ?? null,
        stripe_session_id: session.id,
        customer_email: customerEmail,
        customer_name: customerName,
        shipping_address: shipping ?? {},
        status: "paid",
      })
      .select()
      .single();

    if (orderError || !order) {
      console.error(`Failed to create order for book ${book.id}:`, orderError);
      continue;
    }

    orders.push({ id: order.id, book });
  }

  const orderIds = orders.map((o) => o.id);
  if (orderIds.length === 0) return;

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
  }

  try {
    // Send confirmation email
    if (setId) {
      await sendSetOrderConfirmation(
        customerEmail,
        customerName,
        setTitle ?? books[0].title,
        books.map((b) => {
          const volume = volumeLabel(b);
          return volume ? `${volume} — ${b.title}` : b.title;
        }),
        orderIds[0]
      );
    } else {
      await sendOrderConfirmation(
        customerEmail,
        customerName,
        bookTitle ?? books[0].title,
        orderIds[0]
      );
    }
  } catch (err) {
    console.error("Confirmation email failed:", err);
  }
}
