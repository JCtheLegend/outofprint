import Stripe from "stripe";

/**
 * Server-only — never import this in client components.
 *
 * Cloudflare Workers has no Node HTTP stack, so the SDK's default client can't
 * reach Stripe at all ("An error occurred with our connection to Stripe").
 * Both overrides below are what make the SDK work in that runtime: fetch for
 * requests, and WebCrypto for verifying webhook signatures.
 */
export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2025-02-24.acacia",
  httpClient: Stripe.createFetchHttpClient(),
});

/**
 * Webhook signature verification must be async on Workers — the synchronous
 * `constructEvent` needs Node's crypto module. Use it with
 * `stripe.webhooks.constructEventAsync`.
 */
export const webhookCryptoProvider = Stripe.createSubtleCryptoProvider();

type ShippingSnapshot = {
  name?: string | null;
  address?: Stripe.Address | null;
};

/**
 * The shipping address a customer entered at checkout.
 *
 * Where it lives depends on the API version the payload was built with: Stripe
 * moved it under `collected_information` in 2026-04-22, and webhook events
 * arrive at the account's default version rather than the one this SDK pins —
 * so `session.shipping_details` is undefined on a current event and the address
 * is silently lost. Read both shapes.
 */
export function sessionShipping(session: Stripe.Checkout.Session): ShippingSnapshot {
  const collected = (
    session as unknown as {
      collected_information?: { shipping_details?: ShippingSnapshot | null } | null;
    }
  ).collected_information?.shipping_details;

  return collected ?? session.shipping_details ?? {};
}

export { formatPrice } from "@/lib/format";
