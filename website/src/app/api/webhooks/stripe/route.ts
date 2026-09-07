import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import type { Book } from "@/lib/supabase";
import { sortVolumes, volumeLabel } from "@/lib/sets";
import { createPrintJob } from "@/lib/print";
import { sendOrderConfirmation, sendSetOrderConfirmation } from "@/lib/email";

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

  const orderIds: string[] = [];

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

    orderIds.push(order.id);

    try {
      // Fire print job
      const volume = volumeLabel(book);
      const printJob = await createPrintJob({
        orderId: order.id,
        bookTitle: volume ? `${book.title} — ${volume}` : book.title,
        pdfUrl: book.pdf_url,
        customerName,
        shippingAddress,
      });

      // Update order with print job ID
      await db
        .from("orders")
        .update({ print_job_id: printJob.printJobId, status: "printing" })
        .eq("id", order.id);
    } catch (err) {
      console.error(`Print job failed for book ${book.id}:`, err);
      // Order is still saved — you can retry manually from Supabase dashboard
    }
  }

  if (orderIds.length === 0) return;

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
