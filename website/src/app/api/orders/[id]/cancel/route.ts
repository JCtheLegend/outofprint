import { NextRequest, NextResponse } from "next/server";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin, type Order } from "@/lib/supabase";
import { cancelPrintJob } from "@/lib/print";
import { isCancelable, cancelDeadline } from "@/lib/orders";

/**
 * Cancel an order and refund it.
 *
 * The order id is the capability — the same unguessable UUID that opens the
 * order page. Everything bought in one checkout is one Lulu print job, so
 * cancelling is all-or-nothing across that session.
 *
 * Order of operations matters: stop the printer first, refund second. A refund
 * we cannot reverse against a book already printing would be the expensive
 * mistake; a cancelled job with a failed refund is recoverable by retrying.
 */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const db = supabaseAdmin();

  const { data: order } = await db.from("orders").select("*").eq("id", id).single<Order>();
  if (!order) {
    return NextResponse.json({ error: "Order not found" }, { status: 404 });
  }

  const { data: siblings } = await db
    .from("orders")
    .select("*")
    .eq("stripe_session_id", order.stripe_session_id);
  const rows = (siblings ?? [order]) as Order[];

  // Already done — say so rather than refunding twice
  if (rows.every((row) => row.status === "canceled")) {
    return NextResponse.json({ canceled: true, alreadyCanceled: true });
  }

  if (!isCancelable(order)) {
    return NextResponse.json(
      {
        error:
          "This order can no longer be canceled — it has gone to the printer. " +
          "Reply to your confirmation email and we'll see what we can do.",
        deadline: cancelDeadline(order).toISOString(),
      },
      { status: 409 }
    );
  }

  // 1. Stop the printer
  const printJobId = rows.find((row) => row.print_job_id)?.print_job_id;
  if (printJobId) {
    try {
      const result = await cancelPrintJob(printJobId);
      if (result === null) {
        return NextResponse.json(
          {
            error:
              "This order is already being printed and can no longer be canceled. " +
              "Reply to your confirmation email and we'll see what we can do.",
          },
          { status: 409 }
        );
      }
    } catch (err) {
      console.error(`Could not cancel Lulu job ${printJobId} for order ${id}:`, err);
      return NextResponse.json(
        { error: "We couldn't reach the printer to cancel. Please try again in a moment." },
        { status: 502 }
      );
    }
  }

  // 2. Refund the payment in full
  let refundId = rows.find((row) => row.refund_id)?.refund_id ?? null;
  if (!refundId) {
    try {
      const session = await stripe.checkout.sessions.retrieve(order.stripe_session_id);
      const paymentIntent =
        typeof session.payment_intent === "string"
          ? session.payment_intent
          : session.payment_intent?.id;

      if (paymentIntent) {
        const refund = await stripe.refunds.create({ payment_intent: paymentIntent });
        refundId = refund.id;
      } else {
        console.error(`No payment intent on session ${order.stripe_session_id}`);
      }
    } catch (err) {
      // The print job is stopped, so nothing will be shipped. Record the
      // cancellation anyway and refund by hand rather than leaving the
      // customer with an order that is neither printing nor canceled.
      console.error(`Refund failed for order ${id}:`, err);
    }
  }

  const { error: updateError } = await db
    .from("orders")
    .update({
      status: "canceled",
      canceled_at: new Date().toISOString(),
      refund_id: refundId,
      lulu_status: "CANCELED",
    })
    .in("id", rows.map((row) => row.id));

  if (updateError) {
    console.error(`Could not mark order ${id} canceled:`, updateError);
    return NextResponse.json({ error: updateError.message }, { status: 500 });
  }

  return NextResponse.json({ canceled: true, refunded: Boolean(refundId), books: rows.length });
}
