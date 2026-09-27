import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin, type Order } from "@/lib/supabase";
import { verifyLuluWebhook, type LuluLineItemStatus, type LuluWebhookPayload } from "@/lib/lulu";
import { resolveSiteUrl, orderStatusUrl } from "@/lib/site";
import { sendShipmentNotification } from "@/lib/email";

/**
 * Lulu print job status updates.
 *
 * Lulu posts here every time one of our print jobs changes state. We record
 * the status against every order row that job covers and, the first time a
 * shipment appears, email the customer their tracking link.
 */

/** Lulu's states, mapped onto the ones `orders.status` allows. */
function orderStatusFor(luluStatus: string): Order["status"] | null {
  switch (luluStatus) {
    case "CREATED":
    case "UNPAID":
    case "PAYMENT_IN_PROGRESS":
    case "PRODUCTION_DELAYED":
    case "PRODUCTION_READY":
    case "IN_PRODUCTION":
      return "printing";
    case "SHIPPED":
      return "shipped";
    case "DELIVERED":
      return "delivered";
    default:
      // REJECTED / CANCELED have no order status of their own; the raw Lulu
      // status is still recorded so the failure is visible.
      return null;
  }
}

function trackingFrom(lineItem: LuluLineItemStatus | undefined) {
  const messages = lineItem?.status?.messages;
  if (!messages) return null;
  const urls = Array.isArray(messages.tracking_urls)
    ? messages.tracking_urls
    : messages.tracking_urls
      ? [messages.tracking_urls]
      : [];
  if (urls.length === 0 && !messages.tracking_id) return null;
  return {
    tracking_id: messages.tracking_id ?? null,
    tracking_carrier: messages.carrier_name ?? null,
    tracking_urls: urls,
  };
}

export async function POST(req: NextRequest) {
  const rawBody = await req.text();

  if (!(await verifyLuluWebhook(rawBody, req.headers.get("Lulu-HMAC-SHA256")))) {
    console.error("Lulu webhook rejected: bad or missing HMAC signature");
    return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
  }

  let payload: LuluWebhookPayload;
  try {
    payload = JSON.parse(rawBody) as LuluWebhookPayload;
  } catch {
    return NextResponse.json({ error: "Malformed payload" }, { status: 400 });
  }

  if (payload.topic !== "PRINT_JOB_STATUS_CHANGED" || !payload.data?.id) {
    // Unknown topics are acknowledged — Lulu deactivates a webhook after five
    // consecutive failures, so never fail on something we simply ignore.
    return NextResponse.json({ received: true });
  }

  const db = supabaseAdmin();
  const printJobId = String(payload.data.id);
  const luluStatus = payload.data.status?.name ?? "UNKNOWN";

  const { data: orders, error } = await db
    .from("orders")
    .select("*")
    .eq("print_job_id", printJobId);

  if (error) {
    // Report the failure so Lulu retries rather than losing the update.
    console.error(`Lulu webhook: could not read orders for print job ${printJobId}:`, error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  if (!orders?.length) {
    console.warn(`Lulu webhook: no orders reference print job ${printJobId}`);
    return NextResponse.json({ received: true });
  }

  const status = orderStatusFor(luluStatus);
  const lineItems = payload.data.line_items ?? [];
  const shippedNow: Order[] = [];

  for (const order of orders as Order[]) {
    // Line items carry our order id, so tracking lands on the right book
    const lineItem =
      lineItems.find((item) => item.external_id === order.id) ??
      (lineItems.length === 1 ? lineItems[0] : undefined);
    const tracking = trackingFrom(lineItem);

    const update: Record<string, unknown> = { lulu_status: luluStatus };
    if (status) update.status = status;
    if (tracking) Object.assign(update, tracking);
    if (status === "shipped" && !order.shipped_at) update.shipped_at = new Date().toISOString();

    const { error: updateError } = await db.from("orders").update(update).eq("id", order.id);
    if (updateError) {
      console.error(`Lulu webhook: could not update order ${order.id}:`, updateError);
      return NextResponse.json({ error: updateError.message }, { status: 500 });
    }

    // Only the transition into "shipped" sends mail, so redeliveries are quiet
    if (status === "shipped" && order.status !== "shipped" && !order.shipped_at) {
      shippedNow.push({ ...order, ...(tracking ?? {}) } as Order);
    }
  }

  if (shippedNow.length > 0) {
    try {
      const siteUrl = resolveSiteUrl(req);
      const { data: books } = await db
        .from("books")
        .select("id,title,volume_label")
        .in("id", shippedNow.map((o) => o.book_id));

      const titleFor = (bookId: string) => {
        const book = books?.find((b) => b.id === bookId);
        if (!book) return "your book";
        return book.volume_label ? `${book.title} — ${book.volume_label}` : book.title;
      };

      const first = shippedNow[0];
      await sendShipmentNotification(
        first.customer_email,
        first.customer_name,
        shippedNow.map((order) => ({ title: titleFor(order.book_id), quantity: order.quantity })),
        first.tracking_urls ?? [],
        first.tracking_carrier,
        orderStatusUrl(siteUrl, first.id)
      );
    } catch (err) {
      // The status is already saved; a failed email must not make Lulu retry
      // and risk deactivating the webhook.
      console.error("Shipping notification failed:", err);
    }
  }

  return NextResponse.json({ received: true });
}
