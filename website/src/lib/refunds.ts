/**
 * Cancellation refunds
 *
 * Stripe keeps its processing fee when a payment is refunded, so a refund of
 * everything the customer paid costs us that fee out of pocket — the Stripe
 * dashboard then shows a refund larger than the payment it netted. A
 * cancellation therefore refunds what was paid less the fee Stripe actually
 * took on that charge (read from its balance transaction, since international
 * cards cost more than the headline 2.9% + 30¢). /policies says so.
 *
 * Server-only.
 */

import type Stripe from "stripe";
import { stripe } from "@/lib/stripe";

export type CancellationRefund = {
  refundId: string;
  /** What went back to the customer */
  refundCents: number;
  /** Stripe's processing fee, kept back */
  feeCents: number;
};

export async function refundLessProcessingFee(sessionId: string): Promise<CancellationRefund | null> {
  const session = await stripe.checkout.sessions.retrieve(sessionId, {
    expand: ["payment_intent.latest_charge.balance_transaction"],
  });

  const paymentIntent = session.payment_intent as Stripe.PaymentIntent | null;
  const charge = paymentIntent?.latest_charge as Stripe.Charge | null | undefined;
  if (!paymentIntent || !charge) {
    console.error(`No charge on session ${sessionId} to refund`);
    return null;
  }

  const balance = charge.balance_transaction as Stripe.BalanceTransaction | null;
  // The fee is settled with the charge, so this is only missing in odd cases.
  // Then refund in full rather than guess at a deduction.
  const feeCents = balance?.fee ?? 0;
  if (!balance) {
    console.error(`No balance transaction on charge ${charge.id}; refunding in full`);
  }

  const refundable = charge.amount - charge.amount_refunded;
  const refundCents = Math.max(0, refundable - feeCents);
  if (refundCents === 0) return null;

  const refund = await stripe.refunds.create(
    { payment_intent: paymentIntent.id, amount: refundCents },
    // Two cancel clicks racing each other must not refund twice
    { idempotencyKey: `cancel-refund-${sessionId}` }
  );

  return { refundId: refund.id, refundCents, feeCents };
}
