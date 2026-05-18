import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin } from "@/lib/supabase";
import { createPrintJob } from "@/lib/print";
import { sendOrderConfirmation } from "@/lib/email";

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
  const { bookId, bookTitle } = session.metadata ?? {};

  if (!bookId) {
    console.error("No bookId in session metadata");
    return;
  }

  // Extract shipping address
  const shipping = session.shipping_details?.address;
  const customerName =
    session.shipping_details?.name ?? session.customer_details?.name ?? "Customer";
  const customerEmail = session.customer_details?.email ?? "";

  // Create order record in Supabase
  const { data: order, error: orderError } = await db
    .from("orders")
    .insert({
      book_id: bookId,
      stripe_session_id: session.id,
      customer_email: customerEmail,
      customer_name: customerName,
      shipping_address: shipping ?? {},
      status: "paid",
    })
    .select()
    .single();

  if (orderError || !order) {
    console.error("Failed to create order:", orderError);
    return;
  }

  // Fetch book PDF URL
  const { data: book } = await db
    .from("books")
    .select("pdf_url, title")
    .eq("id", bookId)
    .single();

  if (!book) {
    console.error("Book not found for order:", bookId);
    return;
  }

  try {
    // Fire print job
    const printJob = await createPrintJob({
      orderId: order.id,
      bookTitle: book.title,
      pdfUrl: book.pdf_url,
      customerName,
      shippingAddress: {
        line1: shipping?.line1 ?? "",
        line2: shipping?.line2 ?? undefined,
        city: shipping?.city ?? "",
        state: shipping?.state ?? "",
        postal_code: shipping?.postal_code ?? "",
        country: shipping?.country ?? "US",
      },
    });

    // Update order with print job ID
    await db
      .from("orders")
      .update({ print_job_id: printJob.printJobId, status: "printing" })
      .eq("id", order.id);

    // Send confirmation email
    await sendOrderConfirmation(customerEmail, customerName, bookTitle ?? book.title, order.id);
  } catch (err) {
    console.error("Print job or email failed:", err);
    // Order is still saved — you can retry manually from Supabase dashboard
  }
}
